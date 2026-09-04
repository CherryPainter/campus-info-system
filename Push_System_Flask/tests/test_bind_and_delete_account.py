"""
身份绑定 + 账号注销安全回归测试（v6.16.0）

覆盖：
- 测试 1: 已绑定学生重复 POST /student/bind 被 403 + code=ALREADY_BOUND（防覆盖他人学号）
- 测试 2: 未绑定学生正常绑定成功
- 测试 3: 注销账号（DELETE /user/me）后 users.is_active=False + 当前 token 撤销
- 测试 4: 注销后再访问需鉴权接口 → 401

设计：复用 test_miniapp_auth.py 的 db_session 风格（SQLite 内存库 + User/StudentProfile
/WechatAccount/TokenBlacklist 表），手造学生 token 直接打路由。

运行：
    cd Push_System_Flask && python -m pytest tests/test_bind_and_delete_account.py -v
"""

import os
import sys
import time
import uuid
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.api_response import api_success
from app.core.extensions import limiter
from app.model.student_profile import StudentProfile
from app.model.student_roster import StudentRoster
from app.model.token_blacklist import TokenBlacklist
from app.model.user import User
from app.model.wechat_account import WechatAccount
from app.services.student_roster_service import StudentRosterService
from app.utils.jwt_auth import JWTManager
from app.utils.student_auth import student_required

import sqlalchemy as _sa

# User.avatar 是 MySQL MEDIUMTEXT，SQLite 无法渲染，测试环境替换为通用 TEXT
User.__table__.c.avatar.type = _sa.Text()

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _make_token(user_id, username="wx_test", role="student", expire_offset=3600):
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
    return _jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    WechatAccount.__table__.create(engine)
    StudentProfile.__table__.create(engine)
    StudentRoster.__table__.create(engine)
    TokenBlacklist.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _patch_db(db_session):
    from app.services import student_roster_service

    with mock.patch(
        "app.core.database.get_db", return_value=db_session
    ), mock.patch(
        "app.utils.jwt_auth.get_db", return_value=db_session
    ), mock.patch.object(
        student_roster_service, "get_db", return_value=db_session
    ):
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
    from app.api.miniapp_auth_routes import miniapp_auth_bp

    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")
    flask_app.register_blueprint(miniapp_auth_bp, url_prefix="/api/miniapp/auth")

    # 保护端点需要 student_required 装饰器链：绑定 / 注销 / 受保护业务
    @flask_app.route("/__guard__/protected", methods=["GET"])
    @student_required
    def _protected():
        return api_success(message="ok")

    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_student(db_session, user_id=1, username="wx_test"):
    user = User(id=user_id, username=username, role="student", is_active=True)
    user.password_hash = "x"  # 满足 NOT NULL
    db_session.add(user)
    profile = StudentProfile(user_id=user_id)
    db_session.add(profile)
    db_session.commit()
    return user, profile


def _seed_roster(school, student_number, class_name, is_active=True):
    """向内存库插入一条预录名单（直接调 service 落 SQLite 内存）"""
    with mock.patch("app.core.database.get_db") as get_db:
        from app.core.database import get_db as real_get_db

        # 用 app context 跑 service 落库（service 自身 get_db，不依赖 fixture 注入）
        pass  # 实际由 service 自己管理 session：先在 db_session 里 add
    # 简化：直接在 db_session 里 add StudentRoster（service 后续用 db_session）
    from app.model.student_roster import StudentRoster

    roster = StudentRoster(
        school=school,
        student_number=student_number,
        class_name=class_name,
        real_name="测试生",
        is_active=is_active,
    )
    return roster


# ==================== bind 防重复 ====================


def test_bind_first_time_succeeds(client, db_session):
    """未绑定学生正常绑定（基线：先有这条断言才能理解下面拒绝的语义）"""
    _create_student(db_session, user_id=1)
    roster = _seed_roster("重庆科创职业学院", "20260001", "计应2401班")
    db_session.add(roster)
    db_session.commit()
    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": "重庆科创职业学院",
            "student_number": "20260001",
            "class_name": "计应2401班",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["bound"] is True
    assert body["profile"]["student_number"] == "20260001"


def test_bind_writes_college_major_from_roster(client, db_session):
    """名单预录的学院/专业应随绑定一并写入 StudentProfile（组织维度随身份同步）。"""
    _create_student(db_session, user_id=1)
    roster = _seed_roster("重庆科创职业学院", "20260001", "计应2401班")
    roster.college = "信息与人工智能学院"
    roster.major = "计算机应用技术"
    db_session.add(roster)
    db_session.commit()
    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": "重庆科创职业学院",
            "student_number": "20260001",
            "class_name": "计应2401班",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["bound"] is True
    assert body["profile"]["college"] == "信息与人工智能学院"
    assert body["profile"]["major"] == "计算机应用技术"


def test_bind_rejects_already_bound(client, db_session):
    """已绑定学生重复 bind → 403 ALREADY_BOUND（防覆盖为他人学号，安全核心断言）"""
    user, profile = _create_student(db_session, user_id=1)
    # 模拟已绑定：手动设置 student_number（首次登录是空，bind 后才有值）
    profile.school = "重庆科创职业学院"
    profile.student_number = "20260001"
    profile.class_name = "计应2401班"
    db_session.commit()

    # 构造另一个学号也在预录名单里（模拟"想换成他人学号"）
    db_session.add(
        _seed_roster("重庆科创职业学院", "20260002", "计应2402班")
    )
    db_session.commit()

    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": "重庆科创职业学院",
            "student_number": "20260002",
            "class_name": "计应2402班",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    body = resp.get_json()
    assert body.get("code") == "ALREADY_BOUND"
    # 关键：profile 的 student_number 没被覆盖（重新 query，避免 refresh 跨 session 报错）
    profile_after = (
        db_session.query(StudentProfile).filter_by(user_id=1).first()
    )
    assert profile_after.student_number == "20260001"


# ==================== 注销账号 ====================


def test_delete_account_disables_user_and_revokes_token(client, app, db_session):
    """DELETE /user/me：users.is_active=False + access_token 进入黑名单"""
    user, _ = _create_student(db_session, user_id=1)
    access_token = _make_token(1)
    user_id = 1
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = client.delete("/api/miniapp/auth/user/me", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"

    # is_active 已被置 False（重新 query 避免跨 session refresh 报错）
    user_after = db_session.query(User).filter_by(id=user_id).first()
    assert user_after.is_active is False
    # access_token 已进入黑名单
    jti = _jwt.decode(
        access_token, SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )["jti"]
    blacklisted = (
        db_session.query(TokenBlacklist)
        .filter_by(jti=jti)
        .first()
    )
    assert blacklisted is not None


def test_deleted_account_cannot_access_business(client, app, db_session):
    """注销后携带原 token 访问需鉴权接口 → 401（黑名单生效）"""
    _create_student(db_session, user_id=1)
    access_token = _make_token(1)
    headers = {"Authorization": f"Bearer {access_token}"}

    # 先注销
    client.delete("/api/miniapp/auth/user/me", headers=headers)
    # 再访问受保护接口
    resp = client.get("/__guard__/protected", headers=headers)
    assert resp.status_code == 401
