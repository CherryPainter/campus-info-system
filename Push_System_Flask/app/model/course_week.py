#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程周次数据模型

存储每周的日期范围，用于判断当前是第几周
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, Index
from app.core.database import Base


class CourseWeek(Base):
    """
    课程周次
    
    存储每周的日期范围（周一~周日），用于判断当前是第几周
    """
    __tablename__ = 'course_weeks'

    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    week_number = Column(Integer, nullable=False, unique=True, comment='周次 (如: 14)')
    start_date = Column(Date, nullable=False, comment='周一日期')
    end_date = Column(Date, nullable=False, comment='周日日期')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='创建时间')

    __table_args__ = (
        Index('idx_course_week_number', 'week_number'),
        Index('idx_course_week_dates', 'start_date', 'end_date'),
    )

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'id': self.id,
            'week_number': self.week_number,
            'start_date': self.start_date.strftime('%Y-%m-%d') if self.start_date else None,
            'end_date': self.end_date.strftime('%Y-%m-%d') if self.end_date else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
