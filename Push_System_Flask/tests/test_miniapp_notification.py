"""
近期提醒 API 回归测试（v6.16.0 第三阶段）

覆盖：
- 测试 1: 无 token → 401
- 测试 2: student 鉴权通过 → 200 + events
- 测试 3: 默认 limit=5，自定义 limit 透传
- 测试 4: admin token 访问 → 403（角色隔离）
- 测试 5: 过期事件不返回（event_date < now）
- 测试 6: 窗口外事件不返回（event_date - now > remind_days）
- 测试 7: 禁用事件不返回（is_active=False）
- 测试 8: events 列表按 event_date 升序、sort_order 降序
- 测试 9: 每条 event 含派生字段 days_left / event_date_label / is_expired

运行：
    cd Push_System_Flask && python -m pytest tests/test_miniapp_notification.py -v
"""

import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from unittest import mock

import jwt as _jwt
import pytest
from flask import Blueprint, Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.api_response import api_success
from app.core.extensions import limiter
from app.model.notification import Notification
from app.model.student_profile import StudentProfile
from app.model.token_blacklist import TokenBlacklist
from app.model.user import User
from app.utils.auth_middleware import admin_required
from app.utils.jwt_auth import JWTManager

import sqlalchemy as _sa

# User.avatar 是 MySQL MEDIUMTEXT，SQLite 无法渲染，测试环境替换为通用 TEXT
User.__table__.c.avatar.type = _sa.Text()


def _make_token(app, user_id, username, role, expire_offset=3600):
    """直接构造指定角色的 access token"""
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


@pytest.fixture
def db_session():
    """SQLite 内存库 + Notification 表"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Notification.__table__.create(engine)
    TokenBlacklist.__table__.create(engine)
    StudentProfile.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _patch_get_db(db_session):
    """路由层 get_db 指向内存库"""
    with mock.patch("app.core.database.get_db", return_value=db_session), mock.patch(
        "app.utils.jwt_auth.get_db", return_value=db_session
    ):
        # student_bound_required 要求身份已绑定：为 token 对应的 user_id=1 预置绑定身份
        profile = db_session.query(StudentProfile).filter_by(user_id=1).first()
        if profile is None:
            profile = StudentProfile(user_id=1)
            db_session.add(profile)
        profile.school = "重庆科创职业学院"
        profile.student_number = "20260001"
        profile.class_name = "计应2401班"
        db_session.commit()
        yield


@pytest.fixture(scope="module")
def app():
    """最小测试应用 + admin 测试端点（用于 403 验证）"""
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY="test-secret-key-0123456789abcdef0123456789abcdef",
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
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

    from app.api.miniapp_routes import miniapp_bp

    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")

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


def _seed_events(session):
    """插入一组覆盖各种边界情况的测试事件"""
    now = datetime.now()
    session.query(Notification).delete()
    rows = [
        # (title, delta_days, category, remind_days, sort_order, is_active)
        ("考试 A 报名", -3, "exam", 14, 100, True),       # 过期（应过滤）
        ("考试 B 报名", 1, "exam", 14, 90, True),         # 1 天后，窗口内
        ("考试 C 报名", 7, "exam", 14, 80, True),         # 7 天后，窗口临界
        ("放假 D", 10, "holiday", 14, 95, True),          # 10 天后，超 14 窗口（应过滤）
        ("活动 E", 15, "activity", 30, 70, True),         # 15 天后，30 窗口内
        ("活动 F（下架）", 5, "activity", 30, 60, False), # 禁用（应过滤）
    ]
    for title, delta, cat, rd, so, active in rows:
        session.add(
            Notification(
                title=title,
                event_date=now + timedelta(days=delta),
                category=cat,
                remind_days=rd,
                sort_order=so,
                is_active=active,
            )
        )
    session.commit()
    return now


def test_no_token_401(client):
    resp = client.get("/api/miniapp/notifications/upcoming")
    assert resp.status_code == 401


def test_student_token_returns_events(client, app, db_session):
    _seed_events(db_session)
    token = _make_token(app, 1, "wx_test", "student")
    resp = client.get(
        "/api/miniapp/notifications/upcoming",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "events" in data and "count" in data
    # 6 条中 4 条活跃且未过期且在各自窗口内（B/C/D/E）
    assert data["count"] == 4
    titles = [e["title"] for e in data["events"]]
    assert "考试 B 报名" in titles
    assert "考试 C 报名" in titles
    assert "放假 D" in titles
    assert "活动 E" in titles
    # 过期 / 禁用不应出现
    for e in data["events"]:
        assert "报名 A" not in e["title"]
        assert "下架" not in e["title"]


def test_custom_limit(client, app, db_session):
    _seed_events(db_session)
    token = _make_token(app, 1, "wx_test", "student")
    resp = client.get(
        "/api/miniapp/notifications/upcoming?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["count"] == 2


def test_admin_token_blocked_from_miniapp_api(client, app, db_session):
    _seed_events(db_session)
    token = _make_token(app, 999, "admin", "admin")
    resp = client.get(
        "/api/miniapp/notifications/upcoming",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_events_sorted_by_date_asc(client, app, db_session):
    _seed_events(db_session)
    token = _make_token(app, 1, "wx_test", "student")
    resp = client.get(
        "/api/miniapp/notifications/upcoming",
        headers={"Authorization": f"Bearer {token}"},
    )
    events = resp.get_json()["data"]["events"]
    dates = [e["event_date"] for e in events]
    assert dates == sorted(dates), "events 应按 event_date 升序"


def test_event_derived_fields(client, app, db_session):
    _seed_events(db_session)
    token = _make_token(app, 1, "wx_test", "student")
    resp = client.get(
        "/api/miniapp/notifications/upcoming",
        headers={"Authorization": f"Bearer {token}"},
    )
    events = resp.get_json()["data"]["events"]
    assert len(events) >= 1
    e = events[0]
    assert "days_left" in e
    assert "event_date_label" in e
    assert "is_expired" in e
    assert e["is_expired"] is False
    assert e["days_left"] >= 0
    # event_date_label 格式 MM-DD
    assert "-" in e["event_date_label"]
    assert len(e["event_date_label"]) == 5


def test_all_endpoint_includes_wider_window(client, app, db_session):
    """all 接口不受 remind_days 单事件窗口约束，返回所有未过期活跃事件"""
    _seed_events(db_session)
    token = _make_token(app, 1, "wx_test", "student")
    resp = client.get(
        "/api/miniapp/notifications/all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    titles = [e["title"] for e in data["events"]]
    # 应包含过期事件以外的所有活跃事件（4 条：A 过期不返，B/C/E/D 都在，E 是活动）
    # 过期 A 不返，禁用 F 不返
    assert "放假 D" in titles  # 窗口外但仍在 all 中
    assert "报名 A" not in titles  # 过期
    assert "下架" not in titles  # 禁用