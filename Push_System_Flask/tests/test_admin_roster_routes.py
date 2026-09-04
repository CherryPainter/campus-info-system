"""
学生名单管理接口回归测试（v6.16.0）

覆盖：
- 测试 1: GET /api/admin/roster/schools 顶层返回 schools 数组，含重庆科创职业学院
- 测试 2: 学生 token 无权访问（admin_required 拦截 → 403）

设计：复用 auth_middleware + admin_required；不依赖真实 MySQL，造 admin token 直接打
路由。重点：验证 api_success(schools=...) 走 **extra 路径后 schools 字段位于响应顶层，
避免管理端前端误从 res.data 取导致下拉空（2026-09-01 截图 bug）。

运行：
    cd Push_System_Flask && python -m pytest tests/test_admin_roster_routes.py -v
"""

import os
import sys
import time
import uuid
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.extensions import limiter
from app.services.student_roster_service import _merge_binding
from app.utils.auth_middleware import admin_required
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _make_token(user_id, username, role):
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
    return _jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
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
    from app.api.admin_roster_routes import admin_roster_bp

    flask_app.register_blueprint(admin_roster_bp, url_prefix="/api/admin/roster")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ==================== /schools 端点 ====================


def test_schools_returns_top_level_array(client):
    """回归：api_success(schools=...) 走 **extra 路径，schools 字段须在响应顶层
    （避免管理端前端误从 res.data 取导致「新建学生」下拉空，2026-09-01 截图）"""
    token = _make_token(1, "admin", "admin")
    resp = client.get(
        "/api/admin/roster/schools", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    # 关键断言：schools 在顶层（**extra 路径），而非 data 字段
    assert "schools" in body
    assert isinstance(body["schools"], list)
    # 必须包含重庆科创职业学院（学生绑定核心学校）
    assert "重庆科创职业学院" in body["schools"]


def test_schools_rejects_student_token(client):
    """学生 token 无权访问名单管理接口（admin_required 拦截）"""
    token = _make_token(2, "wx_student", "student")
    resp = client.get(
        "/api/admin/roster/schools", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


# ==================== /students 列表端点（数据字段结构回归） ====================


def test_list_returns_data_array_not_items(client):
    """回归：列表数据须位于 data 字段（前端 UserManagementRoster.load() 读 res.data / res.total）。

    历史上曾误写成 api_success(total=..., items=...)，items 走 **extra 路径位于响应顶层，
    而前端读 res.data → 恒为 undefined → 名单列表永远为空（"加了学生也不显示"）。
    修复后须用 data= 包裹列表。
    """
    fake_items = [
        {
            "id": 1,
            "school": "重庆科创职业学院",
            "student_number": "20260001",
            "class_name": "计算机2301",
            "real_name": "张三",
            "remark": "",
            "is_active": True,
            "created_at": "2026-09-01 00:00:00",
            "updated_at": "2026-09-01 00:00:00",
        }
    ]
    with mock.patch(
        "app.api.admin_roster_routes.StudentRosterService"
    ) as svc:
        svc.list.return_value = {
            "items": fake_items,
            "total": 1,
            "page": 1,
            "page_size": 20,
        }
        token = _make_token(1, "admin", "admin")
        resp = client.get(
            "/api/admin/roster/students",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    # 关键断言：列表在 data，而非顶层 items
    assert "data" in body
    assert isinstance(body["data"], list)
    assert body["data"][0]["student_number"] == "20260001"
    assert "items" not in body
    # 总数在 total（前端读 res.total）
    assert body["total"] == 1


# ==================== 绑定状态聚合（纯函数） ====================


def test_merge_binding_attaches_claimed_user():
    """名单条目按 (school, student_number) 命中已绑定身份时，应写入 bound_user_id/username。"""
    items = [
        {"school": "重庆科创职业学院", "student_number": "20260001", "class_name": "计算机2301"},
        {"school": "重庆科创职业学院", "student_number": "20260002", "class_name": "计算机2301"},
    ]
    profiles = [
        {
            "school": "重庆科创职业学院",
            "student_number": "20260001",
            "user_id": 7,
            "updated_at": "2026-09-01 10:00:00",
        }
    ]
    users = [{"id": 7, "username": "wx_zhang"}]
    _merge_binding(items, profiles, users)

    assert items[0]["bound_user_id"] == 7
    assert items[0]["bound_username"] == "wx_zhang"
    assert items[0]["bound_at"] == "2026-09-01 10:00:00"
    # 未被认领的条目保持 None
    assert items[1]["bound_user_id"] is None
    assert items[1]["bound_username"] is None


def test_merge_binding_no_profile_means_unbound():
    """没有任何已绑定身份时，所有条目均为未绑定（None），不抛错。"""
    items = [{"school": "重庆大学", "student_number": "20260099", "class_name": "物理2301"}]
    _merge_binding(items, [], [])
    assert items[0]["bound_user_id"] is None
    assert items[0]["bound_username"] is None
    assert items[0]["bound_at"] is None


# ==================== service 层 college/major 透传（组织维度，2026-09-04） ====================


class _FakeQuery:
    """链式 mock：filter_by/filter 原样返回自身，first 可配置。"""

    def __init__(self, first_result=None):
        self._first_result = first_result

    def filter_by(self, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_result

    def count(self):
        return 0

    def all(self):
        return []

    def order_by(self, *args):
        return self

    def offset(self, n):
        return self

    def limit(self, n):
        return self


class _FakeSession:
    """最小可用 session 替身：记录被 add 的对象，支持 commit/rollback/refresh/close。"""

    def __init__(self, query_first=None):
        self.added = []
        self._query_first = query_first

    def query(self, model):
        return _FakeQuery(self._query_first)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, row):
        pass

    def close(self):
        pass


def test_service_create_persists_college_major():
    """create() 应把学院/专业透传到 StudentRoster 实例（名单组织维度落库）。"""
    from app.model.student_roster import StudentRoster
    from app.services.student_roster_service import StudentRosterService

    fake = _FakeSession()
    with mock.patch("app.services.student_roster_service.get_db", return_value=fake):
        row, err = StudentRosterService.create(
            school="重庆科创职业学院",
            student_number="20260001",
            class_name="计算机2301",
            college="信息与人工智能学院",
            major="计算机应用技术",
            real_name="张三",
        )
    assert err is None
    assert row is not None
    assert isinstance(row, StudentRoster)
    assert row.college == "信息与人工智能学院"
    assert row.major == "计算机应用技术"
    assert row.class_name == "计算机2301"


def test_service_update_persists_college_major():
    """update() 应能修改学院/专业。"""
    from app.model.student_roster import StudentRoster
    from app.services.student_roster_service import StudentRosterService

    existing = StudentRoster(
        school="重庆科创职业学院",
        student_number="20260001",
        class_name="计算机2301",
        college="旧学院",
        major="旧专业",
    )
    fake = _FakeSession(query_first=existing)
    with mock.patch("app.services.student_roster_service.get_db", return_value=fake):
        row, err = StudentRosterService.update(
            roster_id=1,
            class_name="计算机2302",
            college="新学院",
            major="新专业",
        )
    assert err is None
    assert row is existing
    assert row.college == "新学院"
    assert row.major == "新专业"
    assert row.class_name == "计算机2302"


def test_service_create_batch_reads_college_major():
    """create_batch() 应读取行内 college/major 并写入 StudentRoster 实例。"""
    from app.model.student_roster import StudentRoster
    from app.services.student_roster_service import StudentRosterService

    fake = _FakeSession()
    rows = [
        {
            "school": "重庆科创职业学院",
            "student_number": "20260001",
            "class_name": "计算机2301",
            "college": "信息与人工智能学院",
            "major": "计算机应用技术",
        },
        {
            "school": "重庆科创职业学院",
            "student_number": "20260002",
            "class_name": "计算机2301",
            # 缺省学院/专业：应落为 None（可空）
        },
    ]
    with mock.patch("app.services.student_roster_service.get_db", return_value=fake):
        result = StudentRosterService.create_batch(rows)
    assert result["created"] == 2
    assert result["failures"] == []
    assert len(fake.added) == 2
    added0 = fake.added[0]
    assert isinstance(added0, StudentRoster)
    assert added0.college == "信息与人工智能学院"
    assert added0.major == "计算机应用技术"
    added1 = fake.added[1]
    assert added1.college is None
    assert added1.major is None


def test_router_create_passes_college_major(client):
    """POST /students 路由应把 college/major 传给 service.create（注册前端表单入参）。"""
    from app.api import admin_roster_routes

    captured = {}

    class _Svc:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            row = mock.MagicMock()
            row.to_dict.return_value = {"id": 1}
            return row, None

    token = _make_token(1, "admin", "admin")
    with mock.patch.object(admin_roster_routes, "StudentRosterService", _Svc):
        resp = client.post(
            "/api/admin/roster/students",
            json={
                "school": "重庆科创职业学院",
                "student_number": "20260001",
                "class_name": "计算机2301",
                "college": "信息与人工智能学院",
                "major": "计算机应用技术",
                "real_name": "张三",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert captured["college"] == "信息与人工智能学院"
    assert captured["major"] == "计算机应用技术"


def test_router_update_passes_college_major(client):
    """PUT /students/<id> 路由应把 college/major 传给 service.update。"""
    from app.api import admin_roster_routes

    captured = {}

    class _Svc:
        @staticmethod
        def update(roster_id, **kwargs):
            captured.update(kwargs)
            row = mock.MagicMock()
            row.to_dict.return_value = {"id": 1}
            return row, None

    token = _make_token(1, "admin", "admin")
    with mock.patch.object(admin_roster_routes, "StudentRosterService", _Svc):
        resp = client.put(
            "/api/admin/roster/students/1",
            json={
                "class_name": "计算机2302",
                "college": "新学院",
                "major": "新专业",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert captured["college"] == "新学院"
    assert captured["major"] == "新专业"
