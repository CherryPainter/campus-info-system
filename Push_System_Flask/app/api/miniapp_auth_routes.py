#!/usr/bin/env python3
"""
微信小程序认证路由（/api/miniapp/auth/*）

与管理端认证路由（/api/auth/*）完全隔离：
- 管理端：用户名 + 密码 + MFA，Token 走 httpOnly cookie
- 小程序：微信 code 登录，双 Token 由小程序端自行保存（Bearer 方式）

两者最终共用 JWTManager 签发/校验，不重建认证体系。
"""

import jwt as _jwt
from flask import Blueprint, current_app, g, request

from app.core.api_response import api_error, api_success
from app.core.extensions import RATE_LIMITS, limiter
from app.core.logger import get_logger
from app.services.wechat_auth_service import WechatAuthError, wechat_auth_service
from app.utils.auth_middleware import jwt_required
from app.utils.student_auth import student_required
from app.utils.security import get_client_ip

# 使用统一日志系统
logger = get_logger(__name__)

# 小程序认证蓝图，挂载前缀 /api/miniapp/auth
miniapp_auth_bp = Blueprint("miniapp_auth", __name__)


def _get_jwt_manager():
    """获取 JWT 管理器实例（延迟从 app.extensions 获取，避免循环导入）"""
    jwt_manager = current_app.extensions.get("jwt_manager")
    if jwt_manager is None:
        logger.error("JWT 管理器未初始化，请在 create_app 中正确注册")
        raise RuntimeError("JWT manager not initialized")
    return jwt_manager


@miniapp_auth_bp.route("/login", methods=["POST"])
@limiter.limit(RATE_LIMITS["strict"])
def miniapp_login():
    """
    微信小程序登录接口

    请求：
        POST /api/miniapp/auth/login
        {"code": "wx.login() 获取的临时登录凭证"}

    成功响应 (200)：
        {
            "status": "success",
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600,
            "user": {"id": 1, "username": "wx_...", "role": "student"},
            "is_new_user": false
        }

    说明：
    - openid 由后端调用微信 code2Session 获得，客户端直接提交 openid 一律拒绝
    - 双 Token 直接返回在响应体中，由小程序端自行保存（uni.setStorageSync），不写 httpOnly cookie
    """
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return api_error(message="缺少登录凭证 code", http_status=400)

    try:
        result = wechat_auth_service.login(
            code=code,
            client_ip=get_client_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
    except WechatAuthError as e:
        return api_error(message=e.message, http_status=e.http_status)

    tokens = result["tokens"]
    logger.info(f"小程序登录成功: user_id={result['user'].get('id')}")
    return api_success(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        user=result["user"],
        is_new_user=result["is_new_user"],
    )


@miniapp_auth_bp.route("/refresh", methods=["POST"])
@limiter.limit(RATE_LIMITS["moderate"])
def miniapp_refresh():
    """
    刷新 access_token 接口

    请求：
        POST /api/miniapp/auth/refresh
        {"refresh_token": "..."}

    成功响应 (200)：
        {
            "status": "success",
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600
        }
    """
    data = request.get_json(silent=True) or {}
    refresh_token = (data.get("refresh_token") or "").strip()
    if not refresh_token:
        return api_error(message="请提供 refresh_token", http_status=401)

    try:
        jwt_manager = _get_jwt_manager()
    except RuntimeError:
        return api_error(message="服务器配置错误", http_status=500)

    try:
        new_tokens = jwt_manager.refresh_access_token(refresh_token)
    except _jwt.ExpiredSignatureError:
        logger.warning("小程序 Token 刷新失败: refresh_token 已过期")
        return api_error(message="刷新令牌已过期，请重新登录", http_status=401)
    except (_jwt.InvalidTokenError, ValueError) as e:
        msg = str(e)
        if "idle timeout" in msg:
            message = "登录会话已闲置过久，请重新登录"
        elif "absolute expiry" in msg:
            message = "登录会话已过期，请重新登录"
        else:
            message = "刷新令牌无效"
        logger.warning(f"小程序 Token 刷新失败: {e}")
        return api_error(message=message, http_status=401)

    logger.info("小程序 access_token 刷新成功")
    return api_success(
        access_token=new_tokens["access_token"],
        refresh_token=new_tokens["refresh_token"],
        expires_in=new_tokens["expires_in"],
    )


@miniapp_auth_bp.route("/logout", methods=["POST"])
@jwt_required
def miniapp_logout():
    """
    登出接口（撤销当前会话的 access_token，可选一并撤销 refresh_token）

    请求：
        POST /api/miniapp/auth/logout
        Authorization: Bearer <access_token>
        {"refresh_token": "..."}  # 可选

    成功响应 (200)：
        {"status": "success", "message": "已成功登出"}
    """
    try:
        jwt_manager = _get_jwt_manager()
    except RuntimeError:
        return api_error(message="服务器配置错误", http_status=500)

    # 从 Authorization 头提取并撤销 access_token（小程序不使用 cookie）
    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        jwt_manager.revoke_token(parts[1].strip())

    # 可选：一并撤销 refresh_token（由小程序端从本地存储传入）
    data = request.get_json(silent=True) or {}
    refresh_token = (data.get("refresh_token") or "").strip()
    if refresh_token:
        jwt_manager.revoke_token(refresh_token, reason="logout_refresh")

    username = g.current_user.get("username", "unknown")
    logger.info(f"小程序登出: user={username}")
    return api_success(message="已成功登出")


@miniapp_auth_bp.route("/user/me", methods=["DELETE"])
@student_required
def delete_account():
    """
    注销当前学生账号（自主注销，不可恢复）

    行为：
    - 软删：users.is_active = False（保留历史数据，微信登录时检测 is_active=False 拒绝）
    - 撤销当前 access_token（黑名单） + 撤销可选 refresh_token
    - 写日志（username + IP + user_id 留痕）

    注意：注销后该微信号无法再次登录小程序（同 openid 命中 is_active=False 用户会被拒）。
    如需恢复请联系管理员在管理端重新启用（users.is_active = True）。
    """
    from app.core.database import get_db
    from app.model.user import User

    try:
        jwt_manager = _get_jwt_manager()
    except RuntimeError:
        return api_error(message="服务器配置错误", http_status=500)

    user_id = int(g.current_user["user_id"])
    username = g.current_user.get("username", "unknown")

    # 1) 撤销当前 access_token（让本次会话立即失效）
    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        jwt_manager.revoke_token(parts[1].strip(), reason="account_delete")

    # 2) 撤销可选 refresh_token（从 query 传入，避免 DELETE body 不规范）
    refresh_token = (request.args.get("refresh_token") or "").strip()
    if refresh_token:
        jwt_manager.revoke_token(refresh_token, reason="account_delete_refresh")

    # 3) 软删：禁用账号（保留数据，wechat_auth_service 检测 is_active=False 拒绝再次登录）
    client_ip = get_client_ip()
    db = get_db()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)
        user.is_active = False
        db.commit()
        logger.warning(
            f"小程序账号注销: user_id={user_id}, username={username}, ip={client_ip}"
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"小程序账号注销失败: user_id={user_id}: {exc}")
        return api_error(message="注销失败，请稍后重试", http_status=500)
    finally:
        db.close()

    return api_success(message="账号已注销")
