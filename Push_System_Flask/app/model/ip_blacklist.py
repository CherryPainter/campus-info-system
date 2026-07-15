#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IP黑名单模型 - 记录被禁止访问的IP地址及异常事件"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from app.core.database import Base


class IPBlacklist(Base):
    """IP黑名单"""
    __tablename__ = 'ip_blacklist'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(45), nullable=False, index=True, comment='IP地址 (支持 IPv4/IPv6)')
    reason = Column(String(200), nullable=True, comment='加入黑名单原因')
    source = Column(String(50), default='manual', comment='来源: manual手动/auto自动检测/ddos攻击检测/rate_limit限频')
    is_active = Column(Boolean, default=True, index=True, comment='是否生效')
    request_count = Column(Integer, default=0, comment='触发时的累计请求数')
    blocked_at = Column(DateTime, default=datetime.now, comment='封禁时间')
    expires_at = Column(DateTime, nullable=True, comment='解封时间（NULL表示永久）')
    created_by = Column(String(50), nullable=True, comment='操作人')
    note = Column(Text, nullable=True, comment='备注')
    created_at = Column(DateTime, default=datetime.now, comment='记录创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='记录更新时间')

    def to_dict(self):
        return {
            'id': self.id,
            'ip_address': self.ip_address,
            'reason': self.reason,
            'source': self.source,
            'is_active': self.is_active,
            'request_count': self.request_count,
            'blocked_at': self.blocked_at.isoformat() if self.blocked_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_by': self.created_by,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class IPSecurityEvent(Base):
    """安全事件记录 - 记录异常访问行为用于分析和自动封禁"""
    __tablename__ = 'ip_security_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(45), nullable=False, index=True, comment='IP地址')
    event_type = Column(String(50), nullable=False, index=True, comment='事件类型: rate_limit_exceeded/sql_injection/xss/suspicious_path/large_request/ddos/file_upload_abuse')
    path = Column(String(500), nullable=True, comment='请求路径')
    method = Column(String(10), nullable=True, comment='HTTP方法')
    user_agent = Column(String(500), nullable=True, comment='User-Agent')
    detail = Column(Text, nullable=True, comment='事件详情（JSON格式）')
    severity = Column(String(20), default='warning', comment='严重程度: info/warning/critical')
    is_blocked = Column(Boolean, default=False, comment='是否因此事件导致IP被封禁')
    is_ignored = Column(Boolean, default=False, comment='是否已忽略/标记处理（忽略后不再需要处置）')
    created_at = Column(DateTime, default=datetime.now, comment='事件时间')

    # 联合索引：快速查询某IP最近的事件
    __table_args__ = (
        Index('ix_ip_events_ip_time', 'ip_address', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'ip_address': self.ip_address,
            'event_type': self.event_type,
            'path': self.path,
            'method': self.method,
            'user_agent': (self.user_agent or '')[:100],  # 截断显示
            'detail': self.detail,
            'severity': self.severity,
            'is_blocked': self.is_blocked,
            'is_ignored': self.is_ignored,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
