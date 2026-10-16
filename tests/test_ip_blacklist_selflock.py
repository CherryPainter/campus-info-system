"""
IP 黑名单「自锁围栏」回归测试（A 级修复项 A1）

背景：手动封禁原本只校验 IP 格式，于是可以把
- 本机/保留地址（无防护意义、可能打断服务自身调用）
- 管理员白名单（REGION_BLOCK_EXCEPTIONS，语义就是「防止误锁自己」）
- **当前请求来源 IP**（一封就再也进不了后台，连解封接口一起被拦）
写进黑名单，属运维可用性事故。

覆盖：
- `_reject_unblockable_ip` 纯函数：四类拒绝 + 正常公网 IP 放行
- 路由层接线：POST /api/admin/ip-blacklist 携带上述地址必须 400，且**不写库**
- 兜底：`_check_ip_blacklist` 对白名单 IP 直接放行（防自动封禁把自己的 IP 写进去）

运行：
    cd Push_System_Flask && python -m pytest tests/test_ip_blacklist_selflock.py -v
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

from app.api.ip_blacklist_routes import _reject_unblockable_ip
from app.core.extensions import limiter
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
        REGION_BLOCK_EXCEPTIONS=[],
    )
    flask_app.extensions["jwt_manager"] = JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    limiter.init_app(flask_app)
    from app.api.ip_blacklist_routes import ip_blacklist_bp

    flask_app.register_blueprint(ip_blacklist_bp, url_prefix="/api/admin/ip-blacklist")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_token():
    return _make_token(999, "admin", "admin")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _check(app, ip, client_ip="9.9.9.9"):
    """在请求上下文中调用待测函数（get_client_ip 依赖 request.remote_addr）。"""
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": client_ip}):
        return _reject_unblockable_ip(ip)


# ============================================================
# 一、纯函数：四类拒绝 + 正常公网放行
# ============================================================


@pytest.mark.parametrize(
    "ip,client_ip",
    [
        ("127.0.0.1", "9.9.9.9"),  # 回环
        ("::1", "9.9.9.9"),  # 回环（IPv6）
        ("0.0.0.0", "9.9.9.9"),  # 未指定
        ("224.0.0.1", "9.9.9.9"),  # 组播
        ("240.0.0.1", "9.9.9.9"),  # 保留
    ],
)
def test_loopback_and_reserved_rejected(app, ip, client_ip):
    msg = _check(app, ip, client_ip)
    assert msg is not None
    assert "本机" in msg or "保留" in msg


def test_admin_whitelist_ip_rejected(app):
    app.config["REGION_BLOCK_EXCEPTIONS"] = ["1.2.3.4"]
    msg = _check(app, "1.2.3.4", "9.9.9.9")
    assert msg is not None
    assert "白名单" in msg


def test_admin_whitelist_cidr_rejected(app):
    """白名单支持 CIDR：网段内的地址同样不许封（否则等于把整个网段的自锁风险留下）"""
    app.config["REGION_BLOCK_EXCEPTIONS"] = ["10.1.0.0/16"]
    msg = _check(app, "10.1.2.3", "9.9.9.9")
    assert msg is not None
    assert "白名单" in msg


def test_current_request_source_rejected(app):
    """最容易被误操作触发的一条：封掉自己所在 IP 后，连解封接口都会被拦下"""
    msg = _check(app, "9.9.9.9", "9.9.9.9")
    assert msg is not None
    assert "当前请求来源" in msg


def test_normal_public_ip_allowed(app):
    assert _check(app, "8.8.8.8", "9.9.9.9") is None


def test_unrelated_private_ip_still_allowed(app):
    """只拦「本机/保留 + 白名单 + 自身来源」，不扩大化到内网地址本身"""
    assert _check(app, "192.168.1.50", "9.9.9.9") is None


def test_invalid_format_rejected(app):
    assert _check(app, "not-an-ip") is not None


# ============================================================
# 二、路由接线：必须 400 且不写库
# ============================================================


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1"],
)
def test_route_rejects_unblockable_ip_and_writes_nothing(app, client, admin_token, ip):
    """接线回归：把守卫从 add_to_blacklist 去掉后，本用例即由 400 变为「尝试写库」失败。"""
    with mock.patch(
        "app.api.ip_blacklist_routes.IPBlacklistService.block_ip"
    ) as fake_block, mock.patch("app.api.ip_blacklist_routes.get_db") as fake_db:
        resp = client.post(
            "/api/admin/ip-blacklist",
            json={"ip_address": ip, "reason": "t"},
            headers=_auth(admin_token),
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
    assert resp.status_code == 400
    fake_block.assert_not_called()
    fake_db.assert_not_called()


def test_route_allows_normal_public_ip(app, client, admin_token):
    """反向对照：正常公网 IP 仍可封禁（证明守卫没有过度拦截）"""
    rec = mock.MagicMock()
    rec.to_dict.return_value = {"ip_address": "8.8.8.8"}
    with mock.patch(
        "app.api.ip_blacklist_routes.IPBlacklistService.block_ip", return_value=rec
    ), mock.patch("app.api.ip_blacklist_routes.get_db") as fake_db:
        fake_db.return_value = mock.MagicMock()
        resp = client.post(
            "/api/admin/ip-blacklist",
            json={"ip_address": "8.8.8.8"},
            headers=_auth(admin_token),
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
    assert resp.status_code in (200, 201)


# ============================================================
# 三、兜底：白名单 IP 永不被黑名单拦截
# ============================================================


def test_check_ip_blacklist_skips_admin_whitelist(app):
    """自动封禁（登录失败信号/扫描/限流）仍可能把管理员 IP 写进库，
    拦截层必须兜一道，否则白名单语义形同虚设。"""
    from app.utils.security import _check_ip_blacklist

    app.config["REGION_BLOCK_EXCEPTIONS"] = ["203.0.113.10"]
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.10"}):
        with mock.patch("app.core.database.get_db") as fake_db:
            assert _check_ip_blacklist("203.0.113.10") is False
            fake_db.assert_not_called()  # 直接短路，连库都不查


def test_ip_in_admin_whitelist_matches_cidr(app):
    from app.utils.security import ip_in_admin_whitelist

    app.config["REGION_BLOCK_EXCEPTIONS"] = ["203.0.113.0/24"]
    with app.app_context():
        assert ip_in_admin_whitelist("203.0.113.7") is True
        assert ip_in_admin_whitelist("198.51.100.7") is False
        assert ip_in_admin_whitelist("") is False
