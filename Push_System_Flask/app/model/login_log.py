#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录日志模型
记录每次登录的详细信息
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text

from app.core.database import Base


class LoginLog(Base):
    """
    登录日志表
    
    记录每次登录的IP地址、时间、设备等信息
    """
    __tablename__ = 'login_logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, comment='用户ID')
    username = Column(String(50), nullable=True, comment='用户名')
    
    # 登录信息
    login_time = Column(DateTime, default=datetime.now, nullable=False, comment='登录时间')
    logout_time = Column(DateTime, nullable=True, comment='退出时间')
    ip_address = Column(String(50), nullable=True, comment='IP地址')
    user_agent = Column(String(500), nullable=True, comment='浏览器/设备信息')
    
    # 位置信息（可选）
    country = Column(String(50), nullable=True, comment='国家')
    region = Column(String(50), nullable=True, comment='地区')
    city = Column(String(50), nullable=True, comment='城市')
    
    # 登录结果
    status = Column(String(20), default='success', comment='登录状态: success/failed')
    failure_reason = Column(String(100), nullable=True, comment='失败原因')
    
    def to_dict(self):
        result = {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'login_time': self.login_time.isoformat() if self.login_time else None,
            'logout_time': self.logout_time.isoformat() if self.logout_time else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'country': self.country,
            'region': self.region,
            'city': self.city,
            'status': self.status,
            'failure_reason': self.failure_reason,
        }
        
        # 计算持续时间
        if self.login_time:
            end_time = self.logout_time or datetime.now()
            duration_seconds = int((end_time - self.login_time).total_seconds())
            
            # 格式化为易读的时间
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            seconds = duration_seconds % 60
            
            if hours > 0:
                result['duration'] = f'{hours}小时{minutes}分钟{seconds}秒'
            elif minutes > 0:
                result['duration'] = f'{minutes}分钟{seconds}秒'
            else:
                result['duration'] = f'{seconds}秒'
        else:
            result['duration'] = None
            
        return result
