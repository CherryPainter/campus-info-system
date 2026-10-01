#!/usr/bin/env python3
"""
CSRF防护模块

为Session认证提供CSRF Token验证
JWT认证不需要CSRF防护（因为JWT不依赖Cookie）

使用方式：
1. 在登录时生成CSRF Token，存储在Session中
2. 在每个状态更改请求（POST/PUT/DELETE/PATCH）中验证CSRF Token
3. CSRF Token可以通过请求头 X-CSRF-Token 或表单字段 _csrf_token 传递

豁免口径（2026-10-01 收窄，见 `is_csrf_exempt_request`）：
原先 `CSRF_EXEMPT_PREFIXES = ["/api/"]` 把**整个** `/api/` 前缀无条件豁免，理由写的是
「所有 API 接口使用 JWT 认证」——这个前提并不成立：`auth_middleware._extract_token`
与 `extensions.get_identity_key` 都是「Authorization 头 → 再退 access_token cookie」，
登录/刷新还会 `set_cookie` 种下 httpOnly 的 access_token / refresh_token / session_id。
也就是说 **同一个 `/api/` 端点既能被 Bearer 调用、也能被 Cookie 调用**，而 Cookie 是
浏览器自动附加的——正是 CSRF 成立的前提。故豁免改为按「凭证形态」判定：
带 `Authorization: Bearer`（显式携带，浏览器不会自动附加）或完全不带认证 cookie
（纯匿名，无环境凭证可被冒用）才豁免；带认证 cookie 的写请求走同源校验。
"""

import functools
import secrets
from urllib.parse import urlsplit

from flask import current_app, jsonify, request
from flask import session as flask_session

from app.core.logger import get_logger

logger = get_logger(__name__)

# CSRF Token配置
CSRF_TOKEN_LENGTH = 32
CSRF_TOKEN_SESSION_KEY = "_csrf_token"
CSRF_TOKEN_HEADER = "X-CSRF-Token"
CSRF_TOKEN_FIELD = "_csrf_token"

# API 路径前缀（其豁免口径见 is_csrf_exempt_request）
CSRF_API_PREFIX = "/api/"

# 会被浏览器自动附加的认证 cookie 名（cookie 认证 = CSRF 前提存在）
AUTH_COOKIE_NAMES = ("access_token", "refresh_token", "session_id")

# 认证流程端点（建立/刷新/终止会话）：这些端点本身就是「拿凭证」的过程，调用时浏览器
# 可能还残留上一段会话的 cookie（例如已登录状态下重新登录 / 切换账号），若按 cookie 口径
# 要求同源反而会拦住正常换号操作，故按精确路径整体豁免。
# 登录 CSRF（把受害者登录成攻击者的账号）风险等级低于数据篡改，且本系统所有会话 cookie
# 均为 SameSite=Lax，跨站 POST 不携带，故此处保持豁免。
CSRF_EXEMPT_PATHS = [
    "/api/auth/login",
    "/api/auth/login/mfa",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/miniapp/auth/login",
    "/api/miniapp/auth/refresh",
    "/api/miniapp/auth/logout",
    "/api/health",  # 健康检查
    "/health",  # 健康检查
]

# 不需要CSRF防护的请求方法（只读请求不需要CSRF）
CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def generate_csrf_token() -> str:
    """
    生成新的CSRF Token

    Returns:
        随机Token字符串
    """
    token = secrets.token_hex(CSRF_TOKEN_LENGTH)
    return token


def get_csrf_token() -> str:
    """
    获取当前Session的CSRF Token（如果不存在则生成新的）

    Returns:
        CSRF Token字符串
    """
    # 对于Flask的Session（客户端Session），直接存在flask_session中
    if CSRF_TOKEN_SESSION_KEY not in flask_session:
        flask_session[CSRF_TOKEN_SESSION_KEY] = generate_csrf_token()
    return flask_session[CSRF_TOKEN_SESSION_KEY]


def validate_csrf_token() -> bool:
    """
    验证请求中的CSRF Token

    Returns:
        True表示验证通过，False表示验证失败
    """
    # 对于Flask的Session（客户端Session），从flask_session中获取
    stored_token = flask_session.get(CSRF_TOKEN_SESSION_KEY)
    if not stored_token:
        logger.warning("[CSRF] Session中不存在CSRF Token")
        return False

    # 从请求头或表单中获取Token
    request_token = request.headers.get(CSRF_TOKEN_HEADER)
    if not request_token:
        request_token = request.form.get(CSRF_TOKEN_FIELD)
    if not request_token:
        request_token = request.json.get(CSRF_TOKEN_FIELD) if request.json else None

    if not request_token:
        logger.warning("[CSRF] 请求中不存在CSRF Token")
        return False

    if request_token != stored_token:
        logger.warning("[CSRF] CSRF Token不匹配")
        return False

    return True


def _has_explicit_bearer() -> bool:
    """请求是否显式携带 `Authorization: Bearer <token>`。

    这里的「显式」是安全前提：该头由前端 JS / 脚本主动写入（本项目两个前端都从
    localStorage 取 token 后自行附加），浏览器**不会**在跨站请求里自动补上，
    因此带该头的请求天然免疫 CSRF。
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return False
    parts = auth_header.split()
    return len(parts) == 2 and parts[0].lower() == "bearer"


def _has_auth_cookie() -> bool:
    """请求是否携带任一认证 cookie（浏览器会自动附加 → CSRF 成立前提）。"""
    return any(request.cookies.get(name) for name in AUTH_COOKIE_NAMES)


def _allowed_origins() -> set:
    """允许的「同源」集合：本站自身 origin + 配置的额外前端 origin。

    本站 origin 用 `request.host_url` 推导——生产由 Nginx 同源反代（前端 SPA 与
    API 同域），此时它与浏览器发出的 Origin 一致；开发环境若前端独立端口，可用
    环境变量 `CSRF_ALLOWED_ORIGINS` 逗号分隔补充（如 http://localhost:5173）。
    """
    origins = set()
    try:
        origins.add(request.host_url.rstrip("/"))
    except Exception:  # noqa: BLE001 - 取不到 host 时不因此放行额外来源
        pass

    configured = current_app.config.get("CSRF_ALLOWED_ORIGINS") or ""
    if isinstance(configured, str):
        configured = configured.split(",")
    for item in configured:
        item = (item or "").strip().rstrip("/")
        if item:
            origins.add(item)
    return origins


def _origin_of(url: str) -> str:
    """从 Origin / Referer 值中提取 `scheme://host[:port]`（Origin 本身即该形态）。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def check_same_site_origin():
    """对「带认证 cookie 的 /api/ 写请求」做同源校验。

    返回 (是否放行, 被拒来源)；被拒来源仅用于日志，不含凭证信息。

    判定规则：
    - 有 Origin：必须精确命中允许集合，否则拒绝（含 `Origin: null`，不在集合内 → 拒）；
    - 无 Origin 但有 Referer：取 Referer 的 scheme://host 比对，同样必须命中；
    - 两者皆无：放行。理由——浏览器发起的跨站写请求**必定**带 Origin（表单/ fetch
      都一样），因此「两个头都没有」意味着调用方不是浏览器（小程序、脚本、服务端调用），
      这类请求不可能被第三方页面触发，不构成 CSRF 载体。
    """
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    allowed = _allowed_origins()

    if origin:
        return (origin.rstrip("/") in allowed), origin

    if referer:
        return (_origin_of(referer) in allowed), referer

    return True, ""


def is_csrf_exempt_request() -> bool:
    """当前请求是否豁免 CSRF 校验（before_request 与 @csrf_protect 共用同一口径）。

    顺序（任一命中即豁免）：
    1. 精确豁免路径（认证流程 / 健康检查）；
    2. 安全方法（GET / HEAD / OPTIONS）；
    3. 视图函数带 `@csrf_exempt`（`f._csrf_exempt = True`）标记；
    4. `/api/` 且显式带 `Authorization: Bearer` —— 凭证由调用方主动携带，免疫 CSRF；
    5. `/api/` 且**不带任何认证 cookie** —— 纯匿名请求没有可被冒用的环境凭证。

    带认证 cookie 又无 Bearer 的 `/api/` 写请求**不豁免**，由调用方改走同源校验
    （见 check_same_site_origin）——这正是跨站/同站伪造会命中的形态。
    """
    if request.path in CSRF_EXEMPT_PATHS:
        return True

    if request.method.upper() in CSRF_SAFE_METHODS:
        return True

    endpoint = getattr(request, "endpoint", None)
    if endpoint:
        view_func = current_app.view_functions.get(endpoint)
        if view_func is not None and getattr(view_func, "_csrf_exempt", False):
            return True

    if request.path.startswith(CSRF_API_PREFIX):
        if _has_explicit_bearer():
            return True
        if not _has_auth_cookie():
            return True

    return False


def csrf_protect(f):
    """
    CSRF防护装饰器

    用于需要CSRF防护的Web端点（使用Session认证的端点）
    API端点（使用JWT认证）不需要此装饰器

    使用方法：
    @app.route('/web/profile', methods=['POST'])
    @csrf_protect
    def update_profile():
        ...
    """

    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if is_csrf_exempt_request():
            return f(*args, **kwargs)

        # 带认证 cookie 的 API 写请求：走同源校验（无 Token 可分发，按来源判定）
        if request.path.startswith(CSRF_API_PREFIX):
            allowed, source = check_same_site_origin()
            if not allowed:
                logger.warning(f"[CSRF] 非同源写请求被拒: {request.path} source={source}")
                return jsonify({"status": "error", "message": "CSRF validation failed"}), 403
            return f(*args, **kwargs)

        # 验证CSRF Token
        if not validate_csrf_token():
            logger.warning(f"[CSRF] CSRF验证失败: {request.path}")
            return jsonify({"status": "error", "message": "CSRF validation failed"}), 403

        return f(*args, **kwargs)

    return decorated_function


def csrf_exempt(f):
    """
    豁免CSRF防护装饰器

    用于API端点（使用JWT认证）或特殊情况

    使用方法：
    @app.route('/api/some-endpoint', methods=['POST'])
    @csrf_exempt
    def some_api():
        ...
    """
    f._csrf_exempt = True
    return f


class CSRFProtect:
    """
    CSRF防护类（可以像Flask-WTF一样使用）

    使用方法：
    csrf = CSRFProtect()
    csrf.init_app(app)
    """

    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """初始化CSRF防护"""
        self.app = app

        # 注册before_request处理器
        app.before_request(self._before_request)

        # 注册上下文处理器（为模板提供CSRF Token）
        app.context_processor(self._context_processor)

        logger.info("[CSRF] CSRF防护已初始化")

    def _before_request(self):
        """在每个请求前检查CSRF Token"""
        if is_csrf_exempt_request():
            return

        # 带认证 cookie 的 /api/ 写请求：无 Token 可分发，按来源是否同源判定
        # （浏览器发起的跨站写请求必带 Origin，伪造方来源必然不是本站 → 拦下）
        if request.path.startswith(CSRF_API_PREFIX):
            allowed, source = check_same_site_origin()
            if not allowed:
                logger.warning(f"[CSRF] 非同源 API 写请求被拒: {request.path} source={source}")
                return jsonify({"status": "error", "message": "CSRF validation failed"}), 403
            return

        # 验证CSRF Token
        if not validate_csrf_token():
            logger.warning(f"[CSRF] CSRF验证失败: {request.path}")
            return jsonify({"status": "error", "message": "CSRF validation failed"}), 403

    def _context_processor(self):
        """为模板提供CSRF Token"""
        return {
            "csrf_token": get_csrf_token,
        }

    def exempt(self, view_func):
        """豁免某个视图函数的CSRF防护"""
        if isinstance(view_func, list | tuple):
            for f in view_func:
                f._csrf_exempt = True
            return view_func
        view_func._csrf_exempt = True
        return view_func
