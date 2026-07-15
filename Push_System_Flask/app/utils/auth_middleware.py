#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JWT 认证中间件
提供 JWT 认证装饰器，用于保护需要认证的 API 端点

设计说明：
- jwt_required: 基础认证装饰器，验证 Bearer Token 并将用户信息存入 g.current_user
- admin_required: 管理员认证装饰器，在 jwt_required 基础上额外检查 role == 'admin'
- 认证失败统一返回 401 状态码和标准错误格式
"""

import functools
import jwt
from flask import request, jsonify, g, current_app
from app.core.logger import get_logger
from app.core.api_response import api_error

# 使用统一日志系统
logger = get_logger(__name__)


def _get_jwt_manager():
    """
    获取 JWT 管理器实例

    从 Flask app 的 extensions 字典中获取 jwt_manager，
    延迟获取以避免循环导入问题。

    Returns:
        JWTManager: JWT 管理器实例

    Raises:
        RuntimeError: JWT 管理器未初始化
    """
    jwt_manager = current_app.extensions.get('jwt_manager')
    if jwt_manager is None:
        logger.error('JWT 管理器未初始化，请在 create_app 中正确注册')
        raise RuntimeError('JWT manager not initialized')
    return jwt_manager


def _extract_token():
    """
    从请求头或 cookie 中提取 Token

    优先级：
    1. Authorization: Bearer <token> (请求头)
    2. access_token cookie

    Returns:
        str or None: 提取到的 token 字符串，失败返回 None
    """
    # 1. 先检查请求头
    auth_header = request.headers.get('Authorization')
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            return parts[1]

    # 2. 检查 cookie (httpOnly)
    return request.cookies.get('access_token')


def jwt_required(f):
    """
    JWT 认证装饰器

    验证请求头中的 Bearer Token：
    1. 提取 Authorization: Bearer <token>
    2. 使用 JWTManager 验证 token 有效性
    3. 检查 token 类型是否为 access
    4. 将用户信息存入 g.current_user

    认证成功后，路由函数可通过 g.current_user 访问用户信息：
        g.current_user = {
            'user_id': 'admin',
            'username': 'admin',
            'role': 'admin',
            'jti': '...',
            'type': 'access'
        }

    认证失败返回：
        401: token 缺失、无效、过期或已被撤销

    使用示例：
        @auth_bp.route('/me')
        @jwt_required
        def get_current_user():
            user = g.current_user
            return jsonify({'username': user['username']})
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. 提取 token
        token = _extract_token()
        if not token:
            logger.warning('JWT 认证失败: 请求头中缺少 Bearer Token')
            return jsonify({
                'status': 'error',
                'message': '缺少认证令牌，请在 Authorization 请求头中提供 Bearer Token'
            }), 401

        # 2. 获取 JWT 管理器并验证 token
        try:
            jwt_manager = _get_jwt_manager()
            payload = jwt_manager.verify_token(token)
        except jwt.ExpiredSignatureError:
            logger.debug('JWT 认证: token 已过期')
            return jsonify({
                'status': 'error',
                'message': '认证令牌已过期，请刷新 token'
            }), 401
        except (jwt.InvalidTokenError, ValueError) as e:
            logger.debug(f'JWT 认证: token 无效 - {e}')
            return jsonify({
                'status': 'error',
                'message': '认证令牌无效'
            }), 401
        except RuntimeError:
            return jsonify({
                'status': 'error',
                'message': '服务器配置错误'
            }), 500

        # 3. 检查 token 类型（只允许 access token 用于 API 认证）
        if payload.get('type') != 'access':
            logger.warning(
                f'JWT 认证失败: token 类型错误 (type={payload.get("type")})'
            )
            return jsonify({
                'status': 'error',
                'message': '令牌类型错误，请使用 access token'
            }), 401

        # 4. 将用户信息存入 Flask 的 g 对象，供路由函数使用
        g.current_user = {
            'user_id': payload.get('user_id'),
            'username': payload.get('username'),
            'role': payload.get('role'),
            'jti': payload.get('jti'),
            'type': payload.get('type'),
            'login_log_id': payload.get('login_log_id'),
        }

        # 5. 服务端 Session 软校验（可撤销层）
        # 若请求携带 session_id cookie 则校验其有效性；
        # Bearer token 调用（无 cookie）跳过，保持向后兼容。
        # 失效时返回结构化撤销原因（revoke_reason / revoke_ip），供前端弹框精确提示。
        sid = request.cookies.get('session_id')
        if sid:
            try:
                from app.services.session_service import session_service
                detail = session_service.get_session_detail(sid)
                if detail['status'] != 'active':
                    reason = detail.get('reason')
                    ip = detail.get('ip')
                    if reason == 'new_login':
                        msg = (f'登录会话已在其他设备（IP：{ip}）登录，当前会话已失效，请重新登录'
                               if ip else '登录会话已在其他设备登录，当前会话已失效，请重新登录')
                    elif reason == 'expired':
                        msg = '登录会话已过期，请重新登录'
                    elif reason == 'admin_revoke':
                        msg = '会话已被管理员强制下线，请重新登录'
                    else:
                        msg = '登录会话已失效，请重新登录'
                    logger.warning(f'JWT 认证: 关联 Session 已失效 (session_id={sid}, reason={reason})')
                    return api_error(message=msg, http_status=401, revoke_reason=reason, revoke_ip=ip)
            except Exception as e:
                # DB 异常时不阻断，避免基础设施抖动导致全站 401
                logger.error(f'Session 校验异常（已跳过）: {e}')

        # 6. 执行被装饰的路由函数
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """
    管理员权限认证装饰器

    在 jwt_required 的基础上，额外检查用户角色是否为 'admin'。
    非管理员用户访问时返回 403 Forbidden。

    使用示例：
        @admin_bp.route('/dashboard')
        @admin_required
        def dashboard():
            return jsonify({'data': 'sensitive info'})
    """
    @functools.wraps(f)
    @jwt_required
    def decorated_function(*args, **kwargs):
        # 从 g.current_user 中获取角色信息
        user = g.get('current_user', {})
        role = user.get('role', '')

        if role != 'admin':
            logger.warning(
                f'管理员权限验证失败: user={user.get("username")}, role={role}'
            )
            return jsonify({
                'status': 'error',
                'message': '权限不足，需要管理员权限'
            }), 403

        return f(*args, **kwargs)

    return decorated_function
