"""
天气模块配置写入围栏回归测试（A 级修复项 A3）

背景：`PUT /api/admin/weather/config` 原本任何管理员都能改 `project_id` / `api_key`。
这两个值是**全校天气数据源的凭证**，被换掉会直接波及所有师生的天气推送（且可能产生
第三方账单），与「普通管理员不应掌握全局凭证」冲突。同时 `location` / `city_name`
无格式校验，写错即让全校天气取不到数据。

覆盖：
- `_current_admin_is_primary`：主管理员 True / 普通管理员 False / 无登录态 False /
  查库异常 False（fail-closed，敏感写操作宁可误拒不误放）
- 路由：非主管理员传 api_key / project_id → 403 且**不落配置**
- 路由：非主管理员改 location / city_name / daily_push_time → 允许（不误伤日常运维）
- 路由：location / city_name 非法格式 → 400 且不落配置
- `_validate_location` / `_validate_city_name` 边界

运行：
    cd Push_System_Flask && python -m pytest tests/test_admin_weather_config_fence.py -v
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

from app.api.admin_routes import (
    _current_admin_is_primary,
    _validate_city_name,
    _validate_location,
)
from app.core import config as cfg_module
from app.core.extensions import limiter
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _make_token(user_id, role="admin"):
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "username": f"u{user_id}",
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
    from app.api.admin_routes import admin_bp

    flask_app.register_blueprint(admin_bp, url_prefix="/api/admin")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _restore_weather_config():
    """路由会就地改 Config 类属性，用例结束后必须还原，避免污染其它测试。"""
    keys = (
        "QWEATHER_PROJECT_ID",
        "QWEATHER_API_KEY",
        "QWEATHER_LOCATION",
        "QWEATHER_CITY_NAME",
        "WEATHER_SCHEDULE_DAILY",
    )
    before = {k: getattr(cfg_module.Config, k, None) for k in keys}
    yield
    for k, v in before.items():
        setattr(cfg_module.Config, k, v)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _put(client, token, body):
    return client.put("/api/admin/weather/config", json=body, headers=_auth(token))


# ============================================================
# 一、主管理员判定
# ============================================================


def _session_returning(user):
    class _S:
        def query(self, *a, **k):
            return self

        def filter_by(self, *a, **k):
            return self

        def first(self):
            return user

        def close(self):
            pass

    return _S()


def test_primary_admin_true(app):
    with app.test_request_context("/"):
        from flask import g

        g.current_user = {"user_id": "1", "role": "admin"}
        with mock.patch(
            "app.core.database.get_db",
            return_value=_session_returning(SimpleNamespace(is_primary=True)),
        ):
            assert _current_admin_is_primary() is True


def test_non_primary_admin_false(app):
    with app.test_request_context("/"):
        from flask import g

        g.current_user = {"user_id": "2", "role": "admin"}
        with mock.patch(
            "app.core.database.get_db",
            return_value=_session_returning(SimpleNamespace(is_primary=False)),
        ):
            assert _current_admin_is_primary() is False


def test_missing_current_user_false(app):
    with app.test_request_context("/"):
        from flask import g

        g.current_user = {}
        assert _current_admin_is_primary() is False


def test_db_error_is_fail_closed(app):
    """查库异常不得放行敏感写操作"""
    with app.test_request_context("/"):
        from flask import g

        g.current_user = {"user_id": "1"}
        with mock.patch("app.core.database.get_db", side_effect=RuntimeError("db down")):
            assert _current_admin_is_primary() is False


# ============================================================
# 二、路由：敏感凭证只许主管理员
# ============================================================


@pytest.mark.parametrize("field", ["api_key", "project_id"])
def test_non_primary_admin_cannot_change_credentials(app, client, field):
    token = _make_token(2)
    with mock.patch(
        "app.api.admin_routes._current_admin_is_primary", return_value=False
    ) as guard:
        resp = _put(client, token, {field: "attacker-value"})
    assert resp.status_code == 403
    guard.assert_called_once()
    # 关键：配置未被改动
    if field == "api_key":
        assert getattr(cfg_module.Config, "QWEATHER_API_KEY", None) != "attacker-value"
    else:
        assert getattr(cfg_module.Config, "QWEATHER_PROJECT_ID", None) != "attacker-value"


def test_primary_admin_can_change_credentials(app, client):
    token = _make_token(1)
    with mock.patch("app.api.admin_routes._current_admin_is_primary", return_value=True):
        resp = _put(client, token, {"api_key": "new-key"})
    assert resp.status_code == 200
    assert cfg_module.Config.QWEATHER_API_KEY == "new-key"


def test_non_primary_admin_can_still_change_location(app, client):
    """不误伤：日常运维字段（位置/城市/推送时间）普通管理员仍可改"""
    token = _make_token(2)
    with mock.patch("app.api.admin_routes._current_admin_is_primary", return_value=False):
        resp = _put(client, token, {"city_name": "重庆"})
    assert resp.status_code == 200


def test_credentials_absent_does_not_trigger_guard(app, client):
    """不传敏感字段时不应调用主管理员校验（避免每次日常改配置都查库）"""
    token = _make_token(2)
    with mock.patch(
        "app.api.admin_routes._current_admin_is_primary", return_value=False
    ) as guard:
        resp = _put(client, token, {"city_name": "重庆"})
    assert resp.status_code == 200
    guard.assert_not_called()


def test_empty_credential_value_is_ignored(app, client):
    """空值等于「没传」，不触发门槛也不覆盖现有凭证"""
    token = _make_token(2)
    before = getattr(cfg_module.Config, "QWEATHER_API_KEY", None)
    with mock.patch("app.api.admin_routes._current_admin_is_primary") as guard:
        resp = _put(client, token, {"api_key": ""})
    assert resp.status_code == 200
    guard.assert_not_called()
    assert getattr(cfg_module.Config, "QWEATHER_API_KEY", None) == before


# ============================================================
# 三、路由：格式校验
# ============================================================


@pytest.mark.parametrize("bad", ["重庆", "106.55", "106.55;29.56", "abc,def", "999,29.5"])
def test_invalid_location_rejected(app, client, bad):
    token = _make_token(1)
    before = getattr(cfg_module.Config, "QWEATHER_LOCATION", None)
    resp = _put(client, token, {"location": bad})
    assert resp.status_code == 400
    assert getattr(cfg_module.Config, "QWEATHER_LOCATION", None) == before


def test_valid_location_accepted(app, client):
    token = _make_token(1)
    resp = _put(client, token, {"location": "106.55,29.56"})
    assert resp.status_code == 200
    assert cfg_module.Config.QWEATHER_LOCATION == "106.55,29.56"


def test_overlong_city_name_rejected(app, client):
    token = _make_token(1)
    resp = _put(client, token, {"city_name": "渝" * 33})
    assert resp.status_code == 400


# ============================================================
# 四、校验函数边界
# ============================================================


@pytest.mark.parametrize(
    "value", ["106.55,29.56", " 106.55 , 29.56 ", "-180,-90", "180,90", "0,0"]
)
def test_validate_location_ok(value):
    assert _validate_location(value) is None


@pytest.mark.parametrize("value", ["", "1,2,3", "181,0", "0,91", "lat,lng", "106.55,"])
def test_validate_location_bad(value):
    assert _validate_location(value) is not None


def test_validate_city_name_ok():
    assert _validate_city_name("重庆") is None


@pytest.mark.parametrize("value", ["", "   ", "渝" * 33, "重庆\n上海"])
def test_validate_city_name_bad(value):
    assert _validate_city_name(value) is not None
