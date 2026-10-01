"""
会话时长单一来源围栏回归测试（B 级修复项 B10）

背景（两处真实的「同一个语义值被抄成 N 份」漂移）：

1. 长短会话的两组时长在登录 / MFA 登录两处各写一遍同样的元组：
   `(7*24*3600, 30*24*3600) if remember_me else (2*3600, 1*24*3600)`。
2. 浏览器端 refresh_token cookie 的 `max_age` 在**三处**各写一个数字：
   - 密码登录：恒 `7 * 24 * 3600`
   - MFA 登录：恒 `7 * 24 * 3600`
   - 刷新：`jwt_manager.refresh_token_expire`
   前两处与 remember_me 完全无关 —— 于是「未勾选记住我」的用户（服务端 Session 24 小时、
   JWT 闲置 2 小时，refresh 应在 2 小时后被服务端拒绝）浏览器里却留着一个 7 天的 cookie：
   关掉浏览器隔天再打开，浏览器照常把 cookie 带上、收到 401「登录会话已闲置过久」，
   cookie 与服务端约束长期处于两个不同的世界。
   同一族问题还包含 MFA 路径的 session_id cookie 恒写 30 天（非 remember_me 也 30 天）。

3. `JWT_REFRESH_IDLE_EXPIRE` / `JWT_REFRESH_ABSOLUTE_EXPIRE` 两个键此前**只**以
   `app.config.get("...", 默认值)` 的形式出现在 app/__init__.py，并未在 Config 中声明，
   即「.env 里写它们毫无作用」的假开关。

修复口径：
- 时长唯一来源 = `app/utils/security.py` 的 `session_limits()` / `refresh_cookie_max_age()`
- cookie 下发唯一收口 = `auth_routes._set_auth_cookies()`
- refresh cookie 的 max_age 由 `generate_tokens` 按**刚写进 token 的同一组数值**推导后
  随返回值下发（`refresh_cookie_max_age` 键），路由不得自行计算

覆盖：
- 纯函数：长短会话取值、三种上限（闲置 / 绝对剩余 / token exp）取最小、边界不为负
- `generate_tokens`：返回值与载荷同源；cookie 有效期不长于 token 自身 exp
- `_set_auth_cookies`：三个 cookie 的 max_age / httponly 逐个断言；无 session_id 时不种
- 接线（真实请求）：
  · /api/auth/refresh 用**不可能值**探测 —— 证明路由确实读 `refresh_cookie_max_age`
  · /api/auth/login 短会话 → refresh cookie 2 小时（修复前恒 7 天），长会话 → 7 天
  · /api/auth/mfa/login 短会话 → refresh cookie 2 小时、session_id cookie 1 天（修复前均 7/30 天）
- 源码守卫：set_cookie 只允许出现在收口函数内；三个调用点齐全；元组魔数不复活

运行：
    cd Push_System_Flask && python -m pytest tests/test_session_lifetime_fence.py -v
"""

import ast
import os
import sys
import time
from unittest import mock

import bcrypt
import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.extensions import limiter
from app.utils.jwt_auth import JWTManager
from app.utils.security import (
    SESSION_LONG_ABSOLUTE,
    SESSION_LONG_IDLE,
    SESSION_SHORT_ABSOLUTE,
    SESSION_SHORT_IDLE,
    refresh_cookie_max_age,
    session_limits,
)

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"
AUTH_ROUTES = os.path.join(ROOT, "app", "api", "auth_routes.py")


# ============================================================
# 工具
# ============================================================


def _cookies(resp):
    """把响应的 Set-Cookie 解析成 {name: {属性: 值}}（属性名统一小写）。"""
    out = {}
    for raw in resp.headers.getlist("Set-Cookie"):
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        name, _, value = parts[0].partition("=")
        attrs = {"value": value}
        for p in parts[1:]:
            k, sep, v = p.partition("=")
            attrs[k.lower()] = v if sep else True
        out[name] = attrs
    return out


def _new_app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
        FORCE_ADMIN_MFA=False,
        RATELIMIT_ENABLED=False,
        AUTH_ENABLED=True,
    )
    limiter.init_app(flask_app)
    return flask_app


def _real_jwt_manager():
    return JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )


# ============================================================
# 一、纯函数：会话时长取值
# ============================================================


def test_short_session_limits():
    assert session_limits(False) == (SESSION_SHORT_IDLE, SESSION_SHORT_ABSOLUTE)
    assert session_limits(False) == (2 * 3600, 24 * 3600)


def test_long_session_limits():
    assert session_limits(True) == (SESSION_LONG_IDLE, SESSION_LONG_ABSOLUTE)
    assert session_limits(True) == (7 * 24 * 3600, 30 * 24 * 3600)


def test_short_session_is_strictly_shorter():
    """短会话的闲置与绝对上限都必须严格小于长会话，否则「记住我」没有意义"""
    short_idle, short_abs = session_limits(False)
    long_idle, long_abs = session_limits(True)
    assert short_idle < long_idle
    assert short_abs < long_abs


# ============================================================
# 二、纯函数：refresh cookie 存活时长（三种上限取最小）
# ============================================================


def test_cookie_follows_idle_for_short_session():
    """短会话：闲置 2 小时是最紧的约束，cookie 就应只活 2 小时（修复前是 7 天）"""
    assert refresh_cookie_max_age(idle_expire=2 * 3600, absolute_expire=24 * 3600) == 2 * 3600


def test_cookie_follows_idle_for_long_session_when_exp_allows():
    """长会话且 refresh token 自身有效期足够长时，cookie 跟随闲置上限 7 天"""
    assert (
        refresh_cookie_max_age(
            idle_expire=7 * 24 * 3600,
            absolute_expire=30 * 24 * 3600,
            refresh_token_expire=60 * 24 * 3600,
        )
        == 7 * 24 * 3600
    )


def test_cookie_capped_by_refresh_token_exp():
    """闲置上限比 token 自身 exp 还长时，cookie 必须以 exp 封顶，否则留死 cookie"""
    assert (
        refresh_cookie_max_age(
            idle_expire=30 * 24 * 3600,
            absolute_expire=90 * 24 * 3600,
            refresh_token_expire=7 * 24 * 3600,
        )
        == 7 * 24 * 3600
    )


def test_cookie_uses_remaining_absolute_not_full_absolute():
    """刷新时绝对上限要扣掉已消耗的时间，否则会把 cookie 续到一个服务端早已失效的时刻"""
    day = 24 * 3600
    assert (
        refresh_cookie_max_age(
            idle_expire=30 * day,
            absolute_expire=30 * day,
            elapsed=20 * day,
        )
        == 10 * day
    )


def test_cookie_is_zero_after_absolute_expired():
    day = 24 * 3600
    assert refresh_cookie_max_age(idle_expire=30 * day, absolute_expire=30 * day, elapsed=31 * day) == 0


def test_cookie_never_negative_on_negative_elapsed():
    """时钟回拨等异常导致的负 elapsed 不能把剩余绝对上限算成负数"""
    assert refresh_cookie_max_age(idle_expire=3600, absolute_expire=7200, elapsed=-99999) == 3600


def test_cookie_defaults_are_short_session():
    """不传参时的默认值必须是短会话，不能是「无上限」"""
    assert refresh_cookie_max_age() == SESSION_SHORT_IDLE


# ============================================================
# 三、generate_tokens：返回值与 token 载荷同源
# ============================================================


def _tokens(**kw):
    return _real_jwt_manager().generate_tokens(
        user_id="1", username="operator", role="operator", **kw
    )


def test_generate_tokens_exposes_cookie_max_age():
    day = 24 * 3600
    t = _tokens(idle_expire=2 * 3600, absolute_expire=day)
    assert t["refresh_cookie_max_age"] == 2 * 3600


def test_generate_tokens_cookie_matches_payload_idle_when_exp_permits():
    """cookie 时长必须与写进载荷的 idle_expire 一致（长会话 + 更长的 token exp）"""
    manager = JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=60 * 24 * 3600,  # exp 比 idle 宽松
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    idle = 7 * 24 * 3600
    t = manager.generate_tokens(
        user_id="1", username="operator", role="operator", idle_expire=idle, absolute_expire=30 * 24 * 3600
    )
    payload = _jwt.decode(t["refresh_token"], SECRET, algorithms=["HS256"])
    assert payload["idle_expire"] == idle
    assert t["refresh_cookie_max_age"] == idle


def test_generate_tokens_cookie_never_outlives_token_exp():
    """核心不变式：cookie 的存活时长不得超过 refresh token 自身的 exp 跨度"""
    t = _tokens(idle_expire=30 * 24 * 3600, absolute_expire=90 * 24 * 3600)
    payload = _jwt.decode(t["refresh_token"], SECRET, algorithms=["HS256"])
    token_lifetime = payload["exp"] - payload["iat"]
    assert t["refresh_cookie_max_age"] <= token_lifetime


def test_generate_tokens_cookie_never_outlives_absolute():
    """核心不变式：任何参数组合下 cookie 都不得超过绝对上限"""
    day = 24 * 3600
    for idle, absolute, elapsed_days in [
        (day, 2 * day, 0),
        (7 * day, 30 * day, 0),
        (30 * day, 30 * day, 25),
        (30 * day, 30 * day, 40),
    ]:
        manager = _real_jwt_manager()
        t = manager.generate_tokens(
            user_id="1",
            username="operator",
            role="operator",
            session_start=time.time() - elapsed_days * day,
            idle_expire=idle,
            absolute_expire=absolute,
        )
        assert t["refresh_cookie_max_age"] <= max(0, absolute - elapsed_days * day)
        assert t["refresh_cookie_max_age"] >= 0
        assert t["refresh_cookie_max_age"] <= idle


def test_generate_tokens_payload_keeps_remember_me_limits():
    """回归防护：载荷里的 idle/absolute 不能被这次改动碰掉（刷新逻辑依赖它们）"""
    day = 24 * 3600
    short = _jwt.decode(
        _tokens(idle_expire=2 * 3600, absolute_expire=day)["refresh_token"], SECRET, algorithms=["HS256"]
    )
    long = _jwt.decode(
        _tokens(idle_expire=7 * day, absolute_expire=30 * day)["refresh_token"],
        SECRET,
        algorithms=["HS256"],
    )
    assert (short["idle_expire"], short["absolute_expire"]) == (2 * 3600, day)
    assert (long["idle_expire"], long["absolute_expire"]) == (7 * day, 30 * day)


# ============================================================
# 四、收口函数 _set_auth_cookies 的真实行为
# ============================================================


def _call_set_cookies(tokens, remember_me=False, session_id=None):
    from app.api.auth_routes import _set_auth_cookies

    app = _new_app()
    with app.test_request_context("/"):
        resp = app.response_class("{}")
        _set_auth_cookies(resp, tokens, remember_me=remember_me, session_id=session_id)
    return _cookies(resp)


def test_set_auth_cookies_uses_token_provided_max_age():
    day = 24 * 3600
    t = _tokens(idle_expire=2 * 3600, absolute_expire=day)
    jar = _call_set_cookies(t, remember_me=False, session_id="SESS-1")

    assert jar["access_token"]["max-age"] == str(t["expires_in"])
    assert jar["refresh_token"]["max-age"] == str(t["refresh_cookie_max_age"])
    assert jar["refresh_token"]["max-age"] == str(2 * 3600)
    assert jar["session_id"]["max-age"] == str(day)


def test_set_auth_cookies_session_cookie_follows_remember_me():
    day = 24 * 3600
    jar = _call_set_cookies(_tokens(idle_expire=7 * day, absolute_expire=30 * day), True, "SESS-1")
    assert jar["session_id"]["max-age"] == str(30 * day)
    assert jar["refresh_token"]["max-age"] == str(7 * day)


def test_set_auth_cookies_all_httponly():
    jar = _call_set_cookies(_tokens(idle_expire=2 * 3600, absolute_expire=24 * 3600), True, "SESS-1")
    for name in ("access_token", "refresh_token", "session_id"):
        assert jar[name]["httponly"] is True, name


def test_set_auth_cookies_skips_session_cookie_when_absent():
    jar = _call_set_cookies(_tokens(idle_expire=2 * 3600, absolute_expire=24 * 3600))
    assert "session_id" not in jar
    assert set(jar) == {"access_token", "refresh_token"}


# ============================================================
# 五、接线：/api/auth/refresh 真实请求（不可能值探测）
# ============================================================


class _FakeJWTManager:
    """只用于探针：返回一个不可能出现的 cookie 时长，证明路由确实读该字段"""

    IMPOSSIBLE = 424242

    def refresh_access_token(self, refresh_token):
        return {
            "access_token": "ACCESS-NEW",
            "refresh_token": "REFRESH-NEW",
            "expires_in": 123,
            "refresh_cookie_max_age": self.IMPOSSIBLE,
        }


def _auth_client(jwt_manager):
    from app.api.auth_routes import auth_bp

    app = _new_app()
    app.extensions["jwt_manager"] = jwt_manager
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    return app.test_client()


def test_refresh_route_reads_cookie_max_age_from_tokens():
    client = _auth_client(_FakeJWTManager())
    client.set_cookie("refresh_token", "R-OLD", domain="localhost")

    resp = client.post("/api/auth/refresh", json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    jar = _cookies(resp)
    assert jar["refresh_token"]["max-age"] == str(_FakeJWTManager.IMPOSSIBLE)
    assert jar["access_token"]["max-age"] == "123"


def test_refresh_route_does_not_reissue_session_cookie(monkeypatch):
    """刷新不得重新下发 session_id cookie（否则会话过期时刻会被悄悄续命）"""
    from app.services.session_service import session_service

    # 让 session 校验通过，才能走到 cookie 下发那一步
    monkeypatch.setattr(
        session_service, "get_session_detail", lambda sid: {"status": "active"}
    )

    client = _auth_client(_FakeJWTManager())
    client.set_cookie("refresh_token", "R-OLD", domain="localhost")
    client.set_cookie("session_id", "SESS-1", domain="localhost")

    resp = client.post("/api/auth/refresh", json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    jar = _cookies(resp)
    assert "session_id" not in jar
    assert set(jar) == {"access_token", "refresh_token"}


# ============================================================
# 六、接线：/api/auth/login 真实请求（DB 打桩，短/长会话两档）
# ============================================================


def _fake_user(password="pw123456", role="operator"):
    user = mock.MagicMock()
    user.id = 1
    user.username = "operator"
    user.role = role
    user.is_active = True
    user.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user.to_dict.return_value = {"id": 1, "username": "operator", "role": role}
    return user


def _patch_login(monkeypatch, user, mfa_row=None):
    """把登录路由的 DB 与非目标逻辑打桩，保留 cookie / token 的真实实现。

    只替换四类外部依赖：get_db（返回按模型分派的假 session）、登录日志写入、
    IP 黑名单判定、登录限流；密码校验用真实 bcrypt 哈希真跑一遍。
    """
    from app.model.user import User
    from app.model.user_mfa import UserMFA

    def _query(model):
        m = mock.MagicMock()
        if model is User:
            m.filter_by.return_value.first.return_value = user
        elif model is UserMFA:
            m.filter_by.return_value.first.return_value = mfa_row
        else:  # LoginLog 等：一律返回 None，避免打成"有上一个未结束会话"
            m.filter_by.return_value.first.return_value = None
        m.filter.return_value.first.return_value = None
        m.filter.return_value.order_by.return_value.first.return_value = None
        return m

    def _get_db():
        s = mock.MagicMock()
        s.query.side_effect = _query
        return s

    monkeypatch.setattr("app.core.database.get_db", _get_db)
    import app.api.auth_routes as ar

    monkeypatch.setattr(ar, "_record_login_log", lambda *a, **k: 99)
    monkeypatch.setattr(ar, "_ip_is_blocked", lambda ip: False)
    monkeypatch.setattr(ar, "_check_login_rate_limit", lambda: None)


def _patch_session_service(monkeypatch, session_id="SESS-1"):
    from app.services.session_service import session_service

    def _create_session(**kwargs):
        s = mock.MagicMock()
        s.session_id = session_id
        return s

    monkeypatch.setattr(session_service, "create_session", _create_session)
    monkeypatch.setattr(session_service, "delete_all_user_sessions", lambda *a, **k: 0)


@pytest.fixture
def login_client(monkeypatch):
    _patch_login(monkeypatch, _fake_user())
    _patch_session_service(monkeypatch)
    client = _auth_client(_real_jwt_manager())
    return client


def test_login_short_session_refresh_cookie_is_two_hours(login_client):
    """修复前这里恒为 7 天，与服务端「闲置 2 小时即失效」直接矛盾。

    断言写**字面量**而不是 SESSION_SHORT_IDLE：拿常量去断言常量，改小常量后断言
    会跟着一起变，等于没锁住（反向验证脚本第一次跑就是这条没变红）。
    """
    resp = login_client.post(
        "/api/auth/login", json={"username": "operator", "password": "pw123456"}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    jar = _cookies(resp)
    assert jar["refresh_token"]["max-age"] == str(2 * 3600)
    assert jar["session_id"]["max-age"] == str(24 * 3600)


def test_login_long_session_refresh_cookie_is_seven_days(login_client):
    resp = login_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "pw123456", "remember_me": True},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    jar = _cookies(resp)
    assert jar["refresh_token"]["max-age"] == str(7 * 24 * 3600)
    assert jar["session_id"]["max-age"] == str(30 * 24 * 3600)


# ============================================================
# 七、接线：/api/auth/mfa/login 真实请求（修复前 session_id 恒 30 天）
# ============================================================


def _mfa_token(remember_me=False):
    now = int(time.time())
    payload = {
        "user_id": "1",
        "username": "operator",
        "role": "admin",
        "ip": "127.0.0.1",
        "agent": "pytest",
        "remember_me": remember_me,
        "type": "mfa",
        "exp": now + 600,
    }
    return _jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
def mfa_client(monkeypatch):
    mfa_row = mock.MagicMock()
    mfa_row.secret = "JBSWY3DPEHPK3PXP"
    mfa_row.enabled = True
    _patch_login(monkeypatch, _fake_user(role="admin"), mfa_row=mfa_row)
    _patch_session_service(monkeypatch)

    from app.utils.mfa import mfa_manager

    monkeypatch.setattr(mfa_manager, "verify_mfa", lambda secret, code, user_id=None: True)

    from app.api.auth_routes import auth_bp

    app = _new_app()
    app.extensions["jwt_manager"] = _real_jwt_manager()
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    return app.test_client()


def test_mfa_login_short_session_cookies(mfa_client):
    resp = mfa_client.post(
        "/api/auth/login/mfa", json={"mfa_token": _mfa_token(False), "code": "123456"}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    jar = _cookies(resp)
    assert jar["refresh_token"]["max-age"] == str(2 * 3600)
    # 修复前这里是硬编码 30 天，而服务端 Session 只有 24 小时
    assert jar["session_id"]["max-age"] == str(24 * 3600)


def test_mfa_login_long_session_cookies(mfa_client):
    resp = mfa_client.post(
        "/api/auth/login/mfa", json={"mfa_token": _mfa_token(True), "code": "123456"}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    jar = _cookies(resp)
    assert jar["refresh_token"]["max-age"] == str(7 * 24 * 3600)
    assert jar["session_id"]["max-age"] == str(30 * 24 * 3600)


# ============================================================
# 八、源码守卫：cookie 下发必须收口，魔数不得复活
# ============================================================

_AUTH_COOKIE_NAMES = {"access_token", "refresh_token", "session_id"}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _tree():
    return ast.parse(_read(AUTH_ROUTES))


def _func_name_of_call(tree, target_name):
    """返回所有调用 target_name 的语句所在的函数名列表"""
    found = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name == target_name and self.stack:
                found.append(self.stack[-1])
            self.generic_visit(node)

    V().visit(tree)
    return found


def test_set_auth_cookies_defined_once():
    tree = _tree()
    defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert defs.count("_set_auth_cookies") == 1, "收口函数必须唯一"


def test_all_three_routes_go_through_helper():
    """登录 / 刷新 / MFA 登录三条路径都必须调用收口函数，缺一条就红"""
    callers = _func_name_of_call(_tree(), "_set_auth_cookies")
    assert sorted(callers) == ["login", "login_mfa", "refresh"], callers


def test_set_cookie_only_inside_helper():
    """set_cookie 只允许出现在 _set_auth_cookies 内，防止再被抄回路由里"""
    owners = set(_func_name_of_call(_tree(), "set_cookie"))
    assert owners == {"_set_auth_cookies"}, owners


def _set_cookie_max_age_exprs():
    """收集所有 set_cookie 调用里 max_age 实参的源码文本（AST 层面，不受注释/字符串干扰）"""
    exprs = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name == "set_cookie":
                for kw in node.keywords:
                    if kw.arg == "max_age":
                        exprs.append(ast.unparse(kw.value))
            self.generic_visit(node)

    V().visit(_tree())
    return exprs


def test_set_cookie_max_age_comes_only_from_two_sources():
    """三个 cookie 的时长必须分别取自 token 返回值与 session_limits，不得是字面量。

    用 AST 取 max_age 实参源码，而不是 grep 文件文本 —— 后者会把解释这段历史的注释
    一起判为违规（本文件第一版就踩了这个坑）。
    """
    assert sorted(_set_cookie_max_age_exprs()) == sorted(
        [
            "tokens['expires_in']",
            "tokens['refresh_cookie_max_age']",
            "session_limits(remember_me)[1]",
        ]
    )


def _pure_number_binops(tree):
    """找出所有「仅由数字常量构成的乘/加表达式」（即 7 * 24 * 3600 这类魔数）"""

    def _is_num(n):
        return isinstance(n, ast.Constant) and isinstance(n.value, int)

    found = []

    class V(ast.NodeVisitor):
        def visit_BinOp(self, node):
            if (
                isinstance(node.op, (ast.Mult, ast.Add))
                and _is_num(node.left)
                and _is_num(node.right)
            ):
                found.append(ast.unparse(node))
            self.generic_visit(node)

    V().visit(tree)
    return found


def test_routes_no_longer_hardcode_time_literals():
    """时长魔数不得在 auth_routes.py 里复活（注释与字符串不算）"""
    assert _pure_number_binops(_tree()) == [], "auth_routes.py 存在硬编码时长表达式"


def test_routes_no_longer_hardcode_session_limit_tuple():
    """两组时长的元组写法不得复活（必须来自 session_limits）"""
    src = _read(AUTH_ROUTES)
    assert "if remember_me else (2 * 3600" not in src
    assert "session_limits(" in src


def test_config_declares_refresh_expire_keys():
    """假开关修复：两个键必须真的在 Config 中声明，否则 .env 里写它们毫无作用"""
    from app.core.config import Config

    assert hasattr(Config, "JWT_REFRESH_IDLE_EXPIRE")
    assert hasattr(Config, "JWT_REFRESH_ABSOLUTE_EXPIRE")
    assert isinstance(Config.JWT_REFRESH_IDLE_EXPIRE, int)
    assert isinstance(Config.JWT_REFRESH_ABSOLUTE_EXPIRE, int)


def test_env_example_documents_refresh_expire_keys():
    from app.core.config import Config

    src = _read(os.path.join(ROOT, ".env.example"))
    assert "JWT_REFRESH_IDLE_EXPIRE=" in src
    assert "JWT_REFRESH_ABSOLUTE_EXPIRE=" in src
    # 值必须与代码内默认一致，避免样例把人带偏
    assert f"JWT_REFRESH_IDLE_EXPIRE={Config.JWT_REFRESH_IDLE_EXPIRE}" in src
    assert f"JWT_REFRESH_ABSOLUTE_EXPIRE={Config.JWT_REFRESH_ABSOLUTE_EXPIRE}" in src
