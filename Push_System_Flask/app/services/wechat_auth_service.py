#!/usr/bin/env python3
"""
微信小程序登录服务

负责：code2Session 换 openid、学生用户/微信账号的创建与复用、登录日志记录、JWT 双 Token 签发。

设计要点（遵循《微信小程序扩展开发指南》红线）：
- openid 必须由本服务通过微信官方 code2Session 接口获得，绝不信任客户端直接提交的 openid。
- AppSecret 只从服务端环境变量读取，绝不进入前端代码。
- 复用现有 JWTManager 签发双 Token，不重建认证体系、不修改现有 JWT 内核。
- 学生 User 的 password_hash 生成随机 bcrypt 哈希：
  既满足 users.password_hash NOT NULL 约束，又保证随机密码无人可知，
  学生账号无法走 /api/auth/login 密码登录（管理端认证入口不受影响）。
"""

import hashlib
import secrets
from datetime import datetime

import bcrypt
import requests

from app.core.config import Config
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.login_log import LoginLog
from app.model.student_profile import StudentProfile
from app.model.user import User
from app.model.wechat_account import WechatAccount

# 使用统一日志系统
logger = get_logger(__name__)

# 微信官方 code2Session 接口
WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatAuthError(Exception):
    """微信认证业务异常（携带用户可读消息与 HTTP 状态码）"""

    def __init__(self, message, http_status=400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


class WechatAuthService:
    """微信小程序认证服务"""

    def code2session(self, code):
        """
        调用微信官方接口，用登录 code 换取 openid/session_key/unionid

        Args:
            code (str): wx.login() 获取的临时登录凭证

        Returns:
            dict: {"openid": str, "session_key": str, "unionid": str|None}

        Raises:
            WechatAuthError: 配置缺失、code 无效或微信服务器异常
        """
        appid = Config.WECHAT_MINIAPP_APPID
        secret = Config.WECHAT_MINIAPP_SECRET
        if not appid or not secret:
            logger.error("微信小程序登录失败: WECHAT_MINIAPP_APPID/SECRET 未配置")
            raise WechatAuthError("微信小程序功能未配置，请联系管理员", http_status=503)

        try:
            resp = requests.get(
                WECHAT_CODE2SESSION_URL,
                params={
                    "appid": appid,
                    "secret": secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"微信 code2Session 请求失败: {e}")
            raise WechatAuthError("微信服务器暂不可用，请稍后再试", http_status=502)

        if data.get("errcode"):
            errcode = data.get("errcode")
            logger.warning(
                f"微信 code2Session 返回错误: errcode={errcode}, errmsg={data.get('errmsg')}"
            )
            if errcode == 40029:  # js_code 无效
                raise WechatAuthError("登录凭证无效，请重新登录", http_status=401)
            if errcode == 45011:  # 接口频率限制
                raise WechatAuthError("微信登录过于频繁，请稍后再试", http_status=429)
            raise WechatAuthError("微信登录失败，请稍后再试", http_status=502)

        openid = data.get("openid")
        if not openid:
            logger.error("微信 code2Session 响应缺少 openid")
            raise WechatAuthError("微信登录失败，请稍后再试", http_status=502)

        return {
            "openid": openid,
            "session_key": data.get("session_key", ""),
            "unionid": data.get("unionid"),
        }

    def login(self, code, client_ip="", user_agent=""):
        """
        微信登录入口：code → openid → 查找/创建学生用户 → 签发 JWT 双 Token

        Args:
            code (str): wx.login() 的临时登录凭证
            client_ip (str): 客户端 IP（写入 last_login_ip 与登录日志）
            user_agent (str): 客户端 UA（写入登录日志）

        Returns:
            dict: {"tokens": {...}, "user": {...}, "is_new_user": bool}

        Raises:
            WechatAuthError: 微信校验失败、配置缺失或账号不可用
        """
        wx_info = self.code2session(code)
        openid = wx_info["openid"]
        is_new_user = False

        db = get_db()
        try:
            account = db.query(WechatAccount).filter_by(openid=openid).first()
            if account:
                # 已绑定用户：复用，刷新最近登录时间与 session_key
                user = db.query(User).filter_by(id=account.user_id).first()
                if not user or not user.is_active:
                    raise WechatAuthError("账号不可用，请联系管理员", http_status=403)
                account.last_login_at = datetime.now()
                if wx_info.get("session_key"):
                    account.session_key = wx_info["session_key"]
            else:
                # 首次登录：创建学生用户 + 微信账号 + 学生资料骨架
                user = self._create_student_user(db, openid)
                db.add(
                    WechatAccount(
                        user_id=user.id,
                        openid=openid,
                        unionid=wx_info.get("unionid"),
                        session_key=wx_info.get("session_key"),
                        last_login_at=datetime.now(),
                    )
                )
                db.add(StudentProfile(user_id=user.id))
                is_new_user = True
                logger.info(
                    f"微信小程序首次登录，创建学生用户: user_id={user.id}, openid={openid[:8]}..."
                )

            user.last_login = datetime.now()
            user.last_login_ip = client_ip
            db.commit()
            db.refresh(user)
        except WechatAuthError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"微信登录落库失败: {e}")
            raise WechatAuthError("登录失败，请稍后再试", http_status=500)
        finally:
            db.close()

        # 新用户公告补推：首次注册（用户创建）时，把近 7 天已发布公告补写进站内信
        if is_new_user:
            try:
                from app.services.announcement_push_service import (
                    announcement_push_service,
                )

                announcement_push_service.push_recent_announcements_to_new_user(user.id)
            except Exception as e:
                logger.warning(f"新用户公告补推失败(忽略): user_id={user.id}: {e}")

        # 记录登录日志（与管理员登录共用 login_logs 表，便于统一审计）
        login_log_id = self._record_login_log(
            user.id, user.username, client_ip, user_agent, "success"
        )

        # 复用现有 JWT 双 Token 机制（role 透传 student，刷新时从原 token 原样取回，无提权路径）
        jwt_manager = self._get_jwt_manager()
        tokens = jwt_manager.generate_tokens(
            user_id=str(user.id),
            username=user.username,
            role=user.role,
            login_log_id=login_log_id,
            idle_expire=Config.WECHAT_SESSION_TIMEOUT,
        )
        logger.info(f"微信小程序登录成功: user_id={user.id}, role={user.role}")

        return {"tokens": tokens, "user": user.to_dict(), "is_new_user": is_new_user}

    @staticmethod
    def _get_jwt_manager():
        """获取 JWT 管理器实例（延迟从 app.extensions 获取，避免循环导入）"""
        from flask import current_app

        jwt_manager = current_app.extensions.get("jwt_manager")
        if jwt_manager is None:
            logger.error("微信登录失败: JWT 管理器未初始化")
            raise WechatAuthError("服务器配置错误", http_status=500)
        return jwt_manager

    @staticmethod
    def _create_student_user(db, openid):
        """
        创建学生用户（role=student）

        - username 由 openid 哈希生成：唯一且不暴露原始 openid
        - password_hash 生成随机 bcrypt 哈希：满足 NOT NULL 约束的同时，
          随机密码无人可知，学生账号无法通过密码登录接口
        """
        base = "wx_" + hashlib.sha256(openid.encode("utf-8")).hexdigest()[:16]
        username = base
        suffix = 1
        while db.query(User).filter_by(username=username).first():
            username = f"{base}_{suffix}"
            suffix += 1

        random_password = secrets.token_hex(16)
        password_hash = bcrypt.hashpw(
            random_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        user = User(
            username=username,
            password_hash=password_hash,
            role="student",
            is_active=True,
            is_primary=False,
        )
        db.add(user)
        db.flush()  # 立即获取 user.id 供关联记录使用
        return user

    @staticmethod
    def _record_login_log(
        user_id, username, ip_address, user_agent, status="success", failure_reason=None
    ):
        """记录登录日志，返回日志ID"""
        db = get_db()
        log_id = None
        try:
            log = LoginLog(
                user_id=user_id,
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                status=status,
                failure_reason=failure_reason,
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            log_id = log.id
        except Exception as e:
            logger.error(f"记录微信登录日志失败: {e}")
        finally:
            db.close()
        return log_id


# 模块级单例
wechat_auth_service = WechatAuthService()
