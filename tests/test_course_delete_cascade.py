"""
课程删除「整组级联」回归测试

背景（用户 2026-10-13 实报）：
一门多节次的自建课（如第 1-4 节）在管理端列表里被合并成一行显示，但数据库按「单节存多行」
存储。旧删除接口 `DELETE /<id>` 只按 id 删一行，导致「删一次只少一个节次、要删多次才删完」
（1-4 节需删 4 次）。

修复：`delete_course` 与 `batch_delete_courses` 改为按「课程身份」（与 /list 合并键一致：
semester_id + week_day + course_name + classroom + week_number，NULL 安全）整组级联硬删。

覆盖：
- 正向：删合并行的 id，整门课（全部节次行）一次性 disappearance，且其他课不受影响。
- 反向验证：撤掉级联（退回「只删 course.id 一行」）后，本用例断言的「整组清零」会变红。
- 批量删除同样级联。
- NULL 教室/周次分支：自建课教室常为空，必须走 is_(None) 比较而非 == None。

运行：
    cd Push_System_Flask && python -m pytest tests/test_course_delete_cascade.py -v
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


def _seed_multiperiod(session, course_name, week_day, periods, classroom=None, week_number=None):
    """按单节存多行，种一门多节次课（模拟自建课：course_key 为 NULL、data_source=admin）。"""
    rows = []
    for p in periods:
        c = Course(
            course_code=f"{course_name}-{p}",
            course_name=course_name,
            semester_id=20261,
            semester_name="2026-2027-1",
            academic_year="2026-2027",
            term=1,
            week_day=week_day,
            period_idx=p,
            periods=list(periods),
            teacher="",
            classroom=classroom,
            building="",
            start_time="08:00",
            end_time="08:45",
            weeks=[1, 2, 3],
            week_number=week_number,
            data_source="admin",
            push_enabled=True,
        )
        session.add(c)
        rows.append(c)
    session.commit()
    return rows


def test_delete_cascades_all_periods(client, session):
    """删合并行的 id，整门 1-4 节课（4 行）一次性清零；另一门课不受影响。

    反向验证：撤掉 delete_course 的级联（退回只删 course.id 一行）后，
    英语课剩余 3 行 → 断言 count==0 会变红。
    """
    english = _seed_multiperiod(session, "英语", week_day=1, periods=[1, 2, 3, 4], classroom=None, week_number=None)
    math = _seed_multiperiod(session, "数学", week_day=1, periods=[1, 2], classroom=None, week_number=None)
    english_first_id = english[0].id

    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.delete(f"/api/course/{english_first_id}", headers=_headers())

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.query(Course).filter(Course.course_name == "英语").count() == 0, "整门英语（含全部节次）应被删光"
    assert session.query(Course).filter(Course.course_name == "数学").count() == 2, "其他课不应被级联误伤"


def test_delete_cascade_with_classroom(client, session):
    """非空教室场景也按身份级联；同星期同教室的不同课互不影响。"""
    english = _seed_multiperiod(session, "英语", week_day=2, periods=[1, 2, 3], classroom="A101", week_number=1)
    physics = _seed_multiperiod(session, "物理", week_day=2, periods=[1], classroom="A101", week_number=1)
    english_first_id = english[0].id

    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.delete(f"/api/course/{english_first_id}", headers=_headers())

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.query(Course).filter(Course.course_name == "英语").count() == 0
    assert session.query(Course).filter(Course.course_name == "物理").count() == 1, "同名不同课不应被删"


def test_batch_delete_cascades(client, session):
    """批量删除：勾选合并后的 1-4 节一行（1 个 id），整组 4 行一并删除。"""
    english = _seed_multiperiod(session, "英语", week_day=3, periods=[1, 2, 3, 4], classroom=None, week_number=None)
    english_first_id = english[0].id

    with mock.patch("app.api.course_routes.get_db", return_value=session), mock.patch(
        "app.api.course_routes._reload_schedule_cache"
    ):
        resp = client.post(
            "/api/course/batch-delete",
            headers=_headers(),
            json={"ids": [english_first_id]},
        )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.query(Course).filter(Course.course_name == "英语").count() == 0, "批量删除也应整组级联"
