#!/usr/bin/env python3
"""受限资源的签名 URL（B 级修复项 B1）。

问题（审计事实）：
反馈截图（`output/feedback-images/`）是「只有提交者本人与管理员应该看到」的内容，
但它的访问路由 `GET /api/feedback-images/<name>` 是**完全公开**的，没有任何鉴权。
文件名由内容 sha256 生成（`generate_secure_filename`），确实不可被枚举，但 URL 一旦
泄漏 —— 转发时的聊天记录、浏览器历史、反向代理访问日志、图片被引用时的 Referer ——
任何人在**任何时间**都能拿到原图，而且服务端事后**无法撤销**（改文件名等于换资源）。

做法：
给这类资源加 `?exp=<unix 秒>&sig=<HMAC>`。
- `sig = HMAC-SHA256(SECRET_KEY, "<path>\\n<exp>")` 的截断十六进制，比较走 `compare_digest`。
- 过期、缺参、签名不符一律拒绝。
- **签名只在服务端输出时生成**：数据库里存的是不带签名的路径（或历史的旧 URL），
  每次 `to_dict()` 输出时重新签名。因此 TTL 到期后重新拉一次列表/详情就得到新签名，
  不会把图片签成永久死链 —— 这是本方案相比「上传时签一次并落库」的关键差别。

为什么不改鉴权：`<img>` 标签无法携带 `Authorization` 头。若改成鉴权接口，管理端与管理端
都要改成 blob 拉取，且小程序 `<Image>` 的 cookie 行为在本地无法验证（见审计报告 §7 的
未验证边界）。签名 URL 是图片类资源在「不可携带凭证」约束下的标准解法。

未覆盖：公告正文图片与公告封面保持公开（有意为之，见 B1 决策记录）——公告本身就是
面向全体学生的内容，加签名只增加复杂度、不增加保护。
"""

import hashlib
import hmac
import time
from urllib.parse import urlsplit

from flask import current_app

from app.core.logger import get_logger

logger = get_logger(__name__)

# 签名默认有效期（秒）6 小时：够看完一次列表/详情并重开页面，又不足以长期外传。
# 可用 config / .env 的 IMAGE_SIGNED_URL_TTL 覆盖（单一来源见 get_signed_url_ttl）。
DEFAULT_SIGNED_URL_TTL = 6 * 3600

# 反馈截图的路由前缀：签名与校验都以「带该前缀的完整路径」为规范形式，
# 这样即使调用方传进来的是裸文件名或绝对 URL，也能归一化到同一签名基准。
FEEDBACK_IMAGE_PREFIX = "/api/feedback-images/"

# 允许的图片扩展名（与路由、上传端同一份口径）
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def get_signed_url_ttl() -> int:
    """签名 URL 有效期（秒）。单一来源：config -> 默认值，不在调用方另写数字。"""
    return int(current_app.config.get("IMAGE_SIGNED_URL_TTL", DEFAULT_SIGNED_URL_TTL))


def _secret() -> bytes:
    secret = current_app.config.get("SECRET_KEY") or ""
    if not secret:
        # 不静默降级：没有密钥就签不出也不能验，宁可显式失败也不放行未签名请求
        raise RuntimeError("SECRET_KEY 未配置，无法生成/校验签名 URL")
    return str(secret).encode("utf-8")


def _signature(path: str, exp: int) -> str:
    canonical = f"{path}\n{int(exp)}".encode()
    return hmac.new(_secret(), canonical, hashlib.sha256).hexdigest()[:32]


def sign_path(path: str, ttl: int | None = None, now: int | None = None) -> str:
    """给规范路径附加 `?exp=&sig=`，返回可直接放进 `<img src>` 的字符串。"""
    now = int(time.time()) if now is None else int(now)
    ttl = get_signed_url_ttl() if ttl is None else int(ttl)
    exp = now + ttl
    return f"{path}?exp={exp}&sig={_signature(path, exp)}"


def verify_signature(path: str, exp, sig, now: int | None = None) -> tuple:
    """校验签名，返回 (是否通过, 原因)。原因仅用于日志，不返回给客户端。

    开头三个参数的显式校验属冗余防御（后面的 try/except 与 compare_digest 本身也能
    挡住空值），保留是为了让「参数不全」与「签名不对」在日志里可区分，且不依赖
    `int()` 抛异常这种隐式路径。
    """
    if not path or exp is None or not sig:
        return False, "缺少签名参数"
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False, "exp 非法"

    now = int(time.time()) if now is None else int(now)
    # exp 视为「不再有效的时刻」：exp == now 即已失效，不留边界模糊地带
    if exp_int <= now:
        return False, "签名已过期"

    if not hmac.compare_digest(_signature(path, exp_int), str(sig)):
        return False, "签名不匹配"
    return True, "ok"


def extract_image_name(value) -> str | None:
    """从任意历史形态里取出反馈截图文件名。

    兼容：裸文件名 / `/xxx.jpg` / `/api/feedback-images/xxx.jpg` /
    带签名或查询串的上述形态 / 绝对 URL。取不到则返回 None（调用方应保持原值不动，
    避免把非本系统的外链改坏）。
    """
    if not isinstance(value, str) or not value.strip():
        return None

    # 去掉 query 与 fragment，只留路径部分（历史数据里可能已经带了签名）
    split = urlsplit(value.strip())
    path = split.path.strip()
    if "feedback-images/" in path:
        name = path.split("feedback-images/", 1)[1]
    else:
        # 兼容「裸文件名 / /xxx.jpg」这类历史形态。
        # 必须排除带 scheme/netloc 的外部 URL —— 否则会把外部图床链接误改成
        # 本系统路径，等于改坏既有数据。
        if split.scheme or split.netloc:
            return None
        candidate = path.lstrip("/")
        if not candidate or "/" in candidate or not candidate.lower().endswith(_IMAGE_EXTS):
            return None
        name = candidate

    name = name.strip("/")
    if not name or "/" in name or name in (".", ".."):
        return None
    return name


def signed_feedback_image_url(value, ttl: int | None = None, now: int | None = None):
    """把任意历史形态的反馈截图引用，归一化为「当前有效的签名 URL」。

    识别不出文件名（例如外部图床链接）时原值返回，保证不破坏既有数据。
    """
    name = extract_image_name(value)
    if not name:
        return value
    return sign_path(f"{FEEDBACK_IMAGE_PREFIX}{name}", ttl=ttl, now=now)
