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

import jwt
from flask import g, jsonify, request

from app.core.logger import get_logger
from app.utils.auth_middleware import jwt_required, _extract_token, _get_jwt_manager

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

        # 用户存在性校验：token 签名有效 ≠ 用户仍存在。
        # 清库/删除/禁用后旧 token 若不在此拦截，会一路放行到落库才以外键错误 500
        # （2026-09-06 实例：bind 命中 student_profiles.user_id 外键失败报 500）。
        # 返回 401 让小程序端走「refresh 失败 → 清 token → 静默重新登录」闭环。
        user_id = user.get("user_id")
        if user_id is not None:
            from app.core.database import get_db
            from app.model.user import User

            db = get_db()
            try:
                # 注意按模型类查询（db.query(User) 而非 User.id），
                # 便于测试桩按模型路由，SQL 语义等价
                alive = (
                    db.query(User).filter_by(id=int(user_id), is_active=True).first()
                    is not None
                )
            finally:
                db.close()
            if not alive:
                logger.warning(
                    f"用户不存在或已禁用，拒绝访问: user_id={user_id}, path={request.path}"
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "账号状态已变更，请重新登录",
                            "code": "USER_GONE",
                        }
                    ),
                    401,
                )

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


def miniapp_optional(f):
    """
    可选鉴权装饰器（小程序"先体验后授权"公开浏览类接口用）

    行为：
    - 携带**合法** access token 时，将用户信息写入 g.current_user（结构同 jwt_required）。
    - 缺少 token / token 无效 / 过期 / 类型不符 时，g.current_user 置为 None，
      但**始终放行**请求（游客态），由路由内部按 user_id 是否为 None 决定返回内容
      （例如公告列表/详情/未读数的已读标记、红点统计对游客返回匿名结果）。

    与 student_required / student_bound_required 的区别：
    后两者遇无 token 或校验失败会返回 401/403 拦截；本装饰器永不拦截，
    仅用于天气、公告等合规要求下"游客可匿名浏览"的接口。
    """

    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 默认游客态：None；路由内用 g.current_user 是否为 None 判断身份
        g.current_user = None

        token = _extract_token()
        if not token:
            return f(*args, **kwargs)

        try:
            jwt_manager = _get_jwt_manager()
            payload = jwt_manager.verify_token(token)
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError, RuntimeError):
            # token 有任何问题都降级为游客，不返回 401（公开浏览接口不拦截）
            return f(*args, **kwargs)

        if payload.get("type") != "access":
            return f(*args, **kwargs)

        g.current_user = {
            "user_id": payload.get("user_id"),
            "username": payload.get("username"),
            "role": payload.get("role"),
            "jti": payload.get("jti"),
            "type": payload.get("type"),
            "login_log_id": payload.get("login_log_id"),
        }
        return f(*args, **kwargs)

    return decorated_function
