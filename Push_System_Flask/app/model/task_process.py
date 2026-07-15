#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务进程模型"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from app.core.database import Base
from app.core.task_state import TaskStatus


class TaskProcess(Base):
    """任务进程"""
    __tablename__ = 'task_processes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment='任务名称')
    task_type = Column(String(50), nullable=False, comment='任务类型: spider课表爬虫, course_full_crawl全量爬取, weather天气, electricity电量, course课表推送, custom自定义, system系统')
    status = Column(String(20), default=TaskStatus.RUNNING, comment='状态: running运行中, completed已完成, completed_empty空成功, failed失败, cancelled已取消, pending待执行')
    pid = Column(Integer, nullable=True, comment='进程ID')
    progress = Column(Integer, default=0, comment='进度百分比 0-100')
    total_items = Column(Integer, default=0, comment='总项目数')
    processed_items = Column(Integer, default=0, comment='已处理项目数')
    message = Column(Text, nullable=True, comment='当前状态信息')
    error_message = Column(Text, nullable=True, comment='错误信息')
    started_at = Column(DateTime, default=datetime.now, comment='开始时间')
    completed_at = Column(DateTime, nullable=True, comment='完成时间')
    duration = Column(Float, default=0.0, comment='执行时长(秒)')
    created_by = Column(String(50), nullable=True, comment='创建人')
    extra_data = Column(Text, nullable=True, comment='额外数据(JSON)')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'task_type': self.task_type,
            'status': self.status,
            'pid': self.pid,
            'progress': self.progress,
            'total_items': self.total_items,
            'processed_items': self.processed_items,
            'message': self.message,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration': self.duration,
            'created_by': self.created_by,
            'extra_data': self.extra_data,
        }
