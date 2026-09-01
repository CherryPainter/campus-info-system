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

from flask import g, jsonify, request

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


def student_bound_required(f):
    """
    学生权限 + 身份绑定校验装饰器

    在 student_required 基础上，额外检查该学生是否已完成身份绑定
    （student_profiles.student_number 非空，即通过预录名单绑定成功）。

    未绑定返回 403 + code=STUDENT_NOT_BOUND，小程序端据此跳转身份绑定页。
    用于除「登录 / 绑定 / 绑定状态 / 学校列表」外的全部学生端业务接口，
    实现"指定学号的学生才有查看对应信息的权力"。
    """

    @functools.wraps(f)
    @student_required
    def decorated_function(*args, **kwargs):
        from app.core.database import get_db
        from app.model.student_profile import StudentProfile

        user = g.get("current_user", {})
        user_id = user.get("user_id")
        if user_id is None:
            return jsonify({"status": "error", "message": "登录状态异常"}), 401

        db = get_db()
        try:
            profile = (
                db.query(StudentProfile)
                .filter_by(user_id=int(user_id))
                .first()
            )
            if not profile or not profile.student_number:
                logger.warning(
                    f"身份未绑定拒绝访问: user_id={user_id}, path={request.path}"
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "请先完成身份认证",
                            "code": "STUDENT_NOT_BOUND",
                        }
                    ),
                    403,
                )
        finally:
            db.close()

        return f(*args, **kwargs)

    return decorated_function
