#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程爬取预约任务模型

用于记录「课程表爬取」的预约计划，支持：
- 爬取范围：指定学期（semester）或全量（all，遍历所有历史学期）
- 执行方式：立即执行（immediate）或预约时间（scheduled）
- 生命周期状态：pending -> running -> completed / failed / cancelled

与 TaskProcess 的区别：
- TaskProcess 记录「实际执行过程」的进程（每次爬取都会产生一条）
- ScheduledCrawlTask 记录「用户的预约计划」本身，可在进程管理模块做增删改查
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean

from app.core.database import Base
from app.core.task_state import TaskStatus


class ScheduledCrawlTask(Base):
    """课程爬取预约任务"""
    __tablename__ = 'scheduled_crawl_tasks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment='任务名称')
    # 爬取范围：semester=指定学期，all=全量（所有历史学期）
    scope = Column(String(20), nullable=False, default='semester', comment='爬取范围: semester指定学期, all全量')
    # 学期 DB 格式 id（如 20251），仅 scope=semester 时有效
    semester_id = Column(Integer, nullable=True, comment='学期ID（DB格式，如20251），指定学期时有效')
    # 教务系统内部学期 id（如 251），爬虫命令行 --semester-id 使用
    eams_id = Column(String(20), nullable=True, comment='教务系统内部学期ID，爬虫命令使用')
    # 执行方式：immediate=立即，scheduled=预约
    schedule_type = Column(String(20), nullable=False, default='immediate', comment='执行方式: immediate立即, scheduled预约')
    # 预约执行时间（仅 schedule_type=scheduled 时有效）
    scheduled_at = Column(DateTime, nullable=True, comment='预约执行时间')
    # 可选：指定周次（一般全量爬取留空表示整学期）
    week = Column(Integer, nullable=True, comment='指定周次（可选）')
    # 状态：pending待执行, running执行中, completed已完成, completed_empty空成功, failed失败, cancelled已取消
    status = Column(String(20), default=TaskStatus.PENDING, comment='状态')
    message = Column(Text, nullable=True, comment='当前状态信息')
    error_message = Column(Text, nullable=True, comment='错误信息')
    created_by = Column(String(50), nullable=True, comment='创建人')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    started_at = Column(DateTime, nullable=True, comment='开始执行时间')
    completed_at = Column(DateTime, nullable=True, comment='完成时间')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'scope': self.scope,
            'semester_id': self.semester_id,
            'eams_id': self.eams_id,
            'schedule_type': self.schedule_type,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'week': self.week,
            'status': self.status,
            'message': self.message,
            'error_message': self.error_message,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }
