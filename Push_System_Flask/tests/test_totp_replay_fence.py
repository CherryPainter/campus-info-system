"""
TOTP 重放防护围栏回归测试（B 级修复项 B9）

背景（审计事实，均可在修复前复现）：
`TOTP.verify(otp, window=1)` 是纯函数，只判断「这个码是不是当前（含前后各一个）窗口的
码」，全程不记录任何已用状态；`UserMFA` 表也没有可用码字段。因此同一个 6 位码在
**90 秒**（3 个 30 秒步长）有效期内可被反复提交、每次都被判为合法 —— 一旦验证码在窗口内
被第三方拿到（肩窥/截图/代理日志），就能再完成一次登录。

修复：为每个用户记录「最近一次成功消费的 TOTP 步号」，要求步号**严格递增**。
存储走 Redis（复用项目既有连接工厂，TTL 自动清理，无迁移），不可用时降级进程内存。

覆盖：
- `TOTP.match_step`：命中返回步号、未命中返回 None、容错窗口边界（±2 步必须落空）
- `TOTP.verify` 行为不放宽（原有调用方语义不变）
- `verify_mfa`：第一次通过、同一码第二次被拒；错误码不消耗步号（"失败不占用"）
- 步号严格递增：新窗口的码可用，旧窗口的码不可用
- 按用户隔离：A 用过的码不影响 B
- Redis 路径：Lua 比较并占用为原子操作（用假 client 断言 GET/SET 语义）
- Redis 不可用：降级内存且仍能拦住同进程重放；同时打 WARNING（不静默）
- 接线：三个调用点（login_mfa / mfa_verify / mfa_disable）都必须传 user_id

运行：
    cd Push_System_Flask && python -m pytest tests/test_totp_replay_fence.py -v
"""

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils import totp_replay_guard as guard
from app.utils.mfa import TOTP, MFAManager, mfa_manager

SECRET = "JBSWY3DPEHPK3PXP"

AUTH_ROUTES = os.path.join(ROOT, "app", "api", "auth_routes.py")


@pytest.fixture(autouse=True)
def _clean_state():
    """每个用例前后都清掉内存降级表与 Redis 记录，避免互相污染"""
    guard._MEMORY.clear()
    yield
    guard._MEMORY.clear()


@pytest.fixture
def no_redis(monkeypatch):
    """强制走内存降级路径"""
    monkeypatch.setattr(guard, "_redis", lambda: None)


def _code(secret=SECRET, offset_steps=0):
    """取指定步号偏移上的验证码（offset_steps=0 即当前步）"""
    totp = TOTP(secret)
    return totp.generate(int(time.time()) + offset_steps * totp.interval)


# ============================================================
# 一、match_step：把「是否有效」升级为「属于哪一步」
# ============================================================


def test_match_step_returns_current_step():
    totp = TOTP(SECRET)
    step = totp.match_step(_code())
    assert step == int(time.time()) // totp.interval


def test_match_step_none_for_wrong_code():
    assert TOTP(SECRET).match_step("000000" if _code() != "000000" else "111111") is None


def test_match_step_none_for_empty():
    assert TOTP(SECRET).match_step("") is None


@pytest.mark.parametrize("offset", [0, -1, 1])
def test_match_step_accepts_fault_tolerance_window(offset):
    """容错窗口不放宽：当前步与前后各一步都必须能命中"""
    assert TOTP(SECRET).match_step(_code(offset_steps=offset)) is not None


@pytest.mark.parametrize("offset", [-3, -2, 2, 3])
def test_match_step_rejects_outside_window(offset):
    """窗口外必须落空（证明容错范围仍是 ±1 步）"""
    assert TOTP(SECRET).match_step(_code(offset_steps=offset)) is None


def test_verify_still_returns_bool():
    """verify 是既有公开语义，改为委托 match_step 后返回值类型与结论都不能变"""
    totp = TOTP(SECRET)
    assert totp.verify(_code()) is True
    assert totp.verify("000000" if _code() != "000000" else "111111") is False


# ============================================================
# 二、verify_mfa：同一个码只能用一次
# ============================================================


def test_first_use_passes(no_redis):
    assert mfa_manager.verify_mfa(SECRET, _code(), 1) is True


def test_same_code_second_use_is_rejected(no_redis):
    """核心修复点：修复前这里第二次仍返回 True"""
    code = _code()
    assert mfa_manager.verify_mfa(SECRET, code, 1) is True
    assert mfa_manager.verify_mfa(SECRET, code, 1) is False


def test_wrong_code_does_not_consume_step(no_redis):
    """失败不得占用步号，否则用户打错一次就会被自己锁住"""
    wrong = "000000" if _code() != "000000" else "111111"
    assert mfa_manager.verify_mfa(SECRET, wrong, 1) is False
    assert mfa_manager.verify_mfa(SECRET, _code(), 1) is True


def test_previous_step_code_rejected_after_use(no_redis):
    """先消费当前步，再补交上一步的码 → 必须拒绝（步号严格递增）"""
    assert mfa_manager.verify_mfa(SECRET, _code(), 1) is True
    assert mfa_manager.verify_mfa(SECRET, _code(offset_steps=-1), 1) is False


def test_next_step_code_accepted_after_current_used(no_redis):
    """严格递增而非「用过就永久锁死」：新窗口的码照常可用"""
    assert mfa_manager.verify_mfa(SECRET, _code(), 1) is True
    assert mfa_manager.verify_mfa(SECRET, _code(offset_steps=1), 1) is True


def test_replay_guard_is_per_user(no_redis):
    """按用户隔离：A 用过的码不影响 B（不同 user_id 各自计数）"""
    code = _code()
    assert mfa_manager.verify_mfa(SECRET, code, 1) is True
    assert mfa_manager.verify_mfa(SECRET, code, 2) is True
    assert mfa_manager.verify_mfa(SECRET, code, 1) is False


def test_empty_inputs_rejected(no_redis):
    assert mfa_manager.verify_mfa("", "123456", 1) is False
    assert mfa_manager.verify_mfa(SECRET, "", 1) is False


def test_verify_mfa_requires_user_id():
    """user_id 必须显式传入：留成可选会让漏传的调用方静默失去防护"""
    with pytest.raises(TypeError):
        mfa_manager.verify_mfa(SECRET, "123456")


def test_reset_clears_record(no_redis):
    code = _code()
    assert mfa_manager.verify_mfa(SECRET, code, 1) is True
    guard.reset(1)
    # 重置后同一个码可再次通过（用于「重置 MFA」等场景）
    assert mfa_manager.verify_mfa(SECRET, code, 1) is True


def test_memory_record_expires(no_redis, monkeypatch):
    """内存降级表必须带过期时间，否则无 Redis 的长期进程里会越积越多"""
    assert mfa_manager.verify_mfa(SECRET, _code(), 1) is True
    assert guard._MEMORY, "应写入内存降级表"

    # 把记录改为已过期，再走一次新的码：旧记录应被清理且不阻止新码
    key = guard._key(1)
    step, _ = guard._MEMORY[key]
    guard._MEMORY[key] = (step, time.time() - 1)
    assert mfa_manager.verify_mfa(SECRET, _code(offset_steps=1), 1) is True
    assert guard._MEMORY[key][1] > time.time()


# ============================================================
# 三、Redis 路径：Lua 为「比较并占用」
# ============================================================


class _FakeRedis:
    """只实现 eval（Lua 比较并占用）与 delete，用于断言 Redis 分支的接线与语义"""

    def __init__(self, ttl_ok=True):
        self.store = {}
        self.calls = []

    def eval(self, script, numkeys, key, step, ttl):
        self.calls.append((key, int(step), int(ttl)))
        assert "redis.call('GET'" in script and "redis.call('SET'" in script, "必须是原子脚本"
        current = self.store.get(key)
        if current is not None and int(current) >= int(step):
            return 0
        self.store[key] = int(step)
        return 1

    def delete(self, key):
        self.store.pop(key, None)
        return 1


def test_redis_branch_uses_atomic_compare_and_set(monkeypatch):
    rc = _FakeRedis()
    monkeypatch.setattr(guard, "_redis", lambda: rc)
    code = _code()

    assert mfa_manager.verify_mfa(SECRET, code, 7) is True
    assert mfa_manager.verify_mfa(SECRET, code, 7) is False
    key, step, ttl = rc.calls[0]
    assert key == "mfa_totp_step:7"
    assert ttl >= 90, "TTL 至少覆盖 3 个步长，否则会把仍可能被接受的记录提前清掉"
    assert mfa_manager.verify_mfa(SECRET, code, 7) is False
    assert guard.key_fingerprint(7) != "7"  # 指纹不得直接等于用户标识


def test_memory_and_lua_implement_the_same_step_rule():
    """无 Redis 环境下无法执行 Lua，故用「同义转写」锁定两条路径的规则一致。

    本用例断言 Lua 脚本里存在与 `_is_new_step` 同义的比较表达式；行为层面的规则正确性
    由走内存路径的用例覆盖（同一个 `_is_new_step`）。真实 Redis 上的 EVAL 行为另见
    test_real_redis_claim_is_monotonic（无 Redis 时跳过）。
    """
    script = guard._CLAIM_LUA
    assert "redis.call('GET', KEYS[1])" in script
    assert "tonumber(cur) >= tonumber(ARGV[1])" in script, "Lua 必须比较已记录步号"
    assert "return 0" in script and "redis.call('SET'" in script
    # 与 Python 版规则对照：都表示「记录存在且不小于本次步号 → 拒绝」
    assert guard._is_new_step(None, 5) is True
    assert guard._is_new_step(5, 5) is False
    assert guard._is_new_step(6, 5) is False
    assert guard._is_new_step(4, 5) is True


def _redis_endpoint():
    """从项目配置解析 Redis 主机端口，用于判断真实 Redis 是否可用"""
    from app.core.config import Config

    url = getattr(Config, "REDIS_URL", "") or ""
    if not url:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname, parsed.port or 6379


def _redis_reachable():
    import socket

    endpoint = _redis_endpoint()
    if not endpoint:
        return False
    sock = socket.socket()
    sock.settimeout(0.8)
    try:
        sock.connect(endpoint)
        return True
    except Exception:
        return False
    finally:
        sock.close()


@pytest.mark.skipif(
    not _redis_reachable(),
    reason="本机 Redis 不可达（无 Redis 环境），Lua 的真实执行行为无法在此验证",
)
def test_real_redis_claim_is_monotonic():
    """真实 Redis 上的 EVAL 行为（有 Redis 时执行）。

    本机没有可用的 Redis（本地 .env 指向 redis://localhost:6379/0 但端口不可达），
    因此这条用例默认跳过 —— 这是如实标注的未验证边界，不是「已验证」。
    """
    from app.services import ip_blacklist_service

    rc = ip_blacklist_service._get_redis_client()
    assert rc is not None, "探测说可达，但工厂拿不到客户端"

    uid = "pytest-totp-replay"
    guard.reset(uid)
    try:
        assert guard.is_replay(uid, 1000) is False
        assert guard.is_replay(uid, 1000) is True
        assert guard.is_replay(uid, 999) is True
        assert guard.is_replay(uid, 1001) is False
        assert rc.get(guard._key(uid)) == "1001"
    finally:
        guard.reset(uid)


def test_redis_unavailable_falls_back_to_memory_and_warns(monkeypatch, caplog):
    """Redis 不可用不得静默：既要降级可用，也要留下明确告警"""
    import logging

    monkeypatch.setattr(guard, "_redis", lambda: None)
    with caplog.at_level(logging.WARNING, logger=guard.__name__):
        assert mfa_manager.verify_mfa(SECRET, _code(), 1) is True
    assert any("降级为进程内存" in r.message for r in caplog.records), caplog.text


def test_redis_error_falls_back_and_warns(monkeypatch, caplog):
    """运行期 Redis 抖动：不得把登录直接打挂，降级后仍要拦住重放"""

    class _Broken:
        def eval(self, *a, **k):
            raise RuntimeError("redis down")

        def delete(self, *a, **k):
            raise RuntimeError("redis down")

    import logging

    monkeypatch.setattr(guard, "_redis", lambda: _Broken())
    code = _code()
    with caplog.at_level(logging.WARNING, logger=guard.__name__):
        assert mfa_manager.verify_mfa(SECRET, code, 1) is True
        assert mfa_manager.verify_mfa(SECRET, code, 1) is False
    assert any("Redis 写入失败" in r.message for r in caplog.records), caplog.text


def test_redis_guard_is_what_blocks_replay(monkeypatch):
    """接线证明：把 Redis 分支换成「永远放行」的假实现，重放就会通过（说明拦截确实来自它）"""

    class _AlwaysAllow:
        def eval(self, *a, **k):
            return 1

        def delete(self, *a, **k):
            return 1

    monkeypatch.setattr(guard, "_redis", lambda: _AlwaysAllow())
    code = _code()
    assert mfa_manager.verify_mfa(SECRET, code, 1) is True
    assert mfa_manager.verify_mfa(SECRET, code, 1) is True  # 假实现下不再拦


# ============================================================
# 四、接线：三个调用点都必须传 user_id
# ============================================================


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_all_call_sites_pass_user_id():
    src = _read(AUTH_ROUTES)
    assert src.count("mfa_manager.verify_mfa(") == 3, "调用点数量变了，请同步检查接线"
    assert src.count("mfa_manager.verify_mfa(user_mfa.secret, code, user_id)") == 3, (
        "有调用点漏传 user_id —— 该路径会静默失去重放防护"
    )


def test_mfa_module_documents_verify_is_not_replay_safe():
    """纯函数 verify 的文档必须写明它不防重放，否则后人会误用"""
    src = _read(os.path.join(ROOT, "app", "utils", "mfa.py"))
    assert "不防重放" in src


def test_replay_guard_does_not_duplicate_redis_factory():
    """不得另起一套 Redis 连接工厂（连接参数/降级策略必须单一来源）"""
    src = _read(os.path.join(ROOT, "app", "utils", "totp_replay_guard.py"))
    assert "Redis.from_url" not in src
    assert "ip_blacklist_service" in src


def test_mfa_manager_is_singleton_instance():
    assert isinstance(mfa_manager, MFAManager)
