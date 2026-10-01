#!/usr/bin/env python3
"""富文本正文的 HTML 白名单清洗（B 级修复项 B5）。

问题（审计事实）：
公告正文与自定义推送正文由管理端 WangEditor 富文本编辑器产出，**原样入库、原样下发**。
服务写入链路（`announcement_service._apply_updates` / `push_routes` 的 create/update）
只做了 `str(value)`，没有任何 HTML 过滤；读取链路同样原样透出。而管理端的编辑器预览
用的是 `dangerouslySetInnerHTML`（`MessageEditor.tsx:749`）—— 于是「一个管理员账号写入的
正文，在另一个管理员的浏览器里以 HTML 执行」这条管理员间存储型 XSS 链路是通的。
小程序端用的是 Taro `<RichText>`（只渲染受限子集、不执行脚本），风险较低，但同一个
正文也会进入管理端预览，故必须从源头清洗。

方案：
- 白名单清洗，用 **nh3**（ammonia 的 Rust 绑定；`bleach` 已停止维护）。
- 标签白名单按**编辑器真实能力**推导：管理端 WangEditor v5.1.23 用的是默认工具栏
  （`toolbarConfig` 只 excludeKeys 了 fullScreen / group-video），即
  headerSelect/blockquote/bold/italic/underline/through/code/sup/sub/clearStyle/color/
  bgColor/fontSize/fontFamily/lineHeight/列表/todo/对齐/缩进/表情/链接/图片/表格/codeBlock/
  divider。据此映射到实际产出的标签集，再与库中真实正文（抓 5 条公告，标签仅
  p/br/h3/img）交叉核对。
- **必须显式给 `filter_style_properties`**：实测（nh3 0.3.7）不传该项时会保留**全部**
  style 属性，包括 `position: fixed`、`z-index`、`background-image: url(http://evil/...)`
  —— 可做点击劫持遮罩与外部探针。默认值不是「安全子集」而是「不过滤」。
- `url_schemes` 收紧为 http/https/mailto/tel：排除 `data:`（避免 `data:text/html` 与超大
  base64 正文入库）与一大批冷门协议。
- 相对路径（`/api/announcement-images/x.png`）必须保留 —— 实测 nh3 默认放行相对 URL。

失败姿态（fail-closed）：
nh3 未安装时**拒绝**清洗请求（抛 `HtmlSanitizerUnavailable`），而不是「清洗失败就放行原文」。
写入被拒 = 管理员看到明确错误；读取被拒 = 明确报错。绝不静默降级为「不过滤」。
启动期由 `check_sanitizer_startup()` 打 ERROR 日志提示安装，但不 fail-fast —— 缺一个
富文本组件的依赖不该把天气/电量/课表等无关功能一起拖死。

已知行为变化（有意接受）：
- 不再保留 `data:` 协议的 `<img src>`（粘贴截图在编辑器里会先上传成站内图片；
  上传失败时图片会变空 src，编辑器中即时可见）。
- 表格/列表/代码块等格式按编辑器能力放行，但库中现网数据没有这些样例，
  故「这些格式端到端不被误伤」未经真实数据验证（见审计报告 §7 未验证边界）。
"""

from app.core.logger import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - 安装与否决定分支
    import nh3 as _nh3
except ImportError:  # pragma: no cover
    _nh3 = None

# 与 requirements.txt 保持一致，供启动期提示使用
REQUIRED_PACKAGE = "nh3"


class HtmlSanitizerUnavailable(RuntimeError):
    """清洗组件不可用：调用方必须拒绝本次写入/读取，不得放行原文。"""


# 标签白名单：由 WangEditor v5 默认工具栏的产出标签推导（见模块 docstring）
ALLOWED_TAGS = frozenset(
    {
        # 段落与结构
        "p",
        "br",
        "hr",
        "div",
        "span",
        "blockquote",
        # 标题（headerSelect / header1-5）
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        # 行内样式（bold / italic / underline / through / sub / sup / code）
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "sub",
        "sup",
        "code",
        # 代码块与引用（codeBlock）
        "pre",
        "mark",
        # 列表（bulletedList / numberedList / todo）
        "ul",
        "ol",
        "li",
        # 链接与图片
        "a",
        "img",
        # 表格（insertTable）
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        "caption",
    }
)

# 属性白名单：`*` 放开 style（属性内还会再按 filter_style_properties 逐条过滤）
ALLOWED_ATTRIBUTES = {
    "*": {"style"},
    # 注意：`a` 不得再声明 rel —— nh3 在 link_rel 生效时由它自己管理该属性，
    # 同时声明会直接抛 ValueError（"rel" attribute is not allowed ... when link_rel is set）。
    "a": {"href", "target", "title"},
    "img": {"src", "alt", "title", "width", "height", "data-href"},
    "table": {"width", "border", "cellpadding", "cellspacing"},
    "td": {"colspan", "rowspan", "width", "height"},
    "th": {"colspan", "rowspan", "width", "height"},
    "ol": {"start", "type"},
}

# style 内允许保留的属性：编辑器能产出的排版类属性 + 少量无害布局属性。
# 明确排除：position / z-index / background-image / behavior / transform / content /
# filter / clip-path / float 等可造成遮挡、外部探针或层叠攻击的属性。
ALLOWED_STYLE_PROPERTIES = frozenset(
    {
        "text-align",
        "text-indent",
        "text-decoration",
        "text-decoration-line",
        "color",
        "background-color",
        "font-size",
        "font-family",
        "font-weight",
        "font-style",
        "line-height",
        "letter-spacing",
        "white-space",
        "word-break",
        "vertical-align",
        "width",
        "height",
        "max-width",
        "max-height",
        "min-width",
        "min-height",
        "margin",
        "margin-top",
        "margin-right",
        "margin-bottom",
        "margin-left",
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "border",
        "border-width",
        "border-style",
        "border-color",
        "border-collapse",
        "border-radius",
        "list-style-type",
    }
)

# 链接协议白名单：排除 data:（data:text/html 可用于旁路）与一大批冷门协议
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})

# 连内容一起丢弃的标签（避免 <script>`代码`</script> 的文本变成可见正文）
STRIP_CONTENT_TAGS = frozenset({"script", "style", "iframe", "object", "embed", "noscript"})


def is_available() -> bool:
    """清洗组件是否可用（供启动期与测试断言）"""
    return _nh3 is not None


def sanitize_html(html):
    """白名单清洗富文本正文。

    Args:
        html: 原始 HTML（None / 空串原样返回，保持「未填」语义）

    Returns:
        str: 清洗后的 HTML

    Raises:
        HtmlSanitizerUnavailable: nh3 未安装（fail-closed，绝不放行原文）
    """
    if html is None:
        return None
    text = str(html)
    if not text:
        return text

    if _nh3 is None:
        raise HtmlSanitizerUnavailable(
            f"富文本清洗组件 {REQUIRED_PACKAGE} 未安装，已拒绝处理该内容"
            f"（安装：pip install -r requirements.txt）。"
        )

    return _nh3.clean(
        text,
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(STRIP_CONTENT_TAGS),
        attributes=ALLOWED_ATTRIBUTES,
        filter_style_properties=set(ALLOWED_STYLE_PROPERTIES),
        url_schemes=set(ALLOWED_URL_SCHEMES),
        link_rel="noopener noreferrer",
    )


def check_sanitizer_startup(app) -> None:
    """启动期检查：缺依赖时打 ERROR（不 fail-fast，避免拖死无关功能）。"""
    if is_available():
        logger.info("富文本清洗组件已就绪（nh3）")
        return
    logger.error(
        f"富文本清洗组件 {REQUIRED_PACKAGE} 未安装：公告/自定义推送正文的写入与读取将被拒绝"
        f"（fail-closed）。请执行 pip install -r requirements.txt 后重启。"
    )
