#!/usr/bin/env python3
"""
用户管理 API 路由蓝图
提供用户信息编辑、登录日志查询等功能
"""

import json
import re
from datetime import datetime, timedelta

from flask import Blueprint, g, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.utils.auth_middleware import admin_required, jwt_required
from app.utils.security import get_client_ip, validate_password_strength
from app.utils.file_upload_security import (
    AVATAR_QUOTA,
    AVATAR_QUOTA_DAYS,
    FileUploadError,
    validate_avatar_data_uri,
)

# 使用统一日志系统
logger = get_logger(__name__)

# 用户管理蓝图，挂载前缀 /api/admin/user
admin_user_bp = Blueprint("admin_user", __name__)

# 邮箱基础格式校验（宽松，仅拦明显非法）
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_and_set_avatar(user, avatar_raw):
    """
    校验头像 data URI 并更新 user 对象，同时维护“一年最多修改 3 次”的频率限制。

    - 直接修改 user.avatar 与 user.avatar_change_log，由调用方负责 commit。
    - 校验失败抛出 FileUploadError（类型/大小/伪造/超频）。

    Args:
        user: User 模型实例
        avatar_raw: 前端传来的 data URI 字符串
    """
    if not avatar_raw:
        raise FileUploadError("头像数据为空")
    validated = validate_avatar_data_uri(avatar_raw)

    # 频率限制：仅统计最近 AVATAR_QUOTA_DAYS 天内的修改
    log = []
    if user.avatar_change_log:
        try:
            log = json.loads(user.avatar_change_log)
        except Exception:
            log = []
    if not isinstance(log, list):
        log = []

    now = datetime.now()
    cutoff = now - timedelta(days=AVATAR_QUOTA_DAYS)
    recent = []
    for t in log:
        if not isinstance(t, str):
            continue
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        if dt > cutoff:
            recent.append(dt)

    if len(recent) >= AVATAR_QUOTA:
        earliest = min(recent)
        next_time = earliest + timedelta(days=AVATAR_QUOTA_DAYS)
        raise FileUploadError(
            f'头像一年仅可修改 {AVATAR_QUOTA} 次，下次可修改时间：{next_time.strftime("%Y-%m-%d %H:%M")}'
        )

    user.avatar = validated
    recent.append(now)
    user.avatar_change_log = json.dumps([dt.isoformat() for dt in recent])


@admin_user_bp.route("/profile", methods=["GET"])
@jwt_required
def get_profile():
    """
    获取当前用户完整信息

    成功响应 (200):
        {
            "status": "success",
            "data": {
                "id": 1,
                "username": "admin",
                "email": "admin@example.com",
                "avatar": "头像URL",
                "role": "admin",
                "is_primary": false,
                "last_login": "2024-01-01T00:00:00",
                "last_login_ip": "127.0.0.1",
                "created_at": "2024-01-01T00:00:00"
            }
        }
    """
    user_id = g.current_user.get("user_id")

    from app.core.database import get_db
    from app.model.user import User

    session = get_db()
    try:
        user = session.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        return api_success(data=user.to_dict())
    finally:
        session.close()


@admin_user_bp.route("/profile", methods=["PUT"])
@jwt_required
def update_profile():
    """
    更新用户个人信息

    请求格式:
        {
            "email": "邮箱",
            "avatar": "头像URL"
        }

    成功响应 (200):
        {
            "status": "success",
            "message": "信息已更新",
            "data": {...}
        }
    """
    user_id = g.current_user.get("user_id")
    data = request.get_json(silent=True) or {}

    from app.core.database import get_db
    from app.model.user import User

    session = get_db()
    try:
        user = session.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        # 更新字段（只更新提供的字段）
        if "email" in data:
            email = data["email"]
            if email and not EMAIL_RE.match(email):
                return api_error(message="邮箱格式不正确", http_status=400)
            user.email = email
        if "avatar" in data:
            try:
                _validate_and_set_avatar(user, data["avatar"])
            except FileUploadError as e:
                return api_error(message=str(e), http_status=400)

        user.updated_at = datetime.now()
        session.commit()

        logger.info(f"用户 {user.username} 更新了个人信息")

        return api_success(message="信息已更新", data=user.to_dict())
    finally:
        session.close()


@admin_user_bp.route("/login-logs", methods=["GET"])
@jwt_required
def get_login_logs():
    """
    获取当前用户的登录日志

    可选查询参数:
        page: 页码，默认为 1
        page_size: 每页数量，默认为 20
        status: 筛选状态 ('success' / 'failed')

    成功响应 (200):
        {
            "status": "success",
            "data": [...],
            "pagination": {
                "page": 1,
                "page_size": 20,
                "total": 100,
                "total_pages": 5
            }
        }
    """
    user_id = g.current_user.get("user_id")

    # 解析查询参数
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    status = request.args.get("status", None)

    # 限制每页最大数量
    page_size = min(page_size, 100)

    from sqlalchemy import desc

    from app.core.database import get_db
    from app.model.login_log import LoginLog

    session = get_db()
    try:
        # 构建查询
        query = session.query(LoginLog).filter_by(user_id=int(user_id))

        # 按状态筛选
        if status:
            query = query.filter_by(status=status)

        # 总数
        total = query.count()

        # 分页获取
        logs = (
            query.order_by(desc(LoginLog.login_time))
            .limit(page_size)
            .offset((page - 1) * page_size)
            .all()
        )

        total_pages = (total + page_size - 1) // page_size

        return api_success(
            data=[log.to_dict() for log in logs],
            pagination={
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        )
    finally:
        session.close()


@admin_user_bp.route("/username", methods=["PUT"])
@jwt_required
def update_username():
    """
    更新用户名（需要验证密码）

    请求格式:
        {
            "username": "新用户名",
            "password": "当前密码"
        }

    成功响应 (200):
        {
            "status": "success",
            "message": "用户名已更新",
            "data": {...}
        }
    """
    import bcrypt

    user_id = g.current_user.get("user_id")
    data = request.get_json(silent=True) or {}

    new_username = data.get("username", "").strip()
    password = data.get("password", "")

    if not new_username or not password:
        return api_error(message="请提供新用户名和当前密码", http_status=400)

    if len(new_username) < 3 or len(new_username) > 50:
        return api_error(message="用户名长度应在3-50个字符之间", http_status=400)

    from app.core.database import get_db
    from app.model.user import User

    session = get_db()
    try:
        user = session.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        # 验证密码
        if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
            return api_error(message="密码错误", http_status=401)

        # 检查新用户名是否已被使用
        existing_user = session.query(User).filter_by(username=new_username).first()
        if existing_user and existing_user.id != int(user_id):
            return api_error(
                message=f'用户名"{new_username}"已被使用，请更换其他用户名', http_status=400
            )

        # 更新用户名
        old_username = user.username
        user.username = new_username
        user.updated_at = datetime.now()
        session.commit()

        logger.info(f"用户 {old_username} 将用户名改为 {new_username}")

        return api_success(message="用户名已更新", data=user.to_dict())
    finally:
        session.close()


# ==============================================
# 管理员用户管理API（需要admin角色）
# ==============================================


@admin_user_bp.route("/users", methods=["GET"])
@admin_required
def get_all_users():
    """
    管理员获取所有用户列表
    """
    from sqlalchemy import case, desc

    from app.core.database import get_db
    from app.model.user import User
    from app.model.user_mfa import UserMFA

    session = get_db()
    try:
        # 获取当前登录用户信息
        current_user_id = g.current_user.get("user_id")
        current_user = session.query(User).filter_by(id=int(current_user_id)).first()
        is_primary_admin = current_user.is_primary if current_user else False

        query = session.query(User)

        # 非主管理员只能看到普通用户（不能看到其他管理员）
        if not is_primary_admin:
            query = query.filter(User.role == "user")

        users = query.order_by(
            case((User.is_primary.is_(True), 0), (User.role == "admin", 1), else_=2),
            desc(User.created_at),
        ).all()

        # 获取所有用户的MFA状态
        user_ids = [str(user.id) for user in users]
        mfa_configs = session.query(UserMFA).filter(UserMFA.user_id.in_(user_ids)).all()
        mfa_status = {mfa.user_id: mfa.enabled for mfa in mfa_configs}

        # 添加MFA状态到用户数据
        result = []
        for user in users:
            user_data = user.to_dict()
            user_data["mfa_enabled"] = mfa_status.get(str(user.id), False)
            # 登录来源分流：student=微信端小程序（openid 登录，无密码/MFA），其余=网页端
            user_data["source"] = "wechat" if user.role == "student" else "web"
            result.append(user_data)

        return api_success(data=result)
    finally:
        session.close()


@admin_user_bp.route("/users", methods=["POST"])
@admin_required
def create_user():
    """
    管理员创建新用户

    请求格式:
        {
            "username": "用户名",
            "password": "密码",
            "role": "user" | "admin" (默认为user)
        }
    """
    import bcrypt

    data = request.get_json(silent=True) or {}

    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")

    if not username or not password:
        return api_error(message="请提供用户名和密码", http_status=400)

    if len(username) < 3 or len(username) > 50:
        return api_error(message="用户名长度应在3-50个字符之间", http_status=400)

    pwd_error = validate_password_strength(password)
    if pwd_error:
        return api_error(message=pwd_error, http_status=400)

    if role not in ["user", "admin"]:
        return api_error(message="角色只能是user或admin", http_status=400)

    from app.core.database import get_db
    from app.model.user import User

    session = get_db()
    try:
        # 获取当前登录用户信息
        current_user_id = g.current_user.get("user_id")
        current_user = session.query(User).filter_by(id=int(current_user_id)).first()
        is_primary_admin = current_user.is_primary if current_user else False

        # 非主管理员不能创建管理员用户
        if role == "admin" and not is_primary_admin:
            return api_error(message="只有主管理员可以创建管理员用户", http_status=403)

        # 检查用户名是否已存在
        existing_user = session.query(User).filter_by(username=username).first()
        if existing_user:
            return api_error(
                message=f'用户名"{username}"已被使用，请更换其他用户名', http_status=400
            )

        # 生成密码哈希
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        # 创建用户
        new_user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        session.add(new_user)
        session.commit()

        logger.info(f"管理员创建了新用户: {username}, 角色: {role}")

        return api_success(message="用户创建成功", data=new_user.to_dict(), http_status=201)
    finally:
        session.close()


@admin_user_bp.route("/users/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    """
    管理员更新用户信息
    """
    data = request.get_json(silent=True) or {}

    from app.core.database import get_db
    from app.model.user import User

    session = get_db()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        # 记录变更前状态，用于判断是否发生"禁用/降权"（需吊销其活跃 token/session，否则旧 token 继续有效）
        prev_active = bool(user.is_active)
        prev_role = user.role or ""

        # 获取当前登录用户信息
        current_user_id = g.current_user.get("user_id")
        current_user = session.query(User).filter_by(id=int(current_user_id)).first()
        is_primary_admin = current_user.is_primary if current_user else False

        # 超级管理员（主管理员）的角色不可修改
        if user.is_primary:
            if "role" in data:
                return api_error(message="超级管理员的角色不可修改", http_status=403)

        # 微信端学生用户的身份字段不可修改（username=openid、role、is_primary 与登录来源绑定）
        if user.role == "student":
            if "role" in data and data["role"] != "student":
                return api_error(message="微信端用户角色不可修改", http_status=403)
            if "username" in data and data["username"] != user.username:
                return api_error(message="微信端用户名为微信标识，不可修改", http_status=403)
            if "is_primary" in data:
                return api_error(message="微信端用户不可设置为主管理员", http_status=403)

        # 只有超级管理员可以修改其他管理员的角色
        if "role" in data and user.role == "admin" and not is_primary_admin:
            return api_error(message="只有超级管理员可以修改其他管理员的角色", http_status=403)

        # 非主管理员不能将用户提升为管理员
        if "role" in data and data["role"] == "admin" and not is_primary_admin:
            return api_error(message="只有主管理员可以创建或提升管理员", http_status=403)

        # 只有超级管理员可以设置/取消主管理员权限
        if "is_primary" in data and not is_primary_admin:
            return api_error(message="只有超级管理员可以设置主管理员权限", http_status=403)

        # 更新字段
        if "username" in data:
            # 检查新用户名是否已被使用
            existing_user = session.query(User).filter_by(username=data["username"]).first()
            if existing_user and existing_user.id != user_id:
                return api_error(
                    message=f"""用户名"{data['username']}"已被使用，请更换其他用户名""",
                    http_status=400,
                )
            user.username = data["username"]

        if "email" in data:
            email = data.get("email")
            if email and not EMAIL_RE.match(email):
                return api_error(message="邮箱格式不正确", http_status=400)
            user.email = email
        if "avatar" in data:
            try:
                _validate_and_set_avatar(user, data.get("avatar"))
            except FileUploadError as e:
                return api_error(message=str(e), http_status=400)
        if "role" in data:
            # 微信端学生用户角色锁定：忽略提交值（前端禁用项仍会带 student 值，不做白名单校验）
            if user.role == "student":
                pass
            elif data["role"] not in ["user", "admin"]:
                return api_error(message="角色只能是user或admin", http_status=400)
            else:
                user.role = data["role"]
        if "is_primary" in data:
            user.is_primary = bool(data["is_primary"])
        if "is_active" in data:
            user.is_active = bool(data["is_active"])

        user.updated_at = datetime.now()
        session.commit()

        # 若本次更新导致该用户"被禁用"或"从 admin 降权"，立即吊销其全部活跃会话，
        # 使其现存 token/会话即刻失效，避免旧凭据在禁用/降权后仍能访问（2026-09-06 加固）。
        # 会话撤销后，依赖 session_id cookie 的请求在 jwt_required 层即返回 401，
        # 前端自动刷新时会因 session 失效而重新登录；纯 Bearer 短时 access 到期后自然失效。
        now_disabled = not bool(user.is_active)
        demoted_from_admin = prev_role == "admin" and (user.role or "") != "admin"
        if (prev_active and now_disabled) or demoted_from_admin:
            from app.core.database import get_db as _sdb
            from app.services.session_service import session_service

            _ss = _sdb()
            try:
                _cnt = session_service.delete_all_user_sessions(
                    int(user_id), reason="admin_disable", by_ip=get_client_ip()
                )
            except Exception as _exc:  # 会话吊销失败不阻断主流程，记日志即可
                logger.warning(f"禁用/降权后吊销会话失败 user_id={user_id}: {_exc}")
                _cnt = 0
            finally:
                _ss.close()
            logger.info(
                f"用户被禁用/降权，已吊销其 {_cnt} 个活跃会话: user_id={user_id}, "
                f"prev_active={prev_active}, prev_role={prev_role}, role={user.role}"
            )

        logger.info(f"管理员更新了用户: {user.username}")

        return api_success(message="用户已更新", data=user.to_dict())
    finally:
        session.close()


@admin_user_bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    """
    管理员删除用户
    """
    # 不能删除自己
    current_user_id = g.current_user.get("user_id")
    if int(current_user_id) == user_id:
        return api_error(message="不能删除自己", http_status=400)

    from app.core.database import get_db
    from app.model.user import User
    from app.model.wechat_account import WechatAccount
    from app.model.student_profile import StudentProfile
    from app.model.user_notification import UserNotification

    session = get_db()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        # 获取当前登录用户信息
        current_user = session.query(User).filter_by(id=int(current_user_id)).first()
        is_primary_admin = current_user.is_primary if current_user else False

        # 超级管理员不可被删除
        if user.is_primary:
            return api_error(message="超级管理员不可被删除", http_status=403)

        # 只有超级管理员可以删除其他管理员
        if user.role == "admin" and not is_primary_admin:
            return api_error(message="只有超级管理员可以删除其他管理员", http_status=403)

        username = user.username

        # 级联清理微信端用户的子表记录（wechat_accounts / student_profiles / user_notifications），
        # 子表 FK 均无 ondelete 级联，直接删 User 会因外键约束失败或留下孤儿数据
        session.query(WechatAccount).filter_by(user_id=user.id).delete()
        session.query(StudentProfile).filter_by(user_id=user.id).delete()
        session.query(UserNotification).filter_by(user_id=user.id).delete()

        session.delete(user)
        session.commit()

        logger.info(f"管理员删除了用户: {username}")

        return api_success(message="用户已删除")
    finally:
        session.close()


@admin_user_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_user_password(user_id):
    """
    管理员重置用户密码
    """
    import bcrypt

    data = request.get_json(silent=True) or {}
    new_password = data.get("password", "")

    pwd_error = validate_password_strength(new_password)
    if pwd_error:
        return api_error(message=pwd_error, http_status=400)

    from app.core.database import get_db
    from app.model.user import User

    session = get_db()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        # 获取当前登录用户信息
        current_user_id = g.current_user.get("user_id")
        current_user = session.query(User).filter_by(id=int(current_user_id)).first()
        is_primary_admin = current_user.is_primary if current_user else False

        # 主管理员密码只能由主管理员自己重置
        if user.is_primary and not is_primary_admin:
            return api_error(message="主管理员密码只能由主管理员自己重置", http_status=403)

        # 微信端学生用户没有账号密码概念（password_hash 为随机占位哈希），禁止重置
        if user.role == "student":
            return api_error(message="微信端用户无需密码，不可重置", http_status=403)

        # 非主管理员不能重置其他管理员的密码
        if user.role == "admin" and not is_primary_admin:
            return api_error(message="只有主管理员可以重置其他管理员的密码", http_status=403)

        # 生成新密码哈希
        password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode(
            "utf-8"
        )
        user.password_hash = password_hash
        user.updated_at = datetime.now()
        session.commit()

        logger.info(f"管理员重置了用户密码: {user.username}")

        return api_success(message="密码已重置")
    finally:
        session.close()


@admin_user_bp.route("/users/<int:user_id>/reset-mfa", methods=["POST"])
@admin_required
def reset_user_mfa(user_id):
    """
    重置用户MFA（关闭MFA）

    权限规则：
    - 超级管理员可以重置任何非超级管理员用户的MFA
    - 非超级管理员只能重置普通用户（role=user）的MFA
    - 超级管理员的MFA不可被任何人重置
    - 非超级管理员不能重置其他管理员的MFA
    """
    from app.core.database import get_db
    from app.model.user import User
    from app.model.user_mfa import UserMFA

    session = get_db()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)

        # 获取当前登录用户信息
        current_user_id = g.current_user.get("user_id")
        current_user = session.query(User).filter_by(id=int(current_user_id)).first()
        is_primary_admin = current_user.is_primary if current_user else False

        # 超级管理员的MFA不可被任何人重置（保护根管理员）
        if user.is_primary:
            return api_error(message="超级管理员的MFA不可被重置", http_status=403)

        # 微信端学生用户不使用 MFA（走 openid 登录体系）
        if user.role == "student":
            return api_error(message="微信端用户不启用MFA", http_status=400)

        # 非超级管理员只能重置普通用户的MFA，不能重置其他管理员的MFA
        if not is_primary_admin and user.role == "admin":
            return api_error(message="非超级管理员不能重置其他管理员的MFA", http_status=403)

        # 查找并删除用户的MFA配置
        mfa_config = session.query(UserMFA).filter_by(user_id=str(user_id)).first()
        if mfa_config:
            session.delete(mfa_config)
            session.commit()
            logger.info(f"管理员 {current_user.username} 重置了用户MFA: {user.username}")
            return api_success(message="MFA已重置（已关闭）")
        else:
            return api_success(message="该用户未启用MFA")
    finally:
        session.close()
