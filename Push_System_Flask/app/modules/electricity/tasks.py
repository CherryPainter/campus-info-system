#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电量子模块定时任务
向 Push_System_Flask APScheduler 注册电量相关调度任务
"""

import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from app.core.logger import get_logger

logger = get_logger(__name__)

# 低电量提醒状态文件（相对于 data/electricity/）
_LOW_POWER_STATE_FILE = '.low_power_state'


# ------------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------------

def _data_dir() -> str:
    """延迟获取数据目录，避免 import 时 Config 未就绪"""
    from app.core.config import Config
    d = os.path.join(Config.BASE_DIR, 'data', 'electricity')
    os.makedirs(d, exist_ok=True)
    return d


def _chart_dir() -> str:
    from app.core.config import Config
    d = os.path.join(Config.BASE_DIR, 'data', 'electricity', 'charts')
    os.makedirs(d, exist_ok=True)
    return d


def _records_path() -> str:
    return os.path.join(_data_dir(), 'usage_records.json')


def _remaining_path() -> str:
    return os.path.join(_data_dir(), 'remaining_power.json')


def _low_power_state_path() -> str:
    return os.path.join(_data_dir(), _LOW_POWER_STATE_FILE)


def _make_crawler():
    from app.core.config import Config
    from app.modules.electricity.crawler import ElectricityCrawler
    return ElectricityCrawler(
        base_url=getattr(Config, 'ELECTRICITY_CRAWLER_BASE_URL', 'http://dk.cqie.cn'),
        cookie=getattr(Config, 'ELECTRICITY_CRAWLER_COOKIE', ''),
        max_pages=getattr(Config, 'ELECTRICITY_CRAWLER_MAX_PAGES', 50),  # 增加到50页以获取更多历史记录
    )


def _make_stats():
    from app.modules.electricity.statistics import UsageStatistics
    return UsageStatistics(_records_path(), _remaining_path())


def _make_chart_gen():
    from app.modules.electricity.chart import ElectricityChartGenerator
    return ElectricityChartGenerator(_records_path(), _chart_dir())


def _send_markdown(content: str, *, notify_only: bool = False) -> None:
    """通过 adapter_service 发送 Markdown 消息"""
    from app.services.adapter_service import adapter_service
    from app.core.config import Config

    # 假期模式：静默面向用户的电量推送；notify_only 状态告警（发给管理员）不受影响
    from app.services.holiday_service import holiday_service
    if not notify_only and holiday_service.is_active()[0]:
        logger.info('[电量] 假期模式静默，跳过发送')
        return

    # notify_only 时使用状态 Webhook（如已配置），否则使用电量专用适配器
    if notify_only:
        webhook = getattr(Config, 'WECOM_STATUS_WEBHOOK', None)
        if webhook:
            try:
                import requests as req
                req.post(webhook, json={
                    'msgtype': 'markdown',
                    'markdown': {'content': content}
                }, timeout=10)
                return
            except Exception as exc:
                logger.warning(f'状态 Webhook 发送失败: {exc}')

    # 使用电量专用适配器，若未配置则回退到通用 wecom 适配器
    adapter = adapter_service.get_adapter('electricity')
    if adapter is None:
        adapter = adapter_service.get_adapter('wecom')
    if adapter is None:
        logger.error('_send_markdown: electricity/wecom 适配器均未初始化，请在后台配置 Webhook')
        return
    adapter.send({'msgtype': 'markdown', 'markdown': {'content': content}})


def _send_image(image_path: str) -> None:
    # 假期模式：图片类电量推送均为面向用户，整段静音
    from app.services.holiday_service import holiday_service
    if holiday_service.is_active()[0]:
        logger.info('[电量] 假期模式静默，跳过图片发送')
        return
    from app.services.adapter_service import adapter_service
    adapter = adapter_service.get_adapter('electricity')
    if adapter is None:
        adapter = adapter_service.get_adapter('wecom')
    if adapter is None:
        logger.error('_send_image: electricity/wecom 适配器均未初始化，请在后台配置 Webhook')
        return
    adapter.send_image(image_path)


def _is_first_fetch() -> bool:
    """
    判断是否为首次爬取

    通过检查数据库中是否有用电记录来判断

    Returns:
        bool: 如果数据库中没有记录则为首次
    """
    try:
        from app.core.database import get_db
        from app.model.electricity import ElectricityRecord
        session = get_db()
        try:
            count = session.query(ElectricityRecord).count()
            return count == 0
        finally:
            session.close()
    except Exception:
        return True


def _has_data() -> bool:
    """检查数据库中是否有用电记录"""
    try:
        from app.core.database import get_db
        from app.model.electricity import ElectricityRecord
        session = get_db()
        try:
            count = session.query(ElectricityRecord).count()
            return count > 0
        finally:
            session.close()
    except Exception:
        return False


def _fetch_and_save(max_pages: int = None) -> tuple:
    """
    爬取最新数据并保存到文件 + 数据库

    爬取策略：
    - 首次爬取：全量爬取（最多50页），获取所有历史数据
    - 日常爬取：只爬1页，获取最新数据，避免给服务器造成压力
    - 数据库无数据时：全量爬取

    Args:
        max_pages: 指定爬取页数，None 则自动判断

    Returns:
        (success: bool, message: str)
    """
    from app.modules.electricity.crawler import set_electricity_spider_running
    set_electricity_spider_running(True)
    
    try:
        crawler = _make_crawler()
        remaining = crawler.fetch_remaining_power()

        # 判断是否首次爬取，决定爬取页数
        if max_pages is None:
            is_first = _is_first_fetch()
            if is_first:
                max_pages = None  # 使用默认值（50页），全量爬取
                logger.info('[电量] 首次爬取，执行全量爬取')
            else:
                max_pages = 1  # 日常只爬1页
                logger.info('[电量] 非首次爬取，只爬取最新1页')
        else:
            # 指定了页数，但检查数据库是否有数据
            # 如果数据库无数据，则全量爬取
            if not _has_data():
                max_pages = None  # 全量爬取
                logger.info('[电量] 数据库无数据，执行全量爬取')
            else:
                logger.info(f'[电量] 指定爬取 {max_pages} 页')

        records = crawler.fetch_usage_records(max_pages=max_pages)

        # 保存用电记录到 JSON 文件（兼容旧逻辑）
        records_path = _records_path()
        with open(records_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        # 保存剩余电量到 JSON 文件
        if remaining:
            remaining_path = _remaining_path()
            with open(remaining_path, 'w', encoding='utf-8') as f:
                json.dump(remaining, f, ensure_ascii=False, indent=2)

        # 保存到数据库（直接保存，不再重复调用爬虫）
        from app.core.database import get_db
        from app.repository.electricity_repository import ElectricityRepository
        from app.modules.electricity.capacity_manager import get_capacity_manager
        from datetime import datetime

        session = get_db()
        try:
            # 保存剩余电量
            remaining_value = remaining
            if isinstance(remaining, dict):
                remaining_value = remaining.get('default', 0)
            remaining_float = float(remaining_value) if remaining_value else 0.0

            ElectricityRepository.create_remaining(
                session=session,
                remaining=remaining_float,
                meter='default',
            )
            session.commit()

            # 更新容量管理器
            capacity_manager = get_capacity_manager()
            capacity_manager.update_remaining(
                current_remaining=remaining_float,
                low_power_threshold=10.0,
            )

            # 批量保存用电记录
            record_tuples = []
            for r in records:
                record_time = None
                if r.get('time'):
                    time_str = r['time']
                    # 尝试多种时间格式解析
                    try:
                        # ISO 格式: 2026-06-29T11:00:00
                        if 'T' in time_str:
                            record_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                        # 空格分隔格式: 2026-06-29 11:00:00
                        else:
                            record_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    except Exception as time_exc:
                        logger.warning(f'[电量] 时间解析失败: {time_str}, 错误: {time_exc}')
                        record_time = datetime.utcnow()
                else:
                    record_time = datetime.utcnow()
                
                record_tuples.append((
                    record_time,
                    float(r.get('usage', 0)) if r.get('usage') else 0.0,
                    r.get('meter', 'default'),
                ))

            created = ElectricityRepository.create_records_batch(session, record_tuples)
            session.commit()

            logger.info(f'电量数据已保存: {created} 条记录，剩余 {remaining}')
        finally:
            session.close()

        logger.info(f'电量数据爬取完成: {len(records)} 条记录，剩余 {remaining}')
        set_electricity_spider_running(False, 'success')
        return True, f'爬取成功，获取 {len(records)} 条记录'
    except Exception as exc:
        msg = f'电量数据爬取失败: {exc}'
        logger.error(msg)
        set_electricity_spider_running(False, 'failed')
        return False, msg


def fetch_electricity_data() -> None:
    """仅爬取并保存电量数据，不推送消息（供手动触发使用）"""
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('爬取电量数据', 'electricity', total_items=1)
    logger.info('[电量] 开始爬取电量数据')
    success, msg = _fetch_and_save()
    if success:
        logger.info(f'[电量] 数据爬取完成: {msg}')
        complete_task_process(pid, 'completed', msg)
    else:
        logger.error(f'[电量] 数据爬取失败: {msg}')
        complete_task_process(pid, 'failed', error=msg)


def _load_last_low_power_time() -> Optional[datetime]:
    state_file = _low_power_state_path()
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                ts = f.read().strip()
            if ts:
                return datetime.fromisoformat(ts)
    except Exception as exc:
        logger.warning(f'加载低电量状态失败: {exc}')
    return None


def _save_last_low_power_time(dt: datetime) -> None:
    state_file = _low_power_state_path()
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            f.write(dt.isoformat())
    except Exception as exc:
        logger.warning(f'保存低电量状态失败: {exc}')


# ------------------------------------------------------------------
# 对外暴露的任务函数
# ------------------------------------------------------------------

def push_electricity_daily() -> None:
    """每日用电报告定时任务"""
    # 假期模式：静默面向用户的电量推送（入口建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service
    if holiday_service.skip_if_active('每日用电报告', 'electricity'):
        return
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('每日用电报告', 'electricity', total_items=1)
    logger.info('[电量] 开始执行每日推送任务')
    try:
        from app.modules.electricity.formatter import ElectricityFormatter

        success, msg = _fetch_and_save()
        if not success:
            _send_markdown(ElectricityFormatter.format_fetch_error('每日用电报告', msg), notify_only=False)
            complete_task_process(pid, 'failed', error=msg)
            return

        stats_obj = _make_stats()
        target_date = datetime.now() - timedelta(days=1)
        stats = stats_obj.get_daily_statistics(target_date)
        remaining = stats_obj.get_remaining_power()

        if stats:
            _send_markdown(ElectricityFormatter.format_daily(stats, remaining))
            logger.info('[电量] 每日推送完成')
        else:
            date_str = target_date.strftime('%Y-%m-%d')
            notice = (
                f'**每日用电报告**\n\n**日期**: {date_str}\n\n'
                f'未找到昨日用电数据\n\n'
                f'**剩余电量**: {remaining.get("default", "未知")} 度\n\n'
                f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'
            )
            _send_markdown(notice)
            logger.warning(f'[电量] 每日推送：{date_str} 无数据，已发送状态通知')

        # 独立检查低电量
        _check_low_power_internal(remaining)
        complete_task_process(pid, 'completed', '每日用电报告推送完成')
    except Exception as exc:
        logger.error(f'[电量] 每日推送任务异常: {exc}', exc_info=True)
        complete_task_process(pid, 'failed', error=str(exc))


def push_electricity_weekly() -> None:
    """每周用电报告定时任务"""
    # 假期模式：静默面向用户的电量推送（入口建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service
    if holiday_service.skip_if_active('每周用电报告', 'electricity'):
        return
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('每周用电报告', 'electricity', total_items=1)
    logger.info('[电量] 开始执行每周推送任务')
    try:
        from app.modules.electricity.formatter import ElectricityFormatter

        # 周报爬1页（数据库无数据时自动全量爬取）
        success, msg = _fetch_and_save(max_pages=1)
        if not success:
            _send_markdown(ElectricityFormatter.format_fetch_error('每周用电报告', msg))
            complete_task_process(pid, 'failed', error=msg)
            return

        stats_obj = _make_stats()
        today = datetime.now()
        # 周一推送上一周，其他日子推送本周
        if today.weekday() == 0:
            week_end = today - timedelta(days=1)
        else:
            week_end = today
        stats = stats_obj.get_weekly_statistics(week_end)
        remaining = stats_obj.get_remaining_power()

        if stats:
            _send_markdown(ElectricityFormatter.format_weekly(stats, remaining))
            # 尝试发送图表
            try:
                chart_gen = _make_chart_gen()
                week_start_str = stats['start_date']
                week_start = datetime.strptime(week_start_str, '%Y-%m-%d')
                chart_path = chart_gen.generate_weekly_chart(week_start)
                if chart_path:
                    _send_image(chart_path)
            except Exception as exc:
                logger.warning(f'[电量] 周报图表生成/发送失败: {exc}')
            logger.info('[电量] 每周推送完成')
        else:
            notice = (
                f'**每周用电报告**\n\n**周期**: {stats_obj.get_weekly_statistics(week_end) or "未知"}\n\n'
                f'未找到本周用电数据\n\n'
                f'**剩余电量**: {remaining.get("default", "未知")} 度\n\n'
                f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'
            )
            _send_markdown(notice)
            logger.warning('[电量] 每周推送：无数据，已发送状态通知')
        complete_task_process(pid, 'completed', '每周用电报告推送完成')
    except Exception as exc:
        logger.error(f'[电量] 每周推送任务异常: {exc}', exc_info=True)
        complete_task_process(pid, 'failed', error=str(exc))


def push_electricity_monthly() -> None:
    """每月用电报告定时任务"""
    # 假期模式：静默面向用户的电量推送（入口建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service
    if holiday_service.skip_if_active('每月用电报告', 'electricity'):
        return
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('每月用电报告', 'electricity', total_items=1)
    logger.info('[电量] 开始执行每月推送任务')
    try:
        from app.modules.electricity.formatter import ElectricityFormatter

        # 月报爬2页（数据库无数据时自动全量爬取）
        success, msg = _fetch_and_save(max_pages=2)
        if not success:
            _send_markdown(ElectricityFormatter.format_fetch_error('每月用电报告', msg))
            complete_task_process(pid, 'failed', error=msg)
            return

        stats_obj = _make_stats()
        today = datetime.now()
        # 推送上个月
        last_month_last_day = today.replace(day=1) - timedelta(days=1)
        stats = stats_obj.get_monthly_statistics(last_month_last_day)
        remaining = stats_obj.get_remaining_power()

        if stats:
            _send_markdown(ElectricityFormatter.format_monthly(stats, remaining))
            try:
                chart_gen = _make_chart_gen()
                chart_path = chart_gen.generate_monthly_chart(stats['year'], stats['month'])
                if chart_path:
                    _send_image(chart_path)
            except Exception as exc:
                logger.warning(f'[电量] 月报图表生成/发送失败: {exc}')
            logger.info('[电量] 每月推送完成')
        else:
            y = last_month_last_day.year
            m = last_month_last_day.month
            notice = (
                f'**每月用电报告**\n\n**月份**: {y}年{m}月\n\n'
                f'未找到上月用电数据\n\n'
                f'**剩余电量**: {remaining.get("default", "未知")} 度\n\n'
                f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'
            )
            _send_markdown(notice)
            logger.warning('[电量] 每月推送：无数据，已发送状态通知')
        complete_task_process(pid, 'completed', '每月用电报告推送完成')
    except Exception as exc:
        logger.error(f'[电量] 每月推送任务异常: {exc}', exc_info=True)
        complete_task_process(pid, 'failed', error=str(exc))


def check_cookie_validity() -> None:
    """Cookie 有效性检测任务"""
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('Cookie有效性检测', 'electricity', total_items=1)
    logger.info('[电量] 开始检测 Cookie 有效性')
    from app.modules.electricity.formatter import ElectricityFormatter
    try:
        crawler = _make_crawler()
        is_valid, reason = crawler.check_cookie_valid()
        if not is_valid:
            _send_markdown(ElectricityFormatter.format_cookie_invalid(reason))
            logger.warning(f'[电量] Cookie 失效: {reason}')
            complete_task_process(pid, 'failed', f'Cookie 失效: {reason}')
        else:
            logger.info('[电量] Cookie 有效性检测通过')
            complete_task_process(pid, 'completed', 'Cookie 有效')
    except Exception as exc:
        logger.error(f'[电量] Cookie 检测异常: {exc}')
        complete_task_process(pid, 'failed', error=str(exc))


def check_low_power() -> None:
    """低电量检测任务（独立触发，每 4 小时一次）"""
    # 假期模式：低电量提醒属面向用户推送，假期静默（建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service
    if holiday_service.skip_if_active('低电量检测', 'electricity'):
        return
    logger.info('[电量] 开始低电量检测')
    stats_obj = _make_stats()
    remaining = stats_obj.get_remaining_power()
    _check_low_power_internal(remaining)


def push_electricity_full_crawl() -> None:
    """全量爬取定时任务（每周执行一次，获取完整历史数据）"""
    # 假期模式：静默面向用户的电量推送（入口建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service
    if holiday_service.skip_if_active('电量全量爬取', 'electricity'):
        return
    from app.api.process_routes import create_task_process, complete_task_process
    pid = create_task_process('电量全量爬取', 'electricity', total_items=1)
    logger.info('[电量] 开始执行全量爬取任务')
    try:
        # 强制全量爬取：忽略首次/非首次判断，最多50页
        success, msg = _fetch_and_save(max_pages=50)
        if not success:
            complete_task_process(pid, 'failed', error=msg)
            return

        from app.modules.electricity.formatter import ElectricityFormatter
        stats_obj = _make_stats()
        remaining = stats_obj.get_remaining_power()

        # 全量爬取完成后发送简要报告
        notice = (
            f'**电量全量爬取报告**\n\n'
            f'{msg}\n\n'
            f'**剩余电量**: {remaining.get("default", "未知")} 度\n\n'
            f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        )
        _send_markdown(notice)
        logger.info(f'[电量] 全量推送完成: {msg}')
        complete_task_process(pid, 'completed', msg)
    except Exception as exc:
        logger.error(f'[电量] 全量爬取任务异常: {exc}')
        complete_task_process(pid, 'failed', error=str(exc))


def _check_low_power_internal(remaining: dict) -> None:
    """内部低电量检测逻辑（可被日报任务复用）"""
    from app.modules.electricity.formatter import ElectricityFormatter
    from app.core.config import Config

    threshold = float(getattr(Config, 'ELECTRICITY_LOW_POWER_THRESHOLD', 10.0))
    reminder_interval_hours = float(getattr(Config, 'ELECTRICITY_LOW_POWER_INTERVAL_HOURS', 4.0))

    power_val = remaining.get('default')
    if power_val is None:
        return

    try:
        power_val = float(power_val)
    except (TypeError, ValueError):
        return

    if power_val > threshold:
        return

    # 检查是否在提醒间隔内
    last_reminder = _load_last_low_power_time()
    if last_reminder:
        elapsed_hours = (datetime.now() - last_reminder).total_seconds() / 3600
        if elapsed_hours < reminder_interval_hours:
            logger.info(
                f'[电量] 低电量提醒跳过：距上次 {elapsed_hours:.1f} 小时 < {reminder_interval_hours} 小时'
            )
            return

    _send_markdown(ElectricityFormatter.format_low_power_alert(power_val))
    _save_last_low_power_time(datetime.now())
    logger.warning(f'[电量] 低电量提醒已发送: 剩余 {power_val:.2f} 度')


def update_cookie_in_memory(new_cookie: str) -> bool:
    """
    运行时更新 Config 内存中的 Cookie，爬虫下次执行立即使用

    Returns:
        是否成功
    """
    try:
        from app.core import config as cfg_module
        cfg_module.Config.ELECTRICITY_CRAWLER_COOKIE = new_cookie
        logger.info('[电量] Cookie 已更新至内存配置')
        return True
    except Exception as exc:
        logger.error(f'[电量] 更新 Cookie 失败: {exc}')
        return False


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
    daily_time = config_svc.get('electricity', 'schedule_daily', None) or app.config.get('ELECTRICITY_SCHEDULE_DAILY', '00:30')
    weekly_day = config_svc.get('electricity', 'schedule_weekly_day', None) or app.config.get('ELECTRICITY_SCHEDULE_WEEKLY_DAY', 'mon')
    weekly_time = config_svc.get('electricity', 'schedule_weekly', None) or app.config.get('ELECTRICITY_SCHEDULE_WEEKLY', '00:30')
    monthly_day = int(config_svc.get('electricity', 'schedule_monthly_day', None) or app.config.get('ELECTRICITY_SCHEDULE_MONTHLY_DAY', 1))
    monthly_time = config_svc.get('electricity', 'schedule_monthly', None) or app.config.get('ELECTRICITY_SCHEDULE_MONTHLY', '00:30')
    cookie_check_time = config_svc.get('electricity', 'cookie_check_time', None) or app.config.get('ELECTRICITY_COOKIE_CHECK_TIME', '20:00')
    # 低电量检测间隔（小时），优先读数据库
    low_power_interval = float(config_svc.get('electricity', 'low_power_interval_hours', None) or app.config.get('ELECTRICITY_LOW_POWER_INTERVAL_HOURS', 4.0))

    d_hour, d_min = map(int, daily_time.split(':'))
    w_hour, w_min = map(int, weekly_time.split(':'))
    m_hour, m_min = map(int, monthly_time.split(':'))
    ck_hour, ck_min = map(int, cookie_check_time.split(':'))

    scheduler.add_job(
        push_electricity_daily,
        trigger=CronTrigger(hour=d_hour, minute=d_min),
        id='electricity_daily',
        name='电量每日报告',
        replace_existing=True,
    )
    logger.info(f'[电量] 每日任务已注册: 每天 {daily_time}')

    scheduler.add_job(
        push_electricity_weekly,
        trigger=CronTrigger(day_of_week=weekly_day, hour=w_hour, minute=w_min),
        id='electricity_weekly',
        name='电量每周报告',
        replace_existing=True,
    )
    logger.info(f'[电量] 每周任务已注册: 每{weekly_day} {weekly_time}')

    scheduler.add_job(
        push_electricity_monthly,
        trigger=CronTrigger(day=monthly_day, hour=m_hour, minute=m_min),
        id='electricity_monthly',
        name='电量每月报告',
        replace_existing=True,
    )
    logger.info(f'[电量] 每月任务已注册: 每月{monthly_day}日 {monthly_time}')

    scheduler.add_job(
        check_cookie_validity,
        trigger=CronTrigger(hour=ck_hour, minute=ck_min),
        id='electricity_cookie_check',
        name='电量 Cookie 检测',
        replace_existing=True,
    )
    logger.info(f'[电量] Cookie 检测任务已注册: 每天 {cookie_check_time}')

    # 低电量检测：使用配置的间隔（小时），最小 1 小时，最大 24 小时
    low_power_hours = max(1, min(24, int(low_power_interval)))
    scheduler.add_job(
        check_low_power,
        trigger=CronTrigger(hour=f'*/{low_power_hours}', minute=0),
        id='electricity_low_power',
        name='电量低电量检测',
        replace_existing=True,
    )
    logger.info(f'[电量] 低电量检测任务已注册: 每 {low_power_hours} 小时')

    # 电量全量爬取：每周日凌晨执行一次（获取完整历史数据）
    full_crawl_day = int(config_svc.get('electricity', 'full_crawl_day', None) or app.config.get('ELECTRICITY_FULL_CRAWL_DAY', 0))  # 0=周日
    full_crawl_time = config_svc.get('electricity', 'full_crawl_time', None) or app.config.get('ELECTRICITY_FULL_CRAWL_TIME', '03:00')
    try:
        fc_hour, fc_min = map(int, str(full_crawl_time).split(':'))
    except (ValueError, AttributeError):
        fc_hour, fc_min = 3, 0

    scheduler.add_job(
        push_electricity_full_crawl,
        trigger=CronTrigger(day_of_week=str(full_crawl_day), hour=fc_hour, minute=fc_min),
        id='electricity_full_crawl',
        name='电量全量爬取',
        replace_existing=True,
    )
    logger.info(f'[电量] 全量爬取任务已注册: 每周{full_crawl_day} {full_crawl_time}')
