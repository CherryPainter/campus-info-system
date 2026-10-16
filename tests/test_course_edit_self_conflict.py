"""
课程编辑「自身兄弟行误判冲突」+ 自建课 data_source 标记回归测试

背景（2026-10-11 生产事故）：
一门课按单节存多行（period_idx=1/2/3 各一行，periods 均为 [1,2,3]）。
编辑时若改动了节次/星期/周次（_schedule_changed=True），后端会调用
_find_period_conflict 做冲突扫描，但只排除「被点击的那一行 old_course_id」，
于是该课自身的兄弟行（同 week_day、节次重叠、周次重叠）被当成冲突 →
返回 400（"与课程《X》冲突"），用户在管理端看到「修改又错了」。

修复（course_routes.py）：编辑分支把整组兄弟行 id 收进 old_course_ids，
并传给 _find_period_conflict(exclude_course_ids=...)，循环体跳过这些行。

覆盖：
- 反向验证：编辑多节次课改节次必须 200（撤掉 exclude_course_ids 接线 → 复现 400）。
- 编辑改星期后 data_source 保持 'admin'。
- 新建多节次课：每行 data_source 必须 'admin'（爬虫不覆盖、可删除）。
- 列表合并：合并记录的 data_source 必须保留 'admin'（决定前端删除按钮是否显示）。

运行：
    cd Push_System_Flask && python -m pytest tests/test_course_edit_self_conflict.py -v
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


def _seed_multi_period(session, week_day=6, periods=(1, 2)):
    """种一门「按单节存多行」的自建课（data_source='admin'），返回各行 id。"""
    semester = {
        "semester_id": 20261,
        "semester_name": "2026-2027-1",
        "academic_year": "2026-2027",
        "term": 1,
    }
    ids = []
    for p in periods:
        c = Course(
            course_code=f"ADMIN-{week_day}-{p}",
            course_name="测试课A",
            teacher="张老师",
            classroom="A101",
            building="",
            week_day=week_day,
            period_idx=p,
            periods=list(periods),
            start_time="08:00",
            end_time="09:45",
            weeks=[6],
            week_number=6,
            data_source="admin",
            push_enabled=True,
            **semester,
        )
        session.add(c)
        session.flush()
        ids.append(c.id)
    session.commit()
    return ids


def test_edit_multi_period_changing_periods_returns_200(client, session):
    """反向验证：编辑把节次从 [1,2] 改成 [1,3]，必须 200。

    撤掉 course_routes.py 编辑分支的 exclude_course_ids 接线 → 兄弟行（period 2）
    被当成冲突 → 返回 400，本用例会变红。这正是 2026-10-11「修改又错了」的根因。
    """
    ids = _seed_multi_period(session, week_day=6, periods=(1, 2))
    old_course_id = ids[0]

    payload = {
        "course_name": "测试课A",
        "week_day": 6,
        "period_idx": "1,3",
        "periods": "1,3",
        "classroom": "A101",
        "weeks": "6",
        "week_number": 6,
        "push_enabled": True,
        "is_edit": True,
        "old_course_id": old_course_id,
    }

    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)

    # 节次 1 保留、3 新增、2 删除：库内只剩 period_idx ∈ {1,3}
    rows = session.query(Course).filter(
        Course.week_day == 6, Course.course_name == "测试课A"
    ).all()
    kept = {c.period_idx for c in rows}
    assert kept == {1, 3}, f"编辑后节次应只剩 1、3，实际 {kept}"
    assert all(c.data_source == "admin" for c in rows), "编辑后每行 data_source 必须为 admin"


def test_edit_multi_period_changing_week_day_keeps_admin_source(client, session):
    """编辑把星期从 6 改成 5（无跨星期冲突），返回 200 且 data_source 仍为 admin。"""
    ids = _seed_multi_period(session, week_day=6, periods=(1, 2))
    old_course_id = ids[0]

    payload = {
        "course_name": "测试课A",
        "week_day": 5,
        "period_idx": "1,2",
        "periods": "1,2",
        "classroom": "A101",
        "weeks": "6",
        "week_number": 6,
        "push_enabled": True,
        "is_edit": True,
        "old_course_id": old_course_id,
    }

    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    rows = session.query(Course).filter(Course.course_name == "测试课A").all()
    assert all(c.week_day == 5 for c in rows), "编辑后星期应整体改为 5"
    assert all(c.data_source == "admin" for c in rows), "编辑后 data_source 必须为 admin"


def test_create_multi_period_marks_admin_source(client, session):
    """新建多节次课：每个节次行 data_source 必须 'admin'（决定前端删除按钮显示）。"""
    payload = {
        "course_name": "新建课B",
        "week_day": 6,
        "period_idx": "1,2,3",
        "periods": "1,2,3",
        "classroom": "B202",
        "semester_id": 20261,
        "weeks": "6",
        "week_number": 6,
        "push_enabled": True,
    }

    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post("/api/course", headers=_headers(), json=payload)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    rows = session.query(Course).filter(Course.course_name == "新建课B").all()
    assert len(rows) == 3, f"应写入 3 行（每节次一行），实际 {len(rows)}"
    assert all(c.data_source == "admin" for c in rows), "新建课每行 data_source 必须为 admin"


def test_list_merge_preserves_admin_source(client, session):
    """列表合并：合并记录的 data_source 必须保留 'admin'（前端据此显示删除按钮）。"""
    _seed_multi_period(session, week_day=6, periods=(1, 2))

    with mock.patch("app.api.course_routes.get_db", return_value=session):
        resp = client.get("/api/course/list?semester_id=20261", headers=_headers())

    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json().get("data", [])
    matched = [d for d in data if d.get("course_name") == "测试课A"]
    assert matched, "列表应含测试课A"
    assert matched[0]["data_source"] == "admin", (
        f"合并记录 data_source 应为 admin，实际 {matched[0].get('data_source')!r}"
    )
