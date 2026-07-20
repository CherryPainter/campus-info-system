#!/usr/bin/env python3
"""
天气子模块定时任务
向 Push_System_Flask APScheduler 注册天气相关调度任务
"""

import os
import threading
from datetime import date, datetime

from app.core.logger import get_logger

logger = get_logger(__name__)

# TTL 配置（秒）
_CACHE_TTL_NOW: int = 30 * 60  # 实时天气缓存 30 分钟
_CACHE_TTL_HOURLY: int = 60 * 60  # 逐小时预报缓存 60 分钟
_CACHE_TTL_ALERT: int = 10 * 60  # 预警缓存 10 分钟


# ------------------------------------------------------------------
# 夜间静默工具
# ------------------------------------------------------------------


def _is_in_quiet_hours() -> bool:
    """检查当前时间是否处于夜间免打扰时段

    从数据库配置读取 quiet_hours_enabled / quiet_hours_start / quiet_hours_end，
    若未配置则回退到默认值 23:00-07:00。

    Returns:
        True 表示当前在静默时段内，不应推送天气消息
    """
    try:
        from app.services.config_service import get_config_service

        config_svc = get_config_service()
        enabled = config_svc.get("weather", "quiet_hours_enabled", "true")
        if str(enabled).lower() in ("false", "0", "no", "off"):
            return False

        start_str = config_svc.get("weather", "quiet_hours_start", "23:00")
        end_str = config_svc.get("weather", "quiet_hours_end", "07:00")
    except Exception:
        start_str, end_str = "23:00", "07:00"

    try:
        s_h, s_m = map(int, str(start_str).split(":"))
        e_h, e_m = map(int, str(end_str).split(":"))
    except (ValueError, AttributeError):
        return False

    from datetime import datetime as _dt
    from datetime import time as _time

    now = _dt.now().time()
    start = _time(s_h, s_m)
    end = _time(e_h, e_m)

    # 处理跨午夜的情况（如 23:00 - 07:00）
    # 结束时间取半开区间（< end）：边界整点（如 07:00）属于“已醒来”，
    # 避免每日晨报（默认 07:00）被静默时段吞掉
    if start <= end:
        return start <= now < end
    else:
        return now >= start or now < end


# ------------------------------------------------------------------
# 延迟工厂函数（避免 import 时 Config 未就绪）
# ------------------------------------------------------------------


def _make_fetcher():
    """延迟创建 WeatherFetcher，从 Config 读取配置。"""
    from app.core.config import Config
    from app.modules.weather.fetcher import WeatherFetcher

    # 构建 location 格式：优先使用 QWEATHER_LOCATION，否则使用经纬度
    location = getattr(Config, "QWEATHER_LOCATION", None)
    if not location:
        # 使用经纬度格式 "longitude,latitude"
        longitude = getattr(Config, "QWEATHER_LONGITUDE", "106.55")
        latitude = getattr(Config, "QWEATHER_LATITUDE", "29.56")
        location = f"{longitude},{latitude}"

    # 获取私钥路径（支持相对路径和绝对路径）
    private_key_path = getattr(Config, "QWEATHER_PRIVATE_KEY_PATH", "ed25519-private.pem")
    if not os.path.isabs(private_key_path):
        # 如果是相对路径，基于项目根目录解析
        private_key_path = os.path.join(Config.BASE_DIR, private_key_path)

    return WeatherFetcher(
        api_key=getattr(Config, "QWEATHER_API_KEY", ""),
        location=location,
        api_host=getattr(Config, "QWEATHER_API_HOST", "https://devapi.qweatherapi.com"),
        credential_id=getattr(Config, "QWEATHER_CREDENTIAL_ID", ""),
        project_id=getattr(Config, "QWEATHER_PROJECT_ID", ""),
        private_key_path=private_key_path,
    )


def _make_cache():
    """延迟创建 WeatherCache。"""
    from app.modules.weather.cache import WeatherCache

    return WeatherCache()


def _make_analyzer():
    """延迟创建 WeatherAnalyzer。"""
    from app.core.config import Config
    from app.modules.weather.analyzer import WeatherAnalyzer

    state_dir = getattr(
        Config, "QWEATHER_DATA_DIR", os.path.join(Config.BASE_DIR, "data", "weather")
    )
    return WeatherAnalyzer(state_dir)


# ------------------------------------------------------------------
# 推送辅助
# ------------------------------------------------------------------


def _send_markdown(content: str, *, notify_only: bool = False) -> None:
    """通过 adapter_service 发送 Markdown 消息。"""
    # 假期模式：静默全体面向用户的天气推送（系统/安全告警不走此函数，不受影响）
    from app.services.holiday_service import holiday_service

    if holiday_service.is_active()[0]:
        logger.info("[天气] 假期模式静默，跳过发送")
        return

    from app.services.adapter_service import adapter_service

    # 使用天气专用适配器
    adapter = adapter_service.get_adapter("weather")
    if adapter is None:
        logger.error("_send_markdown: weather 适配器未初始化")
        return
    adapter.send({"msgtype": "markdown", "markdown": {"content": content}})


# ------------------------------------------------------------------
# 推送守卫：夜间免打扰 + 每日上限
# ------------------------------------------------------------------
_PUSH_COUNT_KEY = "weather_daily_push_count"


def _parse_dt(value):
    """将字符串时间解析为 datetime（无时区），失败返回 None。"""
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def _get_today_push_count() -> int:
    """返回今日已推送天气消息条数（跨午夜自动归零）。"""
    try:
        cache = _make_cache()
        data = cache.get(_PUSH_COUNT_KEY) or {}
        today = date.today().isoformat()
        if data.get("date") != today:
            return 0
        return int(data.get("count", 0))
    except Exception:
        return 0


def _inc_today_push_count() -> int:
    """递增并返回今日推送计数。"""
    try:
        cache = _make_cache()
        today = date.today().isoformat()
        data = cache.get(_PUSH_COUNT_KEY) or {}
        if data.get("date") != today:
            data = {"date": today, "count": 0}
        data["count"] = int(data.get("count", 0)) + 1
        cache.set(_PUSH_COUNT_KEY, data, 24 * 3600)
        return data["count"]
    except Exception:
        return 0


def _maybe_push(content: str) -> bool:
    """统一的天气推送出口：先判夜间免打扰与每日上限，再发送。

    Returns:
        True 表示已推送，False 表示被抑制（免打扰/达上限）。
    """
    if _is_in_quiet_hours():
        logger.info("[天气] 推送被抑制：处于夜间免打扰时段")
        return False
    try:
        from app.services.config_service import get_config_service

        limit = int(get_config_service().get("weather", "daily_push_limit", 8) or 0)
    except Exception:
        limit = 8
    if limit > 0 and _get_today_push_count() >= limit:
        logger.info(f"[天气] 推送被抑制：已达每日上限({limit}条)")
        return False
    _send_markdown(content)
    _inc_today_push_count()
    return True


# ------------------------------------------------------------------
# 定时更新任务（仅更新缓存，不推送）
# ------------------------------------------------------------------


def update_weather_now() -> None:
    """每 30 分钟更新实时天气（更新缓存 + 保存数据库）。"""
    # 假期模式：静默期间不刷新天气缓存（提前返回，避免刷屏进程表）
    from app.services.holiday_service import holiday_service

    if holiday_service.skip_if_active("更新实时天气", "weather", record=False):
        return
    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("更新实时天气", "weather", total_items=1)
    logger.info("[天气] 开始更新实时天气")
    try:
        fetcher = _make_fetcher()
        cache = _make_cache()
        data = fetcher.fetch_now()
        if data:
            cache.set("now", data, _CACHE_TTL_NOW)
            from app.services.weather_service import WeatherService

            svc = WeatherService(fetcher)
            svc.fetch_and_save_now()
            logger.info("[天气] 实时天气已更新（缓存+数据库）")
            complete_task_process(pid, "completed", "实时天气更新成功")
        else:
            logger.warning("[天气] 实时天气数据为空")
            complete_task_process(pid, "failed", "实时天气数据为空")
    except Exception as exc:
        logger.error(f"[天气] 更新实时天气失败: {exc}")
        complete_task_process(pid, "failed", error=str(exc))


# 保留旧名称作为别名，兼容已有代码
update_now_weather = update_weather_now


def update_weather_hourly() -> None:
    """每 60 分钟更新逐小时天气预报（更新缓存 + 保存数据库）。"""
    # 假期模式：静默期间不刷新天气缓存（提前返回，避免刷屏进程表）
    from app.services.holiday_service import holiday_service

    if holiday_service.skip_if_active("更新逐小时预报", "weather", record=False):
        return
    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("更新逐小时预报", "weather", total_items=1)
    logger.info("[天气] 开始更新逐小时预报")
    try:
        fetcher = _make_fetcher()
        cache = _make_cache()
        data = fetcher.fetch_hourly()
        if data:
            cache.set("hourly", data, _CACHE_TTL_HOURLY)
            from app.services.weather_service import WeatherService

            svc = WeatherService(fetcher)
            svc.fetch_and_save_hourly()
            logger.info("[天气] 逐小时预报已更新（缓存+数据库）")
            complete_task_process(pid, "completed", "逐小时预报更新成功")
        else:
            logger.warning("[天气] 逐小时预报数据为空")
            complete_task_process(pid, "failed", "逐小时预报数据为空")
    except Exception as exc:
        logger.error(f"[天气] 更新逐小时预报失败: {exc}")
        complete_task_process(pid, "failed", error=str(exc))


# 保留旧名称作为别名，兼容已有代码
update_hourly_weather = update_weather_hourly


_alert_update_lock = threading.Lock()


def update_weather_alert() -> None:
    """每 10 分钟更新天气预警（有新预警时触发推送）。"""
    # 假期模式：静默期间不更新天气预警缓存（提前返回，避免刷屏进程表）
    from app.services.holiday_service import holiday_service

    if holiday_service.skip_if_active("更新天气预警", "weather", record=False):
        return
    # 防止并发执行：如果上一次还在跑，直接跳过
    if not _alert_update_lock.acquire(blocking=False):
        logger.warning("[天气] 天气预警更新任务已在执行中，跳过本次调用")
        return

    try:
        _update_weather_alert_impl()
    finally:
        _alert_update_lock.release()


def _update_weather_alert_impl() -> None:
    """实际执行天气预警更新逻辑（含数据库持久化和时效性检查）"""
    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("更新天气预警", "weather", total_items=1)
    logger.info("[天气] 开始更新天气预警缓存")
    try:
        fetcher = _make_fetcher()
        cache = _make_cache()
        data = fetcher.fetch_alert()
        cache.set("alert", {"warnings": data}, _CACHE_TTL_ALERT)

        # 将预警数据持久化到数据库（修复：之前只存缓存不存DB，导致历史记录为空）
        if data:
            try:
                from datetime import datetime as _dt

                from app.core.database import get_db
                from app.repository.weather_repository import WeatherRepository

                session = get_db()
                try:
                    current_ids = set()
                    now_dt = _dt.now()

                    # 预警归属城市（用于历史记录展示）
                    try:
                        from app.services.config_service import get_config_service

                        _city_name = (
                            get_config_service().get("weather", "city_name", "重庆") or "重庆"
                        )
                    except Exception:
                        _city_name = "重庆"

                    for alert in data:
                        alert_id = alert.get("id", "")
                        if not alert_id:
                            continue
                        current_ids.add(alert_id)

                        # 检查是否已存在
                        if WeatherRepository.alert_exists(session, alert_id):
                            continue

                        # 预警时效性检查：已过期的预警不入库
                        end_time_str = alert.get("end_time", "")
                        end_dt = _parse_dt(end_time_str)
                        if end_dt is not None:
                            try:
                                if now_dt > end_dt:
                                    logger.info(
                                        f"[天气] 预警 {alert_id} 已过期({end_time_str})，跳过入库"
                                    )
                                    continue
                            except (ValueError, TypeError):
                                pass

                        # 存入数据库（修正参数签名，匹配 WeatherRepository.create_alert）
                        _severity = (
                            alert.get("severity", "") or alert.get("color_code", "") or "unknown"
                        )
                        _color_code = (
                            alert.get("color_code", "") or alert.get("severity", "") or "unknown"
                        )
                        WeatherRepository.create_alert(
                            session=session,
                            alert_id=alert_id,
                            city_name=_city_name,
                            headline=alert.get("headline", ""),
                            event_type=alert.get("event_type", ""),
                            severity=_severity,
                            color_code=_color_code,
                            description=alert.get("description", ""),
                            start_time=_parse_dt(alert.get("start_time", "")),
                            end_time=end_dt,
                        )
                        logger.debug(f'[天气] 预警已入库: {alert_id} - {alert.get("headline", "")}')

                    # 将 API 不再返回的旧活跃预警标记为解除
                    active_alerts = WeatherRepository.get_active_alerts(session)
                    for aa in active_alerts:
                        if aa.alert_id not in current_ids:
                            WeatherRepository.deactivate_alert(session, aa.alert_id)
                            logger.info(
                                f'[天气] 预警已自动解除: {aa.alert_id} - {(aa.headline or "")}'
                            )

                    session.commit()
                finally:
                    session.close()

                    logger.info(f"[天气] 预警数据已持久化: {len(data)} 条")
            except Exception as db_exc:
                logger.warning(f"[天气] 预警持久化失败(不影响推送): {db_exc}")

            _check_and_push_new_alerts(data, cache)
        else:
            # 无预警时，也检查并清除数据库中的过期预警
            try:
                from app.core.database import get_db
                from app.repository.weather_repository import WeatherRepository

                session = get_db()
                try:
                    active_alerts = WeatherRepository.get_active_alerts(session)
                    for aa in active_alerts:
                        WeatherRepository.deactivate_alert(session, aa.alert_id)
                    if active_alerts:
                        session.commit()
                        logger.info(f"[天气] 已清除 {len(active_alerts)} 条过期预警")
                finally:
                    session.close()
            except Exception:
                pass

            logger.debug("[天气] 当前无天气预警")

        logger.info("[天气] 天气预警缓存已更新")
        complete_task_process(
            pid, "completed", f"天气预警更新完成，{len(data) if data else 0} 条预警"
        )
    except Exception as exc:
        logger.error(f"[天气] 更新天气预警缓存失败: {exc}")
        complete_task_process(pid, "failed", error=str(exc))


# 保留旧名称作为别名，兼容已有代码
update_alert_weather = update_weather_alert


def _check_and_push_new_alerts(alerts: list, cache) -> None:
    """检查预警是否有更新，有新预警时推送。

    去重策略（根治“同内容反复推送”）：
    1. 同批次内按 (event_type, headline) 去重，内容相同的预警只处理一条；
    2. 跨批次/跨进程重启：基于数据库 weather_alerts.is_pushed 比对，
       已推送过的预警不再推送（内存缓存重启即丢，不可靠，已弃用）。
    """
    # 夜间免打扰：安静时段内不推送预警（预警数据仍会入库，历史正常）
    if _is_in_quiet_hours():
        logger.info("[天气] 预警推送跳过：当前处于夜间免打扰时段")
        return

    # 预警总开关
    try:
        from app.services.config_service import get_config_service

        alert_enabled = str(
            get_config_service().get("weather", "alert_enabled", "true")
        ).lower() not in ("false", "0", "no", "off")
    except Exception:
        alert_enabled = True

    if not alert_enabled:
        logger.info("[天气] 预警推送已关闭（alert_enabled=false），跳过预警推送")
        return

    if not alerts:
        return

    from app.core.database import get_db
    from app.modules.weather.message import WeatherFormatter
    from app.repository.weather_repository import WeatherRepository

    # 同批次按 (event_type, headline) 去重，避免内容相同的预警重复推送
    seen_keys: set = set()
    deduped = []
    for a in alerts:
        key = (a.get("event_type", ""), a.get("headline", ""))
        if key in seen_keys:
            logger.debug(f'[天气] 同批内容去重，跳过重复预警: {a.get("headline", "")}')
            continue
        seen_keys.add(key)
        deduped.append(a)

    analyzer = _make_analyzer()
    session = get_db()
    try:
        for alert in deduped:
            aid = alert.get("id", "")
            if not aid:
                continue

            # 已推送过则跳过去重（数据库比对，重启后仍有效）
            if WeatherRepository.is_alert_pushed(session, aid):
                logger.info(f'[天气] 预警已推送过，跳过去重: {aid} - {alert.get("headline", "")}')
                continue

            events = analyzer.analyze(None, None, [alert])
            for event in events:
                if event.get("type") == "alert":
                    message = WeatherFormatter.format_weather_alert(event)
                    if _maybe_push(message):
                        logger.info(f'[天气] 新预警已推送: {alert.get("headline", "")}')
                        # 仅推送成功才标记已推送，避免被限流抑制后永久丢失
                        WeatherRepository.mark_alert_pushed(session, aid)
                    else:
                        logger.info(f"[天气] 预警被抑制未推送（免打扰/达上限），暂不标记: {aid}")
                    break  # 一次只推送一条
        session.commit()
    except Exception as exc:
        logger.error(f"[天气] 预警推送去重失败: {exc}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()


# ------------------------------------------------------------------
# 推送任务
# ------------------------------------------------------------------


def push_weather_daily() -> None:
    """每日晨报推送任务。"""
    # 假期模式：静默全体面向用户的天气推送（入口建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service

    if holiday_service.skip_if_active("每日天气晨报", "weather"):
        return
    # 夜间静默检查
    if _is_in_quiet_hours():
        logger.info("[天气] 每日晨报跳过：当前处于夜间免打扰时段")
        return

    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("每日天气晨报", "weather", total_items=1)
    logger.info("[天气] 开始执行每日晨报推送")
    try:
        cache = _make_cache()
        fetcher = None  # 延迟创建，按需使用

        now_data = cache.get("now")
        if not now_data:
            fetcher = _make_fetcher()
            now_data = fetcher.fetch_now()
            if now_data:
                cache.set("now", now_data, _CACHE_TTL_NOW)

        hourly_data = cache.get("hourly")
        if not hourly_data:
            if fetcher is None:
                fetcher = _make_fetcher()
            hourly_data = fetcher.fetch_hourly()
            if hourly_data:
                cache.set("hourly", hourly_data, _CACHE_TTL_HOURLY)

        if not now_data:
            from app.modules.weather.message import WeatherFormatter

            _send_markdown(WeatherFormatter.format_fetch_error("每日晨报", "实时天气数据获取失败"))
            complete_task_process(pid, "failed", "实时天气数据获取失败")
            return

        alert_cache = cache.get("alert")
        alerts_count = 0
        if alert_cache and isinstance(alert_cache.get("warnings"), list):
            alerts_count = len(alert_cache["warnings"])

        analyzer = _make_analyzer()
        hourly_list = hourly_data if isinstance(hourly_data, list) else []
        analysis = analyzer.get_daily_summary(now_data, hourly_list)
        analysis["alerts_count"] = alerts_count

        from app.modules.weather.message import WeatherFormatter

        message = WeatherFormatter.format_daily_report(now_data, analysis)
        if _maybe_push(message):
            logger.info("[天气] 每日晨报推送完成")
        else:
            logger.info("[天气] 每日晨报被抑制（免打扰/达上限）")
        complete_task_process(pid, "completed", "每日晨报推送完成")
    except Exception as exc:
        logger.error(f"[天气] 每日晨报推送失败: {exc}")
        from app.modules.weather.message import WeatherFormatter

        _send_markdown(WeatherFormatter.format_fetch_error("每日晨报", str(exc)))
        complete_task_process(pid, "failed", error=str(exc))


# 保留旧名称作为别名，兼容已有代码
send_daily_report = push_weather_daily


def push_weather_analysis() -> None:
    """分析+条件推送任务。"""
    # 假期模式：静默全体面向用户的天气推送（入口建 skipped 记录后跳过）
    from app.services.holiday_service import holiday_service

    if holiday_service.skip_if_active("天气分析推送", "weather"):
        return
    # 夜间静默检查：静默时段内不推送分析消息（数据更新照常进行）
    if _is_in_quiet_hours():
        logger.info("[天气] 分析推送跳过：当前处于夜间免打扰时段")
        return

    from app.services.process_service import complete_task_process, create_task_process

    pid = create_task_process("天气分析推送", "weather", total_items=1)
    logger.info("[天气] 开始执行分析推送任务")
    try:
        cache = _make_cache()
        fetcher = None  # 延迟创建，按需使用

        # 检查缓存状态
        now_data = cache.get("now")
        hourly_data = cache.get("hourly")
        alert_cache = cache.get("alert")

        logger.info(
            f"[天气] 缓存状态: 实时天气={bool(now_data)}, 逐小时预报={bool(hourly_data)}, 预警信息={bool(alert_cache)}"
        )

        # 如果没有缓存，尝试重新获取
        if not now_data:
            logger.info("[天气] 无实时天气缓存，尝试重新获取")
            fetcher = _make_fetcher()
            now_data = fetcher.fetch_now()
            if now_data:
                cache.set("now", now_data, _CACHE_TTL_NOW)
                logger.info(
                    f'[天气] 实时天气重新获取成功: {now_data.get("text")}, 温度={now_data.get("temp")}'
                )
            else:
                logger.warning("[天气] 无法获取实时天气数据")

        if not hourly_data:
            if fetcher is None:
                fetcher = _make_fetcher()
            hourly_data = fetcher.fetch_hourly()
            if hourly_data:
                cache.set("hourly", hourly_data, _CACHE_TTL_HOURLY)
                logger.info(f"[天气] 逐小时预报重新获取成功，共 {len(hourly_data)} 条")

        alert_data = alert_cache.get("warnings", []) if alert_cache else []
        logger.info(f"[天气] 当前预警数量: {len(alert_data)}")

        if not now_data:
            logger.error("[天气] 无法获取实时天气数据，跳过分析推送")
            complete_task_process(pid, "completed", "无实时天气数据，跳过")
            return

        hourly_list = hourly_data if isinstance(hourly_data, list) else []

        # 显示当前天气信息
        current_temp = now_data.get("temp", "N/A")
        current_weather = now_data.get("text", "N/A")
        current_feels_like = now_data.get("feels_like", "N/A")
        logger.info(
            f"[天气] 当前天气: {current_weather}, 温度={current_temp}, 体感={current_feels_like}"
        )

        analyzer = _make_analyzer()
        events = analyzer.analyze(now_data, hourly_list, alert_data)

        logger.info(f"[天气] 分析结果: 找到 {len(events)} 个需要推送的事件")

        if not events:
            logger.info("[天气] 分析结果无需要推送的事件（可能是因为天气正常，或者事件处于冷却期）")
            complete_task_process(pid, "completed", "无需要推送的事件（天气正常或冷却期）")
            return

        from app.modules.weather.message import WeatherFormatter

        # 预警总开关：关闭时过滤掉 alert 类型事件
        try:
            from app.services.config_service import get_config_service

            alert_enabled = str(
                get_config_service().get("weather", "alert_enabled", "true")
            ).lower() not in ("false", "0", "no", "off")
        except Exception:
            alert_enabled = True

        # 将本次需要推送的事件合并为一条汇总消息，避免单次运行连推多条打扰用户
        parts = []
        for event in events:
            event_type = event.get("type", "")
            if event_type == "alert" and not alert_enabled:
                logger.info("[天气] 预警推送已关闭，跳过预警事件")
                continue
            try:
                if event_type == "rain":
                    ev = dict(event)
                    ev["has_heavy_rain"] = event.get("severity") == "high"
                    parts.append(WeatherFormatter.format_rain_alert(ev))
                elif event_type == "heat":
                    parts.append(WeatherFormatter.format_heat_alert(now_data, event))
                elif event_type == "cold":
                    parts.append(WeatherFormatter.format_cold_alert(now_data, event))
                elif event_type == "alert":
                    parts.append(WeatherFormatter.format_weather_alert(event))
                else:
                    logger.warning(f"[天气] 未知事件类型: {event_type}")
                    continue
                logger.info(f'[天气] 已加入汇总: {event_type} — {event.get("title", "")}')
            except Exception as exc:
                logger.error(f"[天气] 格式化事件失败: {exc}")

        if parts:
            combined = "\n\n".join(parts)
            if _maybe_push(combined):
                logger.info(f"[天气] 分析汇总推送完成，合并 {len(parts)} 个事件")
            else:
                logger.info(
                    f"[天气] 分析汇总被抑制（免打扰/达上限），合并 {len(parts)} 个事件未推送"
                )
        else:
            logger.info("[天气] 无可推送事件（预警关闭或无匹配类型）")

        complete_task_process(pid, "completed", f"分析推送完成，共处理 {len(events)} 个事件")
    except Exception as exc:
        logger.error(f"[天气] 分析推送任务失败: {exc}")
        import traceback

        logger.error(traceback.format_exc())
        complete_task_process(pid, "failed", error=str(exc))


# 保留旧名称作为别名，兼容已有代码
analyze_and_push = push_weather_analysis


# ------------------------------------------------------------------
# 手动刷新全部缓存
# ------------------------------------------------------------------


def refresh_all_cache() -> dict:
    """手动刷新全部天气缓存。"""
    result = {"now": False, "hourly": False, "alert": False}
    try:
        fetcher = _make_fetcher()
        cache = _make_cache()

        now_data = fetcher.fetch_now()
        if now_data:
            cache.set("now", now_data, _CACHE_TTL_NOW)
            result["now"] = True

        hourly_data = fetcher.fetch_hourly()
        if hourly_data:
            cache.set("hourly", hourly_data, _CACHE_TTL_HOURLY)
            result["hourly"] = True

        alert_data = fetcher.fetch_alert()
        cache.set("alert", {"warnings": alert_data}, _CACHE_TTL_ALERT)
        result["alert"] = True
    except Exception as exc:
        logger.error(f"[天气] 刷新全部缓存失败: {exc}")
        result["error"] = str(exc)

    return result


# ------------------------------------------------------------------
# 注册到 APScheduler
# ------------------------------------------------------------------


def register_tasks(scheduler, app) -> None:
    """将天气相关定时任务注册到 APScheduler 实例。

    注册 5 个任务：
    1. weather_update_now     — interval 30min — update_weather_now
    2. weather_update_hourly  — interval 60min — update_weather_hourly
    3. weather_update_alert   — interval 10min — update_weather_alert
    4. weather_daily_report   — cron 07:00    — push_weather_daily
    5. weather_analyze_push   — interval 30min — push_weather_analysis

    Args:
        scheduler: BackgroundScheduler 实例。
        app: Flask app 实例（用于读取 config）。
    """
    from apscheduler.triggers.cron import CronTrigger

    # 1. 实时天气更新（每 30 分钟）
    scheduler.add_job(
        update_weather_now,
        trigger="interval",
        minutes=30,
        id="weather_update_now",
        name="天气实时数据更新",
        replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info("[天气] 实时天气更新任务已注册: 每 30 分钟")

    # 2. 逐小时预报更新（每 60 分钟）
    scheduler.add_job(
        update_weather_hourly,
        trigger="interval",
        minutes=60,
        id="weather_update_hourly",
        name="天气逐小时预报更新",
        replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info("[天气] 逐小时预报更新任务已注册: 每 60 分钟")

    # 3. 预警更新（每 10 分钟）
    scheduler.add_job(
        update_weather_alert,
        trigger="interval",
        minutes=10,
        id="weather_update_alert",
        name="天气预警更新",
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info("[天气] 预警更新任务已注册: 每 10 分钟")

    # 4. 每日晨报
    # 优先从数据库读取推送时间（key: weather.schedule_daily），回退到 Config.WEATHER_SCHEDULE_DAILY
    from app.services.config_service import get_config_service

    config_svc = get_config_service()
    daily_time = config_svc.get("weather", "schedule_daily", None) or app.config.get(
        "WEATHER_SCHEDULE_DAILY", "07:00"
    )
    try:
        d_hour, d_min = map(int, daily_time.split(":"))
    except (ValueError, AttributeError):
        d_hour, d_min = 7, 0

    scheduler.add_job(
        push_weather_daily,
        trigger=CronTrigger(hour=d_hour, minute=d_min),
        id="weather_daily_report",
        name="天气每日晨报",
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(f"[天气] 每日晨报任务已注册: 每天 {daily_time}")

    # 5. 分析+条件推送（每 30 分钟）
    scheduler.add_job(
        push_weather_analysis,
        trigger="interval",
        minutes=30,
        id="weather_analyze_push",
        name="天气分析推送",
        replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info("[天气] 分析推送任务已注册: 每 30 分钟")

    logger.info("[天气] 所有定时任务注册完成")
