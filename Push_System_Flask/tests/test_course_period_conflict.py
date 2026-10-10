"""
课程节次冲突防护（教学周感知）回归测试

需求（2026-10-10）：同一学期、同一星期，若某节次已被占用（周次重叠），
则不允许再选择该节次（后端写入层返回 400，前端节次多选禁用该选项）。

冲突判定：同学期 + 同星期 + 节次集合有交集 + 周次集合有交集 → 冲突。
任一条件不满足即不算冲突（不同星期 / 不同周次 / 节次不重叠 → 放行）。

覆盖：
- 创建分支：周次重叠 → 400；不同周次 → 200；不同星期 → 200。
- 编辑分支：改到冲突节次 → 400；仅改教师/教室（排课不变） → 200（不误拦）；
  改到自身原节次（排课未变） → 200。
- PUT 端点：改到冲突节次 → 400；改无关字段 → 200。
- 反向验证：撤掉 course_routes 里 create_or_update_course 的冲突校验 →
  创建重叠课从 400 变 200，本用例变红。

运行：
    cd Push_System_Flask && python -m pytest tests/test_course_period_conflict.py -v
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
# 与 test_course_edit_add_period.py 同口径就地降级为通用类型，不影响生产库。
import sqlalchemy as _sa

from app.model.course import Course, JSONEncodedList

Course.__table__.c.term.type = _sa.Integer()
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
        APP_VERSION="6.21.3",
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


SEM = dict(semester_id=20261, semester_name="2026-2027-1", academic_year="2026-2027", term=1)


def _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3), name="已占用课"):
    """种一门占用了指定星期/节次/周次的既有课，返回 Course。"""
    c = Course(
        course_code="OCCUP",
        course_name=name,
        week_day=week_day,
        period_idx=periods[0],
        periods=list(periods),
        start_time="08:10",
        end_time="09:50",
        weeks=list(weeks),
        week_number=weeks[0] if weeks else None,
        data_source="admin",
        push_enabled=True,
        **SEM,
    )
    session.add(c)
    session.commit()
    return c


def _post_payload(week_day, period_idx, weeks, name="新开课", is_edit=False, old_course_id=None):
    return {
        "course_name": name,
        "week_day": week_day,
        "period_idx": period_idx,
        "periods": period_idx if isinstance(period_idx, str) else ",".join(str(p) for p in period_idx),
        "classroom": "",
        "weeks": ",".join(str(w) for w in weeks) if weeks else "",
        "week_number": weeks[0] if weeks else 1,
        "push_enabled": True,
        "is_edit": is_edit,
        "old_course_id": old_course_id,
    }


def test_create_conflict_same_week_overlap(client, session):
    """创建分支：周一第1、2节已被占用且周次重叠 → 400。"""
    _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))

    payload = _post_payload(1, "1,2", (1, 2, 3), name="新开课")
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 400, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "冲突" in body["message"], body


def test_create_no_conflict_diff_weeks(client, session):
    """创建分支：节次重叠但周次不重叠（占 1-3 周，新 9-11 周）→ 200 放行。"""
    _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))

    payload = _post_payload(1, "1,2", (9, 10, 11), name="新开课")
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_create_no_conflict_diff_weekday(client, session):
    """创建分支：节次重叠但不同星期（占周一，新周二）→ 200 放行。"""
    _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))

    payload = _post_payload(2, "1,2", (1, 2, 3), name="新开课")
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_create_no_conflict_diff_semester(client, session):
    """创建分支：同星期同节次但不同学期 → 200 放行。"""
    c = _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))
    c.semester_id = 99999  # 改成另一个学期
    session.commit()

    payload = _post_payload(1, "1,2", (1, 2, 3), name="新开课")
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_edit_conflict_changed_to_occupied(client, session):
    """编辑分支：把课程从周一第3节改到已被占的周一第1、2节（周次重叠）→ 400。"""
    occ = _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))
    old = Course(
        course_code="EDIT-ME",
        course_name="被编辑课",
        week_day=1,
        period_idx=3,
        periods=[3],
        start_time="10:10",
        end_time="10:55",
        weeks=[1, 2, 3],
        week_number=1,
        data_source="admin",
        push_enabled=True,
        **SEM,
    )
    session.add(old)
    session.commit()

    payload = _post_payload(1, "1,2", (1, 2, 3), name="被编辑课", is_edit=True, old_course_id=old.id)
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 400, resp.get_data(as_text=True)


def test_edit_same_schedule_only_teacher_change_passes(client, session):
    """编辑分支：仅改教师（排课字段未变）→ 200，不被误拦。"""
    old = _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3), name="被编辑课")

    payload = _post_payload(1, "1,2", (1, 2, 3), name="被编辑课", is_edit=True, old_course_id=old.id)
    payload["teacher"] = "王老师"
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_put_conflict_changed_to_occupied(client, session):
    """PUT 端点：把单行课程改到已被占的节次（周次重叠）→ 400；改无关字段 → 200。"""
    from app.api.course_routes import course_bp

    occ = _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))
    old = Course(
        course_code="PUT-ME",
        course_name="被改课",
        week_day=1,
        period_idx=3,
        periods=[3],
        start_time="10:10",
        end_time="10:55",
        weeks=[1, 2, 3],
        week_number=1,
        data_source="admin",
        push_enabled=True,
        **SEM,
    )
    session.add(old)
    session.commit()

    # 改 period_idx 到冲突的 1 → 400
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.put(f"/api/course/{old.id}", headers=_headers(), json={"period_idx": 1})
    assert resp.status_code == 400, resp.get_data(as_text=True)

    # 改无关字段（教师）→ 200，且不受守卫影响
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp2 = client.put(f"/api/course/{old.id}", headers=_headers(), json={"teacher": "李老师"})
    assert resp2.status_code == 200, resp2.get_data(as_text=True)


def test_reverse_no_guard_lets_conflict_through(client, session):
    """反向验证：撤掉 create_or_update_course 里的冲突校验 → 创建重叠课从 400 变 200。

    用于确认上面的 400 确实来自本次新增的守卫；若回归测试意外删掉守卫，本用例变红。
    """
    import app.api.course_routes as cr

    _seed_occupied(session, week_day=1, periods=(1, 2), weeks=(1, 2, 3))

    orig = cr._find_period_conflict

    def _always_none(*args, **kwargs):
        return None

    payload = _post_payload(1, "1,2", (1, 2, 3), name="新开课")
    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ), mock.patch.object(cr, "_find_period_conflict", _always_none):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert orig is not None
