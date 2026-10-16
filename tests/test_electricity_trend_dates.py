#!/usr/bin/env python3
"""
电量趋势图「用电日」口径回归测试

背景（2026-09-23 修复）：
`/api/miniapp/electricity/trend` 背后的 `ElectricityService.get_usage_trend` 此前
直接把 `electricity_records.record_time`（**结算时刻** = 用电日 + 1 天的 00:0x）
的日期当作「用电日」返回，造成两点问题：

1. 趋势点整体错位一天：图上标着「9/6」的点其实是 9/5 的用电量；末点「今天」
   画的往往是昨天的量，当日真正的 0 反被挤到不存在的明天。
2. 与用电记录列表 / 日报 / 周报 / 月报口径不一致——后者均已按
   「结算日 - 1 天 = 用电日」展示（见 test_electricity_daily_aggregate）。

修复口径（全项目统一，勿改）：
  趋势聚合先经 `ElectricityService._settle_date_to_usage_date` 换算成用电日，
  再按用电日合计当天全部分表。

用例通过 monkeypatch 把服务内部的 get_db 指向测试会话（并屏蔽其 close），
结束后回滚，不污染数据库。
"""

from datetime import datetime, timedelta

import pytest

import app.services.electricity_service as es
from app.core.database import get_db
from app.model.electricity import ElectricityRecord
from app.services.electricity_service import ElectricityService

# 使用不存在的用户 ID，避免与真实数据混淆
TEST_USER = 999997


class _KeepOpenSession:
    """代理测试会话：屏蔽 service 内部的 close()，其余查询原样转发"""

    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture
def session(monkeypatch):
    """提供数据库会话，并把 service 内部的 get_db 指向它；用例结束后回滚"""
    s = get_db()
    monkeypatch.setattr(es, "get_db", lambda: _KeepOpenSession(s))
    yield s
    s.rollback()
    s.close()


def _seed(session, rows):
    """写入用电记录：rows = [(record_time, usage, meter), ...]"""
    session.add_all(
        [
            ElectricityRecord(record_time=t, usage=u, meter=m, user_id=TEST_USER)
            for t, u, m in rows
        ]
    )
    session.flush()


def _settle_of(usage_day: datetime) -> datetime:
    """用电日 -> 其结算时刻（= 用电日 + 1 天的 00:09:51）"""
    return datetime(usage_day.year, usage_day.month, usage_day.day, 0, 9, 51) + timedelta(
        days=1
    )


def test_trend_uses_usage_day_not_settle_day(session):
    """结算日的用量必须落在「用电日 = 结算日 - 1」的点上（此前错位一天）"""
    usage_day = datetime.now() - timedelta(days=3)
    settle = _settle_of(usage_day)

    _seed(session, [(settle, 7.37, "31栋512")])

    points = ElectricityService(user_id=TEST_USER).get_usage_trend(days=7)
    by_date = {p["date"]: p["usage"] for p in points}

    assert by_date[usage_day.strftime("%Y-%m-%d")] == pytest.approx(7.37), (
        "用量应记在用电日（结算日 - 1）上"
    )
    assert by_date[settle.strftime("%Y-%m-%d")] == 0.0, "结算日本身不应再有用量"


def test_trend_merges_sub_meters_by_usage_day(session):
    """同一天两块分表合并为一天；相邻两天不串点"""
    d1 = datetime.now() - timedelta(days=2)
    d2 = datetime.now() - timedelta(days=4)

    _seed(
        session,
        [
            (_settle_of(d1), 0.75, "电表: 31栋512照明"),  # 历史未清洗写法
            (_settle_of(d1), 1.71, "310512"),
            (_settle_of(d2), 5.00, "310512"),
        ],
    )

    points = ElectricityService(user_id=TEST_USER).get_usage_trend(days=7)
    by_date = {p["date"]: p["usage"] for p in points}

    assert by_date[d1.strftime("%Y-%m-%d")] == pytest.approx(2.46), "两块分表应合计"
    assert by_date[d2.strftime("%Y-%m-%d")] == pytest.approx(5.00), "相邻两天不得串点"


def test_trend_points_shape_and_order(session):
    """点数 = days，按用电日升序（旧 -> 新），末点为今天"""
    points = ElectricityService(user_id=TEST_USER).get_usage_trend(days=30)

    assert len(points) == 30
    dates = [p["date"] for p in points]
    assert dates == sorted(dates), "应按用电日升序返回"
    assert dates[-1] == datetime.now().strftime("%Y-%m-%d"), "末点应为今天"
    assert all(isinstance(p["usage"], float) for p in points)
