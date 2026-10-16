# -*- coding: utf-8 -*-
"""
天气预警推送总开关（weather.alert_enabled）端到端有效性测试

背景：用户发现管理端「系统设置」页与「天气管理」页对同一个预警推送开关显示状态不一致
（一处显示「是/开」，另一处显示「关」），质疑：到底信谁的？这个设置到底有没有真的生效？

本测试用**隔离的 SQLite 克隆库 + 临时 .env** 跑真实代码（绝不碰生产 MySQL、绝不碰真 .env），验证：

1. 真值源唯一性：运行时推送、天气页 GET、系统设置页 GET 三条读取路径都从
   `module_configs.weather.alert_enabled` 同一张表取值，不存在第二份真相。
2. 两条写路径都落同一张表：
   - 天气页开关 → PUT /api/admin/weather/config（专属端点，布尔规范成小写 true/false）
   - 系统设置页开关 → PUT /api/admin/config/weather/alert_enabled（通用端点，写表 + 写 .env）
3. 运行时真的生效：alert_enabled=false 时推送分支被跳过；true 时执行推送。
4. 两条写路径不会造成「持久分叉」：无论走哪条，两个 GET 端点拿到的值始终一致。
5. 暴露隐患：通用端点把 Python 布尔存成 "False"/"True"（首字母大写），专属端点存
   "false"/"true"；当前所有读路径都 .lower() 兜底，不会立刻出错，但两份存储表示不一致，
   属于应消除的隐患（见 test_capitalization_quirk）。

隔离说明：config_routes 在模块顶层 `from app.core.database import get_db`，只在
app.core.database.get_db 上打补丁盖不到它，所以本装置同时补丁
`app.api.config_routes.get_db`；并将所有 ".env" 路径重定向到临时文件，避免任何真实副作用。

运行：
    cd Push_System_Flask && python -m pytest tests/test_weather_alert_enabled_e2e.py -v
"""

import os
import sys
import time
import types
import uuid
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.extensions import limiter
from app.model.module_config import ModuleConfig
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


# ============================================================
# 隔离 DB 环境（SQLite 克隆 module_configs + 临时 .env）
# ============================================================


@pytest.fixture
def env(tmp_path):
    """建只含 module_configs 的 SQLite 库，并把两处 get_db 与 ".env" 写入都指向隔离环境。"""
    db_path = tmp_path / "test_module_configs.db"
    engine = create_engine(f"sqlite:///{db_path}")
    ModuleConfig.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False)

    def _get_db():
        return Session()

    tmp_env = tmp_path / "redirected.env"
    real_join = os.path.join

    def fake_join(*a):
        # 只把写 .env 的路径重定向到临时文件；其余 join 保持原行为
        if a and a[-1] == ".env":
            return str(tmp_env)
        return real_join(*a)

    with mock.patch("app.core.database.get_db", side_effect=_get_db), mock.patch(
        "app.api.config_routes.get_db", side_effect=_get_db
    ), mock.patch("os.path.join", side_effect=fake_join):
        # 重置 ConfigService 单例，避免跨用例的 .env 兜底缓存污染
        import app.services.config_service as cs

        cs._config_service = None
        yield {"Session": Session, "env_file": tmp_env}


def seed(env, value):
    """把 weather.alert_enabled 这一行的值直接写成 value（字符串）。"""
    Session = env["Session"]
    s = Session()
    try:
        row = (
            s.query(ModuleConfig)
            .filter_by(module="weather", key="alert_enabled")
            .first()
        )
        if row is None:
            row = ModuleConfig(
                module="weather",
                key="alert_enabled",
                value_type="boolean",
                is_editable=True,
                is_sensitive=False,
                description="测试",
            )
            s.add(row)
        row.value = value
        s.commit()
    finally:
        s.close()


def read_row(env):
    Session = env["Session"]
    s = Session()
    try:
        row = (
            s.query(ModuleConfig)
            .filter_by(module="weather", key="alert_enabled")
            .first()
        )
        return row.value if row else None
    finally:
        s.close()


# ============================================================
# Flask app + client（复刻 fence 测试的 JWT 装配）
# ============================================================


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


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


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
    from app.api.config_routes import config_bp

    flask_app.register_blueprint(admin_bp, url_prefix="/api/admin")
    flask_app.register_blueprint(config_bp, url_prefix="/api/admin/config")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# ============================================================
# 一、真值源唯一性
# ============================================================


def test_source_of_truth_is_module_configs(client, env):
    """运行时推送、天气页 GET、系统设置页 GET 都从同一张 module_configs 表取 alert_enabled。"""
    seed(env, "true")
    token = _make_token(1)

    from app.api.admin_routes import _read_weather_push_config
    from app.services.config_service import get_config_service

    # 运行时推送读取的真实语句（tasks.py:552-554）所用服务
    assert get_config_service().get("weather", "alert_enabled", "true") is True
    # 天气页 GET 端点取值
    assert _read_weather_push_config()["alert_enabled"] is True
    # 系统设置页 GET 端点取值
    r_settings = client.get("/api/admin/config", headers=_auth(token))
    item = next(
        c
        for c in r_settings.get_json()["data"]["weather"]["configs"]
        if c["key"] == "alert_enabled"
    )
    assert item["value"] is True


# ============================================================
# 二、两条写路径都落同一张表
# ============================================================


def test_weather_page_write_path_lands_in_module_configs(client, env):
    """天气页开关：PUT /api/admin/weather/config 写的是 module_configs（小写 true/false）。"""
    seed(env, "true")
    token = _make_token(1)

    resp = client.put(
        "/api/admin/weather/config",
        json={"alert_enabled": False},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert read_row(env) == "false"

    # 两个 GET 端点应同步反映 OFF
    r_weather = client.get("/api/admin/weather/config", headers=_auth(token))
    assert r_weather.get_json()["data"]["alert_enabled"] is False
    r_settings = client.get("/api/admin/config", headers=_auth(token))
    item = next(
        c
        for c in r_settings.get_json()["data"]["weather"]["configs"]
        if c["key"] == "alert_enabled"
    )
    assert item["value"] is False


def test_settings_page_write_path_lands_in_module_configs(client, env):
    """系统设置页开关：PUT /api/admin/config/weather/alert_enabled 写 module_configs + .env。

    注意：通用端点用 str(new_value) 存值，前端传 JS 布尔 false → Python False → 存成 "False"
    （首字母大写）。本用例同时验证 .env 也被写入了 WEATHER_ALERT_ENABLED。
    """
    seed(env, "true")
    token = _make_token(1)

    resp = client.put(
        "/api/admin/config/weather/alert_enabled",
        json={"value": False},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    # 修复后：通用端点与专属端点一致，均存小写 "false"
    assert read_row(env) == "false"

    # 读路径 .lower() 兜底，仍读到 False
    r_settings = client.get("/api/admin/config", headers=_auth(token))
    item = next(
        c
        for c in r_settings.get_json()["data"]["weather"]["configs"]
        if c["key"] == "alert_enabled"
    )
    assert item["value"] is False
    # .env 同步写入（重定向到临时文件，同样小写）
    assert "WEATHER_ALERT_ENABLED=false" in env["env_file"].read_text(encoding="utf-8")


# ============================================================
# 三、运行时真的生效（推送闸门 ON/OFF）
# ============================================================


def test_runtime_gate_skips_push_when_disabled(env):
    """alert_enabled=false：_check_and_push_new_alerts 在总开关处提前 return，绝不推送。"""
    seed(env, "false")
    import app.modules.weather.tasks as T

    push_spy = mock.MagicMock(return_value=True)
    with mock.patch.object(T, "_is_in_quiet_hours", return_value=False), mock.patch.object(
        T, "_maybe_push", push_spy
    ):
        T._check_and_push_new_alerts(
            [{"id": "a1", "event_type": "warning", "headline": "H"}], None
        )
    push_spy.assert_not_called()


def test_runtime_gate_pushes_when_enabled(env):
    """alert_enabled=true：_check_and_push_new_alerts 走到推送分支，调用 _maybe_push。"""
    seed(env, "true")
    import app.modules.weather.tasks as T

    push_spy = mock.MagicMock(return_value=True)
    stub_analyzer = types.SimpleNamespace(
        analyze=lambda a, b, alerts: [{"type": "alert", "headline": "H"}]
    )
    with mock.patch.object(T, "_is_in_quiet_hours", return_value=False), mock.patch.object(
        T, "_maybe_push", push_spy
    ), mock.patch.object(T, "_make_analyzer", return_value=stub_analyzer), mock.patch(
        "app.repository.weather_repository.WeatherRepository.is_alert_pushed",
        return_value=False,
    ), mock.patch(
        "app.repository.weather_repository.WeatherRepository.mark_alert_pushed",
        return_value=None,
    ), mock.patch(
        "app.modules.weather.message.WeatherFormatter.format_weather_alert",
        return_value="msg",
    ):
        T._check_and_push_new_alerts(
            [{"id": "a1", "event_type": "warning", "headline": "H"}], None
        )
    push_spy.assert_called_once()


# ============================================================
# 四、两条写路径不会造成持久分叉
# ============================================================


def test_no_persistent_divergence_between_two_uis(client, env):
    """无论走天气页还是系统设置页切换，两个 GET 端点拿到的值始终一致。"""
    token = _make_token(1)

    def both_get():
        w = client.get("/api/admin/weather/config", headers=_auth(token)).get_json()[
            "data"
        ]["alert_enabled"]
        s_item = next(
            c
            for c in client.get("/api/admin/config", headers=_auth(token))
            .get_json()["data"]["weather"]["configs"]
            if c["key"] == "alert_enabled"
        )
        return w, s_item["value"]

    # 初始
    seed(env, "true")
    assert both_get() == (True, True)

    # 走天气页关掉
    client.put(
        "/api/admin/weather/config", json={"alert_enabled": False}, headers=_auth(token)
    )
    assert both_get() == (False, False)

    # 走系统设置页打开
    client.put(
        "/api/admin/config/weather/alert_enabled",
        json={"value": True},
        headers=_auth(token),
    )
    assert both_get() == (True, True)

    # 再走天气页关掉
    client.put(
        "/api/admin/weather/config", json={"alert_enabled": False}, headers=_auth(token)
    )
    assert both_get() == (False, False)


# ============================================================
# 五、隐患：两条写路径存储表示不一致（benign，但应消除）
# ============================================================


def test_capitalization_quirk(client, env):
    """修复后：两条写路径都存小写 true/false，存储表示一致（不再有 "False"/"True" 隐患）。"""
    token = _make_token(1)

    # 走天气页（专属）→ 小写
    seed(env, "true")
    client.put(
        "/api/admin/weather/config", json={"alert_enabled": False}, headers=_auth(token)
    )
    assert read_row(env) == "false"

    # 走系统设置页（通用）→ 修复后同样小写，两路径存储表示一致
    client.put(
        "/api/admin/config/weather/alert_enabled",
        json={"value": False},
        headers=_auth(token),
    )
    assert read_row(env) == "false"
