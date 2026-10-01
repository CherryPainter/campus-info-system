"""
新密码强度围栏回归测试（B 级修复项 B8）

背景：
「设置新密码」的服务端校验此前在**三处各写一遍魔数 6**：
- `auth_routes.change_password`（管理员自助改密）
- `admin_user_routes.create_user`（管理员建号）
- `admin_user_routes.reset_user_password`（管理员重置）

分散写法的必然结果是「改一处漏一处」——只要有一处忘了改，就会出现
「按提示改的密码被后端 400 拒绝」。同时三个前端提示（admin-frontend
**Profile.tsx / UserManagement.tsx**）也把 6 写死，必须与服务端同源。
现收敛为 `app/utils/security.py` 的 `MIN_PASSWORD_LENGTH` +
`validate_password_strength()` 单一来源。

覆盖：
- 纯函数：长度小于下限拒绝、等于下限放行、空值拒绝；错误文案含下限数字
- 常量本身为 8（前端提示必须与之一致，此处锁死防止被无声改回）
- 接线（wiring）：三个端点都必须过这个校验——7 位密码一律 400，
  且在**触碰数据库之前**就被拒（`get_db` 不被调用）
- 反证：8 位密码能通过长度闸门（证明拦的是长度，不是把所有人都拦掉）

运行：
    cd Push_System_Flask && python -m pytest tests/test_password_strength_fence.py -v
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
from app.utils.jwt_auth import JWTManager
from app.utils.security import MIN_PASSWORD_LENGTH, validate_password_strength

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _make_token(user_id=1, username="admin", role="admin"):
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


def _new_app(blueprint_importer, url_prefix):
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
    flask_app.register_blueprint(blueprint_importer, url_prefix=url_prefix)
    return flask_app


@pytest.fixture
def auth_client():
    """只挂 auth 蓝图：POST /api/auth/change-password"""
    from app.api.auth_routes import auth_bp

    return _new_app(auth_bp, "/api/auth").test_client()


@pytest.fixture
def admin_user_client():
    """只挂 admin_user 蓝图（真实前缀 /api/admin/user，见 app/__init__.py:335）"""
    from app.api.admin_user_routes import admin_user_bp

    return _new_app(admin_user_bp, "/api/admin/user").test_client()


# ============================================================
# 一、纯函数：长度闸门
# ============================================================


def test_min_length_constant_is_8():
    """锁死常量：前端三处提示文案与服务端同源，改这里必须同步前端。

    该断言刻意用字面量 8（而非 MIN_PASSWORD_LENGTH）——否则把常量改成 4
    测试照样绿，等于没锁。
    """
    assert MIN_PASSWORD_LENGTH == 8


def test_rejects_below_minimum():
    assert validate_password_strength("a" * 7) is not None
    assert validate_password_strength("123456") is not None  # 旧的 6 位口径必须已被拒绝


def test_accepts_at_minimum():
    assert validate_password_strength("a" * 8) is None


def test_rejects_empty_and_none():
    assert validate_password_strength("") is not None
    assert validate_password_strength(None) is not None


def test_error_message_carries_the_limit():
    """文案必须带上下限数字，否则用户不知道要改多长；且要能被前端直接展示。"""
    msg = validate_password_strength("a" * 7)
    assert "8" in msg


def test_does_not_crash_on_non_string():
    """非字符串输入不得抛 TypeError（否则端点 500）。"""
    validate_password_strength(12345678)  # 不抛异常即通过


# ============================================================
# 二、接线：三个「设置新密码」端点都必须过闸
# ============================================================


def test_change_password_rejects_short_before_db(auth_client):
    """自助改密：7 位新密码 → 400，且**不得触碰数据库**（闸门在 get_db 之前）。"""
    token = _make_token()
    with mock.patch("app.core.database.get_db") as get_db:
        resp = auth_client.post(
            "/api/auth/change-password",
            json={"old_password": "whatever", "new_password": "a" * 7},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    assert "8" in resp.get_json()["message"]
    get_db.assert_not_called()


def test_change_password_short_password_not_six(auth_client):
    """反证旧口径：6 位密码现在也必须被拒（此前是放行的）。"""
    token = _make_token()
    with mock.patch("app.core.database.get_db") as get_db:
        resp = auth_client.post(
            "/api/auth/change-password",
            json={"old_password": "whatever", "new_password": "abc123"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    get_db.assert_not_called()


def test_change_password_valid_length_passes_gate(auth_client):
    """8 位密码应通过长度闸门（随后因用户不存在 404，证明没被长度拦掉）。"""
    token = _make_token()
    session = mock.MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    with mock.patch("app.core.database.get_db", return_value=session):
        resp = auth_client.post(
            "/api/auth/change-password",
            json={"old_password": "whatever", "new_password": "a" * 8},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404
    assert session.query.called


def test_create_user_rejects_short_password(admin_user_client):
    """管理员建号：7 位密码 → 400，且未触碰数据库。"""
    token = _make_token()
    with mock.patch("app.core.database.get_db") as get_db:
        resp = admin_user_client.post(
            "/api/admin/user/users",
            json={"username": "newuser", "password": "a" * 7, "role": "user"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    assert "8" in resp.get_json()["message"]
    get_db.assert_not_called()


def test_create_user_valid_length_passes_gate(admin_user_client):
    """8 位密码应通过长度闸门（进入 DB 查询阶段即算通过）。"""
    token = _make_token()
    session = mock.MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    with mock.patch("app.core.database.get_db", return_value=session) as get_db:
        admin_user_client.post(
            "/api/admin/user/users",
            json={"username": "newuser", "password": "a" * 8, "role": "user"},
            headers={"Authorization": f"Bearer {token}"},
        )
    get_db.assert_called()


def test_reset_password_rejects_short(admin_user_client):
    """管理员重置密码：7 位 → 400，且未触碰数据库。"""
    token = _make_token()
    with mock.patch("app.core.database.get_db") as get_db:
        resp = admin_user_client.post(
            "/api/admin/user/users/2/reset-password",
            json={"password": "a" * 7},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    assert "8" in resp.get_json()["message"]
    get_db.assert_not_called()


def test_reset_password_empty_still_rejected(admin_user_client):
    """空密码语义不变：仍是 400（旧实现是 `not new_password or len < 6`）。"""
    token = _make_token()
    with mock.patch("app.core.database.get_db") as get_db:
        resp = admin_user_client.post(
            "/api/admin/user/users/2/reset-password",
            json={"password": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    get_db.assert_not_called()
