"""
微信小程序认证与学生端 API 回归测试（v6.16.0 第一阶段）

对照《微信小程序扩展开发指南》§38 回归项：
- 测试 6/7: 微信首次登录创建学生用户、再次登录复用已有用户
- 测试 8:   access_token 过期 → 401
- 测试 9:   refresh_token 轮换（旧 refresh 撤销，二次刷新 401）
- 测试 10:  student 访问 admin API → 403（角色隔离）
- 测试 11:  admin 访问 student API → 403（角色隔离）
- 测试 12:  无 Token 访问受保护 API → 401
- 补充:     code2Session 微信侧错误、登录缺 code、学生资料 GET/PUT（仅本人，防 IDOR）、
           logout 撤销 Token 后原 Token 失效

运行：
    cd Push_System_Flask && python -m pytest tests/test_miniapp_auth.py -v
"""

import os
import sys
import time
import uuid
from unittest import mock

import jwt as _jwt
import pytest
import sqlalchemy as _sa
from flask import Blueprint, Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.api_response import api_success
from app.core.extensions import limiter
from app.model.login_log import LoginLog
from app.model.student_profile import StudentProfile
from app.model.token_blacklist import TokenBlacklist
from app.model.user import User
from app.model.wechat_account import WechatAccount
from app.services.wechat_auth_service import WechatAuthError, wechat_auth_service
from app.utils.auth_middleware import admin_required
from app.utils.jwt_auth import JWTManager

# User.avatar 是 MySQL MEDIUMTEXT，SQLite 无法渲染，测试环境替换为通用 TEXT（不影响生产库）
User.__table__.c.avatar.type = _sa.Text()

# 测试用的固定 openid（真实流程中由微信 code2Session 返回，测试里 mock）
OPENID = "oGZ8U5JxTestOpenId1234567890"


@pytest.fixture
def db_session():
    """SQLite 内存库（StaticPool 保持单连接，session.close() 后数据不丢）"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    WechatAccount.__table__.create(engine)
    StudentProfile.__table__.create(engine)
    LoginLog.__table__.create(engine)
    TokenBlacklist.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _db_getdb_patch(db_session):
    """把各模块的 get_db 全部指向内存库，避免连接真实 MySQL"""
    with mock.patch("app.core.database.get_db", return_value=db_session), mock.patch(
        "app.services.wechat_auth_service.get_db", return_value=db_session
    ), mock.patch("app.utils.jwt_auth.get_db", return_value=db_session):
        yield


@pytest.fixture(scope="module")
def app():
    """最小测试应用：JWTManager + 小程序蓝图 + 一个 admin 测试端点（验证角色隔离）"""
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY="test-secret-key-0123456789abcdef0123456789abcdef",
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
        # 测试环境禁用限流，避免 strict(10/min) 等规则干扰多用例累计请求
        RATELIMIT_ENABLED=False,
    )
    flask_app.extensions["jwt_manager"] = JWTManager(
        secret_key=flask_app.config["SECRET_KEY"],
        access_token_expire=flask_app.config["JWT_ACCESS_TOKEN_EXPIRE"],
        refresh_token_expire=flask_app.config["JWT_REFRESH_TOKEN_EXPIRE"],
        refresh_idle_expire=flask_app.config["JWT_REFRESH_IDLE_EXPIRE"],
        refresh_absolute_expire=flask_app.config["JWT_REFRESH_ABSOLUTE_EXPIRE"],
    )
    limiter.init_app(flask_app)

    from app.api.miniapp_auth_routes import miniapp_auth_bp
    from app.api.miniapp_routes import miniapp_bp

    flask_app.register_blueprint(miniapp_auth_bp, url_prefix="/api/miniapp/auth")
    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")

    # 最小 admin 测试端点：验证 student 访问 admin API 被 403 拦截
    admin_test_bp = Blueprint("admin_test", __name__)

    @admin_test_bp.route("/only-admin", methods=["GET"])
    @admin_required
    def only_admin():
        return api_success(message="admin only")

    flask_app.register_blueprint(admin_test_bp, url_prefix="/api/admin")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, code="test-code-001"):
    """模拟小程序登录：mock 微信 code2Session 返回固定 openid"""
    with mock.patch.object(
        wechat_auth_service,
        "code2session",
        return_value={"openid": OPENID, "session_key": "test-session-key", "unionid": None},
    ):
        return client.post("/api/miniapp/auth/login", json={"code": code})


def _make_token(app, user_id, username, role, expire_offset=3600):
    """直接构造指定角色的 access token（绕过登录，便于角色隔离测试）"""
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expire_offset,
    }
    return _jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


# ========== 测试 6/7：微信首次/再次登录 ==========


def test_first_login_creates_student_user(client, db_session):
    resp = _login(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["access_token"] and body["refresh_token"]
    assert body["is_new_user"] is True
    assert body["user"]["role"] == "student"

    user = db_session.query(User).filter_by(id=body["user"]["id"]).one()
    assert user.role == "student"
    assert user.username.startswith("wx_")
    assert user.password_hash  # 随机 bcrypt 哈希：满足 NOT NULL 约束且不可用于密码登录
    assert user.is_active is True

    account = db_session.query(WechatAccount).filter_by(openid=OPENID).one()
    assert account.user_id == user.id
    assert account.session_key == "test-session-key"

    profile = db_session.query(StudentProfile).filter_by(user_id=user.id).one()
    assert profile.student_number is None  # 首次登录只建骨架，学号等由本人后续补充

    logs = db_session.query(LoginLog).filter_by(user_id=user.id).all()
    assert len(logs) == 1 and logs[0].status == "success"


def test_second_login_reuses_user(client, db_session):
    first = _login(client).get_json()
    # 不同 code、同一 openid → 复用同一用户，不重复创建
    second = _login(client, code="test-code-002").get_json()
    assert second["is_new_user"] is False
    assert second["user"]["id"] == first["user"]["id"]
    assert db_session.query(User).count() == 1
    assert db_session.query(WechatAccount).count() == 1
    assert db_session.query(StudentProfile).count() == 1


# ========== 登录参数与微信侧错误 ==========


def test_login_missing_code_400(client):
    resp = client.post("/api/miniapp/auth/login", json={})
    assert resp.status_code == 400
    assert "code" in resp.get_json()["message"]


def test_login_wechat_error_40029(client):
    """微信 code2Session 返回 js_code 无效（40029）→ 401，不透传 openid"""
    def _boom(code):
        raise WechatAuthError("登录凭证无效，请重新登录", http_status=401)

    with mock.patch.object(wechat_auth_service, "code2session", side_effect=_boom):
        resp = client.post("/api/miniapp/auth/login", json={"code": "bad-code"})
    assert resp.status_code == 401
    assert "凭证无效" in resp.get_json()["message"]


def test_login_wechat_config_missing_503(client):
    """AppID/Secret 未配置时登录返回 503 配置错误"""
    def _no_config(code):
        raise WechatAuthError("微信小程序功能未配置，请联系管理员", http_status=503)

    with mock.patch.object(wechat_auth_service, "code2session", side_effect=_no_config):
        resp = client.post("/api/miniapp/auth/login", json={"code": "code"})
    assert resp.status_code == 503


# ========== 测试 8/12：Token 过期与缺失 ==========


def test_expired_access_token_401(client, app):
    expired = _make_token(app, 1, "wx_test", "student", expire_offset=-3600)
    resp = client.get(
        "/api/miniapp/user/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401
    assert "过期" in resp.get_json()["message"]


def test_no_token_401(client):
    assert client.get("/api/miniapp/user/me").status_code == 401
    assert client.get("/api/miniapp/student/profile").status_code == 401
    assert client.put("/api/miniapp/student/profile", json={}).status_code == 401


# ========== 测试 10/11：角色隔离 ==========


def test_student_token_blocked_from_admin_api(client, app):
    body = _login(client).get_json()
    resp = client.get(
        "/api/admin/only-admin", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 403

    # 对照组：admin token 可访问 admin 端点
    admin_token = _make_token(app, 999, "admin", "admin")
    ok = client.get("/api/admin/only-admin", headers={"Authorization": f"Bearer {admin_token}"})
    assert ok.status_code == 200


def test_admin_token_blocked_from_miniapp_api(client, app):
    admin_token = _make_token(app, 999, "admin", "admin")
    for path in ("/api/miniapp/user/me", "/api/miniapp/student/profile"):
        resp = client.get(path, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 403, path


# ========== 学生资料（防 IDOR） ==========


def _bind_student(db_session, user_id, student_number="20260001"):
    """模拟学生已通过预录名单完成身份绑定（student_bound_required 要求 student_number 非空）"""
    profile = db_session.query(StudentProfile).filter_by(user_id=user_id).one()
    profile.school = "重庆科创职业学院"
    profile.student_number = student_number
    profile.class_name = "计应2401班"
    db_session.commit()
    return profile


def test_profile_get_and_update_own_only(client, db_session):
    body = _login(client).get_json()
    user_id = body["user"]["id"]
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    _bind_student(db_session, user_id)

    resp = client.get("/api/miniapp/student/profile", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["profile"]["user_id"] == user_id

    # 更新本人资料；顺带尝试传 user_id=999（IDOR 尝试，应被字段白名单过滤）
    resp = client.put(
        "/api/miniapp/student/profile",
        json={
            "real_name": "张三",
            "phone": "13800000000",
            "user_id": 999,
            "role": "admin",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    profile = db_session.query(StudentProfile).filter_by(user_id=user_id).one()
    assert profile.real_name == "张三"
    assert profile.user_id == user_id  # user_id 不可被客户端篡改

    # 身份字段（学号/班级/学校）已移出 PUT 白名单：绑定后不可再改，防绕过名单
    resp = client.put(
        "/api/miniapp/student/profile",
        json={"student_number": "99999999", "class_name": "黑客班", "school": "某校"},
        headers=headers,
    )
    assert resp.status_code == 400
    profile = db_session.query(StudentProfile).filter_by(user_id=user_id).one()
    assert profile.student_number == "20260001"


def test_profile_update_invalid_fields_400(client, db_session):
    body = _login(client).get_json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    _bind_student(db_session, body["user"]["id"])
    resp = client.put(
        "/api/miniapp/student/profile", json={"not_a_field": "x"}, headers=headers
    )
    assert resp.status_code == 400


# ========== 测试 9：refresh 轮换 ==========


def test_refresh_rotation(client):
    body = _login(client).get_json()
    refresh_token = body["refresh_token"]

    resp = client.post("/api/miniapp/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    new_body = resp.get_json()
    assert new_body["access_token"] and new_body["refresh_token"]

    # 旧 refresh_token 已被轮换撤销 → 二次刷新 401
    resp2 = client.post("/api/miniapp/auth/refresh", json={"refresh_token": refresh_token})
    assert resp2.status_code == 401

    # 新 access_token 可正常访问
    ok = client.get(
        "/api/miniapp/user/me", headers={"Authorization": f"Bearer {new_body['access_token']}"}
    )
    assert ok.status_code == 200


def test_refresh_missing_token_401(client):
    resp = client.post("/api/miniapp/auth/refresh", json={})
    assert resp.status_code == 401


# ========== logout 撤销 ==========


def test_logout_revokes_token(client):
    body = _login(client).get_json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    resp = client.post(
        "/api/miniapp/auth/logout",
        json={"refresh_token": body["refresh_token"]},
        headers=headers,
    )
    assert resp.status_code == 200

    # 登出后原 access_token 已进黑名单 → 401
    after = client.get("/api/miniapp/user/me", headers=headers)
    assert after.status_code == 401
