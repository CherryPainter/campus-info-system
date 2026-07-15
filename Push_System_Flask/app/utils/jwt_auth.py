#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JWT 认证工具模块
提供 JWT Token 的生成、验证、刷新功能
支持 access_token (短期) + refresh_token (长期) 双 Token 机制

设计说明：
- access_token: 短期有效（默认1小时），用于日常 API 请求认证
- refresh_token: 长期有效（默认7天），用于刷新 access_token，避免频繁登录
- 每个 token 包含 jti (JWT ID)，用于支持 token 撤销（黑名单机制）
- 使用 MySQL 持久化存储已撤销的 token jti，支持多实例部署和重启恢复
"""

import uuid
import time
import hashlib
import jwt
from datetime import datetime
from app.core.config import Config
from app.core.logger import get_logger
from app.core.database import get_db
from app.model.token_blacklist import TokenBlacklist

# 使用统一日志系统
logger = get_logger(__name__)


class JWTManager:
    """
    JWT 认证管理器

    职责：
    1. 生成 access_token 和 refresh_token 双 token
    2. 验证 token 有效性（签名、过期、黑名单）
    3. 使用 refresh_token 刷新 access_token
    4. 管理 token 撤销（黑名单），持久化到 MySQL

    属性：
        secret_key (str): JWT 签名密钥
        access_token_expire (int): access_token 有效期（秒）
        refresh_token_expire (int): refresh_token 有效期（秒）
    """

    def __init__(self, secret_key, access_token_expire=3600, refresh_token_expire=604800,
                 refresh_idle_expire=259200, refresh_absolute_expire=2592000):
        """
        初始化 JWT 管理器

        Args:
            secret_key (str): JWT 签名密钥，从 Config.SECRET_KEY 获取
            access_token_expire (int): access_token 有效期（秒），默认 3600（1小时）
            refresh_token_expire (int): refresh_token 有效期（秒），默认 604800（7天）
            refresh_idle_expire (int): refresh_token 闲置超时（秒），默认 259200（3天），
                距上次活跃(iat)超过此值则 refresh 失效，防止关浏览器跑路后被长期冒用
            refresh_absolute_expire (int): refresh_token 绝对有效期（秒），默认 2592000（30天），
                距首次登录(session_start)超过此值强制失效，防止无限续期
        """
        if len(secret_key) < 32:
            logger.warning(
                f'JWT 密钥强度不足 (长度 {len(secret_key)})，建议至少 32 字符。'
                f'当前密钥将导致严重安全风险。'
            )
        self.secret_key = secret_key
        self.access_token_expire = access_token_expire
        self.refresh_token_expire = refresh_token_expire

        self.refresh_idle_expire = refresh_idle_expire
        self.refresh_absolute_expire = refresh_absolute_expire

        logger.info(
            f'JWT 管理器初始化完成: '
            f'access_token 有效期 {access_token_expire}s, '
            f'refresh_token 有效期 {refresh_token_expire}s, '
            f'refresh idle 超时 {refresh_idle_expire}s, '
            f'refresh 绝对上限 {refresh_absolute_expire}s, '
            f'黑名单存储: MySQL'
        )

    def _get_token_hash(self, token: str) -> str:
        """计算 token 的 SHA256 哈希"""
        return hashlib.sha256(token.encode()).hexdigest()

    def generate_tokens(self, user_id, username, role='admin', login_log_id=None,
                        session_start=None, idle_expire=None, absolute_expire=None):
        """
        生成 access_token 和 refresh_token

        Args:
            user_id (str): 用户唯一标识
            username (str): 用户名
            role (str): 用户角色，默认 'admin'
            login_log_id (int): 登录日志ID，可选
            session_start (float): 首次登录时间戳，用于绝对上限计算
            idle_expire (int): refresh 闲置超时（秒），None 时取类默认（受 remember_me 控制）
            absolute_expire (int): refresh 绝对上限（秒），None 时取类默认（受 remember_me 控制）

        Returns:
            dict: 包含 access_token、refresh_token、expires_in 的字典
        """
        # 闲置/绝对上限可按 remember_me 透传：未传则用类默认（长会话配置）
        idle_expire = idle_expire if idle_expire is not None else self.refresh_idle_expire
        absolute_expire = absolute_expire if absolute_expire is not None else self.refresh_absolute_expire
        now = time.time()

        # 生成 access_token payload
        access_payload = {
            'user_id': user_id,
            'username': username,
            'role': role,
            'type': 'access',
            'jti': str(uuid.uuid4()),
            'iat': int(now),
            'exp': int(now + self.access_token_expire),
        }
        
        if login_log_id is not None:
            access_payload['login_log_id'] = login_log_id

        # 生成 refresh_token payload
        refresh_payload = {
            'user_id': user_id,
            'username': username,
            'role': role,
            'type': 'refresh',
            'jti': str(uuid.uuid4()),
            'iat': int(now),
            'exp': int(now + self.refresh_token_expire),
        }
        
        if session_start is not None:
            refresh_payload['session_start'] = session_start

        # 把本会话的闲置/绝对上限写入 refresh token，刷新时读取（支持 remember_me 长短会话）
        refresh_payload['idle_expire'] = int(idle_expire)
        refresh_payload['absolute_expire'] = int(absolute_expire)

        if login_log_id is not None:
            refresh_payload['login_log_id'] = login_log_id

        # 使用 HS256 算法签名
        access_token = jwt.encode(access_payload, self.secret_key, algorithm='HS256')
        refresh_token = jwt.encode(refresh_payload, self.secret_key, algorithm='HS256')

        logger.info(
            f'JWT token 已生成: user={username}, role={role}, '
            f'access_jti={access_payload["jti"]}, refresh_jti={refresh_payload["jti"]}'
        )

        return {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': self.access_token_expire,
        }

    def verify_token(self, token):
        """
        验证 token 有效性

        Args:
            token (str): 待验证的 JWT token 字符串

        Returns:
            dict: 解码后的 payload 数据

        Raises:
            jwt.ExpiredSignatureError: token 已过期
            jwt.InvalidTokenError: token 无效
            ValueError: token 已被撤销
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            logger.debug('JWT token 已过期')
            raise
        except jwt.InvalidTokenError as e:
            logger.debug(f'JWT token 无效: {e}')
            raise

        # 检查黑名单
        jti = payload.get('jti')
        if jti and self.is_revoked(jti):
            logger.warning(f'JWT token 验证失败: token 已被撤销 (jti={jti})')
            raise ValueError('Token has been revoked')

        return payload

    def refresh_access_token(self, refresh_token):
        """
        使用 refresh_token 换取新的 access_token

        Args:
            refresh_token (str): refresh token 字符串

        Returns:
            str: 新的 access_token
        """
        payload = self.verify_token(refresh_token)

        if payload.get('type') != 'refresh':
            logger.warning('JWT refresh 失败: token 类型不是 refresh')
            raise ValueError('Invalid token type: expected refresh token')

        now = time.time()
        old_jti = payload.get('jti')
        user_id = payload.get('user_id')
        exp = payload.get('exp', 0)

        # idle 超时检查：距上次活跃(iat)超过阈值则失效，防止"关浏览器跑路"后被长期冒用
        # 阈值优先取本 refresh token 自带的 idle_expire（remember_me 决定），否则回退类默认
        idle_expire = int(payload.get('idle_expire', self.refresh_idle_expire))
        iat = payload.get('iat', 0)
        if now - iat > idle_expire:
            logger.warning(
                f'JWT refresh 失败: idle 超时 (user={payload.get("username")}, '
                f'距上次活跃 {int(now - iat)}s > 阈值 {idle_expire}s)'
            )
            if old_jti:
                self.revoke_token_by_jti(old_jti, user_id, exp, reason='idle_timeout')
            raise ValueError('refresh token idle timeout')

        # 绝对上限检查：距首次登录(session_start)超过阈值强制失效，防止无限续期
        # 阈值优先取本 refresh token 自带的 absolute_expire（remember_me 决定），否则回退类默认
        absolute_expire = int(payload.get('absolute_expire', self.refresh_absolute_expire))
        session_start = payload.get('session_start', iat)
        if now - session_start > absolute_expire:
            logger.warning(
                f'JWT refresh 失败: 超过绝对有效期 (user={payload.get("username")}, '
                f'会话已 {int(now - session_start)}s > 阈值 {absolute_expire}s)'
            )
            if old_jti:
                self.revoke_token_by_jti(old_jti, user_id, exp, reason='absolute_expire')
            raise ValueError('refresh token absolute expiry')

        # 撤销旧的 refresh_token（一次性使用）
        if old_jti:
            self.revoke_token_by_jti(old_jti, user_id, exp)

        # 安全：role 必须从原 token 显式获取，默认 'user' 防止权限提升
        role = payload.get('role')
        if not role:
            logger.error(f'JWT refresh 失败: token payload 缺少 role 字段 (user={payload.get("username")})')
            raise ValueError('Invalid token: missing role claim')
        new_tokens = self.generate_tokens(
            user_id=payload['user_id'],
            username=payload['username'],
            role=role,
            session_start=session_start,
            idle_expire=idle_expire,
            absolute_expire=absolute_expire,
        )

        logger.info(
            f'JWT access_token 已刷新: user={payload["username"]}, '
            f'旧 refresh_jti={old_jti} 已撤销'
        )

        # 返回完整令牌对，由调用方把新的 refresh_token 写回 cookie，完成轮换
        return new_tokens

    def decode_token(self, token):
        """解码 token（不验证过期时间）"""
        return jwt.decode(token, self.secret_key, algorithms=['HS256'], options={'verify_exp': False})

    def revoke_token(self, token, reason='logout'):
        """
        撤销 token

        Args:
            token (str): 要撤销的 JWT token 字符串
            reason (str): 撤销原因
        """
        try:
            payload = self.decode_token(token)
            jti = payload.get('jti')
            user_id = payload.get('user_id')
            exp = payload.get('exp', 0)
            if jti:
                self.revoke_token_by_jti(jti, user_id, exp, reason)
                logger.info(f'JWT token 已撤销: jti={jti}, user={payload.get("username")}')
        except jwt.InvalidTokenError as e:
            logger.warning(f'JWT token 撤销失败: 无法解码 - {e}')

    def revoke_token_by_jti(self, jti, user_id, exp, reason='logout'):
        """
        通过 jti 撤销 token

        Args:
            jti (str): JWT ID
            user_id (str): 用户ID
            exp (int): 过期时间戳
            reason (str): 撤销原因
        """
        session = get_db()
        try:
            # 检查是否已存在
            existing = session.query(TokenBlacklist).filter_by(jti=jti).first()
            if existing:
                return
            
            # 添加到黑名单
            blacklist_entry = TokenBlacklist(
                jti=jti,
                token_hash='',  # 可选，用于额外验证
                user_id=user_id,
                expires_at=datetime.fromtimestamp(exp),
                reason=reason,
            )
            session.add(blacklist_entry)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f'撤销 token 失败: {e}')
        finally:
            session.close()

    def is_revoked(self, jti):
        """
        检查 token 是否已被撤销

        Args:
            jti (str): JWT ID

        Returns:
            bool: True 表示已撤销
        """
        session = get_db()
        try:
            row = session.query(TokenBlacklist).filter_by(jti=jti).first()
            return row is not None
        finally:
            session.close()

    @property
    def blacklist_size(self):
        """获取黑名单中已撤销 token 的数量"""
        session = get_db()
        try:
            return session.query(TokenBlacklist).count()
        finally:
            session.close()

    def cleanup_expired_blacklist(self, max_age=86400):
        """
        清理黑名单中过期的条目

        Args:
            max_age (int): 最大保留时间（秒），默认 86400（24小时）
        """
        session = get_db()
        try:
            cutoff = datetime.fromtimestamp(time.time() - max_age)
            deleted = session.query(TokenBlacklist).filter(
                TokenBlacklist.revoked_at < cutoff
            ).delete()
            session.commit()
            if deleted > 0:
                logger.info(f'JWT 黑名单清理完成: 删除 {deleted} 条过期记录')
        except Exception as e:
            session.rollback()
            logger.error(f'清理黑名单失败: {e}')
        finally:
            session.close()
