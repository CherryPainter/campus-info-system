#!/usr/bin/env python3
"""统一任务查询接口

提供系统级「按 ID 查任务」的单一入口，无论任务来自 task_processes（实际执行进程）
还是 scheduled_crawl_tasks（爬取预约计划），前端都通过同一接口、同一返回结构查询状态，
消除各页面各自对接不同端点的碎片化轮询。

端点：
- GET /api/tasks/<id>?type=<process|crawl>   查询任务状态（统一 {status,data,message} 结构）
"""

from flask import Blueprint, request

from app.core.api_response import api_error, api_success
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.scheduled_crawl_task import ScheduledCrawlTask
from app.model.task_process import TaskProcess
from app.utils.auth_middleware import jwt_required

logger = get_logger(__name__)

task_bp = Blueprint("task", __name__, url_prefix="/tasks")


@task_bp.route("/<int:task_id>", methods=["GET"])
@jwt_required
def get_task(task_id: int):
    """查询任务状态（统一入口）。

    Query 参数：
        type: 'process'（默认，查 task_processes）| 'crawl'（查 scheduled_crawl_tasks）
              缺省时按 process -> crawl 顺序自动探测。
    """
    task_type = request.args.get("type", "").strip()

    session = get_db()
    try:
        # 指定类型直接查对应表
        if task_type == "crawl":
            task = (
                session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
            )
            if not task:
                return api_error(message="爬取任务不存在", http_status=404)
            return api_success(data=task.to_dict(), source="crawl")

        # 默认 / process：先查 task_processes
        if task_type in ("", "process"):
            task = session.query(TaskProcess).filter(TaskProcess.id == task_id).first()
            if task:
                return api_success(data=task.to_dict(), source="process")
            if task_type == "process":
                return api_error(message="进程不存在", http_status=404)

        # 未指定 type 且 process 未命中：探测 scheduled_crawl_tasks
        task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
        if task:
            return api_success(data=task.to_dict(), source="crawl")

        return api_error(message="任务不存在", http_status=404)
    except Exception as e:
        logger.error(f"[统一任务查询] 查询失败: {e}")
        return api_error(message=str(e), http_status=500)
    finally:
        session.close()
