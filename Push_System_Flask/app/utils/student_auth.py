#!/usr/bin/env python3
"""
学生角色认证装饰器

在 jwt_required 基础上额外检查 role == 'student'，用于保护 /api/miniapp/* 学生端接口。

权限模型：
- admin_required（现有）：仅管理员可访问管理后台能力
- student_required（本模块）：仅学生角色可访问小程序学生端能力
两套能力互斥，student 无权访问 @admin_required 接口，admin 亦无权访问本装饰器保护的学生接口。
"""

import functools

from flask import g, jsonify

from app.core.logger import get_logger
from app.utils.auth_middleware import jwt_required

# 使用统一日志系统
logger = get_logger(__name__)


def student_required(f):
    """
    学生权限认证装饰器

    在 jwt_required 的基础上，额外检查用户角色是否为 'student'。
    非学生用户访问时返回 403 Forbidden。

    使用示例：
        @miniapp_bp.route("/user/me")
        @student_required
        def me():
            ...
    """

    @functools.wraps(f)
    @jwt_required
    def decorated_function(*args, **kwargs):
        # 从 g.current_user 中获取角色信息
        user = g.get("current_user", {})
        role = user.get("role", "")

        if role != "student":
            logger.warning(f'学生权限验证失败: user={user.get("username")}, role={role}')
            return jsonify({"status": "error", "message": "权限不足，需要学生身份"}), 403

        return f(*args, **kwargs)

    return decorated_function
