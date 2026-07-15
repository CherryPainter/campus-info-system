#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务状态机与任务类型常量（后端统一任务模型核心）

本模块是「统一任务模型」的基石，消除 TaskProcess / ScheduledCrawlTask / PushTask
三处分散的硬编码状态字符串与任务类型字符串，所有任务状态的写入与读取都必须引用
本模块常量，避免拼写漂移与语义歧义。

状态词汇（与前端 src/hooks + src/api 约定保持一致）：
    pending          待执行（任务已创建，后台线程尚未启动）
    running          执行中
    completed        成功完成（且有数据）
    completed_empty  成功完成但未获取任何数据（如该学期尚未排课）
    failed           失败
    cancelled        已取消（手动停止）
"""

# ============ 任务状态 ============
class TaskStatus:
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    COMPLETED_EMPTY = 'completed_empty'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


# ============ 任务类型 ============
class TaskType:
    SPIDER = 'spider'                       # 课表爬虫（单实例，内存并发锁）
    COURSE_FULL_CRAWL = 'course_full_crawl' # 全量爬取
    COURSE = 'course'                       # 课表推送
    WEATHER = 'weather'                     # 天气
    ELECTRICITY = 'electricity'             # 电量
    CRAWL = 'crawl'                         # 预约爬取任务（scheduled_crawl_task）
    CUSTOM = 'custom'                       # 自定义推送
    SYSTEM = 'system'                       # 系统任务


# 终态集合：进入后状态不再变化
TERMINAL_STATUSES = frozenset({
    TaskStatus.COMPLETED,
    TaskStatus.COMPLETED_EMPTY,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
})


def is_terminal(status: str) -> bool:
    """判断状态是否为终态。"""
    return status in TERMINAL_STATUSES


def is_running(status: str) -> bool:
    """判断状态是否为执行中。"""
    return status == TaskStatus.RUNNING


def is_success(status: str) -> bool:
    """判断状态是否为成功（含「空成功」）。"""
    return status in (TaskStatus.COMPLETED, TaskStatus.COMPLETED_EMPTY)
