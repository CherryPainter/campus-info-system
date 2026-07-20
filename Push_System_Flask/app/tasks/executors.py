#!/usr/bin/env python3
"""课表爬虫与推送的执行逻辑（触发函数）。

这些函数由 scheduler.py 的 APScheduler 作业注册调用，也被 admin_routes / 手动触发接口直接调用。
共享的可变状态集中在 app.tasks.scheduler_state，本模块通过 scheduler_state.X 读写。
"""

import os
import subprocess
import sys

from app.core.config import Config
from app.core.logger import get_logger
from app.core.task_state import TaskStatus, TaskType
from app.services.process_service import complete_task_process, create_task_process
from app.services.rule_service import rule_service
from app.services.schedule_service import schedule_service
from app.services.spider_runner import run_spider_process
from app.services.task_service import task_service
from app.tasks import scheduler_state

logger = get_logger(__name__)


def _read_spider_log_tail(spider_dir, lines=10):
    """读取爬虫日志文件的最后几行，用于定位子进程失败原因"""
    import glob

    log_dir = os.path.join(spider_dir, "output", "logs")
    if not os.path.isdir(log_dir):
        return ""
    log_files = sorted(
        glob.glob(os.path.join(log_dir, "course_spider_*.log")), key=os.path.getmtime, reverse=True
    )
    if not log_files:
        return ""
    try:
        with open(log_files[0], encoding="utf-8") as f:
            all_lines = f.readlines()
        tail = "".join(all_lines[-lines:]).strip()
        return tail if tail else ""
    except Exception:
        return ""


def run_spider(trigger_source="cron"):
    """执行爬虫（带并发保护和三次重试）

    Args:
        trigger_source: 触发来源，'cron' 表示定时触发，'manual' 表示手动触发

    Returns:
        bool: True 表示爬虫执行成功，False 表示失败或被跳过
    """
    if scheduler_state._spider_running:
        logger.warning("爬虫正在执行中，跳过本次触发")
        return False

    # 假期模式：静默期间无需同步课表（提前返回，不触发失败告警）
    from app.services.holiday_service import holiday_service

    if holiday_service.is_active()[0]:
        logger.info("[爬虫] 假期模式静默中，跳过课表爬取")
        return False

    # 不在教学周内（暑假/寒假/其他假期）无需同步课表，跳过爬取。
    # 与周课表推送同源逻辑：基于 teaching_week_service 开学日推算自动判断，
    # 无需手动开假期模式即可在假期自动停爬；异常时回退为继续爬（fail-open）。
    if not _is_in_teaching_week():
        logger.info("[爬虫] 当前不在教学周内（假期/暑假），跳过课表爬取")
        return False

    source_label = "定时" if trigger_source == "cron" else "手动"
    scheduler_state._spider_running = True
    logger.info(f"{source_label}触发爬虫执行...")
    scheduler_state._spider_status["last_run"] = __import__("datetime").datetime.now().isoformat()
    scheduler_state._spider_status["last_result"] = "running"
    scheduler_state._spider_status["last_error"] = None

    # 创建进程记录
    spider_pid = create_task_process(f"课程表同步爬取（{source_label}）", "spider", total_items=1)

    # 使用配置中的基础路径计算爬虫目录
    spider_dir = os.path.join(Config.BASE_DIR, "app", "cqie-course-timetable")
    script = os.path.join(spider_dir, "main.py")

    if not os.path.exists(script):
        logger.error(f"爬虫脚本不存在: {script}")
        scheduler_state._spider_running = False
        return False

    # 最多重试 3 次（Python 解析与 env 注入由 SpiderRunner 统一处理）
    max_retries = 3
    success = False
    last_error = None
    last_exit_code = None

    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            logger.info(f"[尝试 {attempt}/{max_retries}] 爬虫重试中...")

        try:
            logger.info(f"开始执行爬虫 (尝试 {attempt}/{max_retries})...")
            result = run_spider_process(timeout=600)

            logger.info(f"爬虫执行完成，返回码: {result.returncode}")

            if result.returncode == 0:
                logger.info(f"爬虫执行成功 (尝试 {attempt}/{max_retries})")
                if result.stdout:
                    logger.debug(f"爬虫输出: {result.stdout[:500]}")
                success = True
                break
            else:
                # 优先取 stderr，若为空则尝试读取爬虫日志文件
                error_msg = result.stderr[:500] if result.stderr.strip() else ""
                if not error_msg:
                    error_msg = _read_spider_log_tail(spider_dir)
                if not error_msg:
                    error_msg = f"exit code {result.returncode} (无错误输出)"
                logger.warning(
                    f"爬虫执行失败 (尝试 {attempt}/{max_retries}, code={result.returncode}): {error_msg}"
                )
                last_error = error_msg
                last_exit_code = result.returncode

                # 不是最后一次尝试时，等一会儿再重试
                if attempt < max_retries:
                    import time

                    wait_seconds = 30  # 30秒后重试
                    logger.info(f"等待 {wait_seconds} 秒后重试...")
                    time.sleep(wait_seconds)

        except subprocess.TimeoutExpired:
            logger.warning(f"爬虫执行超时 (尝试 {attempt}/{max_retries})")
            last_error = "Timeout (600s)"
            last_exit_code = -1

            if attempt < max_retries:
                import time

                wait_seconds = 30
                logger.info(f"等待 {wait_seconds} 秒后重试...")
                time.sleep(wait_seconds)

        except Exception as e:
            logger.warning(f"爬虫执行异常 (尝试 {attempt}/{max_retries}): {e}")
            last_error = str(e)
            last_exit_code = -2

            if attempt < max_retries:
                import time

                wait_seconds = 30
                logger.info(f"等待 {wait_seconds} 秒后重试...")
                time.sleep(wait_seconds)

    try:
        if success:
            scheduler_state._spider_status["last_result"] = "success"
            # 标记今日爬虫已成功执行
            today_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
            scheduler_state._spider_success_dates[today_str] = True
            _cleanup_stale_dates()
            # 检查是否有被延迟的每日课表推送
            _try_deferred_daily_push()
            # 系统侧接管落库 + 周次锚点同步（爬虫子进程只产出 JSON/图片）。
            # v6.11.1：每日爬虫同步将「当前周」数据入库（来源标记 daily）。
            # 用每日爬取的当前周正确数据 upsert 修正全量爬取的当前周错误，实现每日校验。
            # 空结果不会覆盖（save_to_database 空结果护栏 return (0, 0) 不入库）。
            # 教学周判定统一由 teaching_week_service 基于开学日推算，彻底脱离 course_weeks 表（已移除）。
            try:
                import importlib as _il

                if spider_dir not in sys.path:
                    sys.path.insert(0, spider_dir)
                _pipeline_mod = _il.import_module("pipeline")
                _daily_processed = os.path.join(spider_dir, "output", "course-data", "processed")
                _created, _updated = _pipeline_mod.save_to_database(
                    _daily_processed, logger, data_source="daily"
                )
                logger.info(
                    f"[每日爬虫] 当前周数据已入库 (data_source=daily): 新增 {_created} 条 / 更新 {_updated} 条"
                )
            except Exception as _e:
                logger.error(f"[每日爬虫] 落库失败（不影响图片生成与推送）: {_e}")

            # 图片生成由系统差遣（--only-image 子命令，复用爬虫 matplotlib 环境）。
            # 爬虫主流程不再自动生成图片（v6.14 爬虫越权收回阶段2），落库成功即触发。
            # 图片失败不影响进程标记与推送。
            try:
                from app.services.spider_runner import run_spider_process as _run_img

                _img_result = _run_img(["--only-image"], timeout=300)
                if _img_result.returncode == 0:
                    logger.info("[每日爬虫] 课程表图片已生成（系统差遣 --only-image）")
                else:
                    logger.warning(
                        f"[每日爬虫] 图片生成失败（--only-image, code={_img_result.returncode}），不影响推送"
                    )
            except Exception as _ie:
                logger.warning(f"[每日爬虫] 图片生成异常（--only-image）: {_ie}")

            complete_task_process(spider_pid, TaskStatus.COMPLETED, "爬虫执行成功")
            return True
        else:
            logger.error(f"爬虫所有 {max_retries} 次尝试均失败")
            scheduler_state._spider_status["last_result"] = "failed"
            scheduler_state._spider_status["last_error"] = last_error
            scheduler_state._spider_status["last_exit_code"] = last_exit_code
            _notify_spider_failure(last_exit_code, last_error)
            complete_task_process(spider_pid, TaskStatus.FAILED, error=last_error)
            return False
    finally:
        scheduler_state._spider_running = False


def _notify_spider_failure(exit_code, error_msg):
    """爬虫失败通知"""
    status_webhook = None

    # 尝试获取状态 webhook
    try:
        from flask import current_app

        status_webhook = current_app.config.get("WECOM_STATUS_WEBHOOK")
    except Exception:
        pass

    if not status_webhook:
        return

    try:
        import requests

        message = {
            "msgtype": "markdown",
            "markdown": {
                "content": f'**爬虫执行异常通知**\n\n时间：{__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n状态：失败\n\n错误码：{exit_code}\n\n错误信息：{error_msg}'
            },
        }
        requests.post(status_webhook, json=message, timeout=10)
    except Exception as e:
        logger.error(f"发送失败通知异常: {e}")


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
    status = dict(scheduler_state._spider_status)
    status["running"] = scheduler_state._spider_running
    try:
        from app.core.database import get_db
        from app.model.task_process import TaskProcess

        session = get_db()
        try:
            spider_running = (
                session.query(TaskProcess)
                .filter(
                    TaskProcess.task_type == TaskType.SPIDER,
                    TaskProcess.status == TaskStatus.RUNNING,
                )
                .first()
                is not None
            )
            # DB 驱动：以实际 SPIDER 进程状态为准，叠加内存锁覆盖提交前窗口
            status["running"] = spider_running or scheduler_state._spider_running
            if not status["running"]:
                # 无运行中日常爬虫：用最近一次 spider 进程终态补充 last_result
                latest = (
                    session.query(TaskProcess)
                    .filter(TaskProcess.task_type == TaskType.SPIDER)
                    .order_by(TaskProcess.started_at.desc())
                    .first()
                )
                if latest and latest.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.COMPLETED_EMPTY,
                    TaskStatus.CANCELLED,
                ):
                    status["last_result"] = (
                        "success" if latest.status == TaskStatus.COMPLETED else latest.status
                    )
                    status["last_error"] = latest.error_message
        finally:
            session.close()
    except Exception:
        # 兜底查询失败不应影响状态返回
        pass
    return status


def _cleanup_stale_dates():
    """清理过期的日期追踪记录（仅保留最近2天）"""
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    for d in list(scheduler_state._spider_success_dates.keys()):
        if d < cutoff:
            del scheduler_state._spider_success_dates[d]
    for d in list(scheduler_state._daily_push_pending.keys()):
        if d < cutoff:
            del scheduler_state._daily_push_pending[d]


def _try_deferred_daily_push():
    """爬虫成功后，检查并补发被延迟的每日课表推送

    当每日课表推送时间（如07:00）与爬虫 cron 时间重合时，
    check_push_rules() 会跳过推送并标记 _daily_push_pending。
    爬虫成功后调用此函数，强制刷新数据并补发。
    """
    from datetime import datetime

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    if today_str not in scheduler_state._daily_push_pending:
        return

    # 清除 pending 标记
    del scheduler_state._daily_push_pending[today_str]

    try:
        # 强制刷新课表数据（爬虫刚产出新数据）
        schedule_service.load_schedules()
        schedules = schedule_service.get_schedules()

        # 使用强制模式补发每日课表推送
        tasks = rule_service.check_conditions_force(now, schedules, rule_type="daily_schedule")

        if tasks:
            created = task_service.create_tasks(tasks)
            if created:
                logger.info(f"[延迟推送] 爬虫完成后补发每日课表，创建 {len(created)} 个推送任务")
        else:
            logger.info("[延迟推送] 爬虫完成后检查每日课表，无匹配规则")
    except Exception as e:
        logger.error(f"[延迟推送] 补发每日课表异常: {e}")


def check_push_rules():
    """检查推送规则"""
    from datetime import datetime

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    # 假期模式：静默全体面向用户的课表推送（调试级日志，避免每分钟刷屏）
    from app.services.holiday_service import holiday_service

    if holiday_service.is_active()[0]:
        logger.debug("[推送规则] 假期模式静默中，跳过本次规则检查")
        return

    # 不在教学周内（暑假/寒假/假期）无课可推，跳过课程推送规则检查。
    # 与课程爬虫同源规则：基于 course_weeks 真实日期范围自动判断，
    # 无需手动开假期模式即可在假期自动停推；异常时回退为继续检查（fail-open）。
    if not _is_in_teaching_week():
        logger.debug("[推送规则] 当前不在教学周内（假期/暑假），跳过课程推送规则检查")
        return

    schedules = schedule_service.get_schedules()

    # 从未成功加载过数据时，跳过所有推送规则（避免在系统刚部署无数据时误触发）
    if not schedule_service.is_data_ready:
        logger.debug("课表数据未就绪，跳过推送规则检查")
        return

    # 数据已就绪但课表为空（如周末/假期），仍允许规则引擎判断（如 daily_no_class）
    tasks = rule_service.check_conditions(now, schedules)

    # 协调机制：如果每日课表推送时间与爬虫 cron 时间重合，
    # 且爬虫今日尚未成功执行，则延迟推送直到爬虫完成
    filtered = []
    for task in tasks:
        if task and task.get("rule_id") == "daily_schedule":
            daily_time = task.get("trigger_condition", {}).get("daily_time", "")
            if daily_time:
                try:
                    push_hour = int(daily_time.split(":")[0])
                    if (
                        push_hour in scheduler_state._spider_cron_hours
                        and today_str not in scheduler_state._spider_success_dates
                    ):
                        logger.info(
                            f"[每日课表] 推送时间 {daily_time} 与爬虫 cron 重合，"
                            f"爬虫今日尚未完成，延迟推送"
                        )
                        scheduler_state._daily_push_pending[today_str] = True
                        continue
                except (ValueError, IndexError):
                    pass
        filtered.append(task)

    if filtered:
        created = task_service.create_tasks(filtered)
        if created:
            logger.info(f"规则检查创建 {len(created)} 个推送任务")


def _is_in_teaching_week():
    """判断今天是否在教学周内。

    布尔封装自教学周唯一真相源 get_current_teaching_week()：
    基于开学日推算当前周次，且不在假期模式内即为 True。
    假期模式激活或非教学周均返回 False（不推送课表）。
    """
    from app.services.teaching_week_service import get_current_teaching_week

    return get_current_teaching_week() is not None


def generate_weekly_course():
    """生成每周课表"""
    logger.info("开始生成每周课表...")
    try:
        # 假期模式：静默全体面向用户的周课表推送
        from app.services.holiday_service import holiday_service

        if holiday_service.is_active()[0]:
            logger.info("[周课表] 假期模式静默中，跳过周课表推送")
            return
        # 在独立线程中执行爬虫（避免阻塞 APScheduler 线程池）
        import threading
        from datetime import datetime

        # 记录爬虫执行前的时间戳，用于后续校验图片新鲜度
        _run_timestamp = datetime.now().timestamp()

        def _run():
            # 假期/暑假自动停发：当前不在任何教学周内即视为「这一周没课」，
            # 跳过爬取与推送（避免爬空数据 + 被误判为爬虫失败发告警）
            if not _is_in_teaching_week():
                logger.info("[周课表] 当前不在教学周内（假期/暑假），跳过周课表推送")
                return
            success = run_spider()
            if not success:
                logger.error("[周课表] 爬虫执行失败，跳过发送课表图片")
                _notify_weekly_failure("爬虫执行失败，未产生新数据")
                return
            _send_weekly_image(_run_timestamp)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    except Exception as e:
        logger.error(f"生成每周课表异常: {e}")


def _send_weekly_image(run_timestamp=None):
    """发送每周课表图片

    Args:
        run_timestamp: 爬虫执行前的时间戳（Unix timestamp），
                       用于校验图片新鲜度，防止发送旧图。
                       为 None 时不做新鲜度校验（兼容非周课表场景）。
    """
    import glob
    from datetime import datetime

    from app.services.task_service import task_service

    # 使用配置中的路径获取课表图片目录
    images_dir = Config.IMAGES_DIR

    if not os.path.exists(images_dir):
        logger.warning(f"课表图片目录不存在: {images_dir}")
        _notify_weekly_failure(f"课表图片目录不存在: {images_dir}")
        return

    # 查找所有图片文件（支持 png 和 jpg）
    png_images = glob.glob(os.path.join(images_dir, "*.png"))
    jpg_images = glob.glob(os.path.join(images_dir, "*.jpg"))
    images = sorted(png_images + jpg_images, key=os.path.getmtime, reverse=True)
    if not images:
        logger.warning("未找到课表图片")
        _notify_weekly_failure("爬虫输出目录中未找到任何课表图片")
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

    logger.info(
        f'找到最新课表图片: {os.path.basename(latest)} (生成时间: {datetime.fromtimestamp(image_mtime).strftime("%Y-%m-%d %H:%M:%S")})'
    )

    # 创建进程记录（图片推送是异步的，创建后立即标记为完成）
    pid = create_task_process("每周课表图片推送", "course", total_items=1)

    task_service.create_task(
        {
            "rule_id": "weekly_schedule",
            "rule_name": "每周课表图片推送",
            "trigger_time": datetime.now(),
            "task_type": "image",
            "sub_type": "weekly_image",
            "image_path": latest,
            "course_info": {"image_name": os.path.basename(latest)},
            "process_id": pid,
        }
    )

    # 标记进程为完成（实际推送由 delivery_service 异步处理）
    complete_task_process(pid, "completed", "图片推送任务已创建，等待异步发送")


def _notify_weekly_failure(reason):
    """周课表发送失败通知

    通过状态 Webhook 通知管理员周课表推送失败，避免用户收到过时信息。
    """
    try:
        from flask import current_app

        status_webhook = current_app.config.get("WECOM_STATUS_WEBHOOK")
    except Exception:
        status_webhook = None

    if not status_webhook:
        logger.warning(f"[周课表] 发送失败，无状态 Webhook 可通知。原因: {reason}")
        return

    try:
        from datetime import datetime

        import requests

        message = {
            "msgtype": "markdown",
            "markdown": {
                "content": (
                    f'**周课表推送失败通知**\n\n'
                    f'时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n'
                    f'原因：{reason}\n\n'
                    f'请检查爬虫是否正常运行，以及教务系统是否可访问。'
                )
            },
        }
        requests.post(status_webhook, json=message, timeout=10)
    except Exception as e:
        logger.error(f"[周课表] 发送失败通知异常: {e}")


def clean_old_processes():
    """清理一个月前的进程记录"""
    from datetime import datetime, timedelta

    from app.core.database import get_db
    from app.model.task_process import TaskProcess

    try:
        session = get_db()
        one_month_ago = datetime.now() - timedelta(days=30)

        # 查询并删除一个月前的记录
        old_processes = (
            session.query(TaskProcess).filter(TaskProcess.started_at < one_month_ago).all()
        )

        deleted_count = len(old_processes)
        for process in old_processes:
            session.delete(process)

        session.commit()
        session.close()

        if deleted_count > 0:
            logger.info(f"[进程清理] 已清理 {deleted_count} 条一个月前的进程记录")
        else:
            logger.info("[进程清理] 没有需要清理的旧进程记录")

    except Exception as e:
        logger.error(f"[进程清理] 清理失败: {e}")


def cleanup_expired_sessions():
    """清理过期的服务端 Session 记录（由定时任务调用）"""
    try:
        from app.services.session_service import session_service

        count = session_service.cleanup_expired_sessions()
        if count > 0:
            logger.info(f"[Session清理] 已清理 {count} 条过期会话")
    except Exception as e:
        logger.error(f"[Session清理] 清理失败: {e}")
