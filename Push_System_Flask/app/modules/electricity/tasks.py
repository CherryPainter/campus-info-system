#!/usr/bin/env python3
"""
电量子模块定时任务
向 Push_System_Flask APScheduler 注册电量相关调度任务

用户化说明（2026-09-01）：
- 每宿舍独立电表，爬虫 Cookie 由学生在小程序自行配置（student_profiles.electricity_cookie）。
- 所有定时任务遍历"配置了 Cookie 的学生"，为每人独立爬取、按 user_id 落库，
  并通过 user_notifications 站内通知下发（企业微信电量推送已整体移除）。
- 无任何学生配置 Cookie 时任务空转（不爬取、不推送），不再依赖全局 Config 的
  ELECTRICITY_CRAWLER_COOKIE。
"""

import os
from datetime import datetime, timedelta

from app.core.logger import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------------


def _make_crawler(cookie: str = ""):
    """构造带指定 Cookie 的电量爬虫（不再读全局 Config Cookie）"""
    from app.core.config import Config
    from app.modules.electricity.crawler import ElectricityCrawler

    return ElectricityCrawler(
        base_url=getattr(Config, "ELECTRICITY_CRAWLER_BASE_URL", "http://dk.cqie.cn"),
        cookie=cookie or "",
        max_pages=getattr(Config, "ELECTRICITY_CRAWLER_MAX_PAGES", 50),
    )


def fetch_electricity_data() -> None:
    """仅爬取并保存电量数据，不推送消息（供管理端手动触发使用）：遍历配置了 Cookie 的学生"""
    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("爬取电量数据", "electricity", total_items=1)
    logger.info("[电量] 开始爬取电量数据")
    students = _iter_students_with_cookie()
    if not students:
        logger.info("[电量] 无学生配置电表 Cookie，爬取任务空转")
        complete_task_process(pid, "completed", "无学生配置电表 Cookie")
        return

    success_count = 0
    fail_msgs = []
    for user_id, cookie in students:
        success, msg = _fetch_and_save(user_id, cookie)
        if success:
            success_count += 1
        else:
            fail_msgs.append(f"用户{user_id}: {msg}")
    if success_count == len(students):
        complete_task_process(pid, "completed", f"{success_count} 个用户爬取完成")
    else:
        complete_task_process(pid, "failed", error="; ".join(fail_msgs[:3]))


def _iter_students_with_cookie() -> list[tuple[int, str]]:
    """
    遍历所有配置了电表 Cookie 的学生

    Returns:
        [(user_id, cookie), ...]，Cookie 去空白
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    session = get_db()
    try:
        rows = (
            session.query(StudentProfile.user_id, StudentProfile.electricity_cookie)
            .filter(StudentProfile.electricity_cookie.isnot(None))
            .all()
        )
        result = []
        for user_id, cookie in rows:
            cookie = (cookie or "").strip()
            if user_id and cookie:
                result.append((user_id, cookie))
        return result
    finally:
        session.close()


def _send_notification(user_id: int, category: str, title: str, content: str) -> None:
    """给指定用户写入一条站内通知（失败仅记日志，不中断任务）"""
    from app.services.user_notification_service import user_notification_service

    if not user_notification_service.create(
        user_id=user_id, category=category, title=title, content=content
    ):
        logger.warning(f"[电量] 站内通知写入失败 user_id={user_id} category={category}")


def _is_first_fetch(user_id: int) -> bool:
    """判断该用户是否为首次爬取（该用户无任何用电记录）"""
    from app.core.database import get_db
    from app.model.electricity import ElectricityRecord

    session = get_db()
    try:
        count = session.query(ElectricityRecord).filter(
            ElectricityRecord.user_id == user_id
        ).count()
        return count == 0
    finally:
        session.close()


def _has_data(user_id: int) -> bool:
    """检查该用户是否有用电记录"""
    from app.core.database import get_db
    from app.model.electricity import ElectricityRecord

    session = get_db()
    try:
        count = session.query(ElectricityRecord).filter(
            ElectricityRecord.user_id == user_id
        ).count()
        return count > 0
    finally:
        session.close()


def _fetch_and_save(user_id: int, cookie: str, max_pages: int | None = None) -> tuple:
    """
    按用户爬取最新数据并保存到数据库

    爬取策略：
    - 该用户首次爬取：全量爬取（最多50页）
    - 日常爬取：只爬1页，获取最新数据，避免给服务器造成压力

    Args:
        user_id: 归属用户ID
        cookie: 该用户的电表爬虫 Cookie
        max_pages: 指定爬取页数，None 则自动判断

    Returns:
        (success: bool, message: str)
    """
    from app.services.electricity_service import get_electricity_service

    service = get_electricity_service(user_id=user_id, cookie=cookie)

    if max_pages is None:
        max_pages = 1 if _has_data(user_id) else None
        if max_pages is None:
            logger.info(f"[电量] 用户 {user_id} 首次爬取，执行全量爬取")

    success, msg = service.fetch_and_save_data(max_pages=max_pages)
    return success, msg


def _build_daily_stats(user_id: int, target_date: datetime) -> dict | None:
    """
    按用户构建每日用电统计（兼容 formatter.format_daily）

    语义与旧 UsageStatistics 一致：记录时间 = 实际用电日 + 1 天，
    因此统计 target_date 当天，需查 record_time 落在 target_date+1 天。
    """
    from app.core.database import get_db
    from app.repository.electricity_repository import ElectricityRepository

    session = get_db()
    try:
        query_start = (target_date + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        query_end = query_start + timedelta(days=1)
        records = ElectricityRepository.get_records(
            session=session,
            start_time=query_start,
            end_time=query_end,
            limit=10000,
            user_id=user_id,
        )
        total = 0.0
        meter_usage: dict[str, float] = {}
        for r in records:
            total += float(r.usage or 0)
            meter_usage[r.meter] = meter_usage.get(r.meter, 0.0) + float(r.usage or 0)
        if total > 0 or meter_usage:
            return {
                "date": target_date.strftime("%Y-%m-%d"),
                "total_usage": total,
                "meter_usage": meter_usage,
            }
        return None
    finally:
        session.close()


def _build_weekly_stats(user_id: int, week_end: datetime) -> dict | None:
    """按用户构建周统计（周一至 week_end，兼容 formatter.format_weekly）"""
    from app.core.database import get_db
    from app.repository.electricity_repository import ElectricityRepository

    session = get_db()
    try:
        weekday = week_end.weekday()
        week_start = week_end - timedelta(days=weekday)
        # 记录时间区间：[周start+1天 00:00, 周end+2天 00:00)
        query_start = (week_start + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        query_end = (week_end + timedelta(days=2)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        records = ElectricityRepository.get_records(
            session=session,
            start_time=query_start,
            end_time=query_end,
            limit=100000,
            user_id=user_id,
        )
        total = 0.0
        meter_usage: dict[str, float] = {}
        daily_usage: dict[str, float] = {}
        for r in records:
            usage = float(r.usage or 0)
            total += usage
            meter_usage[r.meter] = meter_usage.get(r.meter, 0.0) + usage
            if r.record_time:
                actual_day = (r.record_time - timedelta(days=1)).strftime("%Y-%m-%d")
                daily_usage[actual_day] = daily_usage.get(actual_day, 0.0) + usage
        if total > 0 or meter_usage:
            iso = week_start.isocalendar()
            return {
                "year": iso[0],
                "week_num": iso[1],
                "start_date": week_start.strftime("%Y-%m-%d"),
                "end_date": week_end.strftime("%Y-%m-%d"),
                "total_usage": total,
                "meter_usage": meter_usage,
                "daily_usage": daily_usage,
                "days_count": len(daily_usage),
            }
        return None
    finally:
        session.close()


def _build_monthly_stats(user_id: int, last_month_last_day: datetime) -> dict | None:
    """按用户构建月统计（兼容 formatter.format_monthly）"""
    from app.core.database import get_db
    from app.repository.electricity_repository import ElectricityRepository

    session = get_db()
    try:
        year = last_month_last_day.year
        month = last_month_last_day.month
        month_start = last_month_last_day.replace(day=1)
        # 记录时间区间：月start+1天 00:00 至 下月1号+1天 00:00
        query_start = (month_start + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        next_month_start = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        query_end = (next_month_start + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        records = ElectricityRepository.get_records(
            session=session,
            start_time=query_start,
            end_time=query_end,
            limit=100000,
            user_id=user_id,
        )
        total = 0.0
        meter_usage: dict[str, float] = {}
        daily_usage: dict[str, float] = {}
        for r in records:
            usage = float(r.usage or 0)
            total += usage
            meter_usage[r.meter] = meter_usage.get(r.meter, 0.0) + usage
            if r.record_time:
                actual_day = (r.record_time - timedelta(days=1)).strftime("%Y-%m-%d")
                daily_usage[actual_day] = daily_usage.get(actual_day, 0.0) + usage
        if total > 0 or meter_usage:
            return {
                "year": year,
                "month": month,
                "total_usage": total,
                "meter_usage": meter_usage,
                "daily_usage": daily_usage,
                "days_count": len(daily_usage),
            }
        return None
    finally:
        session.close()


def _get_remaining(user_id: int) -> dict:
    """按用户获取最新剩余电量 {'default': float}，无数据返回 {}"""
    from app.core.database import get_db
    from app.repository.electricity_repository import ElectricityRepository

    session = get_db()
    try:
        record = ElectricityRepository.get_latest_remaining(
            session, "default", user_id=user_id
        )
        return {"default": record.remaining} if record else {}
    finally:
        session.close()


# ------------------------------------------------------------------
# 对外暴露的任务函数
# ------------------------------------------------------------------


def push_electricity_daily() -> None:
    """每日用电报告定时任务：遍历配置了 Cookie 的学生，各自爬取并写入站内通知"""
    from app.services.holiday_service import holiday_service
    from app.services.process_service import complete_task_process, create_task_process

    if holiday_service.skip_if_active("每日用电报告", "electricity"):
        return

    pid = create_task_process("每日用电报告", "electricity", total_items=1)
    logger.info("[电量] 开始执行每日推送任务")
    try:
        students = _iter_students_with_cookie()
        if not students:
            logger.info("[电量] 无学生配置电表 Cookie，每日任务空转")
            complete_task_process(pid, "completed", "无学生配置电表 Cookie")
            return

        from app.modules.electricity.formatter import ElectricityFormatter

        target_date = datetime.now() - timedelta(days=1)
        for user_id, cookie in students:
            success, msg = _fetch_and_save(user_id, cookie, max_pages=1)
            if not success:
                _send_notification(
                    user_id,
                    "fetch_error",
                    "每日用电报告生成失败",
                    ElectricityFormatter.format_fetch_error("每日用电报告", msg),
                )
                continue

            stats = _build_daily_stats(user_id, target_date)
            remaining = _get_remaining(user_id)
            if stats:
                _send_notification(
                    user_id,
                    "electricity_daily",
                    f"每日用电报告（{stats['date']}）",
                    ElectricityFormatter.format_daily(stats, remaining),
                )
            # 独立检查低电量
            _check_low_power_internal(user_id, remaining)

        complete_task_process(pid, "completed", "每日用电报告推送完成")
    except Exception as exc:
        logger.error(f"[电量] 每日推送任务异常: {exc}", exc_info=True)
        complete_task_process(pid, "failed", error=str(exc))


def push_electricity_weekly() -> None:
    """每周用电报告定时任务：遍历配置了 Cookie 的学生"""
    from app.services.holiday_service import holiday_service
    from app.services.process_service import complete_task_process, create_task_process

    if holiday_service.skip_if_active("每周用电报告", "electricity"):
        return

    pid = create_task_process("每周用电报告", "electricity", total_items=1)
    logger.info("[电量] 开始执行每周推送任务")
    try:
        students = _iter_students_with_cookie()
        if not students:
            logger.info("[电量] 无学生配置电表 Cookie，每周任务空转")
            complete_task_process(pid, "completed", "无学生配置电表 Cookie")
            return

        from app.modules.electricity.formatter import ElectricityFormatter

        today = datetime.now()
        # 周一推送上一周，其他日子推送本周
        week_end = today - timedelta(days=1) if today.weekday() == 0 else today
        for user_id, cookie in students:
            success, msg = _fetch_and_save(user_id, cookie, max_pages=1)
            if not success:
                _send_notification(
                    user_id,
                    "fetch_error",
                    "每周用电报告生成失败",
                    ElectricityFormatter.format_fetch_error("每周用电报告", msg),
                )
                continue

            stats = _build_weekly_stats(user_id, week_end)
            remaining = _get_remaining(user_id)
            if stats:
                _send_notification(
                    user_id,
                    "electricity_weekly",
                    f"每周用电报告（第{stats['week_num']}周）",
                    ElectricityFormatter.format_weekly(stats, remaining),
                )

        complete_task_process(pid, "completed", "每周用电报告推送完成")
    except Exception as exc:
        logger.error(f"[电量] 每周推送任务异常: {exc}", exc_info=True)
        complete_task_process(pid, "failed", error=str(exc))


def push_electricity_monthly() -> None:
    """每月用电报告定时任务：遍历配置了 Cookie 的学生"""
    from app.services.holiday_service import holiday_service
    from app.services.process_service import complete_task_process, create_task_process

    if holiday_service.skip_if_active("每月用电报告", "electricity"):
        return

    pid = create_task_process("每月用电报告", "electricity", total_items=1)
    logger.info("[电量] 开始执行每月推送任务")
    try:
        students = _iter_students_with_cookie()
        if not students:
            logger.info("[电量] 无学生配置电表 Cookie，每月任务空转")
            complete_task_process(pid, "completed", "无学生配置电表 Cookie")
            return

        from app.modules.electricity.formatter import ElectricityFormatter

        last_month_last_day = datetime.now().replace(day=1) - timedelta(days=1)
        for user_id, cookie in students:
            success, msg = _fetch_and_save(user_id, cookie, max_pages=2)
            if not success:
                _send_notification(
                    user_id,
                    "fetch_error",
                    "每月用电报告生成失败",
                    ElectricityFormatter.format_fetch_error("每月用电报告", msg),
                )
                continue

            stats = _build_monthly_stats(user_id, last_month_last_day)
            remaining = _get_remaining(user_id)
            if stats:
                _send_notification(
                    user_id,
                    "electricity_monthly",
                    f"每月用电报告（{stats['year']}年{stats['month']}月）",
                    ElectricityFormatter.format_monthly(stats, remaining),
                )

        complete_task_process(pid, "completed", "每月用电报告推送完成")
    except Exception as exc:
        logger.error(f"[电量] 每月推送任务异常: {exc}", exc_info=True)
        complete_task_process(pid, "failed", error=str(exc))


def check_cookie_validity() -> None:
    """Cookie 有效性检测任务：遍历配置了 Cookie 的学生，失效时写站内通知"""
    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("Cookie有效性检测", "electricity", total_items=1)
    logger.info("[电量] 开始检测 Cookie 有效性")
    try:
        students = _iter_students_with_cookie()
        if not students:
            logger.info("[电量] 无学生配置电表 Cookie，检测任务空转")
            complete_task_process(pid, "completed", "无学生配置电表 Cookie")
            return

        from app.modules.electricity.formatter import ElectricityFormatter

        invalid_count = 0
        for user_id, cookie in students:
            crawler = _make_crawler(cookie)
            is_valid, reason = crawler.check_cookie_valid()
            if not is_valid:
                invalid_count += 1
                _send_notification(
                    user_id,
                    "cookie_invalid",
                    "电表 Cookie 已失效",
                    ElectricityFormatter.format_cookie_invalid(reason),
                )
                logger.warning(f"[电量] 用户 {user_id} Cookie 失效: {reason}")
            else:
                logger.info(f"[电量] 用户 {user_id} Cookie 有效性检测通过")

        if invalid_count:
            complete_task_process(pid, "failed", f"{invalid_count} 个用户 Cookie 失效")
        else:
            complete_task_process(pid, "completed", "Cookie 全部有效")
    except Exception as exc:
        logger.error(f"[电量] Cookie 检测异常: {exc}")
        complete_task_process(pid, "failed", error=str(exc))


def check_low_power() -> None:
    """低电量检测任务（独立触发）：遍历配置了 Cookie 的学生"""
    from app.services.holiday_service import holiday_service

    if holiday_service.skip_if_active("低电量检测", "electricity"):
        return
    logger.info("[电量] 开始低电量检测")
    students = _iter_students_with_cookie()
    if not students:
        logger.info("[电量] 无学生配置电表 Cookie，低电量检测空转")
        return
    for user_id, _cookie in students:
        remaining = _get_remaining(user_id)
        _check_low_power_internal(user_id, remaining)


def push_electricity_full_crawl() -> None:
    """全量爬取定时任务（每周一次）：遍历配置了 Cookie 的学生，获取完整历史数据"""
    from app.services.holiday_service import holiday_service
    from app.services.process_service import complete_task_process, create_task_process

    if holiday_service.skip_if_active("电量全量爬取", "electricity"):
        return

    pid = create_task_process("电量全量爬取", "electricity", total_items=1)
    logger.info("[电量] 开始执行全量爬取任务")
    try:
        students = _iter_students_with_cookie()
        if not students:
            logger.info("[电量] 无学生配置电表 Cookie，全量爬取空转")
            complete_task_process(pid, "completed", "无学生配置电表 Cookie")
            return

        success_count = 0
        for user_id, cookie in students:
            success, msg = _fetch_and_save(user_id, cookie, max_pages=50)
            if success:
                success_count += 1
                logger.info(f"[电量] 用户 {user_id} 全量爬取完成: {msg}")
            else:
                logger.warning(f"[电量] 用户 {user_id} 全量爬取失败: {msg}")

        complete_task_process(pid, "completed", f"{success_count}/{len(students)} 个用户爬取完成")
    except Exception as exc:
        logger.error(f"[电量] 全量爬取任务异常: {exc}")
        complete_task_process(pid, "failed", error=str(exc))


def _check_low_power_internal(user_id: int, remaining: dict) -> None:
    """内部低电量检测逻辑（按用户，去重基于站内通知记录）"""
    from app.core.config import Config
    from app.modules.electricity.formatter import ElectricityFormatter

    threshold = float(getattr(Config, "ELECTRICITY_LOW_POWER_THRESHOLD", 10.0))
    reminder_interval_hours = float(getattr(Config, "ELECTRICITY_LOW_POWER_INTERVAL_HOURS", 4.0))

    power_val = remaining.get("default")
    if power_val is None:
        return

    try:
        power_val = float(power_val)
    except (TypeError, ValueError):
        return

    if power_val > threshold:
        return

    # 检查是否在提醒间隔内（查该用户最近 low_power 站内通知）
    from app.core.database import get_db
    from app.model.user_notification import UserNotification

    session = get_db()
    try:
        cutoff = datetime.now() - timedelta(hours=reminder_interval_hours)
        recent = (
            session.query(UserNotification.id)
            .filter(
                UserNotification.user_id == user_id,
                UserNotification.category == "low_power",
                UserNotification.created_at >= cutoff,
            )
            .first()
        )
    finally:
        session.close()
    if recent:
        logger.info(f"[电量] 用户 {user_id} 低电量提醒跳过：间隔内已提醒")
        return

    _send_notification(
        user_id,
        "low_power",
        "低电量提醒",
        ElectricityFormatter.format_low_power_alert(power_val),
    )
    logger.warning(f"[电量] 用户 {user_id} 低电量提醒已发送: 剩余 {power_val:.2f} 度")


# ------------------------------------------------------------------
# 注册到 APScheduler
# ------------------------------------------------------------------


def register_tasks(scheduler, app) -> None:
    """
    将电量相关定时任务注册到 APScheduler 实例

    优先从数据库读取配置（key 与 Config 属性完全对应），回退到 app.config。

    Args:
        scheduler: BackgroundScheduler 实例
        app: Flask app 实例（用于读取 config）
    """
    from apscheduler.triggers.cron import CronTrigger

    from app.services.config_service import get_config_service

    config_svc = get_config_service()

    # 优先读数据库，回退 app.config（app.config 由 Config.reload() 同步）
    daily_time = config_svc.get("electricity", "schedule_daily", None) or app.config.get(
        "ELECTRICITY_SCHEDULE_DAILY", "00:30"
    )
    weekly_day = config_svc.get("electricity", "schedule_weekly_day", None) or app.config.get(
        "ELECTRICITY_SCHEDULE_WEEKLY_DAY", "mon"
    )
    weekly_time = config_svc.get("electricity", "schedule_weekly", None) or app.config.get(
        "ELECTRICITY_SCHEDULE_WEEKLY", "00:30"
    )
    monthly_day = int(
        config_svc.get("electricity", "schedule_monthly_day", None)
        or app.config.get("ELECTRICITY_SCHEDULE_MONTHLY_DAY", 1)
    )
    monthly_time = config_svc.get("electricity", "schedule_monthly", None) or app.config.get(
        "ELECTRICITY_SCHEDULE_MONTHLY", "00:30"
    )
    cookie_check_time = config_svc.get("electricity", "cookie_check_time", None) or app.config.get(
        "ELECTRICITY_COOKIE_CHECK_TIME", "20:00"
    )
    # 低电量检测间隔（小时），优先读数据库
    low_power_interval = float(
        config_svc.get("electricity", "low_power_interval_hours", None)
        or app.config.get("ELECTRICITY_LOW_POWER_INTERVAL_HOURS", 4.0)
    )

    d_hour, d_min = map(int, daily_time.split(":"))
    w_hour, w_min = map(int, weekly_time.split(":"))
    m_hour, m_min = map(int, monthly_time.split(":"))
    ck_hour, ck_min = map(int, cookie_check_time.split(":"))

    scheduler.add_job(
        push_electricity_daily,
        trigger=CronTrigger(hour=d_hour, minute=d_min),
        id="electricity_daily",
        name="电量每日报告",
        replace_existing=True,
    )
    logger.info(f"[电量] 每日任务已注册: 每天 {daily_time}")

    scheduler.add_job(
        push_electricity_weekly,
        trigger=CronTrigger(day_of_week=weekly_day, hour=w_hour, minute=w_min),
        id="electricity_weekly",
        name="电量每周报告",
        replace_existing=True,
    )
    logger.info(f"[电量] 每周任务已注册: 每{weekly_day} {weekly_time}")

    scheduler.add_job(
        push_electricity_monthly,
        trigger=CronTrigger(day=monthly_day, hour=m_hour, minute=m_min),
        id="electricity_monthly",
        name="电量每月报告",
        replace_existing=True,
    )
    logger.info(f"[电量] 每月任务已注册: 每月{monthly_day}日 {monthly_time}")

    scheduler.add_job(
        check_cookie_validity,
        trigger=CronTrigger(hour=ck_hour, minute=ck_min),
        id="electricity_cookie_check",
        name="电量 Cookie 检测",
        replace_existing=True,
    )
    logger.info(f"[电量] Cookie 检测任务已注册: 每天 {cookie_check_time}")

    # 低电量检测：使用配置的间隔（小时），最小 1 小时，最大 24 小时
    low_power_hours = max(1, min(24, int(low_power_interval)))
    scheduler.add_job(
        check_low_power,
        trigger=CronTrigger(hour=f"*/{low_power_hours}", minute=0),
        id="electricity_low_power",
        name="电量低电量检测",
        replace_existing=True,
    )
    logger.info(f"[电量] 低电量检测任务已注册: 每 {low_power_hours} 小时")

    # 电量全量爬取：每周日凌晨执行一次（获取完整历史数据）
    full_crawl_day = int(
        config_svc.get("electricity", "full_crawl_day", None)
        or app.config.get("ELECTRICITY_FULL_CRAWL_DAY", 0)
    )  # 0=周日
    full_crawl_time = config_svc.get("electricity", "full_crawl_time", None) or app.config.get(
        "ELECTRICITY_FULL_CRAWL_TIME", "03:00"
    )
    try:
        fc_hour, fc_min = map(int, str(full_crawl_time).split(":"))
    except (ValueError, AttributeError):
        fc_hour, fc_min = 3, 0

    scheduler.add_job(
        push_electricity_full_crawl,
        trigger=CronTrigger(day_of_week=str(full_crawl_day), hour=fc_hour, minute=fc_min),
        id="electricity_full_crawl",
        name="电量全量爬取",
        replace_existing=True,
    )
    logger.info(f"[电量] 全量爬取任务已注册: 每周{full_crawl_day} {full_crawl_time}")
