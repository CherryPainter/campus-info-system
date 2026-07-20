#!/usr/bin/env python3
"""
天气监控 API 路由
提供天气数据查询、手动触发推送等接口

职责：
- 仅处理 HTTP 请求/响应
- 业务逻辑委托给 Service 层
- 数据访问委托给 Repository 层

认证方式：统一使用 JWT Bearer Token
- @jwt_required: 需要登录即可访问（查询数据、触发任务）
- @admin_required: 需要管理员权限（模块状态、配置管理）
- 无装饰器: 公开端点（健康检查）
"""

import threading

from flask import Blueprint, current_app, g, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.utils.auth_middleware import admin_required, jwt_required

logger = get_logger(__name__)

weather_bp = Blueprint("weather", __name__)


@weather_bp.route("/health")
def health():
    """天气模块健康检查（无需认证）"""
    import time

    return api_success(status="ok", module="weather", timestamp=int(time.time()))


@weather_bp.route("/status")
@admin_required
def status():
    """天气模块状态（需管理员权限）"""
    from app.modules.weather.analyzer import WeatherAnalyzer

    analyzer = WeatherAnalyzer()

    # 判断模块是否启用
    jwt_configured = bool(current_app.config.get("QWEATHER_CREDENTIAL_ID")) and bool(
        current_app.config.get("QWEATHER_PROJECT_ID")
    )
    api_key_configured = bool(current_app.config.get("QWEATHER_API_KEY"))
    enabled = jwt_configured or api_key_configured

    return api_success(
        module="weather",
        enabled=enabled,
        api_key_configured=api_key_configured,
        jwt_configured=jwt_configured,
        config={
            "location": current_app.config.get("QWEATHER_LOCATION", "106.55,29.56"),
            "city_name": current_app.config.get("QWEATHER_CITY_NAME", "重庆"),
            "daily_push_time": current_app.config.get("WEATHER_SCHEDULE_DAILY", "07:00"),
        },
        cooldown=dict(analyzer._cooldown_state.items()),
    )


@weather_bp.route("/now")
@jwt_required
def get_now():
    """获取实时天气（优先从数据库读取，过期则重新采集）"""
    from app.services.weather_service import weather_service

    svc = weather_service
    data = svc.get_now_weather()
    if data is None:
        return api_error(message="数据获取失败，请稍后重试", http_status=503)
    return api_success(data=data)


@weather_bp.route("/hourly")
@jwt_required
def get_hourly():
    """获取 24h 预报（优先从数据库读取，过期则重新采集）"""
    from app.services.weather_service import weather_service

    svc = weather_service
    data = svc.get_hourly_forecast()
    if not data:
        return api_error(message="数据获取失败，请稍后重试", http_status=503)
    return api_success(data=data)


@weather_bp.route("/alert")
@jwt_required
def get_alert():
    """获取预警数据（优先从数据库读取，无数据则采集）"""
    from app.services.weather_service import weather_service

    svc = weather_service
    alerts = svc.get_active_alerts()

    # 如果数据库无预警，尝试从 API 获取
    if not alerts:
        new_alerts = svc.fetch_and_save_alerts()
        if new_alerts:
            alerts = svc.get_active_alerts()

    return api_success(data={"warnings": alerts})


@weather_bp.route("/alert/history")
@jwt_required
def get_alert_history():
    """获取预警历史记录（已过期的预警），支持分页

    可选查询参数:
        page: 页码，默认为 1
        page_size: 每页数量，默认为 20，最大 100

    成功响应 (200):
        {
            "status": "success",
            "data": [...],
            "pagination": {"page": 1, "page_size": 20, "total": 100, "total_pages": 5}
        }
    """
    from sqlalchemy import desc

    from app.core.database import get_db
    from app.model.weather import WeatherAlert

    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    page_size = min(page_size, 100)

    session = get_db()
    try:
        query = (
            session.query(WeatherAlert)
            .filter(WeatherAlert.is_active.is_(False))
            .order_by(desc(WeatherAlert.created_at))
        )

        total = query.count()
        total_pages = (total + page_size - 1) // page_size

        history = query.limit(page_size).offset((page - 1) * page_size).all()

        return api_success(
            data=[alert.to_dict() for alert in history],
            pagination={
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        )
    finally:
        session.close()


@weather_bp.route("/statistics")
@jwt_required
def get_statistics():
    """获取天气统计数据（实时天气 + 24h 预报）"""
    from app.services.weather_service import weather_service

    svc = weather_service
    now_data = svc.get_now_weather()
    hourly_data = svc.get_hourly_forecast()

    return api_success(data={"now": now_data, "hourly": hourly_data or []})


@weather_bp.route("/trigger/daily", methods=["POST"])
@admin_required
def trigger_daily():
    """手动触发每日晨报（仅管理员）"""
    return _trigger_task("push_weather_daily", "每日天气晨报")


@weather_bp.route("/trigger/update_now", methods=["POST"])
@admin_required
def trigger_update_now():
    """手动触发实时天气更新（仅管理员）"""
    return _trigger_task("update_weather_now", "实时天气更新")


@weather_bp.route("/trigger/update_hourly", methods=["POST"])
@admin_required
def trigger_update_hourly():
    """手动触发 24h 预报更新（仅管理员）"""
    return _trigger_task("update_weather_hourly", "24h 预报更新")


@weather_bp.route("/trigger/check_alerts", methods=["POST"])
@admin_required
def trigger_check_alerts():
    """手动触发预警检查（仅管理员）"""
    return _trigger_task("update_weather_alert", "天气预警检查")


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------


def _trigger_task(func_name: str, label: str):
    """通用手动触发逻辑（JWT 认证由装饰器保证）"""
    try:
        import app.modules.weather.tasks as weather_tasks

        task_func = getattr(weather_tasks, func_name)
        thread = threading.Thread(target=task_func, daemon=True)
        thread.start()
        user = g.get("current_user", {})
        logger.info(f'[天气] {user.get("username")} 手动触发 {label}')
        return api_success(message=f"{label} 任务已触发")
    except Exception as exc:
        logger.error(f"[天气] 触发 {label} 失败: {exc}")
        return api_error(message=f"触发失败: {exc}", http_status=500)
