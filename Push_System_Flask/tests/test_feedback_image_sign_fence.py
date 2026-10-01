"""
反馈截图签名 URL 围栏回归测试（B 级修复项 B1）

背景（审计事实）：
`GET /api/feedback-images/<name>` 此前是**完全公开、无任何鉴权**的路由。文件名由内容
sha256 生成确实不可枚举，但反馈截图属于「仅提交者与管理员应可见」的内容 —— URL 一旦
泄漏（转发、浏览器历史、代理日志、Referer），任何人在任何时间都能取走原图，服务端事后
无法撤销（改文件名等于换资源）。

修复：给该路由加 `?exp=<unix 秒>&sig=<HMAC-SHA256(SECRET_KEY, "<path>\\n<exp>")>`。
- 签名只在**服务端输出时生成**（`Feedback.to_dict()` / 上传响应），库里存的值会被
  归一化后重新签名，所以 TTL 到期不会把历史反馈里的图片签成死链。
- 公告正文图与公告封面**保持公开**（有意为之）：公告本身就是面向全体学生的内容。

覆盖：
- `sign_path` / `verify_signature`：往返、过期、篡改 sig、篡改路径（签名与路径绑定）、
  缺参、非法 exp、TTL 来自配置
- `extract_image_name`：五种历史形态都能取到文件名；外链/穿越串返回 None
- `signed_feedback_image_url`：历史形态归一化到同一规范路径；旧签名被换成新签名
- 真实路由：无签名 403、签名有效 200、过期 403、篡改 403、跨文件签名 403、非图片后缀 400
- 输出链路：`Feedback.to_dict()` 输出的每个截图 URL 都可通过路由校验
- 上传链路：`/api/miniapp/feedback/upload` 返回的是带签名的 URL
- 反向面：公告图片路由不得被加签名（公开放行，避免误伤）
- 静态守卫：路由必须调用 verify_signature；不得退回「只要扩展名合法就发送」

运行：
    cd Push_System_Flask && python -m pytest tests/test_feedback_image_sign_fence.py -v
"""

import io
import json
import os
import sys
import time
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.extensions import limiter
from app.utils.signed_url import (
    DEFAULT_SIGNED_URL_TTL,
    FEEDBACK_IMAGE_PREFIX,
    extract_image_name,
    get_signed_url_ttl,
    sign_path,
    signed_feedback_image_url,
    verify_signature,
)

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"
ROUTES_SRC = os.path.join(ROOT, "app", "api", "routes.py")
FEEDBACK_ROUTES_SRC = os.path.join(ROOT, "app", "api", "feedback_routes.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _app(ttl=None):
    flask_app = Flask(__name__)
    config = {
        "SECRET_KEY": SECRET,
        "RATELIMIT_ENABLED": False,
        "AUTH_ENABLED": True,
        "APP_VERSION": "6.21.0",
    }
    if ttl is not None:
        config["IMAGE_SIGNED_URL_TTL"] = ttl
    flask_app.config.update(config)
    limiter.init_app(flask_app)

    from app.api.routes import api_bp

    flask_app.register_blueprint(api_bp, url_prefix="/api")
    return flask_app


@pytest.fixture
def image_root(tmp_path, monkeypatch):
    """造一个真实的反馈图目录，并把 Config.OUTPUT_DIR 指过去"""
    from app.core.config import Config

    root = tmp_path / "output"
    fb_dir = root / "feedback-images"
    fb_dir.mkdir(parents=True)
    (fb_dir / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    (fb_dir / "other.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 64)
    monkeypatch.setattr(Config, "OUTPUT_DIR", str(root), raising=False)
    return root


@pytest.fixture
def client(image_root):
    return _app().test_client()


# ============================================================
# 一、签名与校验（纯函数）
# ============================================================


def test_sign_and_verify_round_trip():
    app = _app()
    with app.app_context():
        url = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png")
        assert "?exp=" in url and "&sig=" in url
        path, _, query = url.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        ok, reason = verify_signature(path, params["exp"], params["sig"])
        assert ok is True, reason


def test_verify_rejects_tampered_signature():
    app = _app()
    with app.app_context():
        url = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png")
        path, _, query = url.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        ok, reason = verify_signature(path, params["exp"], params["sig"][:-1] + "0")
        assert ok is False
        assert reason == "签名不匹配"


def test_verify_rejects_signature_bound_to_other_path():
    """签名与路径绑定：拿 A 图的签名去访问 B 图必须失败"""
    app = _app()
    with app.app_context():
        url = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png")
        _, _, query = url.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        ok, _ = verify_signature(FEEDBACK_IMAGE_PREFIX + "b.png", params["exp"], params["sig"])
        assert ok is False


def test_verify_rejects_expired():
    app = _app()
    with app.app_context():
        url = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png", ttl=60, now=int(time.time()) - 3600)
        path, _, query = url.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        ok, reason = verify_signature(path, params["exp"], params["sig"])
        assert ok is False
        assert reason == "签名已过期"


def test_verify_rejects_exp_at_boundary():
    """exp 恰等于 now 视为已过期（不允许「卡在过期瞬间」的模糊地带）"""
    app = _app()
    now = 1_700_000_000
    with app.app_context():
        url = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png", ttl=100, now=now - 100)
        path, _, query = url.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        assert int(params["exp"]) == now
        ok, reason = verify_signature(path, params["exp"], params["sig"], now=now)
        assert ok is False and reason == "签名已过期"


@pytest.mark.parametrize(
    "exp,sig",
    [(None, "abc"), ("", "abc"), ("abc", "abc"), ("1700000000", ""), ("1700000000", None)],
)
def test_verify_rejects_missing_or_malformed(exp, sig):
    app = _app()
    with app.app_context():
        ok, _ = verify_signature(FEEDBACK_IMAGE_PREFIX + "a.png", exp, sig)
        assert ok is False


def test_ttl_reads_config_and_falls_back():
    app = _app(ttl=120)
    with app.app_context():
        assert get_signed_url_ttl() == 120
    bare = Flask(__name__)
    with bare.app_context():
        assert get_signed_url_ttl() == DEFAULT_SIGNED_URL_TTL


def test_missing_secret_key_fails_loudly():
    """没有 SECRET_KEY 时不得静默放行/静默不签名"""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = ""
    with app.app_context():
        with pytest.raises(RuntimeError):
            sign_path(FEEDBACK_IMAGE_PREFIX + "a.png")


def test_ttl_does_not_change_signature_for_same_exp():
    """签名只覆盖 path 与 exp：TTL 变化本身不该改变同一 exp 的签名"""
    app = _app()
    with app.app_context():
        a = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png", ttl=100, now=1_700_000_000)
        b = sign_path(FEEDBACK_IMAGE_PREFIX + "a.png", ttl=999, now=1_700_000_000 - 899)
        assert a == b


# ============================================================
# 二、文件名提取与历史形态归一化
# ============================================================


@pytest.mark.parametrize(
    "value",
    [
        "shot.png",
        "/shot.png",
        "/api/feedback-images/shot.png",
        "/api/feedback-images/shot.png?exp=1&sig=abc",
        "https://yuetang.cloud/api/feedback-images/shot.png?v=1",
        "http://127.0.0.1:29528/api/feedback-images/shot.png",
    ],
)
def test_extract_image_name_accepts_legacy_forms(value):
    assert extract_image_name(value) == "shot.png"


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        123,
        "https://example.com/evil.png",
        "/api/announcement-images/shot.png",
        "/api/feedback-images/../secret.png",
        "/api/feedback-images/a/b.png",
    ],
)
def test_extract_image_name_rejects_others(value):
    assert extract_image_name(value) is None


def test_signed_url_normalizes_all_legacy_forms_to_same_path():
    app = _app()
    with app.app_context():
        forms = [
            "shot.png",
            "/shot.png",
            "/api/feedback-images/shot.png",
            "/api/feedback-images/shot.png?exp=1&sig=deadbeef",
        ]
        paths = {signed_feedback_image_url(v).split("?")[0] for v in forms}
        assert paths == {FEEDBACK_IMAGE_PREFIX + "shot.png"}


def test_signed_url_replaces_stale_signature():
    """输出时必须重新签名：库里存的旧签名不得被原样透出"""
    app = _app()
    with app.app_context():
        stale = sign_path(
            FEEDBACK_IMAGE_PREFIX + "shot.png", ttl=10, now=int(time.time()) - 86400
        )
        fresh = signed_feedback_image_url(stale)
        assert fresh != stale
        path, _, query = fresh.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        assert verify_signature(path, params["exp"], params["sig"])[0] is True


def test_signed_url_keeps_unknown_values_untouched():
    """识别不出文件名（外部链接）时原值返回，不破坏既有数据"""
    app = _app()
    with app.app_context():
        assert signed_feedback_image_url("https://example.com/a.png") == "https://example.com/a.png"
        assert signed_feedback_image_url("") == ""


# ============================================================
# 三、真实路由：签名是唯一通行证
# ============================================================


def _url_for(name, ttl=3600, now=None):
    app = _app()
    with app.app_context():
        return sign_path(FEEDBACK_IMAGE_PREFIX + name, ttl=ttl, now=now)


def test_unsigned_request_is_rejected(client):
    resp = client.get("/api/feedback-images/shot.png")
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_valid_signature_serves_image(client):
    resp = client.get(_url_for("shot.png"))
    assert resp.status_code == 200
    assert resp.data.startswith(b"\x89PNG")


def test_expired_signature_is_rejected(client):
    resp = client.get(_url_for("shot.png", ttl=60, now=int(time.time()) - 3600))
    assert resp.status_code == 403


def test_tampered_signature_is_rejected(client):
    url = _url_for("shot.png")
    resp = client.get(url[:-1] + ("0" if url[-1] != "0" else "1"))
    assert resp.status_code == 403


def test_signature_for_other_file_is_rejected(client):
    """拿 other.jpg 的签名访问 shot.png → 403（签名与路径绑定）"""
    url = _url_for("other.jpg").replace("other.jpg", "shot.png")
    resp = client.get(url)
    assert resp.status_code == 403


def test_missing_signature_params_is_rejected(client):
    assert client.get("/api/feedback-images/shot.png?exp=99999999999").status_code == 403
    assert client.get("/api/feedback-images/shot.png?sig=abc").status_code == 403


def test_bad_extension_still_400_before_signature(client):
    """扩展名白名单仍在签名之前生效（不泄漏「图片是否存在」）"""
    resp = client.get("/api/feedback-images/evil.txt")
    assert resp.status_code == 400


def test_signature_cannot_be_forged_with_public_info(client):
    """仅凭已知的路径与过期时间伪造签名必须失败"""
    exp = int(time.time()) + 3600
    resp = client.get(f"/api/feedback-images/shot.png?exp={exp}&sig={'a' * 32}")
    assert resp.status_code == 403


# ============================================================
# 四、输出链路：to_dict 必须重新签名
# ============================================================


def _feedback_with_images(images):
    from app.model.feedback import Feedback

    fb = Feedback(
        id=1,
        user_id=1,
        type="bug",
        content="x",
        status="pending",
        images=json.dumps(images),
    )
    return fb


def test_to_dict_signs_each_image():
    app = _app()
    with app.app_context():
        data = _feedback_with_images(
            ["/api/feedback-images/shot.png", "https://example.com/ext.png"]
        ).to_dict()
        assert len(data["images"]) == 2
        first, second = data["images"]
        path, _, query = first.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&"))
        assert path == FEEDBACK_IMAGE_PREFIX + "shot.png"
        assert verify_signature(path, params["exp"], params["sig"])[0] is True
        # 外链保持原样
        assert second == "https://example.com/ext.png"


def test_to_dict_output_passes_the_route(client):
    """闭环：to_dict 产出的 URL 直接拿去请求路由必须 200（两端口径一致）"""
    app = _app()
    with app.app_context():
        url = _feedback_with_images(["/api/feedback-images/shot.png"]).to_dict()["images"][0]
    assert client.get(url).status_code == 200


def test_to_dict_output_still_works_for_bare_filename(client):
    """历史数据可能只存裸文件名；归一化后同样能通过路由校验"""
    app = _app()
    with app.app_context():
        url = _feedback_with_images(["shot.png"]).to_dict()["images"][0]
    assert client.get(url).status_code == 200


def test_to_dict_handles_empty_and_broken_images():
    app = _app()
    with app.app_context():
        assert _feedback_with_images([]).to_dict()["images"] == []
        fb = _feedback_with_images([])
        fb.images = "not-json"
        assert fb.to_dict()["images"] == []
        fb.images = json.dumps({"a": 1})  # 非列表脏数据
        assert fb.to_dict()["images"] == []


# ============================================================
# 五、上传链路：返回带签名的 URL
# ============================================================


def _png_bytes(size=(4, 4)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _token(role="student"):
    now = int(time.time())
    payload = {
        "user_id": "1",
        "username": "wx_student",
        "role": role,
        "type": "access",
        "jti": "test-jti",
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, SECRET, algorithm="HS256")


def test_feedback_upload_returns_signed_url(tmp_path, monkeypatch):
    """上传响应里的 url 必须带签名，否则编辑器立刻预览就会 403"""
    from app.api.feedback_routes import miniapp_bp
    from app.core.config import Config

    root = tmp_path / "output"
    monkeypatch.setattr(Config, "OUTPUT_DIR", str(root), raising=False)

    app = _app()
    from app.utils.jwt_auth import JWTManager

    app.extensions["jwt_manager"] = JWTManager(
        secret_key=SECRET,
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")

    session = mock.MagicMock()
    with mock.patch("app.core.database.get_db", return_value=session):
        resp = app.test_client().post(
            "/api/miniapp/feedback/upload",
            data={"file": (io.BytesIO(_png_bytes()), "a.png")},
            headers={"Authorization": f"Bearer {_token()}"},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["errno"] == 0, body
    url = body["data"]["url"]
    assert url.startswith(FEEDBACK_IMAGE_PREFIX) and "?exp=" in url and "&sig=" in url
    # 该 URL 必须能通过验签（与路由同一口径）
    path, _, query = url.partition("?")
    params = dict(kv.split("=", 1) for kv in query.split("&"))
    with app.app_context():
        assert verify_signature(path, params["exp"], params["sig"])[0] is True


# ============================================================
# 六、公开放行面 + 静态守卫
# ============================================================


def test_announcement_image_stays_public(tmp_path, monkeypatch):
    """公告图片必须有意外链式公开：加签名属误伤（公告面向全体学生）"""
    from app.core.config import Config

    root = tmp_path / "output"
    ann = root / "announcement-images"
    ann.mkdir(parents=True)
    (ann / "notice.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    monkeypatch.setattr(Config, "OUTPUT_DIR", str(root), raising=False)

    resp = _app().test_client().get("/api/announcement-images/notice.png")
    assert resp.status_code == 200


def test_route_calls_verify_signature():
    src = _read(ROUTES_SRC)
    block = src.split("def feedback_image(")[1].split("@api_bp.route")[0]
    assert "verify_signature(" in block, "反馈图路由必须验签"
    assert "http_status=403" in block, "验签失败必须拒绝（403），不得静默发送"


def test_other_image_routes_not_signed():
    """只有反馈图需要签名；公告图/封面保持原样（防误伤）"""
    src = _read(ROUTES_SRC)
    for fn in ("def announcement_image(", "def announcement_cover("):
        block = src.split(fn)[1].split("@api_bp.route")[0]
        assert "verify_signature(" not in block, f"{fn} 不应被加签名"


def test_upload_route_uses_sign_path():
    src = _read(FEEDBACK_ROUTES_SRC)
    assert "sign_path(" in src, "上传响应必须走签名工具，不得退回手写 URL"
    assert 'url = f"/api/feedback-images/{stored_name}"' not in src, "手写无签名 URL 不得复活"


def test_no_plain_concat_of_feedback_image_url_outside_tool():
    """归一化只允许发生在 signed_url 模块里（防第二份拼接逻辑漂移）"""
    model_src = _read(os.path.join(ROOT, "app", "model", "feedback.py"))
    assert "signed_feedback_image_url(" in model_src
    assert '"/api/feedback-images/' not in model_src
