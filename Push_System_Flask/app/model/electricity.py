#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电量模块数据模型

存储电量相关数据：用电记录、剩余电量
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from app.core.database import Base


class ElectricityRecord(Base):
    """
    用电记录表

    存储每次用电记录
    """
    __tablename__ = 'electricity_records'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    record_time = Column(DateTime, nullable=False, index=True, comment='记录时间')
    usage = Column(Float, nullable=False, comment='用电量(度)')
    meter = Column(String(100), nullable=False, comment='电表名称')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='创建时间')

    # 复合索引：按时间和电表查询
    __table_args__ = (
        Index('idx_time_meter', 'record_time', 'meter'),
    )

    def __repr__(self) -> str:
        return f'<ElectricityRecord(id={self.id}, time={self.record_time}, usage={self.usage}, meter={self.meter})>'

    def to_dict(self) -> dict:
        """转换为字典格式，时间格式为 YYYY-MM-DD HH:MM:SS"""
        return {
            'id': self.id,
            'time': self.record_time.strftime('%Y-%m-%d %H:%M:%S') if self.record_time else None,
            'usage': self.usage,
            'meter': self.meter,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class ElectricityRemaining(Base):
    """
    剩余电量表

    存储每次查询的剩余电量
    """
    __tablename__ = 'electricity_remaining'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    meter = Column(String(100), nullable=False, default='default', comment='电表名称')
    remaining = Column(Float, nullable=False, comment='剩余电量(度)')
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='记录时间')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='创建时间')

    def __repr__(self) -> str:
        return f'<ElectricityRemaining(id={self.id}, meter={self.meter}, remaining={self.remaining})>'

    def to_dict(self) -> dict:
        """转换为字典格式，时间格式为 YYYY-MM-DD HH:MM:SS"""
        return {
            'id': self.id,
            'meter': self.meter,
            'remaining': self.remaining,
            'recorded_at': self.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if self.recorded_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class ElectricityTotalCapacity(Base):
    """
    电量总量记录表

    用于记录电量充值/总量变化的历史
    当检测到电量异常增加时（如充值），记录新的总量基准
    """
    __tablename__ = 'electricity_total_capacity'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    meter = Column(String(100), nullable=False, default='default', comment='电表名称')
    total_capacity = Column(Float, nullable=False, comment='总量(度)')
    remaining_at_record = Column(Float, nullable=False, comment='记录时的剩余电量(度)')
    record_reason = Column(String(50), nullable=False, default='auto_detect', comment='记录原因: auto_detect-自动检测, low_power-低电量警告, manual-手动设置')
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='记录时间')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='创建时间')

    # 复合索引：按电表和时间查询
    __table_args__ = (
        Index('idx_capacity_meter_time', 'meter', 'recorded_at'),
    )

    def __repr__(self) -> str:
        return f'<ElectricityTotalCapacity(id={self.id}, meter={self.meter}, total={self.total_capacity})>'

    def to_dict(self) -> dict:
        """转换为字典格式，时间格式为 YYYY-MM-DD HH:MM:SS"""
        return {
            'id': self.id,
            'meter': self.meter,
            'total_capacity': self.total_capacity,
            'remaining_at_record': self.remaining_at_record,
            'record_reason': self.record_reason,
            'recorded_at': self.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if self.recorded_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
