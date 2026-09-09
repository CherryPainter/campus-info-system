#!/usr/bin/env python3
"""
匿名会话令牌（仅用于公开浏览接口的可溯源 + 按会话限流）

背景：
- 天气 / 公告等公开接口对未登录用户零凭证开放，无法像已登录请求那样按 user_id 溯源。
- 微信小程序的 wx.request **不维护 cookie**（服务端 Set-Cookie 不会被自动存/回传），
  因此"服务端下发 session cookie"在小程序端行不通。
- 本模块改为：服务端签发一个**带时间戳、签名**的匿名令牌（uuid + 过期时间 + HMAC 签名），
  通过响应头 X-Anon-Token 下发给客户端；客户端（小程序）首次拿到后存本地，
  后续请求通过请求头 X-Anon-Token 回传。服务端据此做：
    1) 限流身份：匿名请求按会话令牌计，而不是笼统按 IP（避免同一出口 NAT 下互相挤占）；
    2) 溯源：访问日志里记录 anon_id，能区分"是哪个匿名会话在调用"。

令牌格式：`<uuid>.<exp_ts>.<sig>`，其中 sig = HMAC-SHA256(SECRET_KEY, "<uuid>.<exp_ts>")[:16]。
- 无有效令牌时退化为按 IP（与现状一致，不破坏任何既有行为）。
- 令牌可被客户端伪造/清空（匿名场景本就无强身份），目的只是"溯源 + 限制滥用的噪声"，
  不是强认证。
"""

import hashlib
import hmac
import time
import uuid

from flask import current_app, request

# 匿名会话令牌有效期（秒）：24 小时。过期后客户端拿不到有效令牌，退化为新会话/按 IP。
ANON_TOKEN_TTL = 86400

# 请求 / 响应头名（小程序端在 request header 带 X-Anon-Token，服务端在 response header 回写）
ANON_TOKEN_HEADER = "X-Anon-Token"

# 公开接口路径前缀（仅这些路径签发/回显匿名令牌并记录访问日志）
PUBLIC_PATH_PREFIXES = (
    "/api/miniapp/weather",
    "/api/miniapp/announcements",
)


def _sign(payload: str) -> str:
    """对 payload 做 HMAC-SHA256 签名（截断 16 位，足够区分+防篡改）"""
    secret = (current_app.config.get("SECRET_KEY") or "").encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def issue_anon_token() -> str:
    """签发一个新匿名令牌（uuid + 当前过期时间戳 + 签名）"""
    uid = uuid.uuid4().hex
    exp = int(time.time()) + ANON_TOKEN_TTL
    payload = f"{uid}.{exp}"
    return f"{payload}.{_sign(payload)}"


def parse_anon_token(token: str | None):
    """
    解析并校验匿名令牌，返回 uuid 字符串；无效/过期/伪造返回 None。

    校验顺序：结构拆解 → 签名比对（constant-time）→ 过期检查。
    """
    if not token or not isinstance(token, str):
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        uid, exp = payload.split(".")
        exp = int(exp)
        if time.time() > exp:
            return None
        return uid
    except Exception:
        # 结构异常（缺段、非数字时间戳等）→ 视为无有效令牌
        return None


def is_public_path(path: str) -> bool:
    """判断请求路径是否属于公开浏览接口（用于决定是否签发/记录）"""
    return any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES)


def attach_anon_session(app):
    """注册 after_request：对公开浏览接口签发 X-Anon-Token 并记录访问日志。

    抽成独立函数，供 create_app 与测试夹具共用，避免逻辑分散 / 测试脚手架漏接。
    """

    @app.after_request
    def anon_session_and_log(response):
        from app.core.logger import get_logger

        log = get_logger(__name__)
        if not is_public_path(request.path):
            return response
        try:
            provided = request.headers.get(ANON_TOKEN_HEADER)
            uid = parse_anon_token(provided)
            if uid:
                # 有效令牌：回写原值，避免每次旋转导致会话 ID 漂移
                response.headers[ANON_TOKEN_HEADER] = provided
                anon_uid = uid
            else:
                token = issue_anon_token()
                response.headers[ANON_TOKEN_HEADER] = token
                anon_uid = parse_anon_token(token)
            # 访问日志（INFO 级，满足"溯源谁在调"；天气轮询较多，必要时可调为 DEBUG）
            log.info(
                "anon_access path=%s method=%s status=%s anon_id=%s ip=%s",
                request.path,
                request.method,
                response.status_code,
                anon_uid,
                request.remote_addr,
            )
        except Exception as e:  # 签发/日志异常绝不影响业务响应
            log.debug(f"anon_session_and_log 异常（已忽略）: {e}")
        return response
