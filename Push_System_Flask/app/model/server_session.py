#!/usr/bin/env python3
"""
服务端Session模型

用于存储服务端Session数据（替代JWT的双认证机制）
支持Web端使用Session认证，API端继续使用JWT
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.core.database import Base


class ServerSession(Base):
    """服务端Session模型"""

    __tablename__ = "server_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Session ID")
    session_id = Column(String(255), unique=True, nullable=False, comment="Session ID (UUID)")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    ip_address = Column(String(45), comment="客户端IP地址")
    user_agent = Column(Text, comment="User Agent")
    data = Column(Text, comment="Session数据（JSON格式）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    expires_at = Column(DateTime, comment="过期时间")
    is_active = Column(Boolean, default=True, comment="是否激活")
    # 撤销信息：用于告知被踢设备“为什么、被谁（IP）踢掉”
    revoked_at = Column(DateTime, comment="撤销时间")
    revoked_reason = Column(String(32), comment="撤销原因: new_login/expired/admin_revoke/logout")
    revoked_by_ip = Column(String(45), comment="撤销操作者IP（如新登录设备IP）")

    # 索引
    __table_args__ = (
        Index("idx_session_id", "session_id"),
        Index("idx_user_id", "user_id"),
        Index("idx_expires_at", "expires_at"),
    )

    def __repr__(self):
        return f"<ServerSession {self.session_id}>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "data": self.data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoked_reason": self.revoked_reason,
            "revoked_by_ip": self.revoked_by_ip,
        }

    @property
    def is_expired(self):
        """检查是否已过期"""
        if not self.expires_at:
            return False
        return datetime.now() > self.expires_at

    @property
    def is_valid(self):
        """检查Session是否有效"""
        return self.is_active and not self.is_expired
