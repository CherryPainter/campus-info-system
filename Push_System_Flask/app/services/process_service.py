"""
进程写入业务服务

收敛原 app.api.process_routes 中以普通函数形式暴露、却被 service / 模块 / 调度层
反向调用的进程写入入口：

- create_task_process
- update_task_progress
- complete_task_process

这三个函数只是对 unified_task_service (uts) 的薄封装，属于业务层职责，不应停留在
api 层，否则会导致下层（service / modules / tasks）反向依赖 api 层，形成分层倒置。

依赖方向：
    api (process_routes) -> services (process_service) -> unified_task_service (uts)
    service / modules / tasks -> services (process_service)   （不再指向 api）
"""

from app.core.task_state import TaskStatus
from app.services import unified_task_service as uts


def create_task_process(
    name: str, task_type: str, total_items: int = 0, created_by: str = "system"
) -> int:
    """
    创建任务进程记录（委托 UnifiedTaskService，统一任务写入入口）

    Args:
        name: 任务名称
        task_type: 任务类型
        total_items: 总项目数
        created_by: 创建人

    Returns:
        int: 创建的进程ID
    """
    return uts.create_process(name, task_type, total_items=total_items, created_by=created_by)


def update_task_progress(process_id: int, processed: int, total: int = None, message: str = None):
    """
    更新任务进度（委托 UnifiedTaskService）
    """
    uts.update_progress(process_id, processed, total=total, message=message)


def complete_task_process(
    process_id: int, status: str = TaskStatus.COMPLETED, message: str = None, error: str = None
):
    """
    完成任务进程（委托 UnifiedTaskService）

    Args:
        process_id: 进程ID
        status: 完成状态 (completed/failed)
        message: 状态信息
        error: 错误信息
    """
    uts.complete_process(process_id, status=status, message=message, error=error)
