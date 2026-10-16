"""
登录前置限流 _check_login_rate_limit 单元测试

覆盖两条路径：
1) Redis 路径：INCR+EXPIRE 固定窗口计数（多 gunicorn worker 共享同一计数），第 6 次起 429
2) 内存降级路径：Redis 不可用时回退进程内存滑动窗口计数（原行为），第 6 次起 429
外加：不同 IP 互不影响、Redis 异常时自动降级内存。

运行：
    python -m pytest tests/test_login_rate_limit.py -v
"""

import os
import sys
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask

from app.api import auth_routes as ar
from app.services import ip_blacklist_service as svc


class _FakeRedisCounter:
    """极简 Redis 计数器桩：INCR 自增 + EXPIRE 记录调用（模拟跨请求共享计数）"""

    def __init__(self):
        self.store = {}
        self.expire_calls = []

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, seconds):
        self.expire_calls.append((key, seconds))
        return True


@pytest.fixture(autouse=True)
def clean_state():
    """每个用例前后清空内存降级字典，避免跨用例污染。"""
    ar._login_attempts.clear()
    yield
    ar._login_attempts.clear()


def _call_limited(ip="9.9.9.9"):
    """在指定 remote_addr 的请求上下文下调用前置限流，返回响应（None=放行）。"""
    with Flask(__name__).test_request_context("/api/auth/login", method="POST") as ctx:
        ctx.request.remote_addr = ip
        return ar._check_login_rate_limit()


def test_redis_path_5_pass_then_429():
    """Redis 路径：前 5 次放行，第 6 次起持续 429，且 key 带 60s 过期。"""
    fake_rc = _FakeRedisCounter()
    with mock.patch.object(svc, "_get_redis_client", lambda: fake_rc):
        for i in range(5):
            assert _call_limited() is None, f"第 {i + 1} 次应放行"
        resp = _call_limited()
        assert resp is not None and resp[1] == 429
        assert _call_limited()[1] == 429  # 持续被拒
    assert fake_rc.store.get("login_rate:9.9.9.9") == 7  # 全部请求都被计数
    assert fake_rc.expire_calls and fake_rc.expire_calls[0][1] == 60


def test_memory_fallback_5_pass_then_429():
    """内存降级路径（Redis 不可用）：前 5 次放行，第 6 次起 429。"""
    with mock.patch.object(svc, "_get_redis_client", lambda: None):
        for i in range(5):
            assert _call_limited() is None, f"第 {i + 1} 次应放行"
        resp = _call_limited()
        assert resp is not None and resp[1] == 429


def test_redis_exception_falls_back_to_memory():
    """Redis 计数异常：自动降级内存路径，仍能限流。"""
    class _BrokenRC:
        def incr(self, key):
            raise RuntimeError("redis down")

    with mock.patch.object(svc, "_get_redis_client", lambda: _BrokenRC()):
        for i in range(5):
            assert _call_limited() is None, f"第 {i + 1} 次应放行"
        resp = _call_limited()
        assert resp is not None and resp[1] == 429


def test_different_ip_not_affected():
    """不同 IP 独立计数：9.9.9.9 被限流不影响 10.0.0.1。"""
    fake_rc = _FakeRedisCounter()
    with mock.patch.object(svc, "_get_redis_client", lambda: fake_rc):
        for _ in range(6):
            _call_limited("9.9.9.9")
        assert _call_limited("10.0.0.1") is None
