"""
上传安全围栏回归测试（B 级修复项 B2 + B6）

B6 —— 上传上限单一来源：
  端点级上限此前是硬编码的 `IMAGE_MAX_SIZE = 20 * 1024 * 1024`，而 Flask 的
  `MAX_CONTENT_LENGTH` 是 10MB。Flask 在**进入视图之前**就按 MAX_CONTENT_LENGTH
  拒绝超大请求体（返回不带说明的 413），所以 20MB 这个值**永远走不到**，是死值：
  用户传 12MB 图片只会看到莫名 413，而不是「图片过大」的友好提示。
  现统一取 `get_upload_max_size()`（= Config.MAX_CONTENT_LENGTH）。

B2 —— 图片内容级校验：
  此前只查扩展名，`把任何文件改名成 .jpg` 就能落盘。现补
  `validate_image_upload_content()`：先 `validate_file_type`（装了 python-magic 时
  做真实 magic bytes 判定），再 `validate_file_content` 用 PIL `Image.verify()`
  确认确实是可解析的图片（本机 python-magic 未安装，PIL 这一步是唯一可靠的内容校验）。

覆盖：
- `get_upload_max_size`：无应用上下文兜底；有上下文取 MAX_CONTENT_LENGTH；配置缺失兜底
- `validate_image_upload_content`：真 PNG 通过；文本改名 .png 被拒；非图片后缀被拒
- 接线（公告正文图 / 公告封面 / 反馈截图）：三个端点都必须真的调用这两个口径——
  把 `get_upload_max_size` 打桩成极小值 → 400「文件大小不能超过」；
  文本改名 .png → 400「图片文件损坏」
- 静态守卫：`IMAGE_MAX_SIZE` / 硬编码 20MB 死值不得复活
- 正向回归：合法 PNG 仍能上传成功（白名单与内容校验不得误伤）

运行：
    cd Push_System_Flask && python -m pytest tests/test_upload_security_fence.py -v
"""

import io
import os
import sys
import time
import uuid
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.extensions import limiter
from app.utils.file_upload_security import (
    _DEFAULT_UPLOAD_MAX_SIZE,
    FileUploadError,
    get_upload_max_size,
    validate_image_upload_content,
)
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"
APP_DIR = ROOT


def _png_bytes(size=(4, 4)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _fs(name, data):
    return FileStorage(stream=io.BytesIO(data), filename=name)


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


def _new_app(*, max_content_length=10 * 1024 * 1024):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
        RATELIMIT_ENABLED=False,
        MAX_CONTENT_LENGTH=max_content_length,
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
def announcement_client():
    from app.api.announcement_routes import announcement_bp

    app = _new_app()
    app.register_blueprint(announcement_bp, url_prefix="/api/admin/announcements")
    return app.test_client()


@pytest.fixture
def feedback_client():
    from app.api.feedback_routes import miniapp_bp

    app = _new_app()
    app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")
    return app.test_client()


# ============================================================
# 一、上传上限单一来源（B6）
# ============================================================


def test_max_size_without_app_context_falls_back():
    assert get_upload_max_size() == _DEFAULT_UPLOAD_MAX_SIZE


def test_max_size_reads_config():
    app = _new_app(max_content_length=3 * 1024 * 1024)
    with app.app_context():
        assert get_upload_max_size() == 3 * 1024 * 1024


def test_max_size_falls_back_when_config_missing():
    app = Flask(__name__)  # 不设 MAX_CONTENT_LENGTH
    with app.app_context():
        assert get_upload_max_size() == _DEFAULT_UPLOAD_MAX_SIZE


def test_max_size_honours_explicit_default():
    app = Flask(__name__)
    with app.app_context():
        assert get_upload_max_size(default=1234) == 1234


def test_dead_20mb_value_is_gone_from_upload_modules():
    """死值守卫：端点上限 > MAX_CONTENT_LENGTH 时那个值是走不到的死值，不得复活。"""
    files = [
        "app/api/announcement_routes.py",
        "app/api/feedback_routes.py",
    ]
    for rel in files:
        with open(os.path.join(APP_DIR, rel), encoding="utf-8") as f:
            src = f.read()
        assert "IMAGE_MAX_SIZE" not in src, f"{rel} 又出现了 IMAGE_MAX_SIZE"
        assert "MAX_ATTACHMENT_SIZE" not in src, f"{rel} 又出现了 MAX_ATTACHMENT_SIZE"
        assert "20 * 1024 * 1024" not in src, f"{rel} 又出现了硬编码 20MB"
        # 必须改为取单一来源
        assert "get_upload_max_size()" in src, f"{rel} 未接入 get_upload_max_size"


# ============================================================
# 二、图片内容级校验（B2）
# ============================================================


def test_content_check_accepts_real_png():
    app = Flask(__name__)
    with app.app_context():
        mime = validate_image_upload_content(_fs("a.png", _png_bytes()))
    assert mime == "image/png"


def test_content_check_rejects_text_renamed_png():
    """核心反证：改扩展名不能绕过（修复前这一步直接放行落盘）。"""
    app = Flask(__name__)
    with app.app_context():
        with pytest.raises(FileUploadError) as exc:
            validate_image_upload_content(_fs("evil.png", b"this is not an image at all"))
    assert "图片文件损坏" in str(exc.value)


def test_content_check_rejects_disallowed_extension():
    app = Flask(__name__)
    with app.app_context():
        with pytest.raises(FileUploadError):
            validate_image_upload_content(_fs("payload.txt", b"hello"))


# ============================================================
# 三、接线：三个上传端点
# ============================================================


def _post_upload(client, url, filename, data, token_role="admin"):
    return client.post(
        url,
        data={"file": (io.BytesIO(data), filename)},
        headers={"Authorization": f"Bearer {_token(token_role)}"},
        content_type="multipart/form-data",
    )


def test_announcement_image_uses_config_size(announcement_client):
    """把单一来源打桩成 1 字节 → 必须 400「不能超过」，证明端点真的去问了该函数。"""
    with mock.patch(
        "app.api.announcement_routes.get_upload_max_size", return_value=1
    ):
        resp = _post_upload(
            announcement_client,
            "/api/admin/announcements/upload-image",
            "a.png",
            _png_bytes(),
        )
    assert resp.status_code == 400
    assert "不能超过" in resp.get_json()["message"]


def test_announcement_image_rejects_fake_image(announcement_client):
    resp = _post_upload(
        announcement_client,
        "/api/admin/announcements/upload-image",
        "evil.png",
        b"not an image",
    )
    assert resp.status_code == 400
    assert "图片文件损坏" in resp.get_json()["message"]


def test_announcement_cover_uses_config_size(announcement_client):
    with mock.patch(
        "app.api.announcement_routes.get_upload_max_size", return_value=1
    ):
        resp = _post_upload(
            announcement_client,
            "/api/admin/announcements/upload-cover",
            "a.png",
            _png_bytes(),
        )
    assert resp.status_code == 400
    assert "不能超过" in resp.get_json()["message"]


def test_announcement_cover_rejects_fake_image(announcement_client):
    resp = _post_upload(
        announcement_client,
        "/api/admin/announcements/upload-cover",
        "evil.png",
        b"not an image",
    )
    assert resp.status_code == 400
    assert "图片文件损坏" in resp.get_json()["message"]


def test_announcement_upload_succeeds_for_real_png(announcement_client, tmp_path):
    """正向回归：合法图片必须仍能上传（校验不得误伤）。落在 tmp_path，不污染 output/。"""
    with mock.patch(
        "app.api.announcement_routes._image_root", return_value=str(tmp_path)
    ):
        resp = _post_upload(
            announcement_client,
            "/api/admin/announcements/upload-image",
            "a.png",
            _png_bytes(),
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["errno"] == 0
    assert body["data"]["url"].startswith("/api/announcement-images/")
    assert len(list(tmp_path.iterdir())) == 1


def _bound_student_db():
    """学生端装饰器要过 `student_required`(用户存在) + 绑定校验(有学号)。

    MagicMock 的属性天然为真：query(...).filter_by(...).first() 返回的桩对象
    既让「用户仍存在」成立，其 `.student_number` 也为真值，一次桩即可满足两道闸。
    """
    session = mock.MagicMock()
    return mock.patch("app.core.database.get_db", return_value=session)


def test_feedback_upload_uses_config_size(feedback_client):
    with _bound_student_db():
        with mock.patch(
            "app.api.feedback_routes.get_upload_max_size", return_value=1
        ):
            resp = _post_upload(
                feedback_client,
                "/api/miniapp/feedback/upload",
                "a.png",
                _png_bytes(),
                token_role="student",
            )
    assert resp.status_code == 400
    assert "不能超过" in resp.get_json()["message"]


def test_feedback_upload_rejects_fake_image(feedback_client):
    with _bound_student_db():
        resp = _post_upload(
            feedback_client,
            "/api/miniapp/feedback/upload",
            "evil.png",
            b"not an image",
            token_role="student",
        )
    assert resp.status_code == 400
    assert "图片文件损坏" in resp.get_json()["message"]
