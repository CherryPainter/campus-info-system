#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务端Session管理服务

提供Session的创建、验证、删除等功能
支持JWT + Session双认证机制

Web端使用Session认证（需要CSRF防护）
API端继续使用JWT认证（无CSRF风险）
"""

import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import and_, or_, text
from flask import request, session as flask_session

from app.core.logger import get_logger
from app.core.database import get_db
from app.model.server_session import ServerSession
from app.model.user import User

logger = get_logger(__name__)


# 撤销相关列（旧库可能缺失），启动期幂等补齐
_SESSION_REVOKE_COLUMNS = {
    'revoked_at': 'DATETIME',
    'revoked_reason': 'VARCHAR(32)',
    'revoked_by_ip': 'VARCHAR(45)',
}

# 用户表头像修改记录列（旧库可能缺失），启动期幂等补齐
_USER_AVATAR_COLUMNS = {
    'avatar_change_log': 'TEXT',
}


class SessionService:
    """服务端Session管理服务（数据库存储）"""
    
    @staticmethod
    def create_session(
        user_id: int,
        ip_address: str = None,
        user_agent: str = None,
        remember_me: bool = False,
        data: Dict[str, Any] = None,
    ) -> Optional[ServerSession]:
        """
        创建新Session
        
        Args:
            user_id: 用户ID
            ip_address: 客户端IP
            user_agent: User Agent
            remember_me: 是否记住我（延长过期时间）
            data: 额外Session数据
            
        Returns:
            ServerSession对象或None
        """
        try:
            # 生成Session ID
            session_id = str(uuid.uuid4())
            
            # 计算过期时间
            if remember_me:
                expires_at = datetime.now() + timedelta(days=30)
            else:
                expires_at = datetime.now() + timedelta(hours=24)
            
            # 获取客户端IP
            if not ip_address:
                ip_address = request.remote_addr if request else None
            
            # 获取User Agent
            if not user_agent:
                user_agent = request.headers.get('User-Agent', '') if request else None
            
            # 创建Session记录
            session_obj = ServerSession(
                session_id=session_id,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                data=json.dumps(data or {}),
                expires_at=expires_at,
                is_active=True,
            )
            
            db_session = get_db()
            try:
                db_session.add(session_obj)
                db_session.commit()
                db_session.refresh(session_obj)
                logger.info(f'[Session] 创建Session成功: user_id={user_id}, session_id={session_id}')
                return session_obj
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 创建Session失败: {exc}')
            return None
    
    @staticmethod
    def validate_session(session_id: str, check_ip: bool = False) -> Optional[User]:
        """
        验证Session是否有效
        
        Args:
            session_id: Session ID
            check_ip: 是否检查IP地址（防止Session劫持）
            
        Returns:
            User对象（如果Session有效）或None
        """
        try:
            db_session = get_db()
            try:
                session_obj = db_session.query(ServerSession).filter(
                    and_(
                        ServerSession.session_id == session_id,
                        ServerSession.is_active == True,
                    )
                ).first()
                
                if not session_obj:
                    logger.warning(f'[Session] Session不存在或已禁用: {session_id}')
                    return None
                
                # 检查是否过期
                if session_obj.is_expired:
                    logger.warning(f'[Session] Session已过期: {session_id}')
                    session_obj.is_active = False
                    db_session.commit()
                    return None
                
                # 检查IP地址（可选，防止Session劫持）
                if check_ip and request:
                    client_ip = request.remote_addr
                    if session_obj.ip_address and session_obj.ip_address != client_ip:
                        logger.warning(f'[Session] Session IP不匹配: {session_id}, 期望={session_obj.ip_address}, 实际={client_ip}')
                        return None
                
                # 更新最后访问时间
                session_obj.updated_at = datetime.now()
                db_session.commit()
                
                # 获取用户
                user = db_session.query(User).filter(User.id == session_obj.user_id).first()
                if not user or not user.is_active:
                    logger.warning(f'[Session] 用户不存在或已禁用: user_id={session_obj.user_id}')
                    return None
                
                return user
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 验证Session失败: {exc}')
            return None
    
    @staticmethod
    def delete_session(session_id: str, reason: str = None, by_ip: str = None) -> bool:
        """
        删除Session（登出 / 管理员踢出）
        
        Args:
            session_id: Session ID
            reason: 撤销原因（logout / admin_revoke 等），记录后供被踢设备显示
            by_ip: 撤销操作者IP（如管理员设备IP），记录后供被踢设备显示
            
        Returns:
            是否成功
        """
        try:
            db_session = get_db()
            try:
                session_obj = db_session.query(ServerSession).filter(
                    ServerSession.session_id == session_id
                ).first()
                
                if not session_obj:
                    return False
                
                session_obj.is_active = False
                if reason:
                    session_obj.revoked_reason = reason
                    session_obj.revoked_at = datetime.now()
                    if by_ip:
                        session_obj.revoked_by_ip = by_ip
                db_session.commit()
                logger.info(f'[Session] 删除Session成功: {session_id}, reason={reason}')
                return True
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 删除Session失败: {exc}')
            return False
    
    @staticmethod
    def delete_all_user_sessions(
        user_id: int,
        except_session_id: str = None,
        reason: str = None,
        by_ip: str = None,
    ) -> int:
        """
        删除用户的所有Session（强制登出所有设备 / 单会话策略踢旧）
        
        Args:
            user_id: 用户ID
            except_session_id: 排除的Session ID（保留当前Session）
            reason: 撤销原因（new_login / logout 等），记录后供被踢设备显示
            by_ip: 撤销操作者IP（如新登录设备IP），记录后供被踢设备显示
            
        Returns:
            删除的Session数量
        """
        try:
            db_session = get_db()
            try:
                query = db_session.query(ServerSession).filter(
                    and_(
                        ServerSession.user_id == user_id,
                        ServerSession.is_active == True,
                    )
                )
                
                if except_session_id:
                    query = query.filter(ServerSession.session_id != except_session_id)
                
                update_vals = {'is_active': False}
                if reason:
                    update_vals['revoked_reason'] = reason
                    update_vals['revoked_at'] = datetime.now()
                    if by_ip:
                        update_vals['revoked_by_ip'] = by_ip
                count = query.update(update_vals, synchronize_session=False)
                db_session.commit()
                logger.info(f'[Session] 删除用户所有Session: user_id={user_id}, count={count}, reason={reason}')
                return count
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 删除用户所有Session失败: {exc}')
            return 0
    
    @staticmethod
    def cleanup_expired_sessions() -> int:
        """
        清理过期Session
        
        Returns:
            清理的Session数量
        """
        try:
            db_session = get_db()
            try:
                count = db_session.query(ServerSession).filter(
                    and_(
                        ServerSession.is_active == True,
                        ServerSession.expires_at < datetime.now(),
                    )
                ).update({'is_active': False}, synchronize_session=False)
                db_session.commit()
                if count > 0:
                    logger.info(f'[Session] 清理过期Session: count={count}')
                return count
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 清理过期Session失败: {exc}')
            return 0
    
    @staticmethod
    def enforce_user_session_limit(user_id: int, max_active: int = 8) -> int:
        """
        治理某用户的活跃会话：惰性清理已过期会话，并限制活跃数量（超出则销最旧）。

        目的：
        - 防止同一用户反复登录导致 server_sessions 表无限叠加（用户反馈的“会话一直在叠加”）。
        - 让过期会话在下次登录时即被清理，而非苦等凌晨3点的定时 cleanup（用户反馈的“session 不会过期”）。
        不影响其他用户的会话，也不踢掉当前刚创建的会话。

        Args:
            user_id: 用户ID
            max_active: 允许保留的最大活跃会话数（不含当前刚创建的）

        Returns:
            本次销除的会话数量
        """
        try:
            db_session = get_db()
            try:
                now = datetime.now()
                # 1) 惰性清理该用户已过期会话
                expired_count = db_session.query(ServerSession).filter(
                    and_(
                        ServerSession.user_id == user_id,
                        ServerSession.is_active == True,
                        ServerSession.expires_at < now,
                    )
                ).update({'is_active': False}, synchronize_session=False)

                # 2) 限制活跃数量：保留最近 max_active 个，超出销最旧
                active = db_session.query(ServerSession).filter(
                    and_(
                        ServerSession.user_id == user_id,
                        ServerSession.is_active == True,
                    )
                ).order_by(ServerSession.updated_at.desc()).all()

                remove_count = 0
                if len(active) > max_active:
                    for old in active[max_active:]:
                        old.is_active = False
                        remove_count += 1

                if expired_count or remove_count:
                    db_session.commit()
                if expired_count or remove_count:
                    logger.info(
                        f'[Session] 治理用户会话: user_id={user_id}, '
                        f'清理过期={expired_count}, 超出上限销旧={remove_count}'
                    )
                return expired_count + remove_count
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 限制用户会话数量失败: {exc}')
            return 0

    @staticmethod
    def get_session_detail(session_id: str) -> Dict[str, Any]:
        """
        返回会话详细状态，供心跳 / 401 响应给出结构化撤销原因（含踢人设备IP）。

        Returns:
            {
                'status': 'active' | 'expired' | 'revoked' | 'not_found',
                'reason':  'new_login' | 'expired' | 'admin_revoke' | 'logout' | None,
                'ip':      撤销操作者IP 或 None,
                'time':    撤销时间(iso) 或 None,
            }
        """
        try:
            db_session = get_db()
            try:
                s = db_session.query(ServerSession).filter(
                    ServerSession.session_id == session_id
                ).first()
                if not s:
                    return {'status': 'not_found', 'reason': 'not_found', 'ip': None, 'time': None}
                # 先判过期（即便 is_active 尚未被置否）
                if s.is_expired:
                    return {'status': 'expired', 'reason': 'expired', 'ip': None, 'time': None}
                if not s.is_active:
                    reason = s.revoked_reason or 'expired'
                    return {
                        'status': 'revoked',
                        'reason': reason,
                        'ip': s.revoked_by_ip,
                        'time': s.revoked_at.isoformat() if s.revoked_at else None,
                    }
                return {'status': 'active', 'reason': None, 'ip': None, 'time': None}
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 查询会话详情失败: {exc}')
            return {'status': 'not_found', 'reason': 'not_found', 'ip': None, 'time': None}

    @staticmethod
    def get_user_sessions(user_id: int) -> list:
        """
        获取用户的所有活跃Session
        
        Args:
            user_id: 用户ID
            
        Returns:
            Session列表
        """
        try:
            db_session = get_db()
            try:
                sessions = db_session.query(ServerSession).filter(
                    and_(
                        ServerSession.user_id == user_id,
                        ServerSession.is_active == True,
                        or_(
                            ServerSession.expires_at == None,
                            ServerSession.expires_at > datetime.now(),
                        )
                    )
                ).order_by(ServerSession.updated_at.desc()).all()
                return [s.to_dict() for s in sessions]
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 获取用户Session失败: {exc}')
            return []

    @staticmethod
    def get_all_active_sessions_with_owner() -> list:
        """
        获取所有活跃会话（含所属用户信息），供管理员总览

        权限由调用方（路由层）控制：超管看全部、普管看全部但不可操作管理员会话。
        返回每条会话附带 owner_username / owner_role / owner_is_primary。
        """
        try:
            db_session = get_db()
            try:
                rows = db_session.query(
                    ServerSession,
                    User.username,
                    User.role,
                    User.is_primary,
                ).join(
                    User, ServerSession.user_id == User.id
                ).filter(
                    and_(
                        ServerSession.is_active == True,
                        or_(
                            ServerSession.expires_at == None,
                            ServerSession.expires_at > datetime.now(),
                        ),
                    )
                ).order_by(ServerSession.updated_at.desc()).all()

                result = []
                for s, username, role, is_primary in rows:
                    d = s.to_dict()
                    d['owner_username'] = username
                    d['owner_role'] = role
                    d['owner_is_primary'] = bool(is_primary)
                    result.append(d)
                return result
            finally:
                db_session.close()
        except Exception as exc:
            logger.error(f'[Session] 获取全部会话失败: {exc}')
            return []


# 全局单例
session_service = SessionService()


def ensure_session_columns():
    """
    幂等补齐 server_sessions 表的撤销相关列（revoked_at/revoked_reason/revoked_by_ip）。
    老库在建表时还没有这些列，create_all 不会补列，故在此用 INFORMATION_SCHEMA 探测后 ALTER。
    失败仅告警不阻断启动。
    """
    try:
        from app.core.database import db_manager
        engine = db_manager.engine
        with engine.connect() as conn:
            existing = {r[0] for r in conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'server_sessions'"
                )
            )}
            for name, ddl in _SESSION_REVOKE_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE server_sessions ADD COLUMN {name} {ddl}"))
                    conn.commit()
                    logger.info(f'[Session] 补齐列: {name}')
    except Exception as exc:
        logger.error(f'[Session] 补齐撤销列失败（若列已存在可忽略）: {exc}')


def ensure_user_columns():
    """
    幂等补齐 users 表的 avatar_change_log 列（老库建表时可能还没有）。
    与 ensure_session_columns 同理：create_all 只建新表不补列，故用 INFORMATION_SCHEMA 探测后 ALTER。
    失败仅告警不阻断启动。
    """
    try:
        from app.core.database import db_manager
        engine = db_manager.engine
        with engine.connect() as conn:
            existing = {r[0] for r in conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'"
                )
            )}
            for name, ddl in _USER_AVATAR_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
                    conn.commit()
                    logger.info(f'[User] 补齐列: {name}')
    except Exception as exc:
        logger.error(f'[User] 补齐列失败（若列已存在可忽略）: {exc}')
