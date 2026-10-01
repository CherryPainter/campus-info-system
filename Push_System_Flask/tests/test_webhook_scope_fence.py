#!/usr/bin/env python3
"""
Webhook 接收范围「服务端围栏」回归测试（2026-10-01）

背景：为什么「电量」必须有受众
-------------------------------
电量是**逐人**数据（每人在小程序自配自己的电表 Cookie，按 user_id 采集与落库）。
若某条 webhook 的接收范围是 global（或不限定受众），就会把多个人的用电数据
汇总成同一条消息发进同一个群 —— 属隐私泄露。为此设了三层围栏：

  1. **客户端** `admin-frontend/src/pages/Webhooks.tsx` 的 `MODULE_SCOPE_KIND`
     不给「全局」选项（含 `all` 时同样强制指定受众）；
  2. **写入层** `app/api/webhook_routes.py` 的 `_check_scope_conflict()`
     —— 本文件的主要回归对象：绕过前端直调 API 也存不进越界配置；
  3. **投递层** `app/services/webhook_push_service.py` 的 `send_module_report()`
     拒发 `scope=global` 的电量报告，兜住库里已有的历史越界数据。

同时回归一个曾把功能整体打挂的 bug
----------------------------------
`_normalize_scope_target()` 早期让「`global`（合法，忽略目标）」与「格式非法」
**都返回 None**，而调用方判 `None` 即报「scope_target 格式错误」→
**任何全局 webhook（课表/天气/系统的默认范围）都保存失败**。
现用哨兵 `_INVALID_SCOPE_TARGET` 把两者区分开（用例
`test_create_broadcast_global_allowed` 即该 bug 的守门用例）。

本文件不连数据库：真 Flask + 真 JWT + 真蓝图 + 桩 get_db/模型，用真实 HTTP 往返
覆盖端点层的状态码、错误文案，以及 **PUT 部分字段的合并语义**（PUT 允许只传部分
字段，围栏必须按「与库内现值合并后的最终配置」判定，否则只传 {"scope":"global"}
就能把一条含电量的记录改成越界配置）。

运行：
    cd Push_System_Flask && python -m pytest tests/test_webhook_scope_fence.py -v
"""

import os
import sys
import time
import uuid
from types import SimpleNamespace
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.extensions import limiter
from app.utils.jwt_auth import JWTManager
from app.api.miniapp_routes import _MAX_WEBHOOKS_PER_STUDENT

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"
WECOM_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
STUDENT_ID = 7


# ==================== 桩：数据库与模型 ====================


CTX = {
    "record": None,
    "created": [],
    "updated": [],
    "deleted": [],
    "webhook_count": 0,
    # 受众存在性校验用的「库内已知成员」：
    # users 表里存在的 user_id，以及 student_rosters 里存在的宿舍值
    "student_ids": {1, STUDENT_ID},
    "dorms": {"31栋512", "A栋305"},
}


class _Record:
    """webhook 记录桩（覆盖被测代码会读写的列）"""

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.name = kw.get("name", "旧群")
        self.url = kw.get("url", WECOM_URL)
        self.modules = kw.get("modules", "course")
        self.scope = kw.get("scope", "global")
        self.scope_target = kw.get("scope_target")
        self.owner_user_id = kw.get("owner_user_id")
        self.is_enabled = True
        self.description = None
        self.last_test_status = None
        self.last_test_time = None

    def update_test_status(self, session, status):
        self.last_test_status = status
        session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "modules": self.modules,
            "module_list": [m for m in (self.modules or "").split(",") if m],
            "scope": self.scope,
            "scope_target": self.scope_target,
            "owner_user_id": self.owner_user_id,
            "is_enabled": self.is_enabled,
            "description": self.description,
        }


class _StubWebhook:
    """
    Webhook 模型桩

    注意必须挂上「列属性」：被测代码会写 `Webhook.owner_user_id == x` 这类表达式，
    属性不存在时**求值那一刻**就 AttributeError（与查询本身无关）。
    """

    id = 0
    name = None
    url = None
    modules = None
    scope = None
    scope_target = None
    owner_user_id = None
    is_enabled = None
    description = None

    @staticmethod
    def get_by_id(session, webhook_id):
        return CTX["record"]

    @staticmethod
    def create(**kw):
        kw.pop("session", None)
        CTX["created"].append(kw)
        return _Record(id=100, **kw)

    @staticmethod
    def update(session, webhook_id, **kw):
        CTX["updated"].append(kw)
        rec = CTX["record"]
        if rec is None:
            return False
        for k, v in kw.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        return True

    @staticmethod
    def delete(session, webhook_id):
        CTX["deleted"].append(webhook_id)
        return True

    @staticmethod
    def get_all_webhooks(session, page=None, page_size=None):
        return []

    @staticmethod
    def get_enabled_webhooks(session, **kw):
        return []

    @staticmethod
    def get_webhooks_by_module(session, module):
        return []


class _FakeQuery:
    """只实现被测代码用到的链式调用"""

    def __init__(self, model):
        self._model = model

    def filter(self, *a, **k):
        return self

    def filter_by(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def distinct(self):
        # 受众存在性校验（宿舍）会 .distinct()
        return self

    def limit(self, *a, **k):
        return self

    def offset(self, *a, **k):
        return self

    def all(self):
        """受众存在性校验会 `query(User.id)` / `query(StudentRoster.dorm)` 取列。

        传进来的是**列对象**（不是模型类），故按列所属表名判定返回哪份桩数据。
        """
        table = getattr(getattr(self._model, "table", None), "name", None)
        if table == "users":
            return [(i,) for i in sorted(CTX["student_ids"])]
        if table == "student_rosters":
            return [(d,) for d in sorted(CTX["dorms"])]
        return []

    def first(self):
        from app.model.student_profile import StudentProfile
        from app.model.user import User

        if self._model is User:
            # student_required 的存在性校验：模拟用户存在且启用
            return SimpleNamespace(id=STUDENT_ID)
        if self._model is StudentProfile:
            return SimpleNamespace(student_number="20260001", electricity_cookie="")
        return None

    def count(self):
        # 仅 webhook 数量上限校验用得到；其余（jwt 黑名单等）返回 0 视为无记录
        if getattr(self._model, "__name__", "") in ("_StubWebhook", "Webhook"):
            return CTX["webhook_count"]
        return 0


class _FakeSession:
    def query(self, model, *a, **k):
        return _FakeQuery(model)

    def add(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


# ==================== fixtures ====================


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """每个用例独立的桩状态 + 不连真实 MySQL"""
    CTX["record"] = None
    CTX["created"] = []
    CTX["updated"] = []
    CTX["deleted"] = []
    CTX["webhook_count"] = 0
    CTX["student_ids"] = {1, STUDENT_ID}
    CTX["dorms"] = {"31栋512", "A栋305"}

    monkeypatch.setattr("app.utils.jwt_auth.get_db", lambda: _FakeSession())
    monkeypatch.setattr("app.core.database.get_db", lambda: _FakeSession())
    # webhook_routes 是 `from app.core.database import get_db` 的模块级绑定，
    # 必须单独替换该模块内的名字
    monkeypatch.setattr("app.api.webhook_routes.get_db", lambda: _FakeSession())
    monkeypatch.setattr("app.api.webhook_routes.Webhook", _StubWebhook)
    # miniapp_routes 是在**函数体内** `from app.model.webhook import Webhook`，
    # 所以还要替换模型模块上的名字（只替换 webhook_routes 里的名字对它无效）；
    # 反过来，webhook_routes 是模块级 import，也必须单独替换。两处都要。
    monkeypatch.setattr("app.model.webhook.Webhook", _StubWebhook)
    # 出站 URL 校验（SSRF 防护）的 DNS 环节：默认桩成「解析到公网 IP」，
    # 使测试离线且结果确定。需要覆盖「解析到内网 / 解析失败」分支时，
    # 由用例内部单独替换该函数（见 TestOutboundUrlGuard 之外的 DNS 用例）。
    monkeypatch.setattr("app.utils.url_guard._resolve_host_ips", lambda host, port: {"1.2.3.4"})
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
    from app.api.webhook_routes import webhook_bp

    flask_app.register_blueprint(webhook_bp, url_prefix="/api/admin/webhooks")
    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")

    from app.utils import anon_session

    anon_session.attach_anon_session(flask_app)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _make_token(app, user_id, username, role):
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


@pytest.fixture
def admin_headers(app):
    return {"Authorization": f"Bearer {_make_token(app, 1, 'admin', 'admin')}"}


@pytest.fixture
def student_headers(app):
    return {"Authorization": f"Bearer {_make_token(app, STUDENT_ID, 'wx_student', 'student')}"}


def _create(client, headers, **payload):
    body = {"name": "群", "url": WECOM_URL, "modules": "course", "scope": "global"}
    body.update(payload)
    return client.post("/api/admin/webhooks", json=body, headers=headers)


def _update(client, headers, webhook_id, payload):
    return client.put(f"/api/admin/webhooks/{webhook_id}", json=payload, headers=headers)


# ==================== 写入层围栏：创建 ====================


def test_create_electricity_global_rejected(client, admin_headers):
    """电量 + 全局：隐私越界，必须拒绝且不落库"""
    resp = _create(client, admin_headers, modules="electricity", scope="global")
    assert resp.status_code == 400
    assert "隐私泄露" in resp.get_json()["message"]
    assert CTX["created"] == []


def test_create_all_global_rejected(client, admin_headers):
    """`all` 含电量，与前端 MODULE_SCOPE_KIND 同口径：同样必须指定受众"""
    resp = _create(client, admin_headers, modules="all", scope="global")
    assert resp.status_code == 400
    assert CTX["created"] == []


def test_create_broadcast_global_allowed(client, admin_headers):
    """
    守门用例：不含逐人模块时，全局是合法默认值，必须能创建成功。

    这正是 `_normalize_scope_target()` 早期让 global 与「格式错误」共用一个 None
    导致的功能性回归（当时任何全局 webhook 都返回 400「scope_target 格式错误」）。
    """
    resp = _create(client, admin_headers, modules="course,weather", scope="global")
    assert resp.status_code == 201
    assert len(CTX["created"]) == 1
    assert CTX["created"][0]["scope_target"] is None


def test_create_electricity_dorm_with_target_allowed(client, admin_headers):
    """电量 + 指定宿舍（有受众）：合法"""
    resp = _create(
        client,
        admin_headers,
        modules="electricity",
        scope="dorm",
        scope_target=["31栋512"],
    )
    assert resp.status_code == 201
    assert CTX["created"][0]["scope_target"] == ["31栋512"]


def test_create_electricity_empty_target_rejected(client, admin_headers):
    """电量 + 空受众：会静默不发，属配置陷阱，必须拒绝"""
    resp = _create(
        client, admin_headers, modules="electricity", scope="dorm", scope_target=[]
    )
    assert resp.status_code == 400
    assert "不能为空" in resp.get_json()["message"]
    assert CTX["created"] == []


def test_create_modules_as_array_returns_400_not_500(client, admin_headers):
    """modules 传数组应是明确的 400，而不是 `.split()` 抛错导致的 500"""
    resp = _create(client, admin_headers, modules=["course"], scope="global")
    assert resp.status_code == 400
    assert resp.status_code != 500


def test_create_scope_target_wrong_type_returns_400(client, admin_headers):
    """student 范围的 scope_target 传字符串（非数组）→ 400 格式错误"""
    resp = _create(
        client,
        admin_headers,
        modules="electricity",
        scope="student",
        scope_target="3",
    )
    assert resp.status_code == 400
    assert "格式错误" in resp.get_json()["message"]


# ==================== 写入层围栏：更新（合并语义） ====================


def test_update_only_scope_to_global_rejected(client, admin_headers):
    """
    PUT 只传 {"scope": "global"}：库内模块含电量 → 合并后即越界，必须拒绝。

    这是「围栏按合并后配置判定」的核心用例：若只看本次传入的字段就放过了。
    """
    CTX["record"] = _Record(
        id=5, modules="electricity", scope="dorm", scope_target=["31栋512"]
    )
    resp = _update(client, admin_headers, 5, {"scope": "global"})
    assert resp.status_code == 400
    assert "隐私泄露" in resp.get_json()["message"]
    assert CTX["updated"] == []
    assert CTX["record"].scope == "dorm"  # 库内记录未被改动


def test_update_only_modules_to_electricity_rejected(client, admin_headers):
    """PUT 只传 {"modules": "electricity"}：库内范围是全局 → 拒绝"""
    CTX["record"] = _Record(id=6, modules="course", scope="global", scope_target=None)
    resp = _update(client, admin_headers, 6, {"modules": "electricity"})
    assert resp.status_code == 400
    assert CTX["updated"] == []


def test_update_rename_keeps_existing_target(client, admin_headers):
    """scope 不变、只改名字：应沿用原有受众正常保存"""
    CTX["record"] = _Record(
        id=7, modules="electricity", scope="dorm", scope_target=["A栋305"]
    )
    resp = _update(client, admin_headers, 7, {"name": "改名", "scope": "dorm"})
    assert resp.status_code == 200
    assert CTX["record"].name == "改名"
    assert CTX["record"].scope_target == ["A栋305"]


def test_update_switch_scope_without_target_rejected(client, admin_headers):
    """
    换 scope 类型（student→dorm）却不带新受众：旧 user_id 目标类型不兼容，
    应清空并要求重新指定（含电量 → 触发空受众拦截）。
    """
    CTX["record"] = _Record(
        id=8, modules="electricity", scope="student", scope_target=[7]
    )
    resp = _update(client, admin_headers, 8, {"scope": "dorm"})
    assert resp.status_code == 400
    assert CTX["updated"] == []


def test_update_only_scope_target_uses_db_scope(client, admin_headers):
    """只传 scope_target（不带 scope）：应按库内 scope 规范化，而不是当成 global"""
    CTX["record"] = _Record(
        id=9, modules="electricity", scope="dorm", scope_target=["A栋305"]
    )
    resp = _update(client, admin_headers, 9, {"scope_target": ["31栋512"]})
    assert resp.status_code == 200
    assert CTX["record"].scope_target == ["31栋512"]


def test_update_missing_webhook_returns_404(client, admin_headers):
    CTX["record"] = None
    resp = _update(client, admin_headers, 999, {"name": "x"})
    assert resp.status_code == 404


# ==================== 鉴权 ====================


def test_admin_endpoint_rejects_student_token(client, student_headers):
    """学生 token 不得访问管理端 webhook 接口（admin_required 拦截）"""
    resp = _create(client, student_headers, modules="course", scope="global")
    assert resp.status_code == 403


# ==================== 小程序端：强制字段 / 数量上限 / URL 白名单 ====================


def _student_create(client, headers, **payload):
    body = {"name": "我的群", "url": WECOM_URL, "modules": "course"}
    body.update(payload)
    return client.post("/api/miniapp/webhooks", json=body, headers=headers)


def test_student_create_forces_scope_and_owner(client, student_headers):
    """
    学生在小程序创建时，服务端强制 `scope=student` + `scope_target=[本人]` + `owner=本人`；
    客户端硬塞 global 与**他人 user_id** 一律被覆写（防越权与范围篡改）。
    """
    resp = _student_create(
        client,
        student_headers,
        modules="course,electricity",
        scope="global",
        scope_target=[999],
        owner_user_id=999,
    )
    assert resp.status_code == 201
    kw = CTX["created"][-1]
    assert kw["scope"] == "student"
    assert kw["scope_target"] == [STUDENT_ID]
    assert kw["owner_user_id"] == STUDENT_ID


def test_student_create_trims_modules_by_whitelist(client, student_headers):
    """模块白名单 {course, electricity, weather}：塞入 system 会被裁掉"""
    resp = _student_create(client, student_headers, modules="course,system,electricity")
    assert resp.status_code == 201
    assert CTX["created"][-1]["modules"] == "course,electricity"


def test_student_create_capped(client, student_headers):
    """单人 webhook 数量上限：达上限拒绝（防止广播副本被滥建放大）"""
    CTX["webhook_count"] = _MAX_WEBHOOKS_PER_STUDENT
    resp = _student_create(client, student_headers, modules="course")
    assert resp.status_code == 400
    assert "最多只能创建" in resp.get_json()["message"]
    assert CTX["created"] == []


def test_student_create_below_cap_allowed(client, student_headers):
    CTX["webhook_count"] = _MAX_WEBHOOKS_PER_STUDENT - 1
    resp = _student_create(client, student_headers, modules="course")
    assert resp.status_code == 201


def test_student_create_rejects_non_wecom_host(client, student_headers):
    """学生自建 URL 仅允许企业微信机器人域名（含后缀伪装域名）"""
    for url in (
        "https://evil.example.com/hook",
        "https://qyapi.weixin.qq.com.evil.example.com/hook",
    ):
        resp = _student_create(client, student_headers, url=url)
        assert resp.status_code == 400
    assert CTX["created"] == []


# ==================== 受众成员存在性校验 ====================


def test_create_student_scope_unknown_id_rejected(client, admin_headers):
    """scope=student 指定了不存在的 user_id：保存会成功但静默不发，必须拦住并点名"""
    resp = _create(
        client,
        admin_headers,
        modules="electricity",
        scope="student",
        scope_target=[STUDENT_ID, 4242],
    )
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "4242" in message and "不存在" in message
    assert str(STUDENT_ID) not in message, "合法 ID 不应出现在错误名单里"
    assert CTX["created"] == []


def test_create_dorm_scope_unknown_dorm_rejected(client, admin_headers):
    """scope=dorm 指定了名单里没有的宿舍：同样拦住并点名"""
    resp = _create(
        client,
        admin_headers,
        modules="electricity",
        scope="dorm",
        scope_target=["31栋512", "99栋999"],
    )
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "99栋999" in message
    assert "31栋512" not in message
    assert CTX["created"] == []


def test_create_student_scope_known_id_allowed(client, admin_headers):
    """成员都存在时正常保存（不能因为加校验而误伤正常配置）"""
    resp = _create(
        client,
        admin_headers,
        modules="electricity",
        scope="student",
        scope_target=[STUDENT_ID],
    )
    assert resp.status_code == 201
    assert CTX["created"][0]["scope_target"] == [STUDENT_ID]


def test_update_unknown_target_rejected_without_writing(client, admin_headers):
    """PUT 换受众时同样校验，且不得写库"""
    CTX["record"] = _Record(
        id=11, modules="electricity", scope="dorm", scope_target=["31栋512"]
    )
    resp = _update(client, admin_headers, 11, {"scope_target": ["99栋999"]})
    assert resp.status_code == 400
    assert CTX["updated"] == []
    assert CTX["record"].scope_target == ["31栋512"]


# ==================== 出站 URL 安全校验（SSRF 防护） ====================


@pytest.mark.parametrize(
    "url,expect_kw",
    [
        ("https://127.0.0.1/hook", "内网或保留地址"),
        ("https://10.0.0.5/hook", "内网或保留地址"),
        ("https://192.168.1.10:8443/hook", "内网或保留地址"),
        ("https://169.254.169.254/latest/meta-data/", "内网或保留地址"),
        ("https://[::1]/hook", "内网或保留地址"),
        ("https://localhost/hook", "本机或内网域名"),
        ("https://intranet.local/hook", "本机或内网域名"),
        ("https://db.internal/hook", "本机或内网域名"),
        ("http://qyapi.weixin.qq.com/hook", "https://"),
        ("https://user:pass@qyapi.weixin.qq.com/hook", "用户名或密码"),
    ],
)
def test_create_rejects_unsafe_url(client, admin_headers, url, expect_kw):
    """管理端 URL 不得指向内网/本机、不得降级协议、不得内嵌凭据"""
    resp = _create(client, admin_headers, url=url)
    assert resp.status_code == 400
    assert expect_kw in resp.get_json()["message"]
    assert CTX["created"] == []


def test_update_rejects_unsafe_url(client, admin_headers):
    """PUT 改 URL 走同一套校验"""
    CTX["record"] = _Record(id=12)
    resp = _update(client, admin_headers, 12, {"url": "https://172.16.0.9/hook"})
    assert resp.status_code == 400
    assert CTX["updated"] == []


def test_url_resolving_to_private_ip_rejected(client, admin_headers, monkeypatch):
    """域名解析到内网（第 6 项校验）：即使字面量看起来正常也要拒"""
    monkeypatch.setattr(
        "app.utils.url_guard._resolve_host_ips", lambda host, port: {"192.168.1.7"}
    )
    resp = _create(client, admin_headers, url="https://relay.example.com/hook")
    assert resp.status_code == 400
    assert "解析到内网" in resp.get_json()["message"]


def test_url_dns_failure_rejected(client, admin_headers, monkeypatch):
    """解析失败按拒绝处理（fail-closed），避免放行未知目标"""
    import socket

    def _boom(host, port):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr("app.utils.url_guard._resolve_host_ips", _boom)
    resp = _create(client, admin_headers, url="https://no-such-host.example/hook")
    assert resp.status_code == 400
    assert "无法解析" in resp.get_json()["message"]


def test_url_guard_env_allowlist(client, admin_headers, monkeypatch):
    """逃生舱：显式放行的主机名（精确匹配）可绕过网段判断"""
    monkeypatch.setenv("WEBHOOK_URL_ALLOWED_HOSTS", "intranet-relay.local")
    resp = _create(client, admin_headers, url="https://intranet-relay.local/hook")
    assert resp.status_code == 201


# ==================== /test 端点：历史内网 URL 拦截 + 限流 ====================


def test_test_endpoint_blocks_legacy_private_url(client, admin_headers, monkeypatch):
    """
    护栏加在写入层之前入库的历史数据可能指向内网/本机。
    /test 会真的发起出站请求，必须在发送前再校验一次并**不发出任何请求**。
    """
    CTX["record"] = _Record(id=13, url="https://192.168.1.5/hook")

    called = []

    def _fake_post(*a, **k):
        called.append(a)
        raise AssertionError("不应发出请求")

    monkeypatch.setattr("app.api.webhook_routes.requests.post", _fake_post)

    resp = client.post("/api/admin/webhooks/13/test", headers=admin_headers)
    assert resp.status_code == 400
    assert "测试已拦截" in resp.get_json()["message"]
    assert called == []


def test_test_endpoint_rate_limited(admin_headers, monkeypatch):
    """
    /test 会真实出站，单独设 strict 档（10 次/分钟）。

    测试环境的共享 app 是 `RATELIMIT_ENABLED=False` 初始化的（否则所有用例都会被默认
    限流影响），此时 flask-limiter 连存储都没建（`init_app` 直接 return），单把
    `enabled` 打开也跑不出限流。所以这里另起一个「开了限流」的 app 真正验证一次，
    结束后把启用状态与存储还原，避免影响其它测试文件。

    **请求之间刻意留间隔（0.25s）**：不等间隔地连打 12 次会先撞上全局默认的
    「10 per second」，那样测到的是默认限流 —— 把本端点的限流装饰器删掉，用例
    依然会通过（假阳性，已实测踩到）。留间隔后，只有端点专属的 10/min 会触发。
    """
    CTX["record"] = _Record(id=14)

    monkeypatch.setattr(
        "app.api.webhook_routes.requests.post",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"errcode": 0}, text="ok"),
    )

    from app.api.webhook_routes import webhook_bp

    probe_app = Flask("webhook-ratelimit-probe")
    probe_app.config.update(SECRET_KEY=SECRET, RATELIMIT_ENABLED=True)
    probe_app.extensions["jwt_manager"] = JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    probe_app.register_blueprint(webhook_bp, url_prefix="/api/admin/webhooks")

    was_enabled = limiter.enabled
    limiter.init_app(probe_app)  # 真正初始化存储并启用限流
    try:
        probe_client = probe_app.test_client()
        codes = []
        for _ in range(12):
            codes.append(
                probe_client.post(
                    "/api/admin/webhooks/14/test", headers=admin_headers
                ).status_code
            )
            time.sleep(0.25)
    finally:
        limiter.reset()
        limiter.enabled = was_enabled
        limiter._storage = None  # 还原成「未初始化」状态，避免影响其它测试

    assert codes[0] == 200, f"首次调用应成功，实际 {codes}"
    assert 429 in codes, f"应出现端点限流拦截，实际 {codes}"
