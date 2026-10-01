"""
管理面最小权限 / 课程导入路径 / 服务信息暴露 围栏回归测试
（B 级修复项 B3 + B4 + B11）

B3 —— 管理端端点权限不足：
  4 个端点在审计时仍是 `@jwt_required`，即**任意已登录学生令牌**都能读到后台信息：
  - GET /api/course/crawl-tasks        全校爬取预约计划列表
  - GET /api/course/crawl-tasks/<id>   计划详情
  - GET /api/admin/processes/running   后台运行态（进程名/任务类型/进度）
  - GET /api/tasks/<id>                统一任务查询（含执行态与错误信息）
  逐一 grep 消费方后确认：全部只有 admin-frontend 调用（`/api/tasks/<id>` 连前端调用方
  都没有），故一律收紧为 `@admin_required`，对现有页面零影响。

B4 —— 课程导入路径穿越：
  `POST /api/course/import` 曾把客户端传来的 `file_path` 直接交给 `open()`，
  管理员令牌（或被盗用的令牌）可读服务器任意文件。现限定为
  「爬虫产出目录 output/course-data/ 内的 .json」，并用 realpath 归一化后再比对。

B11 —— 服务信息端点自述攻击面：
  `GET /api/` 曾返回 7 条管理端路径的 `endpoints` 清单（两端前端均无消费方），
  等于给扫描器一份目录。现不再返回；`version` / `your_ip` 经权衡保留。

覆盖：
- 学生令牌访问 4 个端点一律 403（逐个断言，缺一个就红）
- 管理令牌访问不是 403（证明收紧的是角色，不是把端点打死）
- 导入路径：非 .json → 400；目录外 .json → 400；目录内不存在 → 404（说明白名单放行）
- `GET /api/` 响应不含 endpoints/攻击面清单，但仍含 version

运行：
    cd Push_System_Flask && python -m pytest tests/test_admin_surface_fence.py -v
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

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"

# 爬虫产出目录（与 course_routes.import_courses 的 allowed_root 同口径）
ALLOWED_ROOT = os.path.realpath(
    os.path.join(ROOT, "app", "cqie-course-timetable", "output", "course-data")
)


def _token(role="admin"):
    now = int(time.time())
    payload = {
        "user_id": "1",
        "username": "admin" if role == "admin" else "wx_student",
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, SECRET, algorithm="HS256")


def _headers(role="admin"):
    return {"Authorization": f"Bearer {_token(role)}"}


def _new_app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
        RATELIMIT_ENABLED=False,
        APP_VERSION="6.20.0",
        AUTH_ENABLED=True,
    )
    flask_app.extensions["jwt_manager"] = JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    limiter.init_app(flask_app)
    return flask_app


@pytest.fixture
def course_client():
    from app.api.course_routes import course_bp

    app = _new_app()
    app.register_blueprint(course_bp, url_prefix="/api/course")
    return app.test_client()


@pytest.fixture
def process_client():
    from app.api.process_routes import process_bp

    app = _new_app()
    app.register_blueprint(process_bp, url_prefix="/api/admin/processes")
    return app.test_client()


@pytest.fixture
def task_client():
    from app.api.task_routes import task_bp

    app = _new_app()
    app.register_blueprint(task_bp, url_prefix="/api/tasks")
    return app.test_client()


# ============================================================
# 一、B3：学生令牌不得读取管理面
# ============================================================


def test_crawl_task_list_rejects_student(course_client):
    resp = course_client.get("/api/course/crawl-tasks", headers=_headers("student"))
    assert resp.status_code == 403


def test_crawl_task_detail_rejects_student(course_client):
    resp = course_client.get("/api/course/crawl-tasks/1", headers=_headers("student"))
    assert resp.status_code == 403


def test_running_processes_rejects_student(process_client):
    resp = process_client.get("/api/admin/processes/running", headers=_headers("student"))
    assert resp.status_code == 403


def test_task_detail_rejects_student(task_client):
    resp = task_client.get("/api/tasks/1", headers=_headers("student"))
    assert resp.status_code == 403


def test_unauthenticated_also_rejected(course_client):
    """无令牌同样不得通过（403/401 皆可，只要不是 200）。"""
    resp = course_client.get("/api/course/crawl-tasks")
    assert resp.status_code in (401, 403)


def test_crawl_task_list_allows_admin(course_client):
    """收紧的是角色，不是把端点打死：管理令牌应正常返回 200。"""
    session = mock.MagicMock()
    session.query.return_value.count.return_value = 0
    session.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
    with mock.patch("app.api.course_routes.get_db", return_value=session):
        resp = course_client.get("/api/course/crawl-tasks", headers=_headers("admin"))
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"


def test_task_detail_allows_admin(task_client):
    """管理令牌查询不存在的任务 → 404（说明已越过权限闸门）。"""
    session = mock.MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    with mock.patch("app.api.task_routes.get_db", return_value=session):
        resp = task_client.get("/api/tasks/999", headers=_headers("admin"))
    assert resp.status_code == 404


# ============================================================
# 二、B4：课程导入路径白名单
# ============================================================


def _import(course_client, file_path):
    return course_client.post(
        "/api/course/import",
        json={"file_path": file_path},
        headers=_headers("admin"),
    )


def test_import_rejects_non_json_extension(course_client):
    resp = _import(course_client, "/etc/passwd")
    assert resp.status_code == 400
    assert "json" in resp.get_json()["message"]


def test_import_rejects_path_outside_allowed_root(course_client):
    """核心反证：目录外的 .json 也必须被拒（修复前会被直接 open()）。"""
    outside = os.path.join(os.path.dirname(ALLOWED_ROOT), "..", "processed_course_table.json")
    resp = _import(course_client, outside)
    assert resp.status_code == 400
    assert "course-data" in resp.get_json()["message"]


def test_import_rejects_traversal_escape(course_client):
    """用 .. 反穿出白名单目录：realpath 归一化后必须仍被拦。"""
    escape = os.path.join(ALLOWED_ROOT, "..", "..", "..", "..", "evil.json")
    resp = _import(course_client, escape)
    assert resp.status_code == 400


def test_import_allows_whitelisted_root_and_reports_missing_file(course_client):
    """白名单内的路径应放行到「文件是否存在」这一步：不存在 → 404（而非 400）。"""
    inside = os.path.join(ALLOWED_ROOT, "processed", "__not_exist__.json")
    resp = _import(course_client, inside)
    assert resp.status_code == 404
    assert "不存在" in resp.get_json()["message"]


# ============================================================
# 三、B11：服务信息端点不再自述攻击面
# ============================================================


def test_index_has_no_endpoint_map():
    from app.api.routes import api_bp

    app = _new_app()
    app.register_blueprint(api_bp, url_prefix="/api")
    resp = app.test_client().get("/api/")
    assert resp.status_code == 200
    body = resp.get_json()
    # 攻击面自述必须消失
    assert "endpoints" not in body
    # 刻意保留的两项仍在（运维核对版本 / 自助查 IP 配白名单）
    assert "version" in body
    assert "your_ip" in body


def test_index_source_has_no_endpoint_dict():
    """源码级守卫：避免有人顺手把 endpoints 清单加回来。"""
    with open(os.path.join(ROOT, "app", "api", "routes.py"), encoding="utf-8") as f:
        src = f.read()
    assert "endpoints={" not in src
    assert "endpoints=" not in src
