#!/usr/bin/env python3
"""推送任务服务"""

import hashlib
import threading
from datetime import datetime

from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)


class TaskService:
    """推送任务管理"""

    def __init__(self):
        self._tasks = {}
        self._processed = {}
        self._retry_queue = []
        self._lock = threading.Lock()
        self._delivered = set()  # 已推送记录：(rule_id, schedule_id, date_str)
        self._cleanup_timer = None

    def init_app(self, app):
        self._app = app
        # 重启恢复：将上轮被中断的任务（processing/retrying）重置为 pending，避免永久卡死
        try:
            self._recover_pending()
        except Exception as e:
            logger.warning(f"[落库] 启动时任务恢复失败: {e}")
        self._start_cleanup_timer()
        logger.info("推送任务服务初始化完成")

    def _start_cleanup_timer(self):
        """启动清理定时器，每天清理一次过期的已推送记录"""
        import threading

        # 每小时检查一次，清理昨天及以前的记录
        self._cleanup_timer = threading.Timer(3600, self._cleanup_delivered)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _cleanup_delivered(self):
        """清理过期的已推送记录和已处理任务"""
        with self._lock:
            today = datetime.now().strftime("%Y-%m-%d")
            # 只保留今天的记录
            self._delivered = {(rid, sid, d) for rid, sid, d in self._delivered if d == today}
            # 清理 _processed：保留最近 500 条
            if len(self._processed) > 500:
                cutoff = len(self._processed) - 500
                # 按更新时间排序，移除最旧的
                sorted_items = sorted(
                    self._processed.items(),
                    key=lambda x: x[1].get("updated_at", x[1].get("created_at", datetime.min)),
                )
                for tid, _ in sorted_items[:cutoff]:
                    del self._processed[tid]
                logger.debug(f"清理了 {cutoff} 条旧已处理任务记录")
            logger.debug(f"清理了已推送记录，保留 {len(self._delivered)} 条今日记录")
        # 继续下一次定时任务
        self._start_cleanup_timer()

    def _generate_id(self, task_data):
        """生成幂等任务 ID（精确到分钟级别）"""
        trigger_time = task_data.get("trigger_time", datetime.now())
        # 只使用日期和小时分钟，不使用秒，避免同一分钟内生成不同 ID
        time_key = trigger_time.strftime("%Y-%m-%d_%H:%M")
        key = f"{task_data.get('rule_id', '')}_{task_data.get('schedule_id', '')}_{time_key}"
        return hashlib.md5(key.encode()).hexdigest()

    def _get_delivered_key(self, task_data):
        """获取去重用的 key（精确到天）"""
        trigger_time = task_data.get("trigger_time", datetime.now())
        date_str = trigger_time.strftime("%Y-%m-%d")
        return (task_data.get("rule_id", ""), task_data.get("schedule_id", ""), date_str)

    def create_task(self, task_data):
        """创建推送任务（幂等 + 每日去重）"""
        # 检查是否已在今日推送过
        delivered_key = self._get_delivered_key(task_data)

        task_id = self._generate_id(task_data)
        with self._lock:
            # 1. 检查任务是否已存在
            if task_id in self._tasks or task_id in self._processed:
                logger.debug(f"任务已存在: {task_id}")
                return None

            # 2. 检查今日是否已推送过同一规则的同一课程
            if delivered_key in self._delivered:
                logger.debug(f"今日已推送过: {delivered_key}")
                return None

            task = {
                "task_id": task_id,
                "status": "pending",
                "priority": self._get_priority(task_data),
                "retry_count": 0,
                "max_retries": self._get_max_retries(),
                "created_at": datetime.now(),
                **task_data,
            }
            self._tasks[task_id] = task
            # 标记为今日已推送
            self._delivered.add(delivered_key)
            logger.info(f'创建推送任务: {task_id} ({task["task_type"]})')
            # 落库持久化（避免重启丢失 pending 任务）
            self._persist_create(task_id, task_data)
            return task_id

    def create_tasks(self, task_list):
        """批量创建任务"""
        return [tid for tid in (self.create_task(t) for t in task_list) if tid]

    def _get_priority(self, task_data):
        """获取任务优先级"""
        priority_map = {
            ("course_reminder", "before_class"): 1,
            ("course_reminder", "before_end_class"): 2,
            ("schedule_summary", "daily"): 3,
            ("course_reminder", "after_class"): 4,
            ("schedule_summary", "weekly"): 5,
        }
        return priority_map.get((task_data.get("task_type"), task_data.get("sub_type")), 3)

    def _get_max_retries(self):
        """读取「推送失败重试次数」配置（push.retry_count），失败回退 3"""
        try:
            from app.services.config_service import get_config_service

            val = get_config_service().get("push", "retry_count", 3)
            return int(val) if val is not None else 3
        except Exception:
            return 3

    def get_pending_tasks(self, limit=100):
        """获取待处理任务（优先从数据库读取，保证重启后可恢复 pending 任务）"""
        try:
            import json

            from app.core.database import get_db
            from app.model.push_task import PushTask

            session = get_db()
            try:
                rows = (
                    session.query(PushTask)
                    .filter(PushTask.status == "pending")
                    .order_by(PushTask.created_at.asc())
                    .limit(limit)
                    .all()
                )
                tasks = []
                for r in rows:
                    try:
                        data = json.loads(r.data) if r.data else {}
                    except Exception:
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    data["task_id"] = r.task_id
                    data["status"] = r.status
                    data["retry_count"] = r.retry_count or 0
                    tasks.append(data)
                return tasks
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"[落库] 读取待处理任务失败，回退内存队列: {e}")
            with self._lock:
                pending = [t for t in self._tasks.values() if t["status"] == "pending"]
                pending.sort(key=lambda x: x["priority"])
                return pending[:limit]

    def update_status(self, task_id, status, result=None):
        """更新任务状态（同时落库，保证重启后可恢复/清理）

        注意：retrying 在内存侧会转换为 pending（未超上限）或 failed（超上限），
        落库必须使用「最终状态」，否则 DB 会卡在 retrying 而再也不被 get_pending_tasks 拉取。
        """
        final_status = status
        retry_count = None
        with self._lock:
            task = self._tasks.get(task_id) or self._processed.get(task_id)
            if not task:
                # 任务不在内存（可能从 DB 恢复，或进程重启后由 delivery_service 直接处理）。
                # 仍尽力落库，保证执行历史一致。
                logger.debug(f"任务 {task_id} 不在内存中，仅落库更新状态: {status}")
            else:
                task["status"] = status
                task["updated_at"] = datetime.now()
                if result:
                    task["result"] = result
                if status in ("success", "failed"):
                    self._tasks.pop(task_id, None)
                    self._processed[task_id] = task
                elif status == "retrying":
                    task["retry_count"] += 1
                    retry_count = task["retry_count"]
                    if task["retry_count"] <= task["max_retries"]:
                        # 重试：回到 pending，等待下次调度
                        final_status = "pending"
                    else:
                        final_status = "failed"
                        self._tasks.pop(task_id, None)
                        self._processed[task_id] = task
        # 落库（使用最终状态）
        self._persist_update(task_id, final_status, retry_count=retry_count)
        return task is not None

    def get_statistics(self):
        """获取任务统计"""
        with self._lock:
            all_tasks = list(self._tasks.values()) + list(self._processed.values())
            counts = {}
            for t in all_tasks:
                counts[t["status"]] = counts.get(t["status"], 0) + 1
            return {
                "pending": counts.get("pending", 0),
                "processing": counts.get("processing", 0),
                "success": counts.get("success", 0),
                "failed": counts.get("failed", 0),
                "total": len(all_tasks),
            }

    # ===================== 落库持久化（push_task_queue） =====================
    def _persist_create(self, task_id, task_data):
        """将新任务落库（push_task_queue），作为内存队列的持久化备份。

        幂等：若 task_id 已存在则跳过，避免重启后规则引擎重发导致重复写入。
        """
        try:
            import json

            from app.core.database import get_db
            from app.model.push_task import PushTask

            session = get_db()
            try:
                exists = session.query(PushTask).filter(PushTask.task_id == task_id).first()
                if exists:
                    return
                row = PushTask(
                    task_id=task_id,
                    task_type=task_data.get("task_type"),
                    sub_type=task_data.get("sub_type"),
                    rule_id=str(task_data.get("rule_id"))
                    if task_data.get("rule_id") is not None
                    else None,
                    schedule_id=str(task_data.get("schedule_id"))
                    if task_data.get("schedule_id") is not None
                    else None,
                    data=json.dumps(task_data, ensure_ascii=False, default=str),
                    status="pending",
                    retry_count=0,
                )
                session.add(row)
                session.commit()
                logger.debug(f"[落库] 已持久化任务: {task_id}")
            except Exception as e:
                session.rollback()
                logger.warning(f"[落库] 持久化任务失败: {e}")
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"[落库] 持久化任务异常: {e}")

    def _persist_update(self, task_id, status, retry_count=None):
        """更新任务的落库状态（使用最终状态）"""
        try:
            from app.core.database import get_db
            from app.model.push_task import PushTask

            session = get_db()
            try:
                row = session.query(PushTask).filter(PushTask.task_id == task_id).first()
                if not row:
                    logger.debug(f"[落库] 更新跳过，任务不存在: {task_id}")
                    return
                row.status = status
                if retry_count is not None:
                    row.retry_count = retry_count
                session.commit()
                logger.debug(f"[落库] 更新任务状态: {task_id} -> {status}")
            except Exception as e:
                session.rollback()
                logger.warning(f"[落库] 更新任务状态失败: {e}")
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"[落库] 更新任务状态异常: {e}")

    def _recover_pending(self):
        """启动时恢复：
        1) 将上轮被中断的任务（processing/retrying）重置为 pending，避免永久卡死；
        2) 清理 7 天前的终态行（执行历史已在 task_processes 留存）。
        """
        try:
            from datetime import timedelta

            from app.core.database import get_db
            from app.model.push_task import PushTask

            session = get_db()
            try:
                interrupted = (
                    session.query(PushTask)
                    .filter(PushTask.status.in_(["processing", "retrying"]))
                    .all()
                )
                for r in interrupted:
                    r.status = "pending"
                if interrupted:
                    session.commit()
                    logger.info(f"[落库] 已恢复 {len(interrupted)} 个中断任务为 pending")
                # 清理旧终态行，避免 push_task_queue 无限增长
                cutoff = datetime.now() - timedelta(days=7)
                deleted = (
                    session.query(PushTask)
                    .filter(PushTask.status.in_(["success", "failed"]))
                    .filter(PushTask.created_at < cutoff)
                    .delete()
                )
                if deleted:
                    session.commit()
                    logger.info(f"[落库] 已清理 {deleted} 条过期终态任务记录")
            except Exception as e:
                session.rollback()
                logger.warning(f"[落库] 恢复/清理任务失败: {e}")
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"[落库] 恢复任务异常: {e}")

    def stop(self):
        """停止服务，清理定时器"""
        if self._cleanup_timer:
            self._cleanup_timer.cancel()


# 全局单例
task_service = TaskService()
