#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程表数据模型（优化版）

支持多学期、完整课程信息存储
"""
from datetime import datetime
import json
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index, TypeDecorator, DECIMAL
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.ext.mutable import MutableList
from app.core.database import Base


class JSONEncodedList(TypeDecorator):
    """
    JSON 编码的列表类型
    
    将 Python list 转换为 JSON 字符串存储，读取时自动转换回 list
    使用 MySQL 的 JSON 类型存储
    """
    impl = String
    
    def load_dialect_impl(self, dialect):
        from sqlalchemy.dialects import mysql
        return dialect.type_descriptor(mysql.JSON())
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return json.dumps(value)
        # 如果是字符串（旧数据格式），尝试解析
        if isinstance(value, str):
            return value
        return json.dumps([])
    
    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                # 旧数据格式：逗号分隔的字符串，转换为列表
                if value.strip():
                    return [int(x.strip()) for x in value.split(',') if x.strip().isdigit()]
                return []
        return []


class Course(Base):
    """
    课程表（优化版）
    
    存储课程信息，支持多学期、完整课程信息
    支持软删除：删除的课程不会被爬虫覆盖
    
    periods 和 weeks 字段使用 JSON 格式存储列表
    """
    __tablename__ = 'courses'
    
    # 主键和标识
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    course_code = Column(String(50), nullable=False, comment='课程代码（如：220110460.02）')
    course_name = Column(String(100), nullable=False, comment='课程名称')
    
    # 学期信息
    semester_id = Column(Integer, nullable=False, comment='学期ID（教务系统）')
    semester_name = Column(String(100), nullable=False, comment='学期名称（如：2025-2026-2）')
    academic_year = Column(String(20), nullable=False, comment='学年（如：2025-2026）')
    term = Column(TINYINT, nullable=False, comment='学期（1=春季，2=秋季）')
    
    # 课程时间信息
    week_day = Column(Integer, nullable=False, comment='星期几（1-7，1=周一）')
    period_idx = Column(Integer, nullable=False, comment='起始节次索引（1-12）')
    periods = Column(MutableList.as_mutable(JSONEncodedList()), nullable=True, comment='所有节次，JSON数组格式（如：[1,2] 或 [5,6,7,8]）')
    start_time = Column(String(10), nullable=False, comment='开始时间（HH:MM）')
    end_time = Column(String(10), nullable=False, comment='结束时间（HH:MM）')
    
    # 周次信息
    weeks = Column(MutableList.as_mutable(JSONEncodedList()), nullable=True, comment='上课周次，JSON数组格式（如：[1,2,3] 或 [1,3,5]）')
    weeks_bitmap = Column(String(30), nullable=True, comment='周次位图（如：111100...，用于快速查询）')
    week_number = Column(Integer, nullable=True, comment='当前周次')
    
    # 教师和教室信息
    teacher = Column(String(100), nullable=True, comment='教师姓名')
    classroom = Column(String(100), nullable=True, comment='教室')
    building = Column(String(50), nullable=True, comment='教学楼')
    
    # 课程属性
    course_type = Column(String(20), nullable=True, comment='课程类型（必修/选修/实践）')
    credit = Column(DECIMAL(3, 1), nullable=True, comment='学分')
    
    # 软删除标记
    is_deleted = Column(Boolean, default=False, nullable=False, comment='是否已删除（软删除）')
    deleted_at = Column(DateTime, nullable=True, comment='删除时间')
    deleted_reason = Column(String(255), nullable=True, comment='删除原因')
    
    # 推送控制
    push_enabled = Column(Boolean, default=True, nullable=False, comment='是否推送提醒')
    
    # 元数据
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='创建时间')
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    crawled_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='爬取时间')

    # 数据来源与校验（v6.11.1 新增）
    # full=全量/指定学期爬虫写入；daily=每日爬虫写入当前周；admin=后台手动新增/编辑
    data_source = Column(String(20), nullable=True, default='full', comment='数据来源')
    last_verified_at = Column(DateTime, nullable=True, comment='最后被爬虫校验/写入的时间')

    # 唯一约束：同一学期、同一课程代码、同一时间，只能有一条记录
    __table_args__ = (
        Index('idx_course_semester', 'semester_id'),
        Index('idx_course_week_day', 'week_day', 'period_idx'),
        Index('idx_course_week_number', 'week_number'),
        Index('idx_course_code', 'course_code'),
        Index('idx_course_is_deleted', 'is_deleted'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'id': self.id,
            'course_code': self.course_code,
            'course_name': self.course_name,
            'semester_id': self.semester_id,
            'semester_name': self.semester_name,
            'academic_year': self.academic_year,
            'term': self.term,
            'teacher': self.teacher,
            'classroom': self.classroom,
            'building': self.building,
            'week_day': self.week_day,
            'period_idx': self.period_idx,
            'periods': self.periods,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'weeks': self.weeks,
            'weeks_bitmap': self.weeks_bitmap,
            'week_number': self.week_number,
            'course_type': self.course_type,
            'credit': float(self.credit) if self.credit else None,
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if self.deleted_at else None,
            'deleted_reason': self.deleted_reason,
            'push_enabled': self.push_enabled,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
            'crawled_at': self.crawled_at.strftime('%Y-%m-%d %H:%M:%S') if self.crawled_at else None,
            'data_source': self.data_source,
            'last_verified_at': self.last_verified_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_verified_at else None,
        }
