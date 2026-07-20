#!/usr/bin/env python3
"""推送任务队列持久化模型

将 task_service 的内存任务队列落库备份，避免后端重启时丢失尚未发出的 pending 推送任务。
已成功发送的推送同时在 task_processes 表留有完整执行历史（由 delivery_service 写入）。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class PushTask(Base):
    """推送任务队列（task_service 内存队列的持久化备份）"""

    __tablename__ = "push_task_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True, comment="幂等任务ID(md5)")
    task_type = Column(String(50), nullable=True, comment="任务类型")
    sub_type = Column(String(50), nullable=True, comment="子类型")
    rule_id = Column(String(50), nullable=True, comment="规则ID")
    schedule_id = Column(String(50), nullable=True, comment="课表ID")
    data = Column(Text, nullable=True, comment="任务数据(JSON)")
    status = Column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
        comment="状态: pending/processing/success/failed/retrying",
    )
    retry_count = Column(Integer, default=0, nullable=False, comment="重试次数")
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, nullable=False, onupdate=datetime.now)
