#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 黑名单模型
用于存储已撤销的 JWT token
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index

from app.core.database import Base


class TokenBlacklist(Base):
    """
    Token 黑名单表
    
    存储已登出或异常的 token，防止被重复使用
    """
    __tablename__ = 'token_blacklist'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(36), nullable=False, unique=True, comment='JWT ID')
    token_hash = Column(String(64), nullable=False, comment='Token SHA256 哈希')
    user_id = Column(String(50), nullable=False, comment='用户ID')
    revoked_at = Column(DateTime, default=datetime.now, comment='撤销时间')
    expires_at = Column(DateTime, nullable=False, comment='Token 过期时间')
    reason = Column(String(100), nullable=True, comment='撤销原因')
    
    # 索引
    __table_args__ = (
        Index('idx_jti', 'jti'),
        Index('idx_user_id', 'user_id'),
        Index('idx_expires', 'expires_at'),
        {'comment': 'Token 黑名单表'},
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'jti': self.jti,
            'user_id': self.user_id,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'reason': self.reason,
        }
