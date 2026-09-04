"""
身份绑定（组织树+一次性码）+ 账号注销安全回归测试（v6.17）

覆盖：
- 组织树：四级链路创建 / 同父重名拒绝 / 非法层级拒绝 / 名称路径定位班级
- 名单：service.create(class_id) 冗余路径继承 / 批量导入按名称路径定位
- 绑定码：生成 8 位码（sha256 落库）/ 正确码绑定成功 / 错码 403 / 核销后不可复用
- 绑定：重复 POST /student/bind → 403 ALREADY_BOUND（防覆盖他人学号）
- 注销：DELETE /user/me 后 users.is_active=False + token 撤销 + 受保护接口 401

设计：SQLite 内存库 + User/StudentProfile/OrgUnit/StudentRoster/WechatAccount/
TokenBlacklist 表；mock get_db 指向同一 session；手造学生 token 直接打路由。

运行：
    cd Push_System_Flask && python -m pytest tests/test_bind_and_delete_account.py -v
"""

import os
import sys
import time
import uuid
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.api_response import api_success
from app.core.extensions import limiter
from app.model.org_unit import OrgUnit
from app.model.student_profile import StudentProfile
from app.model.student_roster import StudentRoster
from app.model.token_blacklist import TokenBlacklist
from app.model.user import User
from app.model.wechat_account import WechatAccount
from app.services.org_unit_service import OrgUnitService
from app.services.student_roster_service import StudentRosterService, _hash_code
from app.utils.jwt_auth import JWTManager
from app.utils.student_auth import student_required

import sqlalchemy as _sa

# User.avatar 是 MySQL MEDIUMTEXT，SQLite 无法渲染，测试环境替换为通用 TEXT
User.__table__.c.avatar.type = _sa.Text()

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"

SCHOOL = "重庆科创职业学院"
COLLEGE = "人工智能与大数据学院"
MAJOR = "计算机应用"
CLASS_NAME = "zk2401"
CODE = "AB3K7P2Q"


def _make_token(user_id, username="wx_test", role="student", expire_offset=3600):
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expire_offset,
    }
    return _jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    WechatAccount.__table__.create(engine)
    StudentProfile.__table__.create(engine)
    OrgUnit.__table__.create(engine)
    StudentRoster.__table__.create(engine)
    TokenBlacklist.__table__.create(engine)
    # expire_on_commit=False：service 方法各自 close() 后返回的 ORM 对象
    # 在测试共享 session 里已提交即过期，关闭后再访问会 DetachedInstanceError
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _patch_db(db_session):
    from app.services import org_unit_service
    from app.services import student_roster_service

    with mock.patch(
        "app.core.database.get_db", return_value=db_session
    ), mock.patch(
        "app.utils.jwt_auth.get_db", return_value=db_session
    ), mock.patch.object(
        student_roster_service, "get_db", return_value=db_session
    ), mock.patch.object(
        org_unit_service, "get_db", return_value=db_session
    ):
        yield


@pytest.fixture(scope="module")
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
    from app.api.miniapp_routes import miniapp_bp
    from app.api.miniapp_auth_routes import miniapp_auth_bp

    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")
    flask_app.register_blueprint(miniapp_auth_bp, url_prefix="/api/miniapp/auth")

    # 保护端点需要 student_required 装饰器链：绑定 / 注销 / 受保护业务
    @flask_app.route("/__guard__/protected", methods=["GET"])
    @student_required
    def _protected():
        return api_success(message="ok")

    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_student(db_session, user_id=1, username="wx_test"):
    user = User(id=user_id, username=username, role="student", is_active=True)
    user.password_hash = "x"  # 满足 NOT NULL
    db_session.add(user)
    profile = StudentProfile(user_id=user_id)
    db_session.add(profile)
    db_session.commit()
    return user, profile


def _seed_class_chain(db_session, class_name=CLASS_NAME):
    """建 学校→学院→专业→班级 四级节点，返回班级节点。

    注意：service 方法各自 close() 会回滚未提交事务，seed 必须立即 commit，
    否则后续 service 查询（find_class_by_path 等）在 close 后找不到刚 flush 的节点。
    """
    school = OrgUnit(parent_id=None, node_type="school", name=SCHOOL)
    db_session.add(school)
    db_session.flush()
    college = OrgUnit(parent_id=school.id, node_type="college", name=COLLEGE)
    db_session.add(college)
    db_session.flush()
    major = OrgUnit(parent_id=college.id, node_type="major", name=MAJOR)
    db_session.add(major)
    db_session.flush()
    cls = OrgUnit(parent_id=major.id, node_type="class", name=class_name)
    db_session.add(cls)
    db_session.flush()
    db_session.commit()
    return cls


def _seed_roster(db_session, student_number, bind_code=CODE, is_active=True):
    """建组织链 + 名单（带绑定码 hash）。返回 (class_node, roster)。"""
    cls = _seed_class_chain(db_session)
    roster = StudentRoster(
        class_id=cls.id,
        school=SCHOOL,
        college=COLLEGE,
        major=MAJOR,
        class_name=cls.name,
        student_number=student_number,
        real_name="测试生",
        bind_code_hash=_hash_code(bind_code) if bind_code else None,
        is_active=is_active,
    )
    db_session.add(roster)
    db_session.commit()
    return cls, roster


# ==================== 组织树（service 集成） ====================


def test_org_tree_chain_and_duplicate_reject(db_session):
    """四级链路创建成功；同父重名与非法层级（专业挂专业）被拒绝。"""
    cls = _seed_class_chain(db_session)
    # 链路有效：班级节点可通过路径定位
    found = OrgUnitService.find_class_by_path(SCHOOL, COLLEGE, MAJOR, CLASS_NAME)
    assert found is not None
    assert found.id == cls.id
    # 同父重名拒绝
    _, err = OrgUnitService.create("class", CLASS_NAME, parent_id=cls.parent_id)
    assert err and "已存在同名班级" in err
    # 非法层级：class 不能挂 school
    school_node = db_session.query(OrgUnit).filter_by(node_type="school").first()
    _, err2 = OrgUnitService.create("major", "某专业", parent_id=school_node.id)
    assert err2 and "只能挂在学院下" in err2
    # 学校顶层不能挂父
    _, err3 = OrgUnitService.create("school", "另一所大学", parent_id=cls.id)
    assert err3 and "顶层" in err3


def test_org_rename_refreshes_roster_path(db_session):
    """重命名专业后，其下名单冗余 major 列应被级联刷新。"""
    cls, roster = _seed_roster(db_session, "20260001")
    # 重命名专业
    major_node = db_session.query(OrgUnit).filter_by(node_type="major").first()
    updated, err = OrgUnitService.rename(major_node.id, "软件技术")
    assert err is None and updated.name == "软件技术"
    # 重新查 roster，冗余列已刷新
    db_session.expire_all()
    roster_after = (
        db_session.query(StudentRoster).filter_by(student_number="20260001").first()
    )
    assert roster_after.major == "软件技术"


def test_org_delete_protected_when_used(db_session):
    """班级下有名单时禁止删除；删空名单后可删。"""
    _, roster = _seed_roster(db_session, "20260001")
    ok, err = OrgUnitService.delete(roster.class_id)
    assert not ok and "仍有学生名单" in err
    # 删除名单后即可删班级
    StudentRosterService.delete(roster.id)
    ok2, err2 = OrgUnitService.delete(roster.class_id)
    assert ok2 and err2 is None


# ==================== 名单 service（冗余路径继承） ====================


def test_roster_create_inherits_org_path(db_session):
    """service.create(class_id) 应自动带出 学校/学院/专业/班级 冗余列。"""
    cls = _seed_class_chain(db_session)
    row, err = StudentRosterService.create(
        class_id=cls.id, student_number="20260002", real_name="李四"
    )
    assert err is None and row is not None
    assert row.school == SCHOOL
    assert row.college == COLLEGE
    assert row.major == MAJOR
    assert row.class_name == CLASS_NAME
    assert row.student_number == "20260002"
    assert row.bind_code_hash is None  # 新建默认无码


def test_roster_create_rejects_bad_class(db_session):
    """class_id 指向专业节点时应拒绝（只允许挂班级）。"""
    _seed_class_chain(db_session)
    major_node = db_session.query(OrgUnit).filter_by(node_type="major").first()
    row, err = StudentRosterService.create(
        class_id=major_node.id, student_number="20260003"
    )
    assert row is None and err and "班级不存在" in err


def test_roster_batch_import_locates_class_by_path(db_session):
    """批量导入按名称路径定位班级（组织须先建好）；无对应班级时报错。"""
    _seed_class_chain(db_session)
    result = StudentRosterService.create_batch(
        [
            {
                "school": SCHOOL,
                "college": COLLEGE,
                "major": MAJOR,
                "class_name": CLASS_NAME,
                "student_number": "20260010",
            }
        ]
    )
    assert result["created"] == 1 and result["failures"] == []
    # 组织不存在 → 失败
    result2 = StudentRosterService.create_batch(
        [
            {
                "school": "某不存在大学",
                "college": "X",
                "major": "Y",
                "class_name": "Z",
                "student_number": "20260011",
            }
        ]
    )
    assert result2["created"] == 0
    assert result2["failures"][0]["reason"].startswith("未找到匹配的班级节点")


# ==================== 绑定码（生成 / 校验 / 核销） ====================


def test_bind_code_generate_and_verify(db_session):
    """生成 8 位码：库内仅 sha256；正确码 verify 通过，错码与无码失败。"""
    _, roster = _seed_roster(db_session, "20260001", bind_code=None)
    assert roster.bind_code_hash is None
    code, err = StudentRosterService.generate_bind_code(roster.id)
    assert err is None and len(code) == 8
    db_session.expire_all()
    roster_after = (
        db_session.query(StudentRoster).filter_by(id=roster.id).first()
    )
    # 库内不是明文
    assert roster_after.bind_code_hash != code
    assert roster_after.bind_code_hash == _hash_code(code)
    # verify 校验
    ok, row = StudentRosterService.verify(SCHOOL, "20260001", code)
    assert ok and row is not None
    # 错码失败
    ok2, _ = StudentRosterService.verify(SCHOOL, "20260001", "ZZZZZZZZ")
    assert not ok2
    # 名单存在但未发放码 → 失败（先由管理员发码才能绑）
    no_code_roster = StudentRoster(
        school=SCHOOL,
        student_number="20260002",
        class_name=CLASS_NAME,
        college=COLLEGE,
        major=MAJOR,
        is_active=True,
        bind_code_hash=None,
    )
    db_session.add(no_code_roster)
    db_session.commit()
    ok3, _ = StudentRosterService.verify(SCHOOL, "20260002", CODE)
    assert not ok3


def test_revoked_code_cannot_reuse(db_session):
    """绑定成功后码被核销（bind_code_hash=None），同码再次 verify 失败。"""
    cls, roster = _seed_roster(db_session, "20260001", bind_code=CODE)
    # 模拟绑定成功核销（与路由一致：清空 hash）
    roster.bind_code_hash = None
    db_session.commit()
    ok, _ = StudentRosterService.verify(SCHOOL, "20260001", CODE)
    assert not ok


# ==================== bind 接口（防重复 / 防冒绑） ====================


def test_bind_first_time_succeeds_with_code(client, db_session):
    """未绑定学生凭正确码绑定成功，profile 继承组织路径（基线）。"""
    _create_student(db_session, user_id=1)
    _, roster = _seed_roster(db_session, "20260001", bind_code=CODE)
    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": SCHOOL,
            "student_number": "20260001",
            "bind_code": CODE,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["bound"] is True
    profile = body["profile"]
    assert profile["student_number"] == "20260001"
    # 组织路径随名单继承写入 profile（学生无需填写）
    assert profile["school"] == SCHOOL
    assert profile["college"] == COLLEGE
    assert profile["major"] == MAJOR
    assert profile["class_name"] == CLASS_NAME
    # 码已核销
    db_session.expire_all()
    roster_after = (
        db_session.query(StudentRoster).filter_by(id=roster.id).first()
    )
    assert roster_after.bind_code_hash is None


def test_bind_rejects_wrong_code(client, db_session):
    """码错误 → 403（学号/班级半公开，码是持有凭证）。"""
    _create_student(db_session, user_id=1)
    _seed_roster(db_session, "20260001", bind_code=CODE)
    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": SCHOOL,
            "student_number": "20260001",
            "bind_code": "WRONG123",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    # 未绑定成功：profile.student_number 仍为空
    profile = db_session.query(StudentProfile).filter_by(user_id=1).first()
    assert profile.student_number is None


def test_bind_rejects_without_code(client, db_session):
    """名单未发放码时不可绑定（管理员先发码）。"""
    _create_student(db_session, user_id=1)
    _seed_roster(db_session, "20260001", bind_code=None)
    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": SCHOOL,
            "student_number": "20260001",
            "bind_code": CODE,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_bind_rejects_already_bound(client, db_session):
    """已绑定学生重复 bind → 403 ALREADY_BOUND（防覆盖为他人学号）"""
    user, profile = _create_student(db_session, user_id=1)
    # 模拟已绑定
    profile.school = SCHOOL
    profile.student_number = "20260001"
    profile.class_name = CLASS_NAME
    db_session.commit()

    # 构造另一个学号也在预录名单里（模拟"想换成他人学号"）
    _seed_roster(db_session, "20260002", bind_code=CODE)
    token = _make_token(1)
    resp = client.post(
        "/api/miniapp/student/bind",
        json={
            "school": SCHOOL,
            "student_number": "20260002",
            "bind_code": CODE,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    body = resp.get_json()
    assert body.get("code") == "ALREADY_BOUND"
    # 关键：profile 的 student_number 没被覆盖（重新 query，避免 refresh 跨 session 报错）
    profile_after = (
        db_session.query(StudentProfile).filter_by(user_id=1).first()
    )
    assert profile_after.student_number == "20260001"


# ==================== 注销账号 ====================


def test_delete_account_disables_user_and_revokes_token(client, app, db_session):
    """DELETE /user/me：users.is_active=False + access_token 进入黑名单"""
    user, _ = _create_student(db_session, user_id=1)
    access_token = _make_token(1)
    user_id = 1
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = client.delete("/api/miniapp/auth/user/me", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"

    # is_active 已被置 False（重新 query 避免跨 session refresh 报错）
    user_after = db_session.query(User).filter_by(id=user_id).first()
    assert user_after.is_active is False
    # access_token 已进入黑名单
    jti = _jwt.decode(
        access_token, SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )["jti"]
    blacklisted = (
        db_session.query(TokenBlacklist)
        .filter_by(jti=jti)
        .first()
    )
    assert blacklisted is not None


def test_deleted_account_cannot_access_business(client, app, db_session):
    """注销后携带原 token 访问需鉴权接口 → 401（黑名单生效）"""
    _create_student(db_session, user_id=1)
    access_token = _make_token(1)
    headers = {"Authorization": f"Bearer {access_token}"}

    # 先注销
    client.delete("/api/miniapp/auth/user/me", headers=headers)
    # 再访问受保护接口
    resp = client.get("/__guard__/protected", headers=headers)
    assert resp.status_code == 401
