"""
公告 / 自定义推送正文 HTML 清洗围栏回归测试（B 级修复项 B5）

背景（审计事实）：
公告正文与自定义推送正文由管理端 WangEditor 富文本编辑器产出，**原样入库、原样下发**：
- 写入链路（`announcement_service._apply_updates`、`push_routes` 的 create/update）只做
  `str(value)` / `.strip()`，没有任何 HTML 过滤；
- 读取链路同样原样透出；
- 而管理端编辑器预览用的是 `dangerouslySetInnerHTML`（MessageEditor.tsx:749）。
=> 「一个管理员写入的正文，在另一个管理员浏览器里以 HTML 执行」这条管理员间存储型 XSS
链路是通的。（小程序端用 Taro `<RichText>`，只渲染受限子集、不执行脚本，风险较低。）

修复：接入 nh3 做白名单清洗，写入与读取两侧都过；组件缺失时 fail-closed（拒绝而非放行原文）。

覆盖：
- 中和能力：script/iframe/style/svg、`on*` 事件、`javascript:` 与 `data:` URL 全部清除
- 保真能力：库中真实正文的形态（p/br/h3/img + `style="text-indent;text-align"` +
  相对图片地址 + `data-href` + alt）必须一字不失，否则等于把公告排版和配图洗没了
- style 过滤：**必须显式给 filter_style_properties** —— nh3 不传该项时会保留全部 style
  （含 position:fixed / z-index / background-image:url(...)，可做点击劫持与外部探针）
- url_schemes 收紧为 http/https/mailto/tel
- fail-closed：nh3 缺失时写入与读取都必须抛错，绝不能「清洗失败就放行原文」
- 接线：公告写入（service.create 捕获 db.add 的对象）、公告读取（to_dict）、
  自定义推送写入（捕获 db.add 的对象）、自定义推送读取（to_dict）
- 静态守卫：requirements.txt 声明 nh3；startup 检查存在

未验证边界（如实标注）：库中现网正文只出现过 p/br/h3/img，**表格/列表/代码块/链接**等
编辑器能力对应的标签是按工具栏能力放行、未经真实数据端到端验证（见审计报告 §7）。

运行：
    cd Push_System_Flask && python -m pytest tests/test_announcement_html_sanitize_fence.py -v
"""

import os
import sys
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils import html_sanitizer
from app.utils.html_sanitizer import (
    ALLOWED_STYLE_PROPERTIES,
    ALLOWED_TAGS,
    HtmlSanitizerUnavailable,
    is_available,
    sanitize_html,
)

# 与库中真实正文同形态的样本（标签/属性/排版与生产数据一致，文字为占位）
REAL_SHAPE = (
    '<h3>标题</h3>'
    '<p style="text-indent: 2em; text-align: justify;">第一段正文。</p>'
    '<p style="text-indent: 2em; text-align: justify;"><br></p>'
    '<p style="text-indent: 2em; text-align: justify;">'
    '<img src="/api/announcement-images/abc.png" alt="图片.png" data-href="" style=""/>'
    "</p>"
)

EVIL = (
    "<p onclick=\"alert(1)\">x</p>"
    "<script>alert('xss')</script>"
    "<style>body{display:none}</style>"
    "<iframe src='http://evil/'></iframe>"
    "<svg onload=alert(1)></svg>"
    "<img src='/api/announcement-images/a.png' onerror=alert(1)>"
    "<a href='javascript:alert(1)'>j</a>"
    "<a href='data:text/html,<script>alert(1)</script>'>d</a>"
    "<p style='position:fixed;z-index:9999;background-image:url(http://evil/x);"
    "text-indent:2em;behavior:url(#x);transform:scale(2)'>y</p>"
)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def unavailable(monkeypatch):
    """模拟 nh3 未安装"""
    monkeypatch.setattr(html_sanitizer, "_nh3", None)


# ============================================================
# 一、前置：组件可用性
# ============================================================


def test_nh3_is_available_in_this_env():
    assert is_available() is True, "运行时环境必须装上 nh3（requirements.txt 已声明）"


def test_none_and_empty_pass_through():
    assert sanitize_html(None) is None
    assert sanitize_html("") == ""


# ============================================================
# 二、中和能力：脚本 / 事件 / 危险协议
# ============================================================


def test_removes_script_tag_and_its_text():
    out = sanitize_html("<p>a</p><script>alert('xss')</script>")
    assert "<script" not in out and "alert" not in out and "<p>a</p>" in out


def test_removes_style_iframe_svg():
    out = sanitize_html("<style>body{}</style><iframe src='http://e/'></iframe><svg onload=1></svg><p>k</p>")
    for bad in ("<style", "<iframe", "<svg", "onload"):
        assert bad not in out
    assert "<p>k</p>" in out


def test_removes_inline_event_handlers():
    out = sanitize_html('<p onclick="alert(1)">x</p><img src="/a.png" onerror="alert(1)">')
    assert "onclick" not in out
    assert "onerror" not in out
    assert "<p>x</p>" in out
    assert 'src="/a.png"' in out


def test_removes_javascript_and_data_urls():
    out = sanitize_html("<a href='javascript:alert(1)'>j</a><a href='data:text/html,x'>d</a>")
    assert "javascript:" not in out
    assert "data:" not in out
    # 链接文字保留（内容不丢），只是不再是可点的危险链接
    assert ">j</a>" in out and ">d</a>" in out


def test_keeps_http_link_and_adds_link_rel():
    out = sanitize_html('<a href="https://example.com/x" target="_blank">go</a>')
    assert 'href="https://example.com/x"' in out
    assert "noopener" in out and "noreferrer" in out


def test_keeps_mailto_and_tel():
    out = sanitize_html('<a href="mailto:a@b.c">m</a><a href="tel:12345">t</a>')
    assert 'href="mailto:a@b.c"' in out
    assert 'href="tel:12345"' in out


def test_drops_other_schemes():
    out = sanitize_html('<a href="ftp://e/x">f</a>')
    assert "ftp:" not in out


# ============================================================
# 三、保真能力：真实正文形态必须一字不失
# ============================================================


def _meaning(out):
    """把 HTML 归一成「有意义的部分」：可见文本 + 标签序列 + style 属性集 + 其他属性集。

    不做逐字节比较 —— nh3 会规范化 style 内部的空白（`text-indent: 2em; text-align: justify`
    变成 `text-indent:2em;text-align:justify`）并丢掉空属性（`style=""`、`data-href=""`），
    这是语义等价的格式差异，不是内容损失。
    """
    import html as _html
    import re

    text = _html.unescape(re.sub(r"<[^>]*>", "", out or "")).strip()
    tags = re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)", out or "")
    styles = {
        p.split(":")[0].strip().lower()
        for s in re.findall(r'style="([^"]*)"', out or "")
        for p in s.split(";")
        if ":" in p
    }
    srcs = re.findall(r'<(?:img|a)[^>]*(?:src|href)="([^"]*)"', out or "")
    return {"text": text, "tags": tags, "styles": styles, "urls": srcs}


def test_real_content_shape_survives_untouched():
    out = sanitize_html(REAL_SHAPE)
    assert _meaning(out) == _meaning(REAL_SHAPE), f"真实形态出现语义损失:\n{out}"


def test_real_shape_keeps_every_tag_and_image():
    out = sanitize_html(REAL_SHAPE)
    assert "<h3>标题</h3>" in out
    assert out.count("<br>") == 1
    assert 'src="/api/announcement-images/abc.png"' in out
    assert "第一段正文。" in out


def test_relative_image_src_survives():
    """图片 GC 与前端显示都依赖相对地址原样保留"""
    out = sanitize_html('<img src="/api/announcement-images/abc.png" alt="a.png" data-href="">')
    assert 'src="/api/announcement-images/abc.png"' in out
    assert 'alt="a.png"' in out
    assert 'data-href=""' in out


def test_style_text_indent_and_align_survive():
    out = sanitize_html('<p style="text-indent: 2em; text-align: justify;">t</p>')
    assert "text-indent" in out and "text-align" in out


def test_editor_capability_tags_allowed():
    """编辑器默认工具栏能产出的标签必须在白名单内（否则会静默吃掉管理员的排版）"""
    for tag in (
        "h1", "h2", "h3", "h4", "h5", "p", "br", "hr", "blockquote", "span",
        "strong", "em", "u", "s", "sub", "sup", "code", "pre",
        "ul", "ol", "li", "a", "img",
        "table", "thead", "tbody", "tr", "th", "td",
    ):
        assert tag in ALLOWED_TAGS, tag


def test_scriptable_tags_not_allowed():
    for tag in ("script", "style", "iframe", "object", "embed", "form", "input", "video", "svg"):
        assert tag not in ALLOWED_TAGS, tag


# ============================================================
# 四、style 过滤（必须显式给 filter_style_properties）
# ============================================================


def test_dangerous_style_properties_dropped():
    out = sanitize_html(
        '<p style="position:fixed;z-index:9999;background-image:url(http://evil/x);'
        'behavior:url(#x);transform:scale(2);text-indent:2em">y</p>'
    )
    for bad in ("position", "z-index", "background-image", "behavior", "transform"):
        assert bad not in out, f"危险 style 未被清除: {bad}"
    assert "text-indent" in out


def test_style_allowlist_is_explicit_and_non_empty():
    """nh3 不传 filter_style_properties 时会保留**全部** style 属性（实测），
    因此本集合必须显式存在且不许含危险项。"""
    assert ALLOWED_STYLE_PROPERTIES, "必须显式给出 style 白名单"
    for bad in ("position", "z-index", "background-image", "behavior", "transform", "float"):
        assert bad not in ALLOWED_STYLE_PROPERTIES


def test_style_filter_is_actually_passed_to_nh3():
    """接线证明：把 filter_style_properties 传成空集，危险属性就会漏出来（说明过滤确实来自它）"""
    with mock.patch.object(html_sanitizer, "_nh3") as fake:
        fake.clean.return_value = "<p>y</p>"
        sanitize_html("<p>y</p>")
    kwargs = fake.clean.call_args.kwargs
    assert kwargs["filter_style_properties"] == set(ALLOWED_STYLE_PROPERTIES)


def test_url_schemes_passed_to_nh3():
    with mock.patch.object(html_sanitizer, "_nh3") as fake:
        fake.clean.return_value = "<p>y</p>"
        sanitize_html("<p>y</p>")
    assert fake.clean.call_args.kwargs["url_schemes"] == {"http", "https", "mailto", "tel"}


def test_tags_passed_to_nh3_is_the_allowlist():
    with mock.patch.object(html_sanitizer, "_nh3") as fake:
        fake.clean.return_value = "<p>y</p>"
        sanitize_html("<p>y</p>")
    assert fake.clean.call_args.kwargs["tags"] == set(ALLOWED_TAGS)


# ============================================================
# 五、fail-closed
# ============================================================


def test_sanitize_raises_when_nh3_missing(unavailable):
    with pytest.raises(HtmlSanitizerUnavailable) as exc:
        sanitize_html("<p>x</p>")
    assert "nh3" in str(exc.value)


def test_none_empty_still_ok_when_nh3_missing(unavailable):
    """未填正文不涉及清洗，不应因为缺依赖而报错"""
    assert sanitize_html(None) is None
    assert sanitize_html("") == ""


def test_announcement_write_rejected_when_nh3_missing(unavailable):
    """写入侧 fail-closed：缺依赖时拒绝写入，绝不静默存原文"""
    from app.model.announcement import Announcement
    from app.services.announcement_service import AnnouncementService

    item = Announcement(title="t")
    with pytest.raises(HtmlSanitizerUnavailable):
        AnnouncementService._apply_updates(item, {"content": "<script>x</script>"})


def test_announcement_read_rejected_when_nh3_missing(unavailable):
    """读取侧 fail-closed：缺依赖时报错，绝不把未过滤正文透给管理端预览"""
    from app.model.announcement import Announcement

    item = Announcement(title="t", content="<script>x</script>")
    with pytest.raises(HtmlSanitizerUnavailable):
        item.to_dict(with_content=True)


def test_startup_check_logs_error_when_missing(unavailable, caplog):
    import logging

    with caplog.at_level(logging.ERROR, logger=html_sanitizer.__name__):
        html_sanitizer.check_sanitizer_startup(None)
    assert any("nh3" in r.message for r in caplog.records), caplog.text


def test_startup_check_logs_info_when_present(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger=html_sanitizer.__name__):
        html_sanitizer.check_sanitizer_startup(None)
    assert any("就绪" in r.message for r in caplog.records), caplog.text


def test_startup_check_wired_in_create_app():
    src = _read(os.path.join(ROOT, "app", "__init__.py"))
    assert "check_sanitizer_startup(" in src


# ============================================================
# 六、接线：写入与读取的四个入口
# ============================================================


def _session():
    return mock.MagicMock()


def test_announcement_service_write_sanitizes(monkeypatch):
    """公告写入：捕获真正被 add 进库的对象，断言 content 已清洗"""
    from app.services import announcement_service as svc

    session = _session()
    monkeypatch.setattr(svc, "get_db", lambda: session)

    svc.AnnouncementService().create({"title": "t", "content": EVIL})
    item = session.add.call_args[0][0]
    assert "<script" not in item.content
    assert "onerror" not in item.content
    assert "javascript:" not in item.content
    assert "position" not in item.content


def test_announcement_to_dict_sanitizes_stored_content():
    """公告读取：库里存量的脏正文在输出时被清洗（写入侧修复无法追溯历史数据）"""
    from app.model.announcement import Announcement

    item = Announcement(title="t", content=EVIL)
    out = item.to_dict(with_content=True)["content"]
    assert "<script" not in out
    assert "onerror" not in out
    assert "position" not in out


def test_announcement_to_dict_keeps_real_shape():
    from app.model.announcement import Announcement

    item = Announcement(title="t", content=REAL_SHAPE)
    assert _meaning(item.to_dict(with_content=True)["content"]) == _meaning(REAL_SHAPE)


def test_announcement_to_dict_without_content_untouched():
    from app.model.announcement import Announcement

    data = Announcement(title="t", content=EVIL).to_dict(with_content=False)
    assert "content" not in data


def test_custom_push_write_sanitizes(monkeypatch):
    """自定义推送写入：与公告共用编辑器，同一条 XSS 链路必须一并堵住"""
    from app.api import push_routes

    session = _session()
    monkeypatch.setattr(push_routes, "get_db", lambda: session)
    monkeypatch.setattr(push_routes, "_send_push", lambda push: True)

    app = _push_app()
    resp = app.test_client().post(
        "/api/push",
        json={"title": "t", "content": EVIL, "msg_type": "text", "push_type": "immediate"},
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    pushed = session.add.call_args[0][0]
    assert "<script" not in pushed.content
    assert "onerror" not in pushed.content


def test_custom_push_to_dict_sanitizes_stored_content():
    from app.model.custom_push import CustomPush

    item = CustomPush(title="t", content=EVIL)
    out = item.to_dict()["content"]
    assert "<script" not in out and "onerror" not in out


def test_custom_push_to_dict_keeps_none():
    from app.model.custom_push import CustomPush

    assert CustomPush(title="t", content=None).to_dict()["content"] is None


# ============================================================
# 七、静态守卫
# ============================================================


def test_requirements_declares_nh3():
    src = _read(os.path.join(ROOT, "requirements.txt"))
    assert "nh3" in src, "依赖必须显式声明，否则部署后 fail-closed 会让公告无法发布"


def test_bleach_not_used():
    """bleach 已停止维护，不得回退到它（注释里提到它不算，看真实调用）"""
    for rel in (
        os.path.join("app", "utils", "html_sanitizer.py"),
        os.path.join("app", "model", "announcement.py"),
        os.path.join("app", "model", "custom_push.py"),
    ):
        src = _read(os.path.join(ROOT, rel))
        assert "import bleach" not in src, rel
        assert "bleach.clean" not in src, rel


def test_sanitizer_module_is_single_entry():
    """清洗实现只允许有一处（其它文件只能调用，不得自己拼白名单）"""
    for rel in (
        os.path.join("app", "model", "announcement.py"),
        os.path.join("app", "model", "custom_push.py"),
        os.path.join("app", "services", "announcement_service.py"),
        os.path.join("app", "api", "push_routes.py"),
    ):
        src = _read(os.path.join(ROOT, rel))
        assert "html_sanitizer" in src, rel
        assert "nh3" not in src, f"{rel} 不应直接调用 nh3"


# ============================================================
# 工具
# ============================================================


def _push_app():
    from flask import Flask

    from app.api.push_routes import push_bp
    from app.core.extensions import limiter
    from app.utils.jwt_auth import JWTManager

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret-key-0123456789abcdef0123456789abcdef",
        RATELIMIT_ENABLED=False,
        AUTH_ENABLED=True,
    )
    app.extensions["jwt_manager"] = JWTManager(
        secret_key=app.config["SECRET_KEY"],
        access_token_expire=3600,
        refresh_token_expire=604800,
        refresh_idle_expire=259200,
        refresh_absolute_expire=2592000,
    )
    limiter.init_app(app)
    app.register_blueprint(push_bp, url_prefix="/api/push")
    return app


def _admin_token():
    import time

    import jwt as _jwt

    now = int(time.time())
    return _jwt.encode(
        {
            "user_id": "1",
            "username": "admin",
            "role": "admin",
            "type": "access",
            "jti": "test-jti",
            "iat": now,
            "exp": now + 3600,
        },
        "test-secret-key-0123456789abcdef0123456789abcdef",
        algorithm="HS256",
    )
