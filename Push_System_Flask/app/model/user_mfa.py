#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户 MFA 配置模型
存储用户的多因素认证配置
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean

from app.core.database import Base


class UserMFA(Base):
    """
    用户 MFA 配置表
    
    存储用户的 TOTP MFA 配置
    """
    __tablename__ = 'user_mfa'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False, unique=True, comment='用户ID')
    secret = Column(String(32), nullable=True, comment='TOTP 密钥 (加密存储)')
    enabled = Column(Boolean, default=False, comment='是否启用 MFA')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
