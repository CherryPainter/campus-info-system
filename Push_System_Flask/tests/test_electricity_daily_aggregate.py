#!/usr/bin/env python3
"""
电量「按用电日聚合」回归测试

背景（2026-09-22 修复）：
小程序电量页的「用电记录」原本直接返回原始明细，导致两个观感问题：

1. 一天两条
   一个宿舍有【两块分表】（如 31栋512 与 310512），同一次爬取各写一条，
   记录时间完全相同（都在次日 00:0x），列表里同一天出现两行。

2. 日期整体错后一天
   electricity_records.record_time 是**结算时刻** = 实际用电日 + 1 天的 00:0x，
   直接拿它当日期展示，用户看到的"9/18"其实是 9/17 的用电量，
   与站内信日报里的「统计日期」对不上。

修复口径（全项目统一，勿改）：
  - 列表/详情按「结算日」分组，一天一条，合计该日全部电表；
  - 展示的用电日 = 结算日 - 1 天；
  - 分表名一律经 ElectricityRepository.normalize_meter 归一化后再合并。

用例在事务中执行，结束后回滚，不污染数据库。
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func

from app.core.database import get_db
from app.model.electricity import ElectricityRecord
from app.repository.electricity_repository import ElectricityRepository
from app.services.electricity_service import ElectricityService

# 使用不存在的用户 ID，避免与真实数据混淆（与 test_electricity_dedup 区分开）
TEST_USER = 999998
# 结算时刻：用电日 2026-09-17 的结算记录落在 2026-09-18 00:09:51
SETTLE_0918 = datetime(2026, 9, 18, 0, 9, 51)


@pytest.fixture
def session():
    """提供数据库会话，用例结束后回滚"""
    s = get_db()
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


# ------------------------------------------------------------------
# 仓储层：按天聚合
# ------------------------------------------------------------------


def test_daily_aggregates_merge_sub_meters(session):
    """同一天两块分表：聚合后一天一条，用量为两块之和"""
    _seed(
        session,
        [
            (SETTLE_0918, 0.75, "电表: 31栋512照明"),  # 历史未清洗写法
            (SETTLE_0918, 1.71, "310512"),
        ],
    )

    rows = ElectricityRepository.get_daily_aggregates(session, user_id=TEST_USER)

    assert len(rows) == 1, f"同一天应聚合成一条，实际 {len(rows)} 条"
    assert rows[0]["settle_date"] == "2026-09-18"
    assert rows[0]["total_usage"] == pytest.approx(2.46), "当日合计应为两块分表之和"
    assert rows[0]["record_count"] == 2
    assert ElectricityRepository.count_daily_aggregates(session, user_id=TEST_USER) == 1, (
        "分页 total 统计的是「天」不是原始条数"
    )


def test_daily_aggregates_order_desc_and_page_by_day(session):
    """按结算日倒序；limit / offset 的单位是「天」"""
    _seed(
        session,
        [
            (SETTLE_0918, 1.00, "31栋512"),
            (SETTLE_0918 - timedelta(days=1), 2.00, "31栋512"),
            (SETTLE_0918 - timedelta(days=2), 3.00, "31栋512"),
        ],
    )

    all_rows = ElectricityRepository.get_daily_aggregates(session, user_id=TEST_USER, limit=10)
    assert [r["settle_date"] for r in all_rows] == ["2026-09-18", "2026-09-17", "2026-09-16"]
    assert [r["total_usage"] for r in all_rows] == [1.00, 2.00, 3.00]

    # offset=1 表示跳过最近 1 天（不是跳过 1 条记录）
    page = ElectricityRepository.get_daily_aggregates(
        session, user_id=TEST_USER, limit=2, offset=1
    )
    assert [r["settle_date"] for r in page] == ["2026-09-17", "2026-09-16"]
    assert ElectricityRepository.count_daily_aggregates(session, user_id=TEST_USER) == 3


def test_daily_aggregates_user_isolated(session):
    """不同用户的数据不得混入同一份合计"""
    _seed(session, [(SETTLE_0918, 1.00, "31栋512")])
    session.add(
        ElectricityRecord(
            record_time=SETTLE_0918, usage=99.00, meter="31栋512", user_id=TEST_USER + 1
        )
    )
    session.flush()

    rows = ElectricityRepository.get_daily_aggregates(session, user_id=TEST_USER)
    assert [r["total_usage"] for r in rows] == [1.00]
    assert ElectricityRepository.count_daily_aggregates(session, user_id=TEST_USER) == 1


# ------------------------------------------------------------------
# 仓储层：用电日窗口
# ------------------------------------------------------------------


def test_usage_day_window_excludes_neighbour_days(session):
    """用电日 D 的记录只落在 D+1 那天，前后两天的记录不得混入"""
    _seed(
        session,
        [
            (SETTLE_0918 - timedelta(days=1), 5.00, "31栋512"),  # 用电日 09-16
            (SETTLE_0918, 0.75, "31栋512"),  # 用电日 09-17
            (SETTLE_0918, 1.71, "310512"),  # 用电日 09-17
            (SETTLE_0918 + timedelta(days=1), 9.99, "31栋512"),  # 用电日 09-18
        ],
    )

    recs = ElectricityRepository.get_records_of_usage_day(
        session, "2026-09-17", user_id=TEST_USER
    )
    assert len(recs) == 2, f"只应命中 09-17 那天的两条，实际 {len(recs)} 条"
    assert sum(float(r.usage or 0) for r in recs) == pytest.approx(2.46)


def test_usage_day_window_boundaries(session):
    """窗口为左闭右开 [D+1 00:00, D+2 00:00)"""
    _seed(
        session,
        [
            (datetime(2026, 9, 18, 0, 0, 0), 1.00, "start-0000"),  # 含
            (datetime(2026, 9, 18, 23, 59, 59), 2.00, "in-2359"),  # 含
            (datetime(2026, 9, 17, 23, 59, 59), 4.00, "before"),  # 不含（属上一天）
            (datetime(2026, 9, 19, 0, 0, 0), 8.00, "after"),  # 不含（属下一天）
        ],
    )

    recs = ElectricityRepository.get_records_of_usage_day(
        session, "2026-09-17", user_id=TEST_USER
    )
    assert sorted(r.meter for r in recs) == ["in-2359", "start-0000"]


def test_daily_totals_between_is_ascending(session):
    """对比口径用的区间合计：按结算日升序，且上界不含"""
    _seed(
        session,
        [
            (SETTLE_0918, 1.00, "31栋512"),
            (SETTLE_0918, 0.50, "310512"),  # 同日另一块分表，需并入同一天
            (SETTLE_0918 + timedelta(days=1), 2.00, "31栋512"),
            (SETTLE_0918 + timedelta(days=2), 3.00, "31栋512"),  # 上界之外
        ],
    )

    totals = ElectricityRepository.get_daily_totals_between(
        session,
        start_time=datetime(2026, 9, 18),
        end_time=datetime(2026, 9, 20),
        user_id=TEST_USER,
    )
    assert totals == [("2026-09-18", 1.50), ("2026-09-19", 2.00)]


# ------------------------------------------------------------------
# 服务层：纯逻辑（不依赖库内数据）
# ------------------------------------------------------------------


def test_settle_date_to_usage_date():
    """结算日 -> 用电日：减 1 天；跨月、非法值都要正确"""
    assert ElectricityService._settle_date_to_usage_date("2026-09-18") == "2026-09-17"
    assert ElectricityService._settle_date_to_usage_date("2026-03-01") == "2026-02-28"
    assert ElectricityService._settle_date_to_usage_date("2026-01-01") == "2025-12-31"
    # 解析失败原样返回，不抛异常
    assert ElectricityService._settle_date_to_usage_date("bad") == "bad"


def test_build_report_payload_weekly():
    """周报 payload：电表名归一化 + 按用量倒序，daily 升序"""
    from app.modules.electricity.tasks import _build_report_payload

    stats = {
        "total_usage": 28.64,
        "days_count": 7,
        "meter_usage": {"电表: 31栋512照明": 18.20, "310512": 10.44},
        "daily_usage": {"2026-09-15": 4.20, "2026-09-14": 3.10},
    }
    payload = _build_report_payload(
        "weekly", stats, {"default": 42.30}, "第 3 周（2026-09-14 ~ 2026-09-20）"
    )

    assert payload["kind"] == "electricity_report"
    assert payload["report_type"] == "weekly"
    assert payload["period_label"] == "第 3 周（2026-09-14 ~ 2026-09-20）"
    assert payload["total_usage"] == pytest.approx(28.64)
    assert payload["days_count"] == 7
    assert payload["avg_daily"] == pytest.approx(4.09, abs=0.01)
    # 归一化后应剩两块不同的分表，且按用量倒序
    assert [m["meter"] for m in payload["meters"]] == ["31栋512", "310512"]
    assert [m["usage"] for m in payload["meters"]] == [18.20, 10.44]
    # daily 升序（旧 -> 新）
    assert payload["daily"] == [
        {"date": "2026-09-14", "usage": 3.10},
        {"date": "2026-09-15", "usage": 4.20},
    ]
    assert payload["remaining"] == pytest.approx(42.30)


def test_build_report_payload_daily_has_no_daily_list():
    """日报只有一天，不应输出 daily 列表；无剩余电量时不写该字段"""
    from app.modules.electricity.tasks import _build_report_payload

    stats = {
        "total_usage": 2.46,
        "days_count": 1,
        "meter_usage": {"31栋512": 0.75, "310512": 1.71},
    }
    payload = _build_report_payload("daily", stats, {}, "2026-09-17")

    assert payload["report_type"] == "daily"
    assert "daily" not in payload
    assert "remaining" not in payload
    assert payload["avg_daily"] == pytest.approx(2.46)


def test_build_report_payload_zero_days_does_not_divide_by_zero():
    """days_count 为 0 时日均按 0 处理，不得抛 ZeroDivisionError"""
    from app.modules.electricity.tasks import _build_report_payload

    payload = _build_report_payload("monthly", {"total_usage": 0, "days_count": 0}, {}, "2026年9月")
    assert payload["avg_daily"] == 0.0


# ------------------------------------------------------------------
# 服务层：与真实库数据的一致性（只读，无数据则跳过）
# ------------------------------------------------------------------


def _pick_user_with_records(session):
    """挑一个用电记录最多的用户（真实数据只读校验用）"""
    row = (
        session.query(ElectricityRecord.user_id)
        .filter(ElectricityRecord.record_time.isnot(None))
        .group_by(ElectricityRecord.user_id)
        .order_by(func.count(ElectricityRecord.id).desc())
        .first()
    )
    return int(row[0]) if row else None


def test_service_daily_records_and_detail_are_consistent(session):
    """
    服务层读真实库（只读）：按天聚合结果与原始记录必须自洽

    校验三点：
      1. days 按用电日严格倒序且不重复，total 等于按天统计的天数；
      2. 取回的一天，其 total_usage == 各分表用量之和（容差 0.01）；
      3. 各分表占比之和约等于 100%。
    """
    user_id = _pick_user_with_records(session)
    if user_id is None:
        pytest.skip("库内无用电记录，跳过真实数据一致性校验")

    svc = ElectricityService(user_id=user_id)
    page = svc.get_daily_records(limit=10, offset=0)

    days = page["days"]
    assert days, "该用户应至少有一天记录"
    dates = [d["date"] for d in days]
    assert dates == sorted(dates, reverse=True), "应按用电日倒序"
    assert len(set(dates)) == len(dates), "同一天不应出现两次（一天一条）"
    assert page["total"] == ElectricityRepository.count_daily_aggregates(
        session, user_id=user_id
    )

    detail = svc.get_daily_detail(dates[0])
    assert detail is not None
    assert detail["date"] == dates[0]
    assert detail["meter_count"] == len(detail["meters"]) >= 1

    meter_sum = sum(m["usage"] for m in detail["meters"])
    assert meter_sum == pytest.approx(detail["total_usage"], abs=0.01), (
        "各分表用量之和应等于当日合计"
    )
    if detail["total_usage"] > 0:
        assert sum(m["percent"] for m in detail["meters"]) == pytest.approx(100.0, abs=0.5)
