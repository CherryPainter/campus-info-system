#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务进程写入服务（UnifiedTaskService）

集中所有 TaskProcess 记录的创建 / 更新 / 查询，作为整个系统任务状态写入的
唯一入口，替代 process_routes 与 delivery_service 中散落重复的 TaskProcess 写入逻辑。

设计要点：
- 所有状态写读一律引用 app.core.task_state.TaskStatus 常量，杜绝硬编码漂移；
- 进程「开始 / 进度 / 完成」三类操作均在此实现，业务代码不得直接 new TaskProcess()；
- 方法的返回值 / 行为与原 process_routes 工具函数保持一致，确保调用方无感知切换。
"""
import os
import logging
from datetime import datetime

from app.core.database import get_db
from app.model.task_process import TaskProcess
from app.core.task_state import TaskStatus

logger = logging.getLogger(__name__)


def create_process(name: str, task_type: str, total_items: int = 0,
                   created_by: str = 'system', pid=None,
                   message: str = '任务启动中...') -> int:
    """创建任务进程记录，返回进程 ID。"""
    session = get_db()
    try:
        process = TaskProcess(
            name=name,
            task_type=task_type,
            status=TaskStatus.RUNNING,
            pid=pid if pid is not None else os.getpid(),
            progress=0,
            total_items=total_items,
            processed_items=0,
            message=message,
            created_by=created_by,
        )
        session.add(process)
        session.commit()
        session.refresh(process)
        process_id = process.id
        logger.info(f'[UnifiedTask] 创建任务进程: {name} (ID={process_id}, type={task_type})')
        return process_id
    finally:
        session.close()


def update_progress(process_id: int, processed: int, total: int = None, message: str = None):
    """更新任务进度（已处理数量 / 总数 / 提示）。"""
    session = get_db()
    try:
        process = session.query(TaskProcess).filter(TaskProcess.id == process_id).first()
        if not process:
            return
        process.processed_items = processed
        if total is not None:
            process.total_items = total
        if message:
            process.message = message
        if process.total_items > 0:
            process.progress = min(100, int(processed * 100 / process.total_items))
        session.commit()
    finally:
        session.close()


def complete_process(process_id: int, status: str = TaskStatus.COMPLETED,
                     message: str = None, error: str = None, progress: int = None):
    """完成任务进程，写入终态与耗时。"""
    session = get_db()
    try:
        process = session.query(TaskProcess).filter(TaskProcess.id == process_id).first()
        if not process:
            return
        process.status = status
        process.completed_at = datetime.now()
        if process.started_at:
            process.duration = (process.completed_at - process.started_at).total_seconds()
        if message:
            process.message = message
        if error:
            process.error_message = error
        if progress is not None:
            process.progress = progress
        elif status == TaskStatus.COMPLETED:
            process.progress = 100
        session.commit()
        logger.info(f'[UnifiedTask] 任务完成: {process.name} (status={status})')
    finally:
        session.close()


def get_running(task_types: list = None) -> list:
    """查询运行中任务（可按 task_type 过滤）。"""
    session = get_db()
    try:
        q = session.query(TaskProcess).filter(TaskProcess.status == TaskStatus.RUNNING)
        if task_types:
            q = q.filter(TaskProcess.task_type.in_(task_types))
        return q.order_by(TaskProcess.started_at.desc()).all()
    finally:
        session.close()


def get_by_id(process_id: int):
    """按 ID 获取任务进程对象（未找到返回 None）。"""
    session = get_db()
    try:
        return session.query(TaskProcess).filter(TaskProcess.id == process_id).first()
    finally:
        session.close()
