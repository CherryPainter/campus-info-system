#!/usr/bin/env python3
"""
Session 管理 API 路由蓝图
提供Session管理接口（查看活跃Session、撤销Session等）

所有端点都需要 @jwt_required 认证

端点列表：
- GET    /api/auth/sessions                    — 获取当前用户的所有活跃Session
- DELETE /api/auth/sessions/<session_id>       — 撤销指定的Session（登出特定设备）
- DELETE /api/auth/sessions                    — 撤销所有Session（登出所有设备）
- GET    /api/auth/csrf-token                  — 获取CSRF Token（用于前端表单提交）
"""

from flask import Blueprint, g, request

from app.core.api_response import api_error, api_success
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.server_session import ServerSession
from app.model.user import User
from app.utils.auth_middleware import jwt_required
from app.utils.security import get_client_ip

logger = get_logger(__name__)

# 创建蓝图
session_bp = Blueprint("session", __name__)


@session_bp.route("/sessions", methods=["GET"])
@jwt_required
def get_sessions():
    """
    获取当前用户的所有活跃Session

    成功响应 (200):
        {
            "status": "success",
            "data": {
                "sessions": [
                    {
                        "session_id": "xxx",
                        "ip_address": "127.0.0.1",
                        "user_agent": "Mozilla/5.0...",
                        "created_at": "2026-01-01T00:00:00",
                        "updated_at": "2026-01-01T01:00:00",
                        "expires_at": "2026-01-02T00:00:00"
                    }
                ]
            }
        }
    """
    from app.services.session_service import session_service

    user_id = g.current_user.get("user_id")
    role = g.current_user.get("role")

    # 普通用户只能看自己的会话；管理员（普管/超管）看全部（含所属用户信息）
    if role == "user":
        sessions = session_service.get_user_sessions(int(user_id))
    else:
        sessions = session_service.get_all_active_sessions_with_owner()

    return api_success(data={"sessions": sessions}, http_status=200)


@session_bp.route("/sessions/<session_id>", methods=["DELETE"])
@jwt_required
def revoke_session(session_id):
    """
    撤销指定的Session（登出特定设备）

    成功响应 (200):
        {
            "status": "success",
            "message": "Session已撤销"
        }
    """
    from app.services.session_service import session_service

    operator_id = g.current_user.get("user_id")
    operator_role = g.current_user.get("role")

    db_session = get_db()
    try:
        target_session = (
            db_session.query(ServerSession).filter(ServerSession.session_id == session_id).first()
        )

        if not target_session:
            return api_error(message="Session不存在", http_status=404)

        # 1. 不能踢出当前登录会话（自己不能踢自己）
        current_sid = request.cookies.get("session_id")
        if target_session.session_id == current_sid:
            return api_error(message="不能踢出当前登录会话", http_status=403)

        # 目标所属用户
        target_user = db_session.query(User).filter(User.id == target_session.user_id).first()
        if not target_user:
            return api_error(message="会话所属用户不存在", http_status=404)

        # 2. 权限分层（与用户管理一致：普管管普通用户，超管管全部）
        if operator_role == "user":
            # 普通用户只能踢自己的会话
            if target_session.user_id != int(operator_id):
                return api_error(message="无权撤销此Session", http_status=403)
        else:
            # 管理员需区分超管 / 普管
            operator = db_session.query(User).filter(User.id == int(operator_id)).first()
            is_primary = bool(operator.is_primary) if operator else False
            if not is_primary:
                # 普管：只能踢普通用户（role != 'admin'）的会话，不能踢任何管理员
                if target_user.role == "admin":
                    return api_error(message="无权踢出管理员会话", http_status=403)

        # 撤销Session（记录撤销原因与操作者IP，供被踢设备弹框显示）
        success = session_service.delete_session(
            session_id, reason="admin_revoke", by_ip=get_client_ip()
        )

        if success:
            return api_success(message="Session已撤销", http_status=200)
        else:
            return api_error(message="撤销Session失败", http_status=500)
    finally:
        db_session.close()


@session_bp.route("/sessions", methods=["DELETE"])
@jwt_required
def revoke_all_sessions():
    """
    撤销所有Session（登出所有设备）

    成功响应 (200):
        {
            "status": "success",
            "message": "已撤销所有Session",
            "data": {
                "count": 3
            }
        }
    """
    from app.services.session_service import session_service

    user_id = g.current_user.get("user_id")
    # 保留当前设备的 Session（从 cookie 取），避免"登出所有设备"把自己也踢下线
    current_sid = request.cookies.get("session_id")

    # 撤销所有Session（保留当前），记录原因与操作者IP，供被踢设备弹框显示
    count = session_service.delete_all_user_sessions(
        int(user_id), except_session_id=current_sid, reason="logout", by_ip=get_client_ip()
    )

    return api_success(
        message=f"已撤销 {count} 个其他设备Session", data={"count": count}, http_status=200
    )


@session_bp.route("/csrf-token", methods=["GET"])
def get_csrf_token():
    """
    获取CSRF Token（用于前端表单提交）

    成功响应 (200):
        {
            "status": "success",
            "data": {
                "csrf_token": "xxx"
            }
        }
    """
    from app.utils.csrf_protect import get_csrf_token as _get_token

    return api_success(data={"csrf_token": _get_token()}, http_status=200)
