#!/usr/bin/env python3
"""
电量用电记录去重逻辑回归测试

覆盖 2026-09-08 修复的两个核心语义（都曾导致线上数据出错）：

1. 同一块电表的不同写法必须合并
   同一块表在库里存在多种写法（老数据未清洗 "电表: 31栋512照明"，
   新数据清洗后 "31栋512"）。若按原始字符串精确匹配去重，两者匹配不上，
   同一块表同一天会被反复插入多份，趋势图按日求和时被成倍放大
   （实际每天约 7 度，图上显示 22 度），记录条数虚高到单用户 2000+。

2. 同一个宿舍的不同分表必须各自保留
   一个宿舍有【两块分表】："31栋512" 与 "310512" 是两块不同的表，
   同一天用电量不同（如 9/6 分别 1.8 和 5.57），当天真实用量 = 各分表之和。
   若只按「用户 + 日期」去重，会把另一块分表当成重复数据误删，
   日用量直接少算一大截。

所有用例在事务中执行结束后回滚，不污染数据库。
"""

from datetime import datetime

import pytest

from app.core.database import get_db
from app.model.electricity import ElectricityRecord
from app.repository.electricity_repository import ElectricityRepository

# 使用一个不存在的用户 ID，避免与真实数据混淆
TEST_USER = 999999
TEST_DAY = datetime(2026, 9, 6, 0, 9, 51)


@pytest.fixture
def session():
    """提供数据库会话，用例结束后回滚"""
    s = get_db()
    yield s
    s.rollback()
    s.close()


def _records_of(session, user_id: int):
    return session.query(ElectricityRecord).filter(ElectricityRecord.user_id == user_id).all()


def test_normalize_meter_strips_noise():
    """电表写法归一化：去掉「电表:」前缀与「照明」后缀"""
    cases = {
        "电表: 31栋512照明": "31栋512",
        "31栋512照明": "31栋512",
        "31栋512": "31栋512",
        "电表: 310512": "310512",
        "310512": "310512",
        "": "default",
        None: "default",
    }
    for raw, expected in cases.items():
        assert ElectricityRepository.normalize_meter(raw) == expected, f"归一化 {raw!r} 失败"


def test_same_meter_different_wording_is_merged(session):
    """同一块表的不同写法应识别为同一条：只更新，不新增"""
    session.add(
        ElectricityRecord(
            record_time=TEST_DAY,
            usage=1.80,
            meter="电表: 31栋512照明",  # 历史未清洗写法
            user_id=TEST_USER,
        )
    )
    session.flush()

    # 新爬取写入的是清洗后的写法，且用电量有更新
    created = ElectricityRepository.create_records_batch(
        session, [(TEST_DAY, 2.10, "31栋512")], user_id=TEST_USER
    )
    session.flush()

    assert created == 0, "同一块表应命中已有记录，不应新增"
    rows = _records_of(session, TEST_USER)
    assert len(rows) == 1, f"应只有 1 条记录，实际 {len(rows)}"
    assert rows[0].usage == 2.10, "用电量应被更新"
    assert rows[0].meter == "31栋512", "电表写法应统一为归一化值"


def test_two_sub_meters_are_both_kept(session):
    """同一个宿舍的两块分表必须各自保留，不能被当成重复删除"""
    session.add(
        ElectricityRecord(
            record_time=TEST_DAY,
            usage=1.80,
            meter="31栋512",
            user_id=TEST_USER,
        )
    )
    session.flush()

    # 另一块分表（照明/空调），归一化后是不同标识
    created = ElectricityRepository.create_records_batch(
        session, [(TEST_DAY, 5.57, "310512")], user_id=TEST_USER
    )
    session.flush()

    assert created == 1, "另一块分表应作为新记录插入"
    rows = _records_of(session, TEST_USER)
    assert len(rows) == 2, f"两块分表都应保留，实际 {len(rows)} 条"

    # 当天真实用量 = 各分表之和
    total = sum(float(r.usage or 0) for r in rows)
    assert round(total, 2) == 7.37, f"当天合计应为 7.37，实际 {total}"


def test_repeated_crawl_does_not_grow(session):
    """重复跑相同的爬取，记录数不应增长"""
    ElectricityRepository.create_records_batch(
        session,
        [(TEST_DAY, 1.80, "31栋512"), (TEST_DAY, 5.57, "310512")],
        user_id=TEST_USER,
    )
    session.flush()
    assert len(_records_of(session, TEST_USER)) == 2

    # 再爬一次，且故意用不同的写法
    created = ElectricityRepository.create_records_batch(
        session,
        [(TEST_DAY, 1.80, "电表: 31栋512照明"), (TEST_DAY, 5.57, "电表: 310512")],
        user_id=TEST_USER,
    )
    session.flush()

    assert created == 0, "重复爬取不应新增记录"
    assert len(_records_of(session, TEST_USER)) == 2, "记录数应保持 2 条"
