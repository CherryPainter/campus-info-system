"""
课程编辑分支「新增节次」回归测试

背景（2026-10-10 生产事故）：
管理端编辑课程、把节次从「1」改成「1,3」时，后端编辑分支会为新增的节次 3 单独
INSERT 一行。但这条新增行此前漏传 `course_code`，而 courses 表 course_code 列
`nullable=False`，导致 commit 抛 IntegrityError(1048)，整次编辑 500 失败
（日志：`Column 'course_code' cannot be null`）。用户在管理端看到「保存失败」，
于是改为先删节、再单独新增，绕过了编辑分支，但每个 Gunicorn worker 缓存不一致
又引发了「今日课程一会一节一会两节」。

覆盖：
- 反向验证：编辑新增节次必须 200 且新增行 course_code 非空（撤掉修复会复现 500）。
- 正常编辑保留/删除/新增三类节次的行数变化正确。

运行：
    cd Push_System_Flask && python -m pytest tests/test_course_edit_add_period.py -v
"""

import os
import sys
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Course 模型用了 MySQL 专有类型（TINYINT / mysql.JSON），SQLite 内存库无法渲染，
# 与 test_course_admin_protection.py 同口径就地降级为通用类型，不影响生产库。
import sqlalchemy as _sa

from app.model.course import Course, JSONEncodedList
_orig_load = JSONEncodedList.load_dialect_impl


def _json_load(self, dialect):
    if dialect.name == "mysql":
        return _orig_load(self, dialect)
    return dialect.type_descriptor(_sa.String())


JSONEncodedList.load_dialect_impl = _json_load


SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _token():
    import time
    import uuid

    import jwt as _jwt

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


def _headers():
    return {"Authorization": f"Bearer {_token()}"}


def _new_app():
    from flask import Flask

    from app.core.extensions import limiter
    from app.utils.jwt_auth import JWTManager

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
def client():
    from app.api.course_routes import course_bp

    app = _new_app()
    app.register_blueprint(course_bp, url_prefix="/api/course")
    return app.test_client()


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Course.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _seed(session):
    """种一门既有手动课：周六第1节，课程代码非空。"""
    c = Course(
        course_code="ADMIN-SEED",
        course_name="职业发展与就业指导.",
        semester_id=20261,
        semester_name="2026-2027-1",
        academic_year="2026-2027",
        term=1,
        week_day=6,
        period_idx=1,
        periods=[1],
        start_time="08:00",
        end_time="08:45",
        weeks=[6],
        week_number=6,
        data_source="admin",
        push_enabled=True,
    )
    session.add(c)
    session.commit()
    return c


def test_edit_add_period_sets_course_code(client, session):
    """反向验证：编辑把节次扩到 1,3，新增的节次3 行必须带 course_code，返回 200。

    撤掉 course_routes.py 编辑分支 to_add 的 course_code 兜底 → commit 抛
    IntegrityError → 返回 500，本用例会变红。
    """
    old = _seed(session)

    payload = {
        "course_name": "职业发展与就业指导.",
        "week_day": 6,
        "period_idx": "1,3",
        "periods": "1,3",
        "classroom": "",
        "weeks": "6",
        "week_number": 6,
        "push_enabled": True,
        "is_edit": True,
        "old_course_id": old.id,
    }

    # 不让本测试的 session 被 _reload_schedule_cache 关闭，避免干扰后续断言
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)

    rows = session.query(Course).filter(
        Course.week_day == 6, Course.course_name == "职业发展与就业指导."
    ).all()
    by_period = {c.period_idx: c for c in rows}
    assert 1 in by_period, "原节次 1 应保留"
    assert 3 in by_period, "新增节次 3 应写入"
    assert by_period[3].course_code, "新增节次 3 的 course_code 不得为空"
    assert by_period[1].course_code == "ADMIN-SEED", "保留行不应被改动身份"


def test_edit_remove_period_deletes_row(client, session):
    """对照组：把节次从 1,3 缩回 1，节次3 行应被删除。"""
    old = Course(
        course_code="ADMIN-SEED",
        course_name="职业发展与就业指导.",
        semester_id=20261,
        semester_name="2026-2027-1",
        academic_year="2026-2027",
        term=1,
        week_day=6,
        period_idx=3,
        periods=[3],
        start_time="10:30",
        end_time="12:10",
        weeks=[6],
        week_number=6,
        data_source="admin",
        push_enabled=True,
    )
    session.add(old)
    session.commit()

    payload = {
        "course_name": "职业发展与就业指导.",
        "week_day": 6,
        "period_idx": "1",
        "periods": "1",
        "classroom": "",
        "weeks": "6",
        "week_number": 6,
        "push_enabled": True,
        "is_edit": True,
        "old_course_id": old.id,
    }
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    rows = session.query(Course).filter(
        Course.week_day == 6, Course.course_name == "职业发展与就业指导."
    ).all()
    assert [c.period_idx for c in rows] == [1], "节次 3 应被删除，仅剩 1"
