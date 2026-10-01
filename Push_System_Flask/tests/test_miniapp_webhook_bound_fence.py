#!/usr/bin/env python3
"""
小程序「第三方消息通知」（学生自建 webhook）绑定围栏回归测试（B 级加固项 B7）

背景
----
`app/api/miniapp_routes.py` 里 5 个学生自建 webhook 路由原本用 `@student_required`，
只校验「是学生角色」，**不校验身份是否已绑定**；而其余学生端业务接口一律
`@student_bound_required`。这造成两处偏差：

  1. **能力不可用**：`scope_target` 定位的是本人课表/电量，未绑定学生没有
     `student_profiles` 记录、没有班级/宿舍归属，进去只能看到空列表且保存必失败
     —— 一个走不通的死胡同；
  2. **不必要的出站面**：`POST /webhooks/<id>/test` 会真的向 qyapi 发起请求，
     不应让「只完成登录、身份未核验」的账号获得该能力。

修复（配对改动，缺一不可）
--------------------------
* **服务端**（最终防线）：5 个路由 `@student_required` → `@student_bound_required`，
  未绑定一律 403 + `code=STUDENT_NOT_BOUND`；
* **前端**：`miniapp-frontend/src/pages/settings/index.tsx` 的「第三方消息通知」入口
  用 `useLoginGuard` 挡游客，并补挂 `useBindStatusWatcher`（该页不是 Tab 页，
  原本没有绑定态监察）——否则未绑定用户点进去只会看到死胡同。

本文件另含一条**反向围栏**（重要）：绑定流程自身的 4 个路由
（`/user/me`、`/student/bind-status`、`/student/schools`、`/student/bind`）
**必须**保持 `@student_required`。若有人「顺手全部改成 bound」，未绑定用户将
无法再查询绑定状态、无法提交绑定 —— 绑定流程被彻底锁死，且服务端单测极难发现。
故此处用「装饰器清单 + 路径白名单」把它钉住。

运行：
    cd Push_System_Flask && python -m pytest tests/test_miniapp_webhook_bound_fence.py -v
"""

import ast
import os
import sys
import time
import uuid
from types import SimpleNamespace

import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.extensions import limiter
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"
WECOM_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
STUDENT_ID = 7
ROUTES_FILE = os.path.join(ROOT, "app", "api", "miniapp_routes.py")

# 5 个学生自建 webhook 路由（method, path）
WEBHOOK_CALLS = [
    ("get", "/api/miniapp/webhooks"),
    ("post", "/api/miniapp/webhooks"),
    ("put", "/api/miniapp/webhooks/1"),
    ("delete", "/api/miniapp/webhooks/1"),
    ("post", "/api/miniapp/webhooks/1/test"),
]

# 绑定流程自身的路由：必须保持 student_required（未绑定用户也要能走完绑定）
BIND_FLOW_PATHS = {
    "/user/me",
    "/student/bind-status",
    "/student/schools",
    "/student/bind",
}


# ==================== 桩：数据库与模型 ====================

CTX = {
    "bound": True,
    "created": [],
    "record": None,
}


class _Record:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.name = kw.get("name", "我的群")
        self.url = kw.get("url", WECOM_URL)
        self.modules = kw.get("modules", "course")
        self.scope = kw.get("scope", "student")
        self.scope_target = kw.get("scope_target")
        self.owner_user_id = kw.get("owner_user_id")
        self.is_enabled = True
        self.description = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "modules": self.modules,
            "scope": self.scope,
            "scope_target": self.scope_target,
            "owner_user_id": self.owner_user_id,
            "is_enabled": self.is_enabled,
        }


class _Col:
    """假列对象：支持 `Webhook.created_at.desc()` / `Webhook.owner_user_id == x` 这类表达式"""

    def desc(self):
        return self

    def asc(self):
        return self

    def is_(self, *a, **k):
        return self

    def __eq__(self, other):
        return self

    def __ne__(self, other):
        return self

    def __hash__(self):
        return id(self)


class _StubWebhook:
    """Webhook 模型桩（挂列属性：被测代码会求值 `Webhook.owner_user_id == x`）"""

    id = _Col()
    name = _Col()
    url = _Col()
    modules = _Col()
    scope = _Col()
    scope_target = _Col()
    owner_user_id = _Col()
    is_enabled = _Col()
    description = _Col()
    created_at = _Col()

    @staticmethod
    def get_by_id(session, webhook_id):
        return CTX["record"]

    @staticmethod
    def create(**kw):
        kw.pop("session", None)
        CTX["created"].append(kw)
        return _Record(**kw)

    @staticmethod
    def update(session, webhook_id, **kw):
        return True

    @staticmethod
    def delete(session, webhook_id):
        return True


class _FakeQuery:
    def __init__(self, model):
        self._model = model

    def filter(self, *a, **k):
        return self

    def filter_by(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def offset(self, *a, **k):
        return self

    def all(self):
        return []

    def count(self):
        return 0

    def first(self):
        from app.model.student_profile import StudentProfile
        from app.model.user import User

        if self._model is User:
            # student_required 的存在性校验：模拟用户存在且启用
            return SimpleNamespace(id=STUDENT_ID)
        if self._model is StudentProfile:
            # CTX["bound"] 决定「有无 student_number」——本文件的核心开关
            if not CTX["bound"]:
                return None
            return SimpleNamespace(
                user_id=STUDENT_ID,
                student_number="20260001",
                school="某某大学",
                class_name="计算机 2026-1 班",
                college="计算机学院",
                major="计算机科学与技术",
                dorm="31栋512",
                to_dict=lambda: {"user_id": STUDENT_ID, "student_number": "20260001"},
            )
        return CTX["record"]


class _FakeSession:
    def query(self, model, *a, **k):
        return _FakeQuery(model)

    def add(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, *a, **k):
        pass

    def close(self):
        pass


# ==================== fixtures ====================


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    CTX["bound"] = True
    CTX["created"] = []
    CTX["record"] = None

    monkeypatch.setattr("app.utils.jwt_auth.get_db", lambda: _FakeSession())
    monkeypatch.setattr("app.core.database.get_db", lambda: _FakeSession())
    # miniapp_routes 是在**函数体内** `from app.model.webhook import Webhook`，
    # 故替换模型模块上的名字即可对其生效
    monkeypatch.setattr("app.model.webhook.Webhook", _StubWebhook)
    # student_schools 走组织树服务，这里桩成空列表避免触库
    monkeypatch.setattr(
        "app.services.org_unit_service.OrgUnitService.list_schools", staticmethod(lambda: [])
    )
    yield


@pytest.fixture(scope="module")
def app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
        RATELIMIT_ENABLED=False,
    )
    flask_app.extensions["jwt_manager"] = JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    limiter.init_app(flask_app)

    from app.api.miniapp_routes import miniapp_bp

    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _make_token(app, user_id, role="student"):
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "username": "wx_student",
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


@pytest.fixture
def student_headers(app):
    return {"Authorization": f"Bearer {_make_token(app, STUDENT_ID)}"}


def _call(client, headers, method, path, **kw):
    return getattr(client, method)(path, headers=headers, **kw)


def _code(resp):
    try:
        return (resp.get_json() or {}).get("code")
    except Exception:  # noqa: BLE001 - 非 JSON 响应（如 500 HTML）不算命中
        return None


def _post_body(path):
    """POST /webhooks 需要合法 body 才能走到业务逻辑；其余 POST 无需 body"""
    if path.rstrip("/") == "/api/miniapp/webhooks":
        return {"json": {"name": "我的群", "url": WECOM_URL, "modules": "course"}}
    return {}


# ==================== 一、源码围栏：装饰器与路由的绑定关系 ====================


def _load_route_functions():
    """解析 miniapp_routes.py，返回 [(func_name, {route_paths}, {decorator_names})]"""
    with open(ROUTES_FILE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        paths, names = set(), set()
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "route"
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                paths.add(dec.args[0].value)
            elif isinstance(dec, ast.Name):
                names.add(dec.id)
            elif isinstance(dec, ast.Attribute):
                names.add(ast.unparse(dec))
            elif isinstance(dec, ast.Call):
                names.add(ast.unparse(dec.func))
        out.append((node.name, paths, names))
    return out


def _route_funcs(substr):
    """取路由路径含 substr 的函数（按路径判定，函数改名也不影响围栏）"""
    return [
        (name, paths, names)
        for name, paths, names in _load_route_functions()
        if any(substr in p for p in paths)
    ]


def test_webhook_routes_require_binding():
    """5 个 webhook 路由必须挂 @student_bound_required（而不是 @student_required）"""
    funcs = _route_funcs("webhooks")
    assert len(funcs) == 5, f"webhook 路由数量异常：{[f[0] for f in funcs]}"
    for name, paths, names in funcs:
        assert "student_bound_required" in names, f"{name} 未挂绑定校验（{paths}）"
        assert "student_required" not in names, f"{name} 仍是 student_required（{paths}）"


def test_bind_flow_routes_stay_student_required():
    """绑定流程自身的 4 个路由必须保持 @student_required（否则绑定被锁死）

    反向围栏：若有人把全文件统一改成 bound，未绑定用户将无法查询绑定状态、
    无法提交绑定 —— 这是比原问题更严重的功能性回归。
    """
    found = set()
    for _name, paths, names in _load_route_functions():
        hit = paths & BIND_FLOW_PATHS
        if not hit:
            continue
        found |= hit
        assert "student_required" in names, f"{hit} 丢了 student_required"
        assert "student_bound_required" not in names, f"{hit} 被误改成 bound，绑定流程会锁死"
    assert found == BIND_FLOW_PATHS, f"绑定流程路由缺失：{BIND_FLOW_PATHS - found}"


def test_no_other_route_uses_bare_student_required():
    """除绑定流程白名单外，不该再有裸 @student_required 路由

    新增学生端业务接口时应默认用 bound（未绑定账号本就无业务数据可读）；
    确有必要保持裸 student_required 的，请加进本文件的 BIND_FLOW_PATHS 并说明理由。
    """
    offenders = []
    for name, paths, names in _load_route_functions():
        if "student_required" not in names:
            continue
        if paths & BIND_FLOW_PATHS:
            continue
        offenders.append((name, sorted(paths)))
    assert not offenders, (
        "发现未加绑定校验的学生端路由（未绑定账号无业务数据，应改为 "
        f"@student_bound_required）：{offenders}"
    )


# ==================== 二、真实 HTTP：未绑定一律 403 ====================


@pytest.mark.parametrize("method,path", WEBHOOK_CALLS)
def test_unbound_student_rejected(client, student_headers, method, path):
    """未绑定令牌访问 5 个 webhook 路由 → 403（服务端最终防线）"""
    CTX["bound"] = False
    resp = _call(client, student_headers, method, path, **_post_body(path))
    assert resp.status_code == 403, f"{method.upper()} {path} 应 403，实际 {resp.status_code}"
    assert _code(resp) == "STUDENT_NOT_BOUND"


@pytest.mark.parametrize("method,path", WEBHOOK_CALLS)
def test_unbound_writes_nothing(client, student_headers, method, path):
    """未绑定时不得产生任何写入（在到达业务逻辑前就被拦下）"""
    CTX["bound"] = False
    _call(client, student_headers, method, path, **_post_body(path))
    assert CTX["created"] == []


@pytest.mark.parametrize("method,path", WEBHOOK_CALLS)
def test_bound_student_passes_fence(client, student_headers, method, path):
    """已绑定令牌不再被绑定围栏拦（反向用例：避免过度拦截把功能打死）"""
    CTX["bound"] = True
    resp = _call(client, student_headers, method, path, **_post_body(path))
    assert not (resp.status_code == 403 and _code(resp) == "STUDENT_NOT_BOUND"), (
        f"{method.upper()} {path} 已绑定仍被绑定围栏拦下"
    )
    assert resp.status_code < 500, f"{method.upper()} {path} 出现 5xx：{resp.status_code}"


def test_bound_create_actually_creates(client, student_headers):
    """已绑定 → 能真正创建，且服务端仍强制 scope=student / owner=本人（回归无回退）"""
    CTX["bound"] = True
    resp = client.post(
        "/api/miniapp/webhooks",
        json={"name": "我的群", "url": WECOM_URL, "modules": "course"},
        headers=student_headers,
    )
    assert resp.status_code == 201
    assert len(CTX["created"]) == 1
    assert CTX["created"][0]["scope"] == "student"
    assert CTX["created"][0]["owner_user_id"] == STUDENT_ID


# ==================== 三、反向围栏：绑定流程必须仍对未绑定用户开放 ====================


BIND_FLOW_CALLS = [
    ("get", "/api/miniapp/user/me", {}),
    ("get", "/api/miniapp/student/bind-status", {}),
    ("get", "/api/miniapp/student/schools", {}),
    ("post", "/api/miniapp/student/bind", {"json": {}}),
]


@pytest.mark.parametrize("method,path,kw", BIND_FLOW_CALLS)
def test_bind_flow_not_blocked_by_binding(client, student_headers, method, path, kw):
    """未绑定令牌访问绑定流程路由 → 不得是 403 STUDENT_NOT_BOUND

    否则用户永远无法查询绑定状态 / 提交绑定，绑定流程彻底不可达。
    """
    CTX["bound"] = False
    resp = _call(client, student_headers, method, path, **kw)
    assert not (resp.status_code == 403 and _code(resp) == "STUDENT_NOT_BOUND"), (
        f"{method.upper()} {path} 被绑定围栏拦住了，绑定流程将不可达"
    )


# ==================== 四、鉴权基线仍成立 ====================


def test_no_token_rejected(client):
    """无令牌 → 401（未因改动而放行）"""
    resp = client.get("/api/miniapp/webhooks")
    assert resp.status_code == 401


def test_admin_token_rejected(client, app):
    """管理员令牌不得访问学生端 webhook（角色互斥仍成立）"""
    headers = {"Authorization": f"Bearer {_make_token(app, 1, role='admin')}"}
    resp = client.get("/api/miniapp/webhooks", headers=headers)
    assert resp.status_code == 403
    assert _code(resp) != "STUDENT_NOT_BOUND"


# ==================== 五、前端配对改动（源码守卫） ====================

SETTINGS_TSX = os.path.join(
    os.path.dirname(ROOT), "miniapp-frontend", "src", "pages", "settings", "index.tsx"
)


def _settings_src():
    if not os.path.exists(SETTINGS_TSX):
        pytest.skip("未找到小程序设置页源码（可能只检出后端子集）")
    with open(SETTINGS_TSX, encoding="utf-8") as fh:
        return fh.read()


def test_settings_page_wires_guard_hooks():
    """设置页确实挂了两个 hook（而非只 import 未调用）"""
    src = _settings_src()
    assert "useLoginGuard" in src, "设置页未引入登录守卫"
    assert "useBindStatusWatcher()" in src, "设置页未挂绑定状态监察"
    assert "const { guard } = useLoginGuard();" in src, "登录守卫未取用 guard"


def _entry_body():
    """取出 goThirdPartyNotify 函数体，避免用「全文包含」这种易被无关代码满足的断言"""
    import re

    src = _settings_src()
    m = re.search(r"const goThirdPartyNotify = \(\) => \{(.*?)\n  \};", src, re.S)
    assert m, "未找到 goThirdPartyNotify 函数"
    return m.group(1)


def test_settings_entry_blocked_for_guest():
    """入口包在登录守卫里：游客点击只提示、不进入

    服务端收紧后若前端不配对，未绑定/游客点「第三方消息通知」会进到死胡同；
    这条守卫防止「前端改动被回退」造成体验回退。
    """
    body = _entry_body()
    assert "guard(" in body, "入口未包在登录守卫里"
    assert "/pages/third-party-notify/index" in body, "入口跳转目标缺失"


def test_settings_entry_blocked_during_bind_guide():
    """绑定引导期不进入（复用 bindGuard.ts）：此时业务接口必 403，进去是死胡同"""
    body = _entry_body()
    assert "isBindGuideActive()" in body, "入口未做绑定引导期判断"
