"""
小程序「编辑资料」身份字段围栏回归测试（A 级修复项 A2）

背景：`PUT /api/miniapp/student/profile` 的字段白名单里原本含 college / major / grade /
real_name。这些字段的权威来源是**预录名单**（student_roster_service 绑定/同步时回填），
留在白名单里等于「学生直接调 API 就能把自己的学院/专业/年级/姓名改成任意值」，
与「身份以名单为准」冲突，也让按学院/年级做的数据统计与推送范围失真。

覆盖：
- 名单派生字段（real_name / college / major / grade）传入后被**忽略**（不落库）
- 白名单字段（nickname / phone / campus_card_number）仍正常写入
- 多字段混合传入时只落白名单内的字段
- 只传被忽略字段时返回 400（没有可更新字段），不产生空写

运行：
    cd Push_System_Flask && python -m pytest tests/test_miniapp_profile_fence.py -v
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

from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


class _FakeProfile:
    """记录被 setattr 的字段，用于断言「哪些字段真的写进去了」。"""

    def __init__(self, user_id=1):
        self.user_id = user_id
        self.nickname = "old"
        self.phone = None
        self.campus_card_number = None
        self.real_name = "张三"
        self.college = "原学院"
        self.major = "原专业"
        self.grade = "2024"
        self.student_number = "20260001"

    def to_dict(self):
        return {"user_id": self.user_id, "nickname": self.nickname}


class _FakeQuery:
    def __init__(self, model):
        self._model = model

    def filter_by(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        from app.model.student_profile import StudentProfile
        from app.model.user import User

        if self._model is StudentProfile:
            return PROFILE
        if self._model is User:
            return SimpleNamespace(id=1)
        return None

    def count(self):
        return 0

    def all(self):
        return []


class _FakeSession:
    def __init__(self):
        self.added = []
        self.committed = 0

    def query(self, model, *a, **k):
        return _FakeQuery(model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        pass

    def close(self):
        pass


PROFILE = _FakeProfile()
SESSION = _FakeSession()


@pytest.fixture(autouse=True)
def _no_db():
    PROFILE.__init__()  # 每个用例重置为初始值
    SESSION.__init__()
    with mock.patch("app.utils.jwt_auth.get_db", return_value=_FakeSession()), mock.patch(
        "app.core.database.get_db", return_value=SESSION
    ):
        yield


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
    from app.api.miniapp_routes import miniapp_bp

    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def token(app):
    now = int(time.time())
    payload = {
        "user_id": "1",
        "username": "wx_student",
        "role": "student",
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def _put(client, token, body):
    return client.put(
        "/api/miniapp/student/profile",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.parametrize("field", ["real_name", "college", "major", "grade"])
def test_roster_derived_field_ignored_alone(client, token, field):
    """名单派生字段单独传入 → 无可更新字段 → 400，且原值不变"""
    before = getattr(PROFILE, field)
    resp = _put(client, token, {field: "被篡改值"})
    assert resp.status_code == 400
    assert getattr(PROFILE, field) == before
    assert SESSION.committed == 0


def test_roster_derived_fields_ignored_when_mixed(client, token):
    """混在白名单字段里传入：只落白名单字段，身份字段一律不动。

    这是本围栏的核心用例——去掉 allowed_fields 的收窄后，学院/专业/年级/姓名会被写脏。
    """
    resp = _put(
        client,
        token,
        {
            "nickname": "新昵称",
            "phone": "13800000000",
            "real_name": "李四",
            "college": "伪造学院",
            "major": "伪造专业",
            "grade": "2099",
        },
    )
    assert resp.status_code == 200
    # 白名单字段正常写入
    assert PROFILE.nickname == "新昵称"
    assert PROFILE.phone == "13800000000"
    # 名单派生字段被忽略
    assert PROFILE.real_name == "张三"
    assert PROFILE.college == "原学院"
    assert PROFILE.major == "原专业"
    assert PROFILE.grade == "2024"


def test_allowed_fields_still_writable(client, token):
    resp = _put(client, token, {"campus_card_number": "2026000001"})
    assert resp.status_code == 200
    assert PROFILE.campus_card_number == "2026000001"


def test_bind_managed_fields_still_rejected(client, token):
    """绑定接口管辖的字段（学号/班级/学校）本就不可自改，回归确认无回退"""
    for field in ("student_number", "class_name", "school"):
        resp = _put(client, token, {field: "x"})
        assert resp.status_code == 400
