"""
名单导入文件围栏回归测试（B 级修复项 B12）

背景：
`admin_roster_routes._parse_upload_file` 此前是 `if 后缀 == .xlsx: 走 openpyxl
else: 当作 CSV 解码`——**没有任何后缀白名单**，任意后缀（.zip/.exe/.txt/.bin）
都会被丢进 CSV 解析器；同时**没有大小上限**，`file_storage.read()` 直接把整个
请求体读进内存。虽然本机 MAX_CONTENT_LENGTH 会先兜一层，但端点自身没有
「这是什么文件、允许多大」的显式声明，等于把解析路径交给上传者挑选。

现补两道入口围栏：
1. 后缀白名单 `.csv` / `.xlsx`（与「模板下载 / 导出」产出的格式一致）；
2. 大小上限取 `get_upload_max_size()`（= Config.MAX_CONTENT_LENGTH），
   与其它上传端点同一口径。

覆盖：
- 后缀：.txt/.zip/.exe/无后缀一律 ValueError；.csv/.xlsx（含大写 .CSV）放行
- 大小：超过 MAX_CONTENT_LENGTH 时 ValueError，且文案带 MB 数字
- 接线：端点把 ValueError 转成 400 并把原因透传给前端（不是 500、不是通用文案）

运行：
    cd Push_System_Flask && python -m pytest tests/test_roster_import_fence.py -v
"""

import io
import os
import sys
import time
import uuid
from contextlib import contextmanager
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.api.admin_roster_routes import ALLOWED_UPLOAD_EXTS, _parse_upload_file
from app.core.extensions import limiter
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"

CSV_BYTES = "学校,学院,专业,班级,学号,姓名\n重庆科创职业学院,人工智能学院,计算机应用,zk2401,20260001,张三\n".encode()


def _fs(name, data):
    return FileStorage(stream=io.BytesIO(data), filename=name)


@contextmanager
def _app_ctx(max_size=10 * 1024 * 1024):
    """`get_upload_max_size()` 读 current_app.config，故需要一个应用上下文。"""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = max_size
    with app.app_context():
        yield app


def _make_token():
    now = int(time.time())
    payload = {
        "user_id": "1",
        "username": "admin",
        "role": "admin",
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
def client():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
        RATELIMIT_ENABLED=False,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
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
    return flask_app.test_client()


# ============================================================
# 一、后缀白名单
# ============================================================


def test_whitelist_is_exactly_csv_and_xlsx():
    """白名单本身锁死（模板下载/导出也只产出这两种）。"""
    assert set(ALLOWED_UPLOAD_EXTS) == {".csv", ".xlsx"}


@pytest.mark.parametrize(
    "name",
    ["roster.txt", "roster.zip", "roster.exe", "roster.bin", "roster", "roster.csv.bak"],
)
def test_rejects_non_whitelisted_extension(name):
    """反证修复前行为：这些后缀此前都会被当 CSV 解析。"""
    with _app_ctx():
        with pytest.raises(ValueError) as exc:
            _parse_upload_file(_fs(name, CSV_BYTES))
    assert "仅支持" in str(exc.value)


def test_accepts_csv():
    with _app_ctx():
        rows = _parse_upload_file(_fs("roster.csv", CSV_BYTES))
    assert rows and rows[0]["student_number"] == "20260001"


def test_accepts_uppercase_suffix():
    """大写后缀应等同（文件名先 lower()），避免 Windows 导出的 .CSV 被误拒。"""
    with _app_ctx():
        rows = _parse_upload_file(_fs("ROSTER.CSV", CSV_BYTES))
    assert rows and rows[0]["real_name"] == "张三"


def test_accepts_xlsx():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["学校", "学院", "专业", "班级", "学号", "姓名"])
    ws.append(["重庆科创职业学院", "人工智能学院", "计算机应用", "zk2401", "20260002", "李四"])
    buf = io.BytesIO()
    wb.save(buf)

    with _app_ctx():
        rows = _parse_upload_file(_fs("roster.xlsx", buf.getvalue()))
    assert rows and rows[0]["student_number"] == "20260002"


# ============================================================
# 二、大小上限（取 MAX_CONTENT_LENGTH，单一来源）
# ============================================================


def test_rejects_oversize_file():
    with _app_ctx(max_size=64):
        with pytest.raises(ValueError) as exc:
            _parse_upload_file(_fs("roster.csv", CSV_BYTES))
    assert "不能超过" in str(exc.value)


def test_size_message_reports_mb():
    """文案须给用户可读的 MB 数字（100 字节 → 0.0MB 也算带数字，只要不抛别的错）。"""
    with _app_ctx(max_size=1):
        with pytest.raises(ValueError) as exc:
            _parse_upload_file(_fs("roster.csv", b"x" * 10))
    assert "MB" in str(exc.value)


def test_size_limit_follows_config_not_hardcoded():
    """同一份文件：上限够大 → 通过；上限压小 → 拒绝。证明读的是配置而非写死的值。"""
    with _app_ctx(max_size=10 * 1024 * 1024):
        assert _parse_upload_file(_fs("roster.csv", CSV_BYTES))
    with _app_ctx(max_size=16):
        with pytest.raises(ValueError):
            _parse_upload_file(_fs("roster.csv", CSV_BYTES))


# ============================================================
# 三、接线：端点必须把 ValueError 变成 400 并把原因透传
# ============================================================


def test_endpoint_surfaces_suffix_error_as_400(client):
    from app.api import admin_roster_routes

    with mock.patch.object(admin_roster_routes, "StudentRosterService") as svc:
        resp = client.post(
            "/api/admin/roster/students/batch",
            data={"file": (io.BytesIO(CSV_BYTES), "roster.txt")},
            headers={"Authorization": f"Bearer {_make_token()}"},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    assert "仅支持" in resp.get_json()["message"]
    # 被入口拦下，绝不能走到业务写入
    svc.create_batch.assert_not_called()


def test_endpoint_surfaces_size_error_as_400(client):
    from app.api import admin_roster_routes

    big = b"x" * (10 * 1024 * 1024 + 1)
    with mock.patch.object(admin_roster_routes, "StudentRosterService") as svc:
        resp = client.post(
            "/api/admin/roster/students/batch",
            data={"file": (io.BytesIO(big), "roster.csv")},
            headers={"Authorization": f"Bearer {_make_token()}"},
            content_type="multipart/form-data",
        )
    # Flask 的 MAX_CONTENT_LENGTH 会先行 413；若放行到视图则必须是带说明的 400
    assert resp.status_code in (400, 413)
    svc.create_batch.assert_not_called()


def test_endpoint_still_imports_valid_csv(client):
    """回归：白名单不能误伤正常流程（合法 csv 仍能进业务写入）。"""
    from app.api import admin_roster_routes

    with mock.patch.object(admin_roster_routes, "StudentRosterService") as svc:
        svc.create_batch.return_value = {"created": 1, "failures": []}
        resp = client.post(
            "/api/admin/roster/students/batch",
            data={"file": (io.BytesIO(CSV_BYTES), "roster.csv")},
            headers={"Authorization": f"Bearer {_make_token()}"},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    svc.create_batch.assert_called_once()
