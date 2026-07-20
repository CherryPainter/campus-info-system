#!/usr/bin/env python3
"""定时任务调度（生命周期）。

执行逻辑（爬虫 / 推送规则 / 周课表 / 清理）见 app.tasks.executors；
共享可变状态见 app.tasks.scheduler_state。本模块只负责 APScheduler 的
启动 / 停止 / 重载 / 查询与触发器描述格式化，避免「生命周期 ↔ 执行」
相互 import 造成的循环依赖。
"""

import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logger import get_logger
from app.services import crawl_task_service as crawl_svc
from app.tasks import executors as _executors
from app.tasks import scheduler_state

logger = get_logger(__name__)

# 以下执行函数由 executors 模块定义，此处 re-export 以保持
# `from app.tasks.scheduler import run_spider, check_push_rules, ...` 等
# 既有引用可用（admin_routes / routes / config_routes / 测试均依赖）。
run_spider = _executors.run_spider
check_push_rules = _executors.check_push_rules
generate_weekly_course = _executors.generate_weekly_course
cleanup_expired_sessions = _executors.cleanup_expired_sessions
get_spider_status = _executors.get_spider_status
_send_weekly_image = _executors._send_weekly_image
_is_in_teaching_week = _executors._is_in_teaching_week
clean_old_processes = _executors.clean_old_processes


def start_scheduler(app):
    """启动定时任务调度器"""
    # ================================================================
    # 防止在 gunicorn worker 中重复启动调度器
    # 配合 gunicorn_config.py: preload_app=True + post_fork 设置环境变量
    # 正常情况下 preload_app 确保 create_app() 只在 master 执行一次；
    # 如果因故未启用 preload_app，此检查也能防止 scheduler 重复启动。
    # ================================================================
    if os.environ.get("GUNICORN_WORKER") == "1":
        logger.info(
            "[Worker %s] 跳过调度器启动（调度器在 master 进程中运行）",
            os.environ.get("GUNICORN_WORKER_ID", "?"),
        )
        return

    scheduler_state._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    # 从数据库读取课程爬虫配置
    from app.services.config_service import get_config_service

    config_svc = get_config_service()
    spider_enabled = config_svc.get("course", "spider_enabled", True)
    # 优先使用 cron 表达式（支持多时间点如 7:00 和 13:00）
    # 仅当显式设置 spider_schedule_mode=interval 且 spider_interval_hours>0 时才使用间隔模式
    spider_schedule_mode = config_svc.get("course", "spider_schedule_mode", "cron")
    spider_interval_hours = config_svc.get("course", "spider_interval_hours", None)

    if spider_enabled:
        # cron 模式为默认且推荐模式，interval 模式需显式配置
        use_interval = (
            spider_schedule_mode == "interval"
            and spider_interval_hours
            and int(spider_interval_hours) > 0
        )

        if use_interval:
            # 使用数据库配置的间隔小时数（interval 模式）
            interval_hours = int(spider_interval_hours)
            scheduler_state._scheduler.add_job(
                run_spider, "interval", hours=interval_hours, id="spider_job", replace_existing=True
            )
            # interval 模式：爬虫在每小时都可能触发，无法精确预测小时集合
            scheduler_state._spider_cron_hours = set()
            logger.info(f"爬虫已注册为间隔模式: 每 {interval_hours} 小时")
        else:
            # cron 表达式优先取数据库配置（即时修改生效），回退到 .env / 默认值
            cron_expr = config_svc.get(
                "course",
                "spider_cron_expression",
                app.config.get("CRON_EXPRESSION", "0 7,13 * * *"),
            )
            parts = cron_expr.split()
            if len(parts) == 5:
                scheduler_state._scheduler.add_job(
                    run_spider,
                    "cron",
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    id="spider_job",
                    replace_existing=True,
                )
                try:
                    scheduler_state._spider_cron_hours = {int(h) for h in parts[1].split(",")}
                except ValueError:
                    scheduler_state._spider_cron_hours = set()
                logger.info(
                    f"爬虫已注册为 cron 模式: {cron_expr}，触发小时: {sorted(scheduler_state._spider_cron_hours)}"
                )
            else:
                logger.warning(
                    f"爬虫 cron 表达式格式非法（需5段）: {cron_expr!r}，回退默认 0 7,13 * * *"
                )
                scheduler_state._scheduler.add_job(
                    run_spider,
                    "cron",
                    minute="0",
                    hour="7,13",
                    day="*",
                    month="*",
                    day_of_week="*",
                    id="spider_job",
                    replace_existing=True,
                )
                scheduler_state._spider_cron_hours = {7, 13}
    else:
        logger.info("[课程] spider_enabled=false，跳过爬虫定时任务注册")

    # 2. 每分钟检查推送规则
    scheduler_state._scheduler.add_job(
        check_push_rules, "interval", seconds=60, id="rule_check_job", replace_existing=True
    )

    # 2.5 每 30 秒扫描课程爬取预约任务（立即任务兜底 + 预约任务到期执行）
    scheduler_state._scheduler.add_job(
        crawl_svc.dispatch_scheduled_crawls,
        "interval",
        seconds=30,
        id="crawl_dispatch_job",
        replace_existing=True,
    )

    # 3. 每周一 0 时生成周课表
    scheduler_state._scheduler.add_job(
        generate_weekly_course,
        "cron",
        day_of_week="mon",
        hour=0,
        minute=0,
        id="weekly_course_job",
        replace_existing=True,
    )

    # 4. 进程记录自动清理已停用（用户 2026-07-20 决定保留历史进程记录）
    #    原 clean_old_processes 定时任务不再注册；如需手动清理可临时调用该函数。
    #    注意：clean_old_processes 函数体保留（已修正 datetime 导入），仅不再被定时触发。

    # 4.5 每天凌晨3点清理过期的服务端 Session 记录
    scheduler_state._scheduler.add_job(
        cleanup_expired_sessions,
        "cron",
        hour=3,
        minute=0,
        id="clean_sessions_job",
        replace_existing=True,
    )

    scheduler_state._scheduler.start()
    logger.info("定时任务调度器已启动")

    # 注册电量监控模块定时任务（Cookie 已配置时才注册）
    if app.config.get("ELECTRICITY_CRAWLER_COOKIE"):
        try:
            from app.modules.electricity.tasks import register_tasks as register_electricity_tasks

            register_electricity_tasks(scheduler_state._scheduler, app)
            logger.info("电量监控模块定时任务已注册")
        except Exception as exc:
            logger.warning(f"电量监控模块任务注册失败（可忽略，Cookie 可能暂未配置）: {exc}")
    else:
        logger.info("ELECTRICITY_CRAWLER_COOKIE 未配置，跳过电量监控定时任务注册")

    # 注册天气模块定时任务（凭据已配置时才注册）
    if app.config.get("QWEATHER_CREDENTIAL_ID") or app.config.get("QWEATHER_API_KEY"):
        try:
            from app.modules.weather.tasks import register_tasks as register_weather_tasks

            register_weather_tasks(scheduler_state._scheduler, app)
            logger.info("天气模块定时任务已注册")
        except Exception as exc:
            logger.warning(f"天气模块任务注册失败: {exc}")
    else:
        logger.info("QWEATHER_CREDENTIAL_ID 未配置，跳过天气模块定时任务注册")


def stop_scheduler():
    """停止调度器"""
    if scheduler_state._scheduler:
        scheduler_state._scheduler.shutdown(wait=False)
        scheduler_state._scheduler = None
        logger.info("定时任务调度器已停止")


def get_scheduler_jobs() -> list:
    """获取所有已注册的定时任务信息

    注意：在 gunicorn preload_app 多进程模式下，调度器只在 master 进程运行，
    worker 进程的 job.next_run_time 是 fork 时的快照，不会随调度器更新。
    因此当 next_run_time 已过期时，从 trigger 重新计算下次执行时间。
    """
    if not scheduler_state._scheduler:
        return []

    from datetime import datetime

    try:
        now = datetime.now(scheduler_state._scheduler.timezone)
    except Exception as e:
        logger.warning(f"[调度器] 获取当前时间失败: {e}，使用系统本地时间")
        now = datetime.now()

    jobs = []
    for job in scheduler_state._scheduler.get_jobs():
        try:
            trigger = job.trigger
            trigger_type = str(trigger).split("(")[0].split(".")[-1] if trigger else "unknown"

            # 解析触发器信息，生成易读的执行频率描述
            trigger_desc = _format_trigger_desc(trigger, trigger_type)

            # 下次执行时间
            next_run = None
            if job.next_run_time and trigger:
                try:
                    # 比较时先确保两者都有时区信息，避免 TypeError
                    if job.next_run_time.tzinfo is None or now.tzinfo is None:
                        # 任一无时区，直接用字符串比较避免 TypeError
                        next_run = job.next_run_time.isoformat()
                    elif job.next_run_time > now:
                        next_run = job.next_run_time.isoformat()
                    else:
                        # 已过期，从 trigger 重新计算
                        next_fire = trigger.get_next_fire_time(None, now)
                        next_run = next_fire.isoformat() if next_fire else None
                except Exception as e:
                    logger.warning(f"[调度器] 计算任务 {job.id} 下次执行时间失败: {e}")
                    next_run = job.next_run_time.isoformat() if job.next_run_time else None
            elif trigger:
                # next_run_time 为 None，尝试从 trigger 计算
                try:
                    next_fire = trigger.get_next_fire_time(None, now)
                    next_run = next_fire.isoformat() if next_fire else None
                except Exception as e:
                    logger.warning(f"[调度器] 计算任务 {job.id} 下次执行时间失败: {e}")

            jobs.append(
                {
                    "id": job.id,
                    "name": job.name or job.id,
                    "trigger_type": trigger_type,
                    "trigger_desc": trigger_desc,
                    "next_run": next_run,
                    "pending": getattr(job, "pending", False),
                }
            )
        except Exception as e:
            logger.warning(f'[调度器] 处理任务 {getattr(job, "id", "unknown")} 信息失败: {e}')
            continue

    return sorted(jobs, key=lambda x: x.get("next_run") or "9999")


def reload_scheduler(app):
    """重新加载所有定时任务（应用最新配置）"""
    logger.info("开始重新加载定时任务调度器...")

    # 先暂停调度器，避免 remove_all_jobs 和重新注册之间的竞态导致任务重复触发
    if scheduler_state._scheduler:
        scheduler_state._scheduler.pause()
        scheduler_state._scheduler.remove_all_jobs()
        logger.info("已清空旧任务")
    else:
        # 如果调度器未启动，重新启动
        start_scheduler(app)
        logger.info("调度器已重新启动")
        return

    # 重新注册基础任务
    # 1. 从数据库读取课程爬虫配置（cron 模式优先）
    from app.services.config_service import get_config_service

    config_svc = get_config_service()
    spider_enabled = config_svc.get("course", "spider_enabled", True)
    spider_schedule_mode = config_svc.get("course", "spider_schedule_mode", "cron")
    spider_interval_hours = config_svc.get("course", "spider_interval_hours", None)

    if spider_enabled:
        use_interval = (
            spider_schedule_mode == "interval"
            and spider_interval_hours
            and int(spider_interval_hours) > 0
        )

        if use_interval:
            interval_hours = int(spider_interval_hours)
            scheduler_state._scheduler.add_job(
                run_spider, "interval", hours=interval_hours, id="spider_job", replace_existing=True
            )
            scheduler_state._spider_cron_hours = set()
            logger.info(f"爬虫已重新注册为间隔模式: 每 {interval_hours} 小时")
        else:
            # cron 表达式优先取数据库配置（即时修改生效），回退到 .env / 默认值
            cron_expr = config_svc.get(
                "course",
                "spider_cron_expression",
                app.config.get("CRON_EXPRESSION", "0 7,13 * * *"),
            )
            parts = cron_expr.split()
            if len(parts) == 5:
                scheduler_state._scheduler.add_job(
                    run_spider,
                    "cron",
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    id="spider_job",
                    replace_existing=True,
                )
                try:
                    scheduler_state._spider_cron_hours = {int(h) for h in parts[1].split(",")}
                except ValueError:
                    scheduler_state._spider_cron_hours = set()
                logger.info(
                    f"爬虫已重新注册为 cron 模式: {cron_expr}，触发小时: {sorted(scheduler_state._spider_cron_hours)}"
                )
            else:
                logger.warning(
                    f"爬虫 cron 表达式格式非法（需5段）: {cron_expr!r}，回退默认 0 7,13 * * *"
                )
                scheduler_state._scheduler.add_job(
                    run_spider,
                    "cron",
                    minute="0",
                    hour="7,13",
                    day="*",
                    month="*",
                    day_of_week="*",
                    id="spider_job",
                    replace_existing=True,
                )
                scheduler_state._spider_cron_hours = {7, 13}
    else:
        logger.info("[课程] spider_enabled=false，跳过爬虫定时任务注册")

    # 2. 每分钟检查推送规则
    scheduler_state._scheduler.add_job(
        check_push_rules, "interval", seconds=60, id="rule_check_job", replace_existing=True
    )

    # 2.5 每 30 秒扫描课程爬取预约任务（立即任务兜底 + 预约任务到期执行）
    scheduler_state._scheduler.add_job(
        crawl_svc.dispatch_scheduled_crawls,
        "interval",
        seconds=30,
        id="crawl_dispatch_job",
        replace_existing=True,
    )

    # 3. 每周一 0 时生成周课表
    scheduler_state._scheduler.add_job(
        generate_weekly_course,
        "cron",
        day_of_week="mon",
        hour=0,
        minute=0,
        id="weekly_course_job",
        replace_existing=True,
    )

    # 3.5 每天凌晨3点清理过期的服务端 Session 记录
    scheduler_state._scheduler.add_job(
        cleanup_expired_sessions,
        "cron",
        hour=3,
        minute=0,
        id="clean_sessions_job",
        replace_existing=True,
    )

    # 重新注册电量监控模块任务（如果配置了）
    if app.config.get("ELECTRICITY_CRAWLER_COOKIE"):
        try:
            from app.modules.electricity.tasks import register_tasks as register_electricity_tasks

            register_electricity_tasks(scheduler_state._scheduler, app)
            logger.info("电量监控模块定时任务已重新注册")
        except Exception as exc:
            logger.warning(f"电量监控模块任务重新注册失败: {exc}")
    else:
        logger.info("ELECTRICITY_CRAWLER_COOKIE 未配置，跳过电量监控模块")

    # 重新注册天气模块任务（如果配置了）
    if app.config.get("QWEATHER_CREDENTIAL_ID") or app.config.get("QWEATHER_API_KEY"):
        try:
            from app.modules.weather.tasks import register_tasks as register_weather_tasks

            register_weather_tasks(scheduler_state._scheduler, app)
            logger.info("天气模块定时任务已重新注册")
        except Exception as exc:
            logger.warning(f"天气模块任务重新注册失败: {exc}")
    else:
        logger.info("QWEATHER_CREDENTIAL_ID 未配置，跳过天气模块")

    # 恢复调度器执行，清除暂停期间积累的积压 misfire
    scheduler_state._scheduler.resume()
    logger.info("定时任务调度器重新加载完成！")


def _format_trigger_desc(trigger, trigger_type: str) -> str:
    """
    格式化触发器为易读的中文描述

    Args:
        trigger: APScheduler 触发器对象
        trigger_type: 触发器类型 ('cron' 或 'interval')

    Returns:
        格式化后的中文描述字符串
    """
    if trigger_type == "cron":
        from apscheduler.triggers.cron import CronTrigger

        if isinstance(trigger, CronTrigger):
            return _format_cron_trigger(trigger)
    elif trigger_type == "interval":
        from apscheduler.triggers.interval import IntervalTrigger

        if isinstance(trigger, IntervalTrigger):
            return _format_interval_trigger(trigger)

    return str(trigger)


def _format_cron_trigger(trigger) -> str:
    """格式化 CronTrigger 为易读描述"""
    # 获取各字段值
    day_of_week = (
        trigger.fields[4].expressions if hasattr(trigger.fields[4], "expressions") else None
    )
    day = trigger.fields[2].expressions if hasattr(trigger.fields[2], "expressions") else None
    month = trigger.fields[3].expressions if hasattr(trigger.fields[3], "expressions") else None
    hour = trigger.fields[5].expressions if hasattr(trigger.fields[5], "expressions") else None
    minute = trigger.fields[6].expressions if hasattr(trigger.fields[6], "expressions") else None

    # 提取实际值
    def get_value(exprs):
        if not exprs:
            return None
        first = exprs[0]
        if hasattr(first, "first"):
            return first.first
        if hasattr(first, "value"):
            return first.value
        return str(first)

    dow_val = get_value(day_of_week)
    day_val = get_value(day)
    month_val = get_value(month)
    hour_val = get_value(hour)
    minute_val = get_value(minute)

    # 星期映射
    week_map = {
        "mon": "周一",
        "tue": "周二",
        "wed": "周三",
        "thu": "周四",
        "fri": "周五",
        "sat": "周六",
        "sun": "周日",
        "0": "周日",
        "1": "周一",
        "2": "周二",
        "3": "周三",
        "4": "周四",
        "5": "周五",
        "6": "周六",
        "7": "周日",
    }

    parts = []

    # 处理星期
    if dow_val is not None:
        dow_str = str(dow_val).lower()
        if dow_str in week_map:
            parts.append(f"每周{week_map[dow_str]}")
        else:
            # 可能是范围或列表
            parts.append(f"每周{dow_val}")

    # 处理日期（每月几号）
    if day_val is not None and month_val is None:
        parts.append(f"{day_val}日")

    # 处理月份
    if month_val is not None:
        parts.append(f"{month_val}月")

    # 处理时间
    if hour_val is not None:
        h = int(hour_val)
        m = int(minute_val) if minute_val is not None else 0
        parts.append(f"{h:02d}:{m:02d}")
    elif minute_val is not None:
        m = int(minute_val)
        parts.append(f"{m:02d}分")

    if parts:
        return " ".join(parts)

    # 默认返回简化格式
    return "定时任务"


def _format_interval_trigger(trigger) -> str:
    """格式化 IntervalTrigger 为易读描述"""
    interval = trigger.interval
    total_seconds = interval.total_seconds()

    if total_seconds < 60:
        return f"每 {int(total_seconds)} 秒"
    elif total_seconds < 3600:
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        if seconds > 0:
            return f"每 {minutes} 分 {seconds} 秒"
        return f"每 {minutes} 分钟"
    elif total_seconds < 86400:
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        if minutes > 0:
            return f"每 {hours} 小时 {minutes} 分"
        return f"每 {hours} 小时"
    else:
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        if hours > 0:
            return f"每 {days} 天 {hours} 小时"
        return f"每 {days} 天"
