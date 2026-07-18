# -*- coding: utf-8 -*-
"""
IP 黑名单模块单元测试

覆盖两类逻辑：
1) 信号感知登录失败判定（滑动窗口 / 分层）→ 走内存降级路径（无 Redis 依赖）
2) IPBlacklistService 的黑名单 CRUD / 安全事件 / 自动封禁 / 过期清理 → 走 SQLite 内存库

运行：
    PYTHONPATH=Push_System_Flask DATABASE_HOST=127.0.0.1 \
        python -m pytest Push_System_Flask/tests/test_ip_blacklist.py -v
"""
import os
import sys
from datetime import datetime, timedelta
from unittest import mock

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 确保 app 可导入
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import ip_blacklist_service as svc
from app.model.ip_blacklist import IPBlacklist, IPSecurityEvent


class _FakeClock:
    """可手动推进的假时钟，保证 evaluate_login_failure 的时间戳单调且可控制窗口。"""

    def __init__(self, start_ts):
        self._t = float(start_ts)

    def now(self):
        return datetime.fromtimestamp(self._t)

    def advance(self, secs):
        self._t += secs


@pytest.fixture
def clock():
    # 固定起始时间：2026-07-18 00:00:00
    start = datetime(2026, 7, 18, 0, 0, 0).timestamp()
    return _FakeClock(start)


@pytest.fixture(autouse=True)
def memory_only():
    """强制登录失败计数走内存降级（无 Redis），并重置内存字典。"""
    svc._login_fail_memory.clear()
    with mock.patch.object(svc, '_get_redis_client', lambda: None):
        yield


@pytest.fixture
def fake_clock(clock):
    """把服务的 datetime 替换为可手动推进的假时钟，保证滑动窗口测试可控。"""
    with mock.patch.object(svc, 'datetime', clock):
        yield clock


@pytest.fixture(autouse=True)
def no_alert():
    """屏蔽封禁告警推送（避免触发企业微信适配器副作用）。"""
    with mock.patch.object(svc.IPBlacklistService, '_send_block_alert',
                           lambda *a, **k: None):
        yield


# ============================================================
# 一、纯逻辑：分层匹配
# ============================================================

def test_match_tier_none_below_threshold():
    assert svc._match_tier(svc.ACCOUNT_FAIL_TIERS, 0) is None
    assert svc._match_tier(svc.ACCOUNT_FAIL_TIERS, 4) is None  # 阈值 5


def test_match_tier_returns_highest_tier():
    # IP_CROSS_ACCOUNT_TIERS: tier1 阈值3 / tier2 阈值5
    assert svc._match_tier(svc.IP_CROSS_ACCOUNT_TIERS, 3) == 1
    assert svc._match_tier(svc.IP_CROSS_ACCOUNT_TIERS, 5) == 2
    assert svc._match_tier(svc.IP_CROSS_ACCOUNT_TIERS, 999) == 2


def test_match_tier_enum_logic():
    # IP_ENUM_TIERS: 阈值 8
    assert svc._match_tier(svc.IP_ENUM_TIERS, 7) is None
    assert svc._match_tier(svc.IP_ENUM_TIERS, 8) == 1


def test_match_tier_volume_logic():
    # IP_VOLUME_TIERS: 阈值 30
    assert svc._match_tier(svc.IP_VOLUME_TIERS, 29) is None
    assert svc._match_tier(svc.IP_VOLUME_TIERS, 30) == 1


# ============================================================
# 二、滑动窗口（内存降级路径）
# ============================================================

def test_win_add_memory_counts_and_expires(fake_clock):
    cnt = svc._win_add(None, svc._AFAIL_PREFIX, 'alice', str(fake_clock._t), fake_clock._t)
    assert cnt == 1
    fake_clock.advance(1)
    cnt = svc._win_add(None, svc._AFAIL_PREFIX, 'alice', str(fake_clock._t), fake_clock._t)
    assert cnt == 2
    # 推进超过窗口(300s)后，旧计数落出
    fake_clock.advance(svc.LOGIN_FAIL_WINDOW_SECONDS + 1)
    cnt = svc._win_add(None, svc._AFAIL_PREFIX, 'alice', str(fake_clock._t), fake_clock._t)
    assert cnt == 1


def test_win_add_dedup_for_cross_account():
    # 跨账号维度 member=用户名，天然去重：同一用户多次失败不增加"不同账号数"
    svc._win_add(None, svc._IPXA_PREFIX, '1.2.3.4', 'alice', 1000.0)
    svc._win_add(None, svc._IPXA_PREFIX, '1.2.3.4', 'alice', 1001.0)
    cnt = svc._win_add(None, svc._IPXA_PREFIX, '1.2.3.4', 'bob', 1002.0)
    assert cnt == 2  # alice, bob


def test_win_del_clears_key():
    svc._win_add(None, svc._AFAIL_PREFIX, 'carol', '1', 1000.0)
    svc._win_del(None, svc._AFAIL_PREFIX, 'carol')
    # 再 add 应从 1 开始
    cnt = svc._win_add(None, svc._AFAIL_PREFIX, 'carol', '2', 2000.0)
    assert cnt == 1


def test_win_zrem_removes_member():
    svc._win_add(None, svc._IPXA_PREFIX, '9.9.9.9', 'dave', 1000.0)
    svc._win_zrem(None, svc._IPXA_PREFIX, '9.9.9.9', 'dave')
    cnt = svc._win_add(None, svc._IPXA_PREFIX, '9.9.9.9', 'eval', 1001.0)
    assert cnt == 1


# ============================================================
# 三、evaluate_login_failure 信号感知决策
# ============================================================

def test_evaluate_account_lock_triggered(fake_clock):
    dec = None
    for _ in range(5):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('1.1.1.1', 'alice', 'password')
    assert dec is not None
    assert dec['scope'] == 'account'
    assert dec['action'] == 'account_lock'
    assert dec['current_count'] == 5


def test_evaluate_account_lock_not_before_threshold(fake_clock):
    for _ in range(4):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('1.1.1.1', 'alice', 'password')
    assert dec is None  # 4 次未达阈值 5


def test_evaluate_notfound_does_not_lock_account(fake_clock):
    # 同一"不存在用户名"尝试 10 次：账号维度不锁定（kind=notfound 不计入账号级）
    for _ in range(10):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('1.1.1.1', 'ghost', 'notfound')
    assert dec is None


def test_evaluate_ip_cross_account_temp_block(fake_clock):
    # 5 个不同账号失败 => 跨账号维度 tier2 => 临时封禁（非永久）
    dec = None
    for i in range(5):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('9.9.9.9', f'user{i}', 'password')
    assert dec['scope'] == 'ip'
    assert dec['action'] == 'temp_block'
    assert dec['source'] == 'login_brute_tier2'
    assert dec['current_count'] == 5


def test_evaluate_distinct_notfound_triggers_cross_account(fake_clock):
    # 8 个不同"不存在用户名" => 跨账号维度先达阈值(5) => 临时封禁
    # （设计上枚举维度阈值 8 被跨账号维度阈值 5 覆盖，故最高优先级为 temp_block）
    dec = None
    for i in range(8):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('7.7.7.7', f'nope{i}', 'notfound')
    assert dec['scope'] == 'ip'
    assert dec['action'] == 'temp_block'
    assert dec['source'] == 'login_brute_tier2'


def test_evaluate_volume_rate_limit(fake_clock):
    # 30 次空参数失败（无用户名）=> 仅 IP 总量维度达阈值 => 限流
    dec = None
    for _ in range(30):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('6.6.6.6', '', 'empty')
    assert dec['scope'] == 'ip'
    assert dec['action'] == 'rate_limit'
    assert dec['source'] == 'login_rate_limit'
    assert dec['current_count'] == 30


def test_evaluate_priority_account_lock_over_rate_limit(fake_clock):
    # 同一账号失败 30 次：账号锁定(account_lock) 优先级高于 IP 限流(rate_limit)
    dec = None
    for _ in range(30):
        fake_clock.advance(1)
        dec = svc.evaluate_login_failure('5.5.5.5', 'victim', 'password')
    assert dec['action'] == 'account_lock'
    assert dec['current_count'] >= 5


def test_evaluate_returns_none_when_quiet():
    # 没有任何失败信号
    assert svc.evaluate_login_failure('0.0.0.0', 'nobody', 'password') is None


def test_reset_login_counters_clears_account(fake_clock):
    for _ in range(5):
        fake_clock.advance(1)
        svc.evaluate_login_failure('3.3.3.3', 'carol', 'password')
    # 已触发账号锁定
    dec = svc.evaluate_login_failure('3.3.3.3', 'carol', 'password')
    assert dec['action'] == 'account_lock'
    # 重置后，再次失败 1 次不应立即再锁定
    assert svc.reset_login_counters('3.3.3.3', 'carol') is True
    dec2 = svc.evaluate_login_failure('3.3.3.3', 'carol', 'password')
    assert dec2 is None  # 计数被清零，仅 1 次


# ============================================================
# 四、黑名单 CRUD / 安全事件 / 自动封禁 / 过期清理（SQLite 内存库）
# ============================================================

@pytest.fixture
def session():
    engine = create_engine('sqlite:///:memory:')
    IPBlacklist.__table__.create(engine)
    IPSecurityEvent.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_is_ip_blocked_false_when_empty(session):
    assert svc.IPBlacklistService.is_ip_blocked(session, '1.1.1.1') is False


def test_block_and_is_blocked_permanent(session):
    rec = svc.IPBlacklistService.block_ip(
        session, '2.2.2.2', reason='manual', source='manual')
    assert rec.is_active is True
    assert rec.expires_at is None  # 永久
    assert svc.IPBlacklistService.is_ip_blocked(session, '2.2.2.2') is True


def test_block_expires_and_auto_unblocks(session):
    svc.IPBlacklistService.block_ip(session, '3.3.3.3', reason='x', duration_hours=1)
    rec = session.query(IPBlacklist).filter_by(ip_address='3.3.3.3').first()
    rec.expires_at = datetime.now() - timedelta(hours=1)
    session.commit()
    # 过期后 is_ip_blocked 返回 False，并把 is_active 置 False
    assert svc.IPBlacklistService.is_ip_blocked(session, '3.3.3.3') is False
    assert rec.is_active is False


def test_unblock(session):
    assert svc.IPBlacklistService.unblock_ip(session, 'never') is False  # 无记录
    svc.IPBlacklistService.block_ip(session, '4.4.4.4', reason='x')
    assert svc.IPBlacklistService.unblock_ip(session, '4.4.4.4') is True
    assert svc.IPBlacklistService.is_ip_blocked(session, '4.4.4.4') is False


def test_block_ip_idempotent_update(session):
    r1 = svc.IPBlacklistService.block_ip(session, '5.5.5.5', reason='first', source='manual')
    r2 = svc.IPBlacklistService.block_ip(session, '5.5.5.5', reason='second', source='manual')
    assert r1.id == r2.id
    assert r2.reason == 'second'
    assert r2.is_active is True
    assert session.query(IPBlacklist).filter_by(ip_address='5.5.5.5').count() == 1


def test_get_blacklist_only_active(session):
    svc.IPBlacklistService.block_ip(session, '6.6.6.6', reason='a')
    svc.IPBlacklistService.block_ip(session, '7.7.7.7', reason='b')
    svc.IPBlacklistService.unblock_ip(session, '6.6.6.6')
    records, total = svc.IPBlacklistService.get_blacklist(session, only_active=True)
    assert total == 1
    assert records[0].ip_address == '7.7.7.7'
    records2, total2 = svc.IPBlacklistService.get_blacklist(session, only_active=False)
    assert total2 == 2


def test_get_blacklist_pagination(session):
    for i in range(5):
        svc.IPBlacklistService.block_ip(session, f'10.0.0.{i}', reason='x')
    page1, total = svc.IPBlacklistService.get_blacklist(session, page=1, per_page=2)
    assert total == 5
    assert len(page1) == 2
    page2, _ = svc.IPBlacklistService.get_blacklist(session, page=2, per_page=2)
    assert len(page2) == 2


def test_record_event_auto_block(session):
    # 降低阈值以便快速触发自动封禁
    low = {
        'rate_limit': {
            'window_seconds': 60,
            'request_count': 3,
            'block_duration_hours': 24,
        }
    }
    last_ev = None
    with mock.patch.dict(svc.AUTO_BLOCK_THRESHOLDS, low, clear=False):
        for _ in range(3):
            last_ev = svc.IPBlacklistService.record_event(
                session, '8.8.8.8', 'rate_limit_exceeded', path='/x', severity='warning')
    # 第 3 次触发自动封禁，最后一次事件被标记为已封禁
    assert last_ev.is_blocked is True
    assert svc.IPBlacklistService.is_ip_blocked(session, '8.8.8.8') is True
    # 该 IP 至少有一条安全事件被标记 is_blocked
    blocked_events = session.query(IPSecurityEvent).filter_by(
        ip_address='8.8.8.8', is_blocked=True).count()
    assert blocked_events >= 1


def test_ignore_event(session):
    ev = svc.IPBlacklistService.record_event(
        session, '9.9.9.9', 'suspicious_path', path='/y')
    assert svc.IPBlacklistService.ignore_event(session, ev.id) is True
    ev2 = session.query(IPSecurityEvent).filter_by(id=ev.id).first()
    assert ev2.is_ignored is True
    assert svc.IPBlacklistService.ignore_event(session, 99999) is False


def test_ban_event_ip(session):
    ev = svc.IPBlacklistService.record_event(
        session, '10.10.10.10', 'sql_injection', path='/z')
    assert svc.IPBlacklistService.is_ip_blocked(session, '10.10.10.10') is False
    ok, msg = svc.IPBlacklistService.ban_event_ip(
        session, ev.id, reason='test', duration_hours=2)
    assert ok is True
    assert '10.10.10.10' in msg
    assert svc.IPBlacklistService.is_ip_blocked(session, '10.10.10.10') is True
    ev2 = session.query(IPSecurityEvent).filter_by(id=ev.id).first()
    assert ev2.is_blocked is True
    assert svc.IPBlacklistService.ban_event_ip(session, 99999) == (False, '事件不存在')


def test_cleanup_expired(session):
    expired = IPBlacklist(
        ip_address='11.11.11.11', is_active=True,
        expires_at=datetime.now() - timedelta(hours=1))
    permanent = IPBlacklist(
        ip_address='12.12.12.12', is_active=True, expires_at=None)
    session.add_all([expired, permanent])
    session.commit()
    cnt = svc.IPBlacklistService.cleanup_expired(session)
    assert cnt == 1
    assert svc.IPBlacklistService.is_ip_blocked(session, '11.11.11.11') is False
    assert svc.IPBlacklistService.is_ip_blocked(session, '12.12.12.12') is True
