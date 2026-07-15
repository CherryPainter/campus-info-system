#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户模型
存储管理员账号信息
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from app.core.database import Base


class User(Base):
    """
    用户表
    
    存储管理员账号、密码哈希等信息
    """
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True, comment='用户名')
    password_hash = Column(String(128), nullable=False, comment='bcrypt 密码哈希')
    role = Column(String(20), default='admin', comment='用户角色')
    is_active = Column(Boolean, default=True, comment='是否启用')
    is_primary = Column(Boolean, default=False, comment='是否为主管理员')
    
    # 个人信息扩展字段
    email = Column(String(100), nullable=True, comment='邮箱')
    avatar = Column(MEDIUMTEXT, nullable=True, comment='头像URL或Base64')
    avatar_change_log = Column(Text, nullable=True, comment='头像修改记录(JSON时间戳列表)')
    
    # 登录相关
    last_login = Column(DateTime, nullable=True, comment='最后登录时间')
    last_login_ip = Column(String(50), nullable=True, comment='最后登录IP')
    
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'avatar': self.avatar,
            'role': self.role,
            'is_active': self.is_active,
            'is_primary': self.is_primary,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'last_login_ip': self.last_login_ip,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
