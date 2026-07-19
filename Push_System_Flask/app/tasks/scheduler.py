#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时任务调度"""
import subprocess
import os
import sys
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.logger import get_logger
from app.core.config import Config

# 使用统一日志系统
logger = get_logger(__name__)

from app.services.schedule_service import schedule_service
from app.services.rule_service import rule_service
from app.services.task_service import task_service
from app.services import crawl_task_service as crawl_svc
from app.core.task_state import TaskStatus, TaskType
from app.services.spider_runner import run_spider_process


_scheduler = None
_spider_running = False  # 爬虫并发执行锁

# 爬虫执行状态记录
_spider_status = {
    'last_run': None,        # 上次执行时间 (ISO 格式)
    'last_result': None,     # 上次执行结果: 'success' / 'failed' / 'running'
    'last_error': None,      # 上次错误信息
    'last_exit_code': None,  # 上次退出码
}

# 爬虫与每日课表推送的协调机制
_spider_success_dates = {}   # {date_str: True} - 爬虫成功执行的日期
_daily_push_pending = {}     # {date_str: True} - 因爬虫未完成而延迟的每日课表推送
_spider_cron_hours = set()   # 爬虫 cron 触发的小时集合（如 {7, 13}）


def _read_spider_log_tail(spider_dir, lines=10):
    """读取爬虫日志文件的最后几行，用于定位子进程失败原因"""
    import glob
    log_dir = os.path.join(spider_dir, 'output', 'logs')
    if not os.path.isdir(log_dir):
        return ''
    log_files = sorted(glob.glob(os.path.join(log_dir, 'course_spider_*.log')),
                       key=os.path.getmtime, reverse=True)
    if not log_files:
        return ''
    try:
        with open(log_files[0], 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        tail = ''.join(all_lines[-lines:]).strip()
        return tail if tail else ''
    except Exception:
        return ''


def start_scheduler(app):
    """启动定时任务调度器"""
    global _scheduler, _spider_cron_hours

    # ================================================================
    # 防止在 gunicorn worker 中重复启动调度器
    # 配合 gunicorn_config.py: preload_app=True + post_fork 设置环境变量
    # 正常情况下 preload_app 确保 create_app() 只在 master 执行一次；
    # 如果因故未启用 preload_app，此检查也能防止 scheduler 重复启动。
    # ================================================================
    if os.environ.get('GUNICORN_WORKER') == '1':
        logger.info('[Worker %s] 跳过调度器启动（调度器在 master 进程中运行）',
                    os.environ.get('GUNICORN_WORKER_ID', '?'))
        return

    _scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
    
    # 从数据库读取课程爬虫配置
    from app.services.config_service import get_config_service
    config_svc = get_config_service()
    spider_enabled = config_svc.get('course', 'spider_enabled', True)
    # 优先使用 cron 表达式（支持多时间点如 7:00 和 13:00）
    # 仅当显式设置 spider_schedule_mode=interval 且 spider_interval_hours>0 时才使用间隔模式
    spider_schedule_mode = config_svc.get('course', 'spider_schedule_mode', 'cron')
    spider_interval_hours = config_svc.get('course', 'spider_interval_hours', None)

    if spider_enabled:
        # cron 模式为默认且推荐模式，interval 模式需显式配置
        use_interval = (
            spider_schedule_mode == 'interval'
            and spider_interval_hours
            and int(spider_interval_hours) > 0
        )

        if use_interval:
            # 使用数据库配置的间隔小时数（interval 模式）
            interval_hours = int(spider_interval_hours)
            _scheduler.add_job(
                run_spider, 'interval',
                hours=interval_hours,
                id='spider_job', replace_existing=True
            )
            # interval 模式：爬虫在每小时都可能触发，无法精确预测小时集合
            _spider_cron_hours = set()
            logger.info(f'爬虫已注册为间隔模式: 每 {interval_hours} 小时')
        else:
            # cron 表达式优先取数据库配置（即时修改生效），回退到 .env / 默认值
            cron_expr = config_svc.get(
                'course', 'spider_cron_expression',
                app.config.get('CRON_EXPRESSION', '0 7,13 * * *')
            )
            parts = cron_expr.split()
            if len(parts) == 5:
                _scheduler.add_job(
                    run_spider, 'cron',
                    minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4],
                    id='spider_job', replace_existing=True
                )
                try:
                    _spider_cron_hours = set(int(h) for h in parts[1].split(','))
                except ValueError:
                    _spider_cron_hours = set()
                logger.info(f'爬虫已注册为 cron 模式: {cron_expr}，触发小时: {sorted(_spider_cron_hours)}')
            else:
                logger.warning(f'爬虫 cron 表达式格式非法（需5段）: {cron_expr!r}，回退默认 0 7,13 * * *')
                _scheduler.add_job(
                    run_spider, 'cron',
                    minute='0', hour='7,13', day='*', month='*', day_of_week='*',
                    id='spider_job', replace_existing=True
                )
                _spider_cron_hours = {7, 13}
    else:
        logger.info('[课程] spider_enabled=false，跳过爬虫定时任务注册')
    
    # 2. 每分钟检查推送规则
    _scheduler.add_job(
        check_push_rules, 'interval',
        seconds=60, id='rule_check_job', replace_existing=True
    )

    # 2.5 每 30 秒扫描课程爬取预约任务（立即任务兜底 + 预约任务到期执行）
    _scheduler.add_job(
        crawl_svc.dispatch_scheduled_crawls, 'interval',
        seconds=30, id='crawl_dispatch_job', replace_existing=True
    )
    
    # 3. 每周一 0 时生成周课表
    _scheduler.add_job(
        generate_weekly_course, 'cron',
        day_of_week='mon', hour=0, minute=0,
        id='weekly_course_job', replace_existing=True
    )
    
    # 4. 进程记录自动清理已停用（用户 2026-07-20 决定保留历史进程记录）
    #    原 clean_old_processes 定时任务不再注册；如需手动清理可临时调用该函数。
    #    注意：clean_old_processes 函数体保留（已修正 datetime 导入），仅不再被定时触发。

    # 4.5 每天凌晨3点清理过期的服务端 Session 记录
    _scheduler.add_job(
        cleanup_expired_sessions, 'cron',
        hour=3, minute=0,
        id='clean_sessions_job', replace_existing=True
    )

    _scheduler.start()
    logger.info('定时任务调度器已启动')

    # 注册电量监控模块定时任务（Cookie 已配置时才注册）
    if app.config.get('ELECTRICITY_CRAWLER_COOKIE'):
        try:
            from app.modules.electricity.tasks import register_tasks as register_electricity_tasks
            register_electricity_tasks(_scheduler, app)
            logger.info('电量监控模块定时任务已注册')
        except Exception as exc:
            logger.warning(f'电量监控模块任务注册失败（可忽略，Cookie 可能暂未配置）: {exc}')
    else:
        logger.info('ELECTRICITY_CRAWLER_COOKIE 未配置，跳过电量监控定时任务注册')

    # 注册天气模块定时任务（凭据已配置时才注册）
    if app.config.get('QWEATHER_CREDENTIAL_ID') or app.config.get('QWEATHER_API_KEY'):
        try:
            from app.modules.weather.tasks import register_tasks as register_weather_tasks
            register_weather_tasks(_scheduler, app)
            logger.info('天气模块定时任务已注册')
        except Exception as exc:
            logger.warning(f'天气模块任务注册失败: {exc}')
    else:
        logger.info('QWEATHER_CREDENTIAL_ID 未配置，跳过天气模块定时任务注册')


def stop_scheduler():
    """停止调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info('定时任务调度器已停止')


def get_scheduler_jobs() -> list:
    """获取所有已注册的定时任务信息

    注意：在 gunicorn preload_app 多进程模式下，调度器只在 master 进程运行，
    worker 进程的 job.next_run_time 是 fork 时的快照，不会随调度器更新。
    因此当 next_run_time 已过期时，从 trigger 重新计算下次执行时间。
    """
    global _scheduler
    if not _scheduler:
        return []

    from datetime import datetime
    try:
        now = datetime.now(_scheduler.timezone)
    except Exception as e:
        logger.warning(f'[调度器] 获取当前时间失败: {e}，使用系统本地时间')
        now = datetime.now()

    jobs = []
    for job in _scheduler.get_jobs():
        try:
            trigger = job.trigger
            trigger_type = str(trigger).split('(')[0].split('.')[-1] if trigger else 'unknown'

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
                    logger.warning(f'[调度器] 计算任务 {job.id} 下次执行时间失败: {e}')
                    next_run = job.next_run_time.isoformat() if job.next_run_time else None
            elif trigger:
                # next_run_time 为 None，尝试从 trigger 计算
                try:
                    next_fire = trigger.get_next_fire_time(None, now)
                    next_run = next_fire.isoformat() if next_fire else None
                except Exception as e:
                    logger.warning(f'[调度器] 计算任务 {job.id} 下次执行时间失败: {e}')

            jobs.append({
                'id': job.id,
                'name': job.name or job.id,
                'trigger_type': trigger_type,
                'trigger_desc': trigger_desc,
                'next_run': next_run,
                'pending': getattr(job, 'pending', False),
            })
        except Exception as e:
            logger.warning(f'[调度器] 处理任务 {getattr(job, "id", "unknown")} 信息失败: {e}')
            continue

    return sorted(jobs, key=lambda x: x.get('next_run') or '9999')


def reload_scheduler(app):
    """重新加载所有定时任务（应用最新配置）"""
    global _scheduler
    
    logger.info('开始重新加载定时任务调度器...')
    
    # 先暂停调度器，避免 remove_all_jobs 和重新注册之间的竞态导致任务重复触发
    if _scheduler:
        _scheduler.pause()
        _scheduler.remove_all_jobs()
        logger.info('已清空旧任务')
    else:
        # 如果调度器未启动，重新启动
        start_scheduler(app)
        logger.info('调度器已重新启动')
        return
    
    # 重新注册基础任务
    # 1. 从数据库读取课程爬虫配置（cron 模式优先）
    from app.services.config_service import get_config_service
    config_svc = get_config_service()
    spider_enabled = config_svc.get('course', 'spider_enabled', True)
    spider_schedule_mode = config_svc.get('course', 'spider_schedule_mode', 'cron')
    spider_interval_hours = config_svc.get('course', 'spider_interval_hours', None)

    global _spider_cron_hours
    if spider_enabled:
        use_interval = (
            spider_schedule_mode == 'interval'
            and spider_interval_hours
            and int(spider_interval_hours) > 0
        )

        if use_interval:
            interval_hours = int(spider_interval_hours)
            _scheduler.add_job(
                run_spider, 'interval',
                hours=interval_hours,
                id='spider_job', replace_existing=True
            )
            _spider_cron_hours = set()
            logger.info(f'爬虫已重新注册为间隔模式: 每 {interval_hours} 小时')
        else:
            # cron 表达式优先取数据库配置（即时修改生效），回退到 .env / 默认值
            cron_expr = config_svc.get(
                'course', 'spider_cron_expression',
                app.config.get('CRON_EXPRESSION', '0 7,13 * * *')
            )
            parts = cron_expr.split()
            if len(parts) == 5:
                _scheduler.add_job(
                    run_spider, 'cron',
                    minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4],
                    id='spider_job', replace_existing=True
                )
                try:
                    _spider_cron_hours = set(int(h) for h in parts[1].split(','))
                except ValueError:
                    _spider_cron_hours = set()
                logger.info(f'爬虫已重新注册为 cron 模式: {cron_expr}，触发小时: {sorted(_spider_cron_hours)}')
            else:
                logger.warning(f'爬虫 cron 表达式格式非法（需5段）: {cron_expr!r}，回退默认 0 7,13 * * *')
                _scheduler.add_job(
                    run_spider, 'cron',
                    minute='0', hour='7,13', day='*', month='*', day_of_week='*',
                    id='spider_job', replace_existing=True
                )
                _spider_cron_hours = {7, 13}
    else:
        logger.info('[课程] spider_enabled=false，跳过爬虫定时任务注册')
    
    # 2. 每分钟检查推送规则
    _scheduler.add_job(
        check_push_rules, 'interval',
        seconds=60, id='rule_check_job', replace_existing=True
    )

    # 2.5 每 30 秒扫描课程爬取预约任务（立即任务兜底 + 预约任务到期执行）
    _scheduler.add_job(
        crawl_svc.dispatch_scheduled_crawls, 'interval',
        seconds=30, id='crawl_dispatch_job', replace_existing=True
    )
    
    # 3. 每周一 0 时生成周课表
    _scheduler.add_job(
        generate_weekly_course, 'cron',
        day_of_week='mon', hour=0, minute=0,
        id='weekly_course_job', replace_existing=True
    )

    # 3.5 每天凌晨3点清理过期的服务端 Session 记录
    _scheduler.add_job(
        cleanup_expired_sessions, 'cron',
        hour=3, minute=0,
        id='clean_sessions_job', replace_existing=True
    )

    # 重新注册电量监控模块任务（如果配置了）
    if app.config.get('ELECTRICITY_CRAWLER_COOKIE'):
        try:
            from app.modules.electricity.tasks import register_tasks as register_electricity_tasks
            register_electricity_tasks(_scheduler, app)
            logger.info('电量监控模块定时任务已重新注册')
        except Exception as exc:
            logger.warning(f'电量监控模块任务重新注册失败: {exc}')
    else:
        logger.info('ELECTRICITY_CRAWLER_COOKIE 未配置，跳过电量监控模块')
    
    # 重新注册天气模块任务（如果配置了）
    if app.config.get('QWEATHER_CREDENTIAL_ID') or app.config.get('QWEATHER_API_KEY'):
        try:
            from app.modules.weather.tasks import register_tasks as register_weather_tasks
            register_weather_tasks(_scheduler, app)
            logger.info('天气模块定时任务已重新注册')
        except Exception as exc:
            logger.warning(f'天气模块任务重新注册失败: {exc}')
    else:
        logger.info('QWEATHER_CREDENTIAL_ID 未配置，跳过天气模块')
    
    # 恢复调度器执行，清除暂停期间积累的积压 misfire
    _scheduler.resume()
    logger.info('定时任务调度器重新加载完成！')


def _format_trigger_desc(trigger, trigger_type: str) -> str:
    """
    格式化触发器为易读的中文描述

    Args:
        trigger: APScheduler 触发器对象
        trigger_type: 触发器类型 ('cron' 或 'interval')

    Returns:
        格式化后的中文描述字符串
    """
    if trigger_type == 'cron':
        from apscheduler.triggers.cron import CronTrigger
        if isinstance(trigger, CronTrigger):
            return _format_cron_trigger(trigger)
    elif trigger_type == 'interval':
        from apscheduler.triggers.interval import IntervalTrigger
        if isinstance(trigger, IntervalTrigger):
            return _format_interval_trigger(trigger)

    return str(trigger)


def _format_cron_trigger(trigger) -> str:
    """格式化 CronTrigger 为易读描述"""
    # 获取各字段值
    day_of_week = trigger.fields[4].expressions if hasattr(trigger.fields[4], 'expressions') else None
    day = trigger.fields[2].expressions if hasattr(trigger.fields[2], 'expressions') else None
    month = trigger.fields[3].expressions if hasattr(trigger.fields[3], 'expressions') else None
    hour = trigger.fields[5].expressions if hasattr(trigger.fields[5], 'expressions') else None
    minute = trigger.fields[6].expressions if hasattr(trigger.fields[6], 'expressions') else None

    # 提取实际值
    def get_value(exprs):
        if not exprs:
            return None
        first = exprs[0]
        if hasattr(first, 'first'):
            return first.first
        if hasattr(first, 'value'):
            return first.value
        return str(first)

    dow_val = get_value(day_of_week)
    day_val = get_value(day)
    month_val = get_value(month)
    hour_val = get_value(hour)
    minute_val = get_value(minute)

    # 星期映射
    week_map = {
        'mon': '周一', 'tue': '周二', 'wed': '周三', 'thu': '周四',
        'fri': '周五', 'sat': '周六', 'sun': '周日',
        '0': '周日', '1': '周一', '2': '周二', '3': '周三',
        '4': '周四', '5': '周五', '6': '周六', '7': '周日'
    }

    parts = []

    # 处理星期
    if dow_val is not None:
        dow_str = str(dow_val).lower()
        if dow_str in week_map:
            parts.append(f'每周{week_map[dow_str]}')
        else:
            # 可能是范围或列表
            parts.append(f'每周{dow_val}')

    # 处理日期（每月几号）
    if day_val is not None and month_val is None:
        parts.append(f'{day_val}日')

    # 处理月份
    if month_val is not None:
        parts.append(f'{month_val}月')

    # 处理时间
    if hour_val is not None:
        h = int(hour_val)
        m = int(minute_val) if minute_val is not None else 0
        parts.append(f'{h:02d}:{m:02d}')
    elif minute_val is not None:
        m = int(minute_val)
        parts.append(f'{m:02d}分')

    if parts:
        return ' '.join(parts)

    # 默认返回简化格式
    return f'定时任务'


def _format_interval_trigger(trigger) -> str:
    """格式化 IntervalTrigger 为易读描述"""
    interval = trigger.interval
    total_seconds = interval.total_seconds()

    if total_seconds < 60:
        return f'每 {int(total_seconds)} 秒'
    elif total_seconds < 3600:
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        if seconds > 0:
            return f'每 {minutes} 分 {seconds} 秒'
        return f'每 {minutes} 分钟'
    elif total_seconds < 86400:
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        if minutes > 0:
            return f'每 {hours} 小时 {minutes} 分'
        return f'每 {hours} 小时'
    else:
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        if hours > 0:
            return f'每 {days} 天 {hours} 小时'
        return f'每 {days} 天'


def run_spider(trigger_source='cron'):
    """执行爬虫（带并发保护和三次重试）
    
    Args:
        trigger_source: 触发来源，'cron' 表示定时触发，'manual' 表示手动触发
    
    Returns:
        bool: True 表示爬虫执行成功，False 表示失败或被跳过
    """
    global _spider_status, _spider_running
    
    if _spider_running:
        logger.warning("爬虫正在执行中，跳过本次触发")
        return False

    # 假期模式：静默期间无需同步课表（提前返回，不触发失败告警）
    from app.services.holiday_service import holiday_service
    if holiday_service.is_active()[0]:
        logger.info('[爬虫] 假期模式静默中，跳过课表爬取')
        return False
    
    source_label = '定时' if trigger_source == 'cron' else '手动'
    _spider_running = True
    logger.info(f"{source_label}触发爬虫执行...")
    _spider_status['last_run'] = __import__('datetime').datetime.now().isoformat()
    _spider_status['last_result'] = 'running'
    _spider_status['last_error'] = None
    
    # 创建进程记录
    from app.api.process_routes import create_task_process, complete_task_process
    spider_pid = create_task_process(f'课程表同步爬取（{source_label}）', 'spider', total_items=1)
    
    # 使用配置中的基础路径计算爬虫目录
    spider_dir = os.path.join(Config.BASE_DIR, 'app', 'cqie-course-timetable')
    script = os.path.join(spider_dir, 'main.py')
    
    if not os.path.exists(script):
        logger.error(f'爬虫脚本不存在: {script}')
        _spider_running = False
        return False
    
    # 最多重试 3 次（Python 解析与 env 注入由 SpiderRunner 统一处理）
    max_retries = 3
    success = False
    last_error = None
    last_exit_code = None
    
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.info(f'[尝试 {attempt}/{max_retries}] 爬虫重试中...')
        
        try:
            logger.info(f'开始执行爬虫 (尝试 {attempt}/{max_retries})...')
            result = run_spider_process(timeout=600)
            
            logger.info(f'爬虫执行完成，返回码: {result.returncode}')
            
            if result.returncode == 0:
                logger.info(f'爬虫执行成功 (尝试 {attempt}/{max_retries})')
                if result.stdout:
                    logger.debug(f'爬虫输出: {result.stdout[:500]}')
                success = True
                break
            else:
                # 优先取 stderr，若为空则尝试读取爬虫日志文件
                error_msg = result.stderr[:500] if result.stderr.strip() else ''
                if not error_msg:
                    error_msg = _read_spider_log_tail(spider_dir)
                if not error_msg:
                    error_msg = f'exit code {result.returncode} (无错误输出)'
                logger.warning(f'爬虫执行失败 (尝试 {attempt}/{max_retries}, code={result.returncode}): {error_msg}')
                last_error = error_msg
                last_exit_code = result.returncode
                
                # 不是最后一次尝试时，等一会儿再重试
                if attempt < max_retries:
                    import time
                    wait_seconds = 30  # 30秒后重试
                    logger.info(f'等待 {wait_seconds} 秒后重试...')
                    time.sleep(wait_seconds)
                    
        except subprocess.TimeoutExpired:
            logger.warning(f'爬虫执行超时 (尝试 {attempt}/{max_retries})')
            last_error = 'Timeout (600s)'
            last_exit_code = -1
            
            if attempt < max_retries:
                import time
                wait_seconds = 30
                logger.info(f'等待 {wait_seconds} 秒后重试...')
                time.sleep(wait_seconds)
                
        except Exception as e:
            logger.warning(f'爬虫执行异常 (尝试 {attempt}/{max_retries}): {e}')
            last_error = str(e)
            last_exit_code = -2
            
            if attempt < max_retries:
                import time
                wait_seconds = 30
                logger.info(f'等待 {wait_seconds} 秒后重试...')
                time.sleep(wait_seconds)
    
    try:
        if success:
            _spider_status['last_result'] = 'success'
            # 标记今日爬虫已成功执行
            today_str = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
            _spider_success_dates[today_str] = True
            _cleanup_stale_dates()
            # 检查是否有被延迟的每日课表推送
            _try_deferred_daily_push()
            # v6.11.1：每日爬虫同步将「当前周」数据入库（来源标记 daily）。
            # 用每日爬取的当前周正确数据 upsert 修正全量爬取的当前周错误，实现每日校验。
            # 空结果不会覆盖（save_to_database 空结果护栏 return (0, 0) 不入库）。
            # create_task_process=False：每日爬虫已有自己的 'spider' 进程记录，
            # 避免再生成冗余的 'course_full_crawl' 进程记录污染执行历史。
            try:
                import sys as _sys
                if spider_dir not in _sys.path:
                    _sys.path.insert(0, spider_dir)
                import importlib as _il
                _pipeline_mod = _il.import_module('pipeline')
                _daily_processed = os.path.join(spider_dir, 'output', 'course-data', 'processed')
                _created, _updated = _pipeline_mod.save_to_database(
                    _daily_processed, logger, data_source='daily', create_task_process=False
                )
                logger.info(f'[每日爬虫] 当前周数据已入库 (data_source=daily): 新增 {_created} 条 / 更新 {_updated} 条')
            except Exception as _e:
                logger.error(f'[每日爬虫] 当前周数据入库失败（不影响图片生成与推送）: {_e}')
            complete_task_process(spider_pid, TaskStatus.COMPLETED, '爬虫执行成功')
            return True
        else:
            logger.error(f'爬虫所有 {max_retries} 次尝试均失败')
            _spider_status['last_result'] = 'failed'
            _spider_status['last_error'] = last_error
            _spider_status['last_exit_code'] = last_exit_code
            _notify_spider_failure(last_exit_code, last_error)
            complete_task_process(spider_pid, TaskStatus.FAILED, error=last_error)
            return False
    finally:
        _spider_running = False


def _notify_spider_failure(exit_code, error_msg):
    """爬虫失败通知"""
    from app.services.adapter_service import adapter_service
    status_webhook = None
    
    # 尝试获取状态 webhook
    import importlib
    try:
        from flask import current_app
        status_webhook = current_app.config.get('WECOM_STATUS_WEBHOOK')
    except Exception:
        pass
    
    if not status_webhook:
        return
    
    try:
        import requests
        message = {
            'msgtype': 'markdown',
            'markdown': {
                'content': f'**爬虫执行异常通知**\n\n时间：{__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n状态：失败\n\n错误码：{exit_code}\n\n错误信息：{error_msg}'
            }
        }
        requests.post(status_webhook, json=message, timeout=10)
    except Exception as e:
        logger.error(f'发送失败通知异常: {e}')


def get_spider_status():
    """获取「日常课表爬虫」（run_spider / 同步课表）执行状态。

    语义边界（勿再回退）：本函数返回的 running **只代表日常课表爬虫**，
    绝不能把「全量/指定学期爬取」(ScheduledCrawlTask) 算进 running。
    原因：前端任务管理页「课表爬虫」卡片读 spider.running，「全量爬取」卡片读
    spider.running_tasks.course_full_crawl（由 admin 路由 spider_status() 单独填充）。
    若把 ScheduledCrawlTask 计入 running，全量爬取时会错误点亮「课表爬虫」卡片。

    自愈策略：running 以数据库中的 SPIDER 类型进程实际状态为准（DB 驱动），
    叠加内存并发锁 _spider_running（覆盖进程行提交前的极短窗口）；进程结束后
    用最近一次 spider 进程终态补充 last_result / last_error，避免重启后误判。
    """
    status = dict(_spider_status)
    status['running'] = _spider_running
    try:
        from app.core.database import get_db
        from app.model.task_process import TaskProcess
        session = get_db()
        try:
            spider_running = session.query(TaskProcess).filter(
                TaskProcess.task_type == TaskType.SPIDER,
                TaskProcess.status == TaskStatus.RUNNING
            ).first() is not None
            # DB 驱动：以实际 SPIDER 进程状态为准，叠加内存锁覆盖提交前窗口
            status['running'] = spider_running or _spider_running
            if not status['running']:
                # 无运行中日常爬虫：用最近一次 spider 进程终态补充 last_result
                latest = session.query(TaskProcess) \
                    .filter(TaskProcess.task_type == TaskType.SPIDER) \
                    .order_by(TaskProcess.started_at.desc()) \
                    .first()
                if latest and latest.status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                                                 TaskStatus.COMPLETED_EMPTY, TaskStatus.CANCELLED):
                    status['last_result'] = ('success' if latest.status == TaskStatus.COMPLETED
                                              else latest.status)
                    status['last_error'] = latest.error_message
        finally:
            session.close()
    except Exception:
        # 兜底查询失败不应影响状态返回
        pass
    return status


def _cleanup_stale_dates():
    """清理过期的日期追踪记录（仅保留最近2天）"""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    for d in list(_spider_success_dates.keys()):
        if d < cutoff:
            del _spider_success_dates[d]
    for d in list(_daily_push_pending.keys()):
        if d < cutoff:
            del _daily_push_pending[d]


def _try_deferred_daily_push():
    """爬虫成功后，检查并补发被延迟的每日课表推送

    当每日课表推送时间（如07:00）与爬虫 cron 时间重合时，
    check_push_rules() 会跳过推送并标记 _daily_push_pending。
    爬虫成功后调用此函数，强制刷新数据并补发。
    """
    from datetime import datetime
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')

    if today_str not in _daily_push_pending:
        return

    # 清除 pending 标记
    del _daily_push_pending[today_str]

    try:
        # 强制刷新课表数据（爬虫刚产出新数据）
        schedule_service.load_schedules()
        schedules = schedule_service.get_schedules()

        # 使用强制模式补发每日课表推送
        tasks = rule_service.check_conditions_force(now, schedules, rule_type='daily_schedule')

        if tasks:
            created = task_service.create_tasks(tasks)
            if created:
                logger.info(f'[延迟推送] 爬虫完成后补发每日课表，创建 {len(created)} 个推送任务')
        else:
            logger.info('[延迟推送] 爬虫完成后检查每日课表，无匹配规则')
    except Exception as e:
        logger.error(f'[延迟推送] 补发每日课表异常: {e}')


def check_push_rules():
    """检查推送规则"""
    from datetime import datetime
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    # 假期模式：静默全体面向用户的课表推送（调试级日志，避免每分钟刷屏）
    from app.services.holiday_service import holiday_service
    if holiday_service.is_active()[0]:
        logger.debug('[推送规则] 假期模式静默中，跳过本次规则检查')
        return
    schedules = schedule_service.get_schedules()
    
    # 从未成功加载过数据时，跳过所有推送规则（避免在系统刚部署无数据时误触发）
    if not schedule_service.is_data_ready:
        logger.debug('课表数据未就绪，跳过推送规则检查')
        return
    
    # 数据已就绪但课表为空（如周末/假期），仍允许规则引擎判断（如 daily_no_class）
    tasks = rule_service.check_conditions(now, schedules)
    
    # 协调机制：如果每日课表推送时间与爬虫 cron 时间重合，
    # 且爬虫今日尚未成功执行，则延迟推送直到爬虫完成
    filtered = []
    for task in tasks:
        if task and task.get('rule_id') == 'daily_schedule':
            daily_time = task.get('trigger_condition', {}).get('daily_time', '')
            if daily_time:
                try:
                    push_hour = int(daily_time.split(':')[0])
                    if push_hour in _spider_cron_hours and today_str not in _spider_success_dates:
                        logger.info(
                            f'[每日课表] 推送时间 {daily_time} 与爬虫 cron 重合，'
                            f'爬虫今日尚未完成，延迟推送'
                        )
                        _daily_push_pending[today_str] = True
                        continue
                except (ValueError, IndexError):
                    pass
        filtered.append(task)
    
    if filtered:
        created = task_service.create_tasks(filtered)
        if created:
            logger.info(f'规则检查创建 {len(created)} 个推送任务')


def _is_in_teaching_week():
    """判断今天是否落在某个教学周内（course_weeks.start_date ~ end_date）。

    用于假期/暑假自动停发课表：不在任何教学周内即视为「这一周没课」，
    跳过周课表推送。基于真实日期范围，不依赖易错的 week_number 推算
    （_calculate_date 在假期会把 week_number=1 误算成本周日期）。

    异常时回退 True（继续推送），避免 course_weeks 数据缺失时静默漏推。
    """
    try:
        from datetime import date
        from app.core.database import get_db
        from app.model.course_week import CourseWeek
        today = date.today()
        session = get_db()
        try:
            cw = session.query(CourseWeek).filter(
                CourseWeek.start_date <= today,
                CourseWeek.end_date >= today
            ).first()
            return cw is not None
        finally:
            session.close()
    except Exception as e:
        logger.warning(f'[周课表] 教学周判断异常，默认视为在教学周内（继续推送）: {e}')
        return True


def generate_weekly_course():
    """生成每周课表"""
    logger.info("开始生成每周课表...")
    try:
        # 假期模式：静默全体面向用户的周课表推送
        from app.services.holiday_service import holiday_service
        if holiday_service.is_active()[0]:
            logger.info('[周课表] 假期模式静默中，跳过周课表推送')
            return
        # 在独立线程中执行爬虫（避免阻塞 APScheduler 线程池）
        import threading
        from datetime import datetime

        # 记录爬虫执行前的时间戳，用于后续校验图片新鲜度
        _run_timestamp = datetime.now().timestamp()

        def _run():
            success = run_spider()
            if not success:
                logger.error('[周课表] 爬虫执行失败，跳过发送课表图片')
                _notify_weekly_failure('爬虫执行失败，未产生新数据')
                return
            # 假期/暑假自动停发：当前不在任何教学周内即视为「这一周没课」，跳过推送
            if not _is_in_teaching_week():
                logger.info('[周课表] 当前不在教学周内（假期/暑假），跳过周课表推送')
                return
            _send_weekly_image(_run_timestamp)
        
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    except Exception as e:
        logger.error(f'生成每周课表异常: {e}')


def _send_weekly_image(run_timestamp=None):
    """发送每周课表图片
    
    Args:
        run_timestamp: 爬虫执行前的时间戳（Unix timestamp），
                       用于校验图片新鲜度，防止发送旧图。
                       为 None 时不做新鲜度校验（兼容非周课表场景）。
    """
    import glob
    from app.services.task_service import task_service
    from datetime import datetime
    
    # 使用配置中的路径获取课表图片目录
    images_dir = Config.IMAGES_DIR
    
    if not os.path.exists(images_dir):
        logger.warning(f'课表图片目录不存在: {images_dir}')
        _notify_weekly_failure(f'课表图片目录不存在: {images_dir}')
        return
    
    # 查找所有图片文件（支持 png 和 jpg）
    png_images = glob.glob(os.path.join(images_dir, '*.png'))
    jpg_images = glob.glob(os.path.join(images_dir, '*.jpg'))
    images = sorted(png_images + jpg_images, key=os.path.getmtime, reverse=True)
    if not images:
        logger.warning('未找到课表图片')
        _notify_weekly_failure('爬虫输出目录中未找到任何课表图片')
        return
    
    latest = images[0]
    image_mtime = os.path.getmtime(latest)
    
    # 新鲜度校验：如果提供了爬虫执行时间戳，确认图片是在爬虫执行之后产生的
    if run_timestamp is not None and image_mtime < run_timestamp:
        logger.error(
            f'[周课表] 最新图片 {os.path.basename(latest)} 的修改时间 '
            f'({datetime.fromtimestamp(image_mtime).strftime("%Y-%m-%d %H:%M:%S")}) '
            f'早于爬虫执行时间 ({datetime.fromtimestamp(run_timestamp).strftime("%Y-%m-%d %H:%M:%S")})，'
            f'疑似旧图，拒绝发送'
        )
        _notify_weekly_failure(
            f'最新图片为旧数据（图片时间: {datetime.fromtimestamp(image_mtime).strftime("%Y-%m-%d %H:%M")}, '
            f'爬虫时间: {datetime.fromtimestamp(run_timestamp).strftime("%Y-%m-%d %H:%M")}），'
            f'爬虫可能未成功产出新图片'
        )
        return
    
    logger.info(f'找到最新课表图片: {os.path.basename(latest)} (生成时间: {datetime.fromtimestamp(image_mtime).strftime("%Y-%m-%d %H:%M:%S")})')
    
    # 创建进程记录（图片推送是异步的，创建后立即标记为完成）
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('每周课表图片推送', 'course', total_items=1)
    
    task_service.create_task({
        'rule_id': 'weekly_schedule',
        'rule_name': '每周课表图片推送',
        'trigger_time': datetime.now(),
        'task_type': 'image',
        'sub_type': 'weekly_image',
        'image_path': latest,
        'course_info': {'image_name': os.path.basename(latest)},
        'process_id': pid,
    })
    
    # 标记进程为完成（实际推送由 delivery_service 异步处理）
    complete_task_process(pid, 'completed', '图片推送任务已创建，等待异步发送')


def _notify_weekly_failure(reason):
    """周课表发送失败通知
    
    通过状态 Webhook 通知管理员周课表推送失败，避免用户收到过时信息。
    """
    try:
        from flask import current_app
        status_webhook = current_app.config.get('WECOM_STATUS_WEBHOOK')
    except Exception:
        status_webhook = None
    
    if not status_webhook:
        logger.warning(f'[周课表] 发送失败，无状态 Webhook 可通知。原因: {reason}')
        return
    
    try:
        import requests
        from datetime import datetime
        message = {
            'msgtype': 'markdown',
            'markdown': {
                'content': (
                    f'**周课表推送失败通知**\n\n'
                    f'时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n'
                    f'原因：{reason}\n\n'
                    f'请检查爬虫是否正常运行，以及教务系统是否可访问。'
                )
            }
        }
        requests.post(status_webhook, json=message, timeout=10)
    except Exception as e:
        logger.error(f'[周课表] 发送失败通知异常: {e}')


def clean_old_processes():
    """清理一个月前的进程记录"""
    from datetime import datetime, timedelta
    from app.core.database import get_db
    from app.model.task_process import TaskProcess
    
    try:
        session = get_db()
        one_month_ago = datetime.now() - timedelta(days=30)
        
        # 查询并删除一个月前的记录
        old_processes = session.query(TaskProcess).filter(
            TaskProcess.started_at < one_month_ago
        ).all()
        
        deleted_count = len(old_processes)
        for process in old_processes:
            session.delete(process)
        
        session.commit()
        session.close()
        
        if deleted_count > 0:
            logger.info(f'[进程清理] 已清理 {deleted_count} 条一个月前的进程记录')
        else:
            logger.info('[进程清理] 没有需要清理的旧进程记录')
            
    except Exception as e:
        logger.error(f'[进程清理] 清理失败: {e}')


def cleanup_expired_sessions():
    """清理过期的服务端 Session 记录（由定时任务调用）"""
    try:
        from app.services.session_service import session_service
        count = session_service.cleanup_expired_sessions()
        if count > 0:
            logger.info(f'[Session清理] 已清理 {count} 条过期会话')
    except Exception as e:
        logger.error(f'[Session清理] 清理失败: {e}')
