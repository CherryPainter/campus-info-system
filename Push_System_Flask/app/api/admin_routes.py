#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理后台 API 路由蓝图
提供系统管理、模块配置、任务触发等管理接口

所有端点都需要 @admin_required 认证（JWT Bearer Token + admin 角色）

端点列表：
- GET  /api/admin/dashboard              — 仪表盘数据（系统状态、模块状态、任务统计）
- GET  /api/admin/weather/config         — 获取天气模块配置
- PUT  /api/admin/weather/config         — 更新天气模块配置
- POST /api/admin/weather/trigger        — 手动触发天气任务
- GET  /api/admin/electricity/config     — 获取电量模块配置
- PUT  /api/admin/electricity/config     — 更新电量模块配置
- POST /api/admin/electricity/trigger   — 手动触发电量任务
- PUT  /api/admin/electricity/cookie    — 更新电量爬虫 Cookie
- GET  /api/admin/electricity/records   — 获取用电记录
- GET  /api/admin/electricity/remaining  — 获取剩余电量
- GET  /api/admin/schedules               — 获取课表数据
- POST /api/admin/tasks/spider            — 手动触发爬虫
- GET  /api/admin/tasks/spider/status    — 爬虫状态
- GET  /api/admin/system/config          — 获取系统配置（非敏感）
- POST /api/admin/system/reload          — 热重载配置
"""

import os
import json
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, g
from app.core.api_response import api_success, api_error, api_paginate

from app.utils.auth_middleware import admin_required
from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)

# 管理后台蓝图，挂载前缀 /api/admin
admin_bp = Blueprint('admin', __name__)


# ============================================================
# 仪表盘
# ============================================================

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """
    仪表盘数据接口

    返回系统状态、各模块状态、任务统计等汇总信息。

    响应示例：
        {
            "status": "success",
            "data": {
                "system": { "app_name": "...", "version": "...", "uptime": "..." },
                "modules": { "weather": {...}, "electricity": {...}, "schedule": {...} },
                "tasks": { "spider_status": {...}, "task_stats": {...} }
            }
        }
    """
    try:
        # ── 时间范围参数 ──
        time_range = request.args.get('time_range', 'this_month')
        start_str = request.args.get('start_date')
        end_str = request.args.get('end_date')

        date_range = _calc_date_range(time_range, start_str, end_str)

        data = {
            'system': _get_system_info(),
            'modules': _get_modules_status(),
            'tasks': _get_tasks_info(date_range),
        }

        resp = {
            'status': 'success',
            'data': data,
        }
        # 返回当前筛选范围信息，前端复用做标签
        if date_range:
            resp['time_label'] = _time_range_label(time_range, date_range)
        return api_success(data=data, **({'time_label': resp['time_label']} if date_range else {}))
    except Exception as e:
        logger.error(f'获取仪表盘数据失败: {e}')
        return api_error(message=f'获取仪表盘数据失败: {e}', http_status=500)


def _get_system_info():
    """
    获取系统基础信息

    Returns:
        dict: 包含应用名称、版本、运行时间等信息
    """
    info = {
        'app_name': current_app.config.get('APP_NAME', '未知'),
        'version': current_app.config.get('APP_VERSION', '未知'),
        'debug': current_app.config.get('DEBUG', False),
        'auth_enabled': current_app.config.get('AUTH_ENABLED', True),
        'timestamp': datetime.now().isoformat(),
    }

    # 尝试获取进程运行时间
    try:
        import psutil
        import time
        process = psutil.Process(os.getpid())
        uptime_seconds = time.time() - process.create_time()
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        info['uptime'] = f'{hours}h {minutes}m'
    except Exception:
        # 回退方案：使用应用启动时间计算
        try:
            from app.core.extensions import _app_start_time
            if _app_start_time:
                import time
                uptime_seconds = time.time() - _app_start_time
                hours = int(uptime_seconds // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                info['uptime'] = f'{hours}h {minutes}m'
            else:
                info['uptime'] = '运行中'
        except Exception:
            info['uptime'] = '运行中'

    return info


def _get_modules_status():
    """
    获取各模块状态

    Returns:
        dict: 天气、电量、课表模块的状态信息
    """
    modules = {}

    # 天气模块状态
    try:
        from app.repository.weather_repository import WeatherRepository
        from app.core.database import get_db

        jwt_configured = bool(current_app.config.get('QWEATHER_CREDENTIAL_ID')) and bool(current_app.config.get('QWEATHER_PROJECT_ID'))
        api_key_configured = bool(current_app.config.get('QWEATHER_API_KEY'))
        weather_enabled = jwt_configured or api_key_configured

        session = get_db()
        try:
            now_record = WeatherRepository.get_latest_now_record(session)
            hourly_records = WeatherRepository.get_hourly_records(session, limit=1)
            alerts = WeatherRepository.get_active_alerts(session)
        finally:
            session.close()

        modules['weather'] = {
            'status': 'ok' if weather_enabled else 'disabled',
            'enabled': weather_enabled,
            'cache': {
                'now': now_record is not None,
                'hourly': len(hourly_records) > 0,
                'alert': len(alerts) > 0,
            },
            'config': {
                'city_name': current_app.config.get('QWEATHER_CITY_NAME', '重庆'),
                'daily_push_time': current_app.config.get('WEATHER_SCHEDULE_DAILY', '07:00'),
            }
        }
    except Exception as e:
        modules['weather'] = {'enabled': False, 'error': str(e)}

    # 电量模块状态
    try:
        from app.services.electricity_service import electricity_service

        electricity_enabled = bool(current_app.config.get('ELECTRICITY_CRAWLER_COOKIE'))
        svc = electricity_service
        remaining = svc.get_remaining_power()
        records = svc.get_usage_records(days=1, limit=1)

        modules['electricity'] = {
            'status': 'ok' if electricity_enabled else 'disabled',
            'enabled': electricity_enabled,
            'cookie_configured': electricity_enabled,
            'data': {
                'records_exists': len(records) > 0,
                'remaining_exists': remaining is not None,
            },
            'config': {
                'low_power_threshold': current_app.config.get('ELECTRICITY_LOW_POWER_THRESHOLD', 10.0),
                'daily_push_time': current_app.config.get('ELECTRICITY_SCHEDULE_DAILY', '00:30'),
            }
        }
    except Exception as e:
        modules['electricity'] = {'enabled': False, 'error': str(e)}

    # 课表模块状态
    try:
        from app.services.schedule_service import schedule_service
        modules['schedule'] = {
            'data_ready': schedule_service.is_data_ready,
            'stats': schedule_service.get_statistics(),
        }
    except Exception as e:
        modules['schedule'] = {'data_ready': False, 'error': str(e)}

    return modules


def _calc_date_range(time_range, start_str, end_str):
    """根据 time_range 参数计算 (start, end) datetime，None 表示不过滤"""
    from datetime import datetime, timedelta
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_range == 'this_month':
        return (today_start.replace(day=1), now)
    elif time_range == 'last_month':
        first_this = today_start.replace(day=1)
        last_month_end = first_this - timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (last_month_start, last_month_end)
    elif time_range == 'this_week':
        week_start = today_start - timedelta(days=now.weekday())
        return (week_start, now)
    elif time_range == 'last_week':
        this_week_start = today_start - timedelta(days=now.weekday())
        last_week_end = this_week_start - timedelta(seconds=1)
        last_week_start = last_week_end - timedelta(days=6)
        last_week_start = last_week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        return (last_week_start, last_week_end)
    elif time_range == 'custom':
        if start_str and end_str:
            try:
                s = datetime.strptime(start_str[:10], '%Y-%m-%d')
                e = datetime.strptime(end_str[:10], '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
                return (s, e)
            except ValueError:
                pass
        # fallback
        return (today_start.replace(day=1), now)
    else:
        # 未知值默认本月
        return (today_start.replace(day=1), now)


def _time_range_label(time_range, date_range):
    """返回可读的时间范围中文标签"""
    if date_range is None:
        return '全部时间'
    fmts = 'mysql'
    try:
        l = date_range[0].strftime('%m/%d') + ' - ' + date_range[1].strftime('%m/%d')
        map_ = {
            'this_month': '本月',
            'last_month': '上月',
            'this_week': '本周',
            'last_week': '上周',
            'custom': l,
        }
        return map_.get(time_range, l)
    except Exception:
        return '自定义'


def _get_tasks_info(date_range=None):
    """
    获取任务相关信息

    Returns:
        dict: 爬虫状态、任务统计、定时任务等信息
    """
    tasks = {}

    # 爬虫状态
    try:
        from app.tasks.scheduler import get_spider_status
        from app.modules.electricity.crawler import get_electricity_spider_status
        tasks['spider_status'] = {
            'course': get_spider_status(),           # 课表爬虫
            'electricity': get_electricity_spider_status(),  # 电量爬虫
        }
    except Exception as e:
        tasks['spider_status'] = {'error': str(e)}

    # 任务统计
    try:
        from app.services.task_service import task_service
        tasks['task_stats'] = task_service.get_statistics()
    except Exception as e:
        tasks['task_stats'] = {'error': str(e)}

    # 进程统计
    try:
        from app.core.database import get_db
        from app.model.task_process import TaskProcess
        from datetime import datetime, timedelta
        from sqlalchemy import func, and_

        session = get_db()
        try:
            now = datetime.now()
            # 默认月份边界（保留兼容）
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            # ── 根据 date_range 构建过滤条件 ──
            dt_filter = None
            if date_range:
                s, e = date_range
                dt_filter = and_(TaskProcess.started_at >= s, TaskProcess.started_at <= e)
                period_start, period_end = s, e
            else:
                period_start = month_start
                period_end = now

            def _with_period(q):
                return q.filter(dt_filter) if dt_filter is not None else q

            # 各状态数量
            status_counts = {}
            for row in _with_period(session.query(TaskProcess.status, func.count(TaskProcess.id)).group_by(TaskProcess.status)).all():
                status_counts[row[0]] = row[1]

            # 期间统计
            period_total = _with_period(session.query(func.count(TaskProcess.id))).scalar() or 0
            period_completed = _with_period(session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.status == 'completed'
            )).scalar() or 0
            period_failed = _with_period(session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.status == 'failed'
            )).scalar() or 0

            # 今日 / 本周 / 本月 保留（前端卡片备用）
            today_total = session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.started_at >= today_start
            ).scalar() or 0
            today_completed = session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.started_at >= today_start,
                TaskProcess.status == 'completed'
            ).scalar() or 0
            today_failed = session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.started_at >= today_start,
                TaskProcess.status == 'failed'
            ).scalar() or 0
            week_total = session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.started_at >= week_start
            ).scalar() or 0
            month_total = session.query(func.count(TaskProcess.id)).filter(
                TaskProcess.started_at >= month_start
            ).scalar() or 0

            # 最近任务（按时间范围筛选）
            recent_tasks = []
            rq = session.query(TaskProcess)
            if dt_filter is not None:
                rq = rq.filter(dt_filter)
            for p in rq.order_by(TaskProcess.started_at.desc()).limit(5).all():
                recent_tasks.append({
                    'id': p.id,
                    'name': p.name,
                    'status': p.status,
                    'started_at': p.started_at.isoformat() if p.started_at else None,
                    'duration': p.duration,
                })

            # 按类型统计（按时间范围筛选）
            type_counts = {}
            for row in _with_period(session.query(TaskProcess.task_type, func.count(TaskProcess.id)).group_by(TaskProcess.task_type)).all():
                type_counts[row[0]] = row[1]

            # 按日期×类型趋势（折线图用）：每天每种任务的次数
            type_trend = {'dates': [], 'series': []}
            if dt_filter is not None:
                from sqlalchemy import cast, Date
                trend_rows = session.query(
                    cast(TaskProcess.started_at, Date).label('day'),
                    TaskProcess.task_type,
                    func.count(TaskProcess.id),
                ).filter(dt_filter).group_by('day', TaskProcess.task_type).order_by('day').all()

                date_map = {}          # date_str -> {task_type: count}
                all_dates = []
                for day, ttype, cnt in trend_rows:
                    ds = day.isoformat() if hasattr(day, 'isoformat') else str(day)
                    if ds not in date_map:
                        date_map[ds] = {}
                        all_dates.append(ds)
                    date_map[ds][ttype] = cnt

                # 按任务类型聚合成 series
                type_set = sorted(set(t for (_, t, _) in trend_rows))
                for ttype in type_set:
                    data = [date_map.get(d, {}).get(ttype, 0) for d in all_dates]
                    type_trend['series'].append({'name': ttype, 'data': data})
                type_trend['dates'] = all_dates

            tasks['process_stats'] = {
                'total': _with_period(session.query(func.count(TaskProcess.id))).scalar() or 0,
                'status_counts': status_counts,
                'type_counts': type_counts,
                'type_trend': type_trend,
                'today': {'total': today_total, 'completed': today_completed, 'failed': today_failed},
                'week': {'total': week_total},
                'month': {'total': month_total},
                'period': {'total': period_total, 'completed': period_completed, 'failed': period_failed},
                'recent_tasks': recent_tasks,
            }
        finally:
            session.close()
    except Exception as e:
        tasks['process_stats'] = {'error': str(e)}

    # 定时任务状态
    try:
        from app.tasks.scheduler import get_scheduler_jobs
        scheduled_jobs = get_scheduler_jobs()
        tasks['scheduled_jobs'] = {
            'total': len(scheduled_jobs),
            'jobs': scheduled_jobs[:5],  # 只返回前5个
        }
    except Exception as e:
        tasks['scheduled_jobs'] = {'error': str(e)}

    return tasks


# ============================================================
# 天气模块管理
# ============================================================

@admin_bp.route('/weather/config')
@admin_required
def get_weather_config():
    """
    获取天气模块配置

    返回天气模块的当前配置信息（敏感信息脱敏显示）。

    响应示例：
        {
            "status": "success",
            "data": {
                "auth_type": "jwt_ed25519",
                "credential_id": "CMGTQMETC6",
                "project_id_configured": true,
                "private_key_configured": true,
                "api_key_configured": false,
                "location": "106.55,29.56",
                "city_name": "重庆",
                "daily_push_time": "07:00"
            }
        }
    """
    credential_id = current_app.config.get('QWEATHER_CREDENTIAL_ID', '')
    project_id = current_app.config.get('QWEATHER_PROJECT_ID', '')
    private_key_path = current_app.config.get('QWEATHER_PRIVATE_KEY_PATH', '')
    api_key = current_app.config.get('QWEATHER_API_KEY', '')

    # 判断认证方式
    if credential_id and project_id and private_key_path:
        auth_type = 'jwt_ed25519'
    elif api_key:
        auth_type = 'api_key'
    else:
        auth_type = 'none'

    return api_success(data={'auth_type': auth_type, 'credential_id': credential_id, 'project_id_configured': bool(project_id), 'private_key_configured': bool(private_key_path) and os.path.exists(private_key_path), 'api_key_configured': bool(api_key), 'api_host': current_app.config.get('QWEATHER_API_HOST', 'https://devapi.qweatherapi.com'), 'location': current_app.config.get('QWEATHER_LOCATION', '106.55,29.56'), 'city_name': current_app.config.get('QWEATHER_CITY_NAME', '重庆'), 'daily_push_time': current_app.config.get('WEATHER_SCHEDULE_DAILY', '07:00'), **_read_weather_push_config()})


def _read_weather_push_config() -> dict:
    """从 module_configs 读取天气推送控制配置（免打扰/上限/预警开关）。"""
    from app.core.database import get_db
    from app.model.module_config import ModuleConfig

    defaults = {
        'quiet_hours_enabled': True,
        'quiet_hours_start': '23:00',
        'quiet_hours_end': '07:00',
        'daily_push_limit': 8,
        'alert_enabled': True,
    }
    session = get_db()
    try:
        result = {}
        for key, default in defaults.items():
            cfg = session.query(ModuleConfig).filter(
                ModuleConfig.module == 'weather', ModuleConfig.key == key
            ).first()
            if not cfg or cfg.value is None:
                result[key] = default
                continue
            if cfg.value_type == 'boolean':
                result[key] = str(cfg.value).lower() in ('true', '1', 'yes')
            elif cfg.value_type == 'integer':
                try:
                    result[key] = int(cfg.value)
                except (ValueError, TypeError):
                    result[key] = default
            else:
                result[key] = cfg.value
        return result
    finally:
        session.close()


@admin_bp.route('/weather/config', methods=['PUT'])
@admin_required
def update_weather_config():
    """
    更新天气模块配置

    请求格式：
        PUT /api/admin/weather/config
        Content-Type: application/json
        {
            "project_id": "your_project_id",     // JWT 项目 ID (可选)
            "api_key": "new_api_key",            // API Key (可选，兼容旧版)
            "location": "106.55,29.56",          // 位置坐标 (可选)
            "city_name": "重庆",                  // 城市名称 (可选)
            "daily_push_time": "07:30"            // 每日推送时间 (可选)
        }
    """
    data = request.get_json(silent=True) or {}
    updates = {}

    # 更新项目 ID (JWT sub)
    if 'project_id' in data:
        new_project_id = data['project_id']
        if new_project_id:
            from app.core import config as cfg_module
            cfg_module.Config.QWEATHER_PROJECT_ID = new_project_id
            updates['project_id'] = '已更新'

    # 更新 API Key（兼容旧版）
    if 'api_key' in data:
        new_key = data['api_key']
        if new_key:
            from app.core import config as cfg_module
            cfg_module.Config.QWEATHER_API_KEY = new_key
            updates['api_key'] = '已更新'

    # 更新位置
    if 'location' in data:
        new_location = data['location']
        if new_location:
            from app.core import config as cfg_module
            cfg_module.Config.QWEATHER_LOCATION = new_location
            updates['location'] = new_location

    # 更新城市名称
    if 'city_name' in data:
        new_city = data['city_name']
        if new_city:
            from app.core import config as cfg_module
            cfg_module.Config.QWEATHER_CITY_NAME = new_city
            updates['city_name'] = new_city

    # 更新推送时间
    if 'daily_push_time' in data:
        new_time = data['daily_push_time']
        if new_time:
            from app.core import config as cfg_module
            cfg_module.Config.WEATHER_SCHEDULE_DAILY = new_time
            updates['daily_push_time'] = new_time

    # 更新推送控制配置（夜间免打扰 / 每日上限 / 预警开关），写入 module_configs 即时生效
    _push_keys = {
        'quiet_hours_enabled': 'boolean',
        'alert_enabled': 'boolean',
        'quiet_hours_start': 'string',
        'quiet_hours_end': 'string',
        'daily_push_limit': 'integer',
    }
    _changed = {}
    for key, vtype in _push_keys.items():
        if key in data and data[key] is not None and data[key] != '':
            raw = data[key]
            if vtype == 'boolean':
                val = 'true' if str(raw).lower() in ('true', '1', 'yes', 'on') else 'false'
            elif vtype == 'integer':
                try:
                    val = str(int(raw))
                except (ValueError, TypeError):
                    continue
            else:
                val = str(raw)
            _changed[key] = val

    if _changed:
        from app.core.database import get_db
        from app.model.module_config import ModuleConfig
        session = get_db()
        try:
            for key, val in _changed.items():
                cfg = session.query(ModuleConfig).filter(
                    ModuleConfig.module == 'weather', ModuleConfig.key == key
                ).first()
                if cfg:
                    cfg.value = val
                    cfg.updated_at = datetime.now()
                updates[key] = val
            session.commit()
        finally:
            session.close()

    logger.info(f'天气模块配置已更新: {updates}')

    return api_success(message='天气模块配置已更新', updates=updates)


@admin_bp.route('/weather/trigger', methods=['POST'])
@admin_required
def trigger_weather_task():
    """
    手动触发天气任务

    请求格式：
        POST /api/admin/weather/trigger
        Content-Type: application/json
        {
            "task_type": "push_weather_daily"  // 任务类型
        }

    支持的 task_type：
    - push_weather_daily      — 每日晨报推送
    - push_weather_analysis   — 天气分析推送
    - update_weather_now      — 更新实时天气
    - update_weather_hourly   — 更新逐小时预报
    - update_weather_alert    — 更新天气预警
    - check_weather_alerts    — 检查天气预警
    - refresh_all_cache       — 刷新全部缓存
    """
    data = request.get_json(silent=True) or {}
    task_type = data.get('task_type', '').strip()

    # 任务类型映射
    task_map = {
        'push_weather_daily': ('push_weather_daily', '每日天气晨报'),
        'push_weather_analysis': ('push_weather_analysis', '天气分析推送'),
        'update_weather_now': ('update_weather_now', '实时天气更新'),
        'update_weather_hourly': ('update_weather_hourly', '逐小时预报更新'),
        'update_weather_alert': ('update_weather_alert', '天气预警更新'),
        'check_weather_alerts': ('update_weather_alert', '天气预警检查'),
        'refresh_all_cache': ('refresh_all_cache', '刷新全部缓存'),
    }

    if task_type not in task_map:
        return api_error(message=f'不支持的任务类型: {task_type}', supported_types=list(task_map.keys()), http_status=400)

    func_name, label = task_map[task_type]

    try:
        import app.modules.weather.tasks as weather_tasks
        task_func = getattr(weather_tasks, func_name)

        # refresh_all_cache 是同步函数，直接调用
        if task_type == 'refresh_all_cache':
            result = task_func()
            return api_success(message=f'{label} 执行完成', result=result)

        # 其他任务在独立线程中执行
        thread = threading.Thread(target=task_func, daemon=True)
        thread.start()

        logger.info(f'[管理后台] 手动触发天气任务: {label}')
        return api_success(message=f'{label} 任务已触发')
    except Exception as e:
        logger.error(f'[管理后台] 触发天气任务失败: {e}')
        return api_error(message=f'触发失败: {e}', http_status=500)


# ============================================================
# 电量模块管理
# ============================================================

@admin_bp.route('/electricity/config')
@admin_required
def get_electricity_config():
    """
    获取电量模块配置

    返回电量模块的当前配置信息（Cookie 脱敏显示）。

    响应示例：
        {
            "status": "success",
            "data": {
                "cookie_configured": true,
                "cookie_preview": "JSESS****",
                "low_power_threshold": 10.0,
                "daily_push_time": "00:30",
                ...
            }
        }
    """
    cookie = current_app.config.get('ELECTRICITY_CRAWLER_COOKIE', '')

    # Cookie 脱敏处理
    cookie_preview = ''
    if cookie:
        if len(cookie) > 12:
            cookie_preview = cookie[:6] + '****' + cookie[-6:]
        else:
            cookie_preview = '****'

    return api_success(data={'cookie_configured': bool(cookie), 'cookie_preview': cookie_preview, 'base_url': current_app.config.get('ELECTRICITY_CRAWLER_BASE_URL', 'http://dk.cqie.cn'), 'max_pages': current_app.config.get('ELECTRICITY_CRAWLER_MAX_PAGES', 50), 'low_power_threshold': current_app.config.get('ELECTRICITY_LOW_POWER_THRESHOLD', 10.0), 'low_power_interval_hours': current_app.config.get('ELECTRICITY_LOW_POWER_INTERVAL_HOURS', 4.0), 'daily_push_time': current_app.config.get('ELECTRICITY_SCHEDULE_DAILY', '00:30'), 'weekly_push_time': current_app.config.get('ELECTRICITY_SCHEDULE_WEEKLY', '00:30'), 'weekly_push_day': current_app.config.get('ELECTRICITY_SCHEDULE_WEEKLY_DAY', 'mon'), 'monthly_push_time': current_app.config.get('ELECTRICITY_SCHEDULE_MONTHLY', '00:30'), 'monthly_push_day': current_app.config.get('ELECTRICITY_SCHEDULE_MONTHLY_DAY', 1), 'cookie_check_time': current_app.config.get('ELECTRICITY_COOKIE_CHECK_TIME', '20:00')})


@admin_bp.route('/electricity/config', methods=['PUT'])
@admin_required
def update_electricity_config():
    """
    更新电量模块配置

    请求格式：
        PUT /api/admin/electricity/config
        Content-Type: application/json
        {
            "low_power_threshold": 15.0,      // 可选
            "low_power_interval_hours": 6.0,    // 可选
            "daily_push_time": "01:00",         // 可选
            "weekly_push_time": "01:00",        // 可选
            "weekly_push_day": "tue",           // 可选
            "monthly_push_time": "01:00",       // 可选
            "monthly_push_day": 15,             // 可选
            "cookie_check_time": "21:00"        // 可选
        }
    """
    data = request.get_json(silent=True) or {}
    updates = {}

    # 配置字段映射：请求参数 -> Config 属性
    config_fields = {
        'low_power_threshold': 'ELECTRICITY_LOW_POWER_THRESHOLD',
        'low_power_interval_hours': 'ELECTRICITY_LOW_POWER_INTERVAL_HOURS',
        'daily_push_time': 'ELECTRICITY_SCHEDULE_DAILY',
        'weekly_push_time': 'ELECTRICITY_SCHEDULE_WEEKLY',
        'weekly_push_day': 'ELECTRICITY_SCHEDULE_WEEKLY_DAY',
        'monthly_push_time': 'ELECTRICITY_SCHEDULE_MONTHLY',
        'monthly_push_day': 'ELECTRICITY_SCHEDULE_MONTHLY_DAY',
        'cookie_check_time': 'ELECTRICITY_COOKIE_CHECK_TIME',
    }

    from app.core import config as cfg_module

    for param_name, config_attr in config_fields.items():
        if param_name in data:
            value = data[param_name]
            if value is not None:
                setattr(cfg_module.Config, config_attr, value)
                updates[param_name] = value

    logger.info(f'电量模块配置已更新: {updates}')

    return api_success(message='电量模块配置已更新', updates=updates)


@admin_bp.route('/electricity/trigger', methods=['POST'])
@admin_required
def trigger_electricity_task():
    """
    手动触发电量任务

    请求格式：
        POST /api/admin/electricity/trigger
        Content-Type: application/json
        {
            "task_type": "push_electricity_daily"  // 任务类型
        }

    支持的 task_type：
    - push_electricity_daily    — 每日用电报告
    - push_electricity_weekly   — 每周用电报告
    - push_electricity_monthly  — 每月用电报告
    - check_cookie_validity     — Cookie 有效性检测
    - check_low_power           — 低电量检测
    """
    data = request.get_json(silent=True) or {}
    task_type = data.get('task_type', '').strip()

    # 任务类型映射
    task_map = {
        'fetch_electricity_data': ('fetch_electricity_data', '电量数据采集'),
        'push_electricity_daily': ('push_electricity_daily', '每日用电报告'),
        'push_electricity_weekly': ('push_electricity_weekly', '每周用电报告'),
        'push_electricity_monthly': ('push_electricity_monthly', '每月用电报告'),
        'check_cookie_validity': ('check_cookie_validity', 'Cookie 有效性检测'),
        'check_low_power': ('check_low_power', '低电量检测'),
    }

    if task_type not in task_map:
        return api_error(message=f'不支持的任务类型: {task_type}', supported_types=list(task_map.keys()), http_status=400)

    func_name, label = task_map[task_type]

    try:
        import app.modules.electricity.tasks as elec_tasks
        task_func = getattr(elec_tasks, func_name)
        thread = threading.Thread(target=task_func, daemon=True)
        thread.start()

        logger.info(f'[管理后台] 手动触发电量任务: {label}')
        return api_success(message=f'{label} 任务已触发')
    except Exception as e:
        logger.error(f'[管理后台] 触发电量任务失败: {e}')
        return api_error(message=f'触发失败: {e}', http_status=500)


@admin_bp.route('/course/trigger', methods=['POST'])
@admin_required
def trigger_course_task():
    """
    手动触发课程推送任务

    请求格式：
        POST /api/admin/course/trigger
        Content-Type: application/json
        {
            "task_type": "push_daily_schedule"  // 任务类型
        }

    支持的 task_type：
    - push_daily_schedule    — 推送今日课表
    - push_weekly_schedule   — 推送本周课表
    - push_weekly_image      — 推送周课表图片
    """
    data = request.get_json(silent=True) or {}
    task_type = data.get('task_type', '').strip()

    # 任务类型映射
    task_map = {
        'push_daily_schedule': ('今日课表推送', 'daily'),
        'push_weekly_image': ('周课表图片推送', 'image'),
    }

    if task_type not in task_map:
        return api_error(message=f'不支持的任务类型: {task_type}', supported_types=list(task_map.keys()), http_status=400)

    label, mode = task_map[task_type]

    try:
        from app.services.rule_service import rule_service
        from app.services.schedule_service import schedule_service
        from app.services.task_service import task_service
        from app.api.process_routes import create_task_process, complete_task_process
        from datetime import datetime, date
        import threading

        # 创建进程记录
        pid = create_task_process(label, 'course', total_items=1, created_by='admin')

        # 使用 schedule_service 的 get_today_schedules 方法获取今日课表
        today_schedules = schedule_service.get_today_schedules()
        all_schedules = schedule_service.get_schedules()

        if not today_schedules:
            complete_task_process(pid, 'failed', error='今日没有课程安排')
            return api_error(message='今日没有课程安排', http_status=400)

        if mode == 'daily':
            # 推送今日课表
            rule = next((r for r in rule_service.get_rules() if r['id'] == 'daily_schedule'), None)
            if rule:
                task = rule_service._check_daily_schedule_force(
                    datetime.now(), today_schedules, all_schedules, rule
                )
                if task:
                    task_service.create_task(task)
                    logger.info(f'[管理后台] 手动触发今日课表推送，共 {len(today_schedules)} 节课')
                    complete_task_process(pid, 'completed', f'{label} 成功，共推送 {len(today_schedules)} 节课')
                else:
                    complete_task_process(pid, 'failed', error='生成推送任务失败')
                    return api_error(message='生成推送任务失败', http_status=500)
            else:
                complete_task_process(pid, 'failed', error='未找到每日课表推送规则')
                return api_error(message='未找到每日课表推送规则', http_status=500)

        elif mode == 'image':
            # 推送周课表图片
            from app.tasks.scheduler import _send_weekly_image
            thread = threading.Thread(target=_send_weekly_image, args=(None,))
            thread.daemon = True
            thread.start()
            logger.info(f'[管理后台] 手动触发周课表图片推送')
            complete_task_process(pid, 'completed', f'{label} 已启动')

        return api_success(message=f'{label} 任务已触发')
    except Exception as e:
        logger.error(f'[管理后台] 触发课程任务失败: {e}')
        return api_error(message=f'触发失败: {e}', http_status=500)


@admin_bp.route('/electricity/cookie', methods=['PUT'])
@admin_required
def update_electricity_cookie():
    """
    更新电量爬虫 Cookie

    请求格式：
        PUT /api/admin/electricity/cookie
        Content-Type: application/json
        {
            "cookie": "JSESSIONID=xxx; leech_k=xxx"
        }
    """
    data = request.get_json(silent=True) or {}
    new_cookie = data.get('cookie', '').strip()

    if not new_cookie:
        return api_error(message='请提供 cookie 字段', http_status=400)

    # 基本格式校验
    if len(new_cookie) < 10 or len(new_cookie) > 4096:
        return api_error(message='Cookie 长度不合法（10-4096 字符）', http_status=400)

    import re
    if re.search(r'[\'\"<>;]', new_cookie):
        return api_error(message='Cookie 包含非法字符', http_status=400)

    try:
        from app.modules.electricity.tasks import update_cookie_in_memory
        success = update_cookie_in_memory(new_cookie)
        if success:
            logger.info('[管理后台] 电量 Cookie 更新成功')
            return api_success(message='Cookie 已更新，爬虫将立即使用新 Cookie')
        return api_error(message='Cookie 更新失败', http_status=500)
    except Exception as e:
        logger.error(f'[管理后台] Cookie 更新异常: {e}')
        return api_error(message=f'服务器异常: {e}', http_status=500)


@admin_bp.route('/electricity/records')
@admin_required
def get_electricity_records():
    """
    获取用电记录

    查询参数：
        limit (int): 返回记录数量限制，默认 50

    响应示例：
        {
            "status": "success",
            "count": 50,
            "records": [...]
        }
    """
    try:
        from app.core.config import Config
        records_path = os.path.join(
            getattr(Config, 'ELECTRICITY_DATA_DIR', ''), 'usage_records.json'
        )

        if not os.path.exists(records_path):
            return api_success(count=0, records=[], message='暂无用电记录数据')

        with open(records_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        # 兼容嵌套列表结构
        if isinstance(records, list) and records and isinstance(records[0], list):
            flat = []
            for sub in records:
                if isinstance(sub, list):
                    flat.extend(sub)
                else:
                    flat.append(sub)
            records = flat

        # 限制返回数量
        limit = request.args.get('limit', 50, type=int)
        limit = min(max(limit, 1), 500)  # 限制在 1-500 之间
        records = records[-limit:]  # 返回最新的记录

        return api_success(count=len(records), records=records)
    except Exception as e:
        logger.error(f'[管理后台] 获取用电记录失败: {e}')
        return api_error(message=f'读取数据失败: {e}', http_status=500)


@admin_bp.route('/electricity/remaining')
@admin_required
def get_electricity_remaining():
    """
    获取剩余电量

    响应示例：
        {
            "status": "success",
            "data": {
                "default": "123.45",
                ...
            }
        }
    """
    try:
        from app.core.config import Config
        remaining_path = os.path.join(
            getattr(Config, 'ELECTRICITY_DATA_DIR', ''), 'remaining_power.json'
        )

        if not os.path.exists(remaining_path):
            return api_success(data=None, message='暂无剩余电量数据')

        with open(remaining_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return api_success(data=data)
    except Exception as e:
        logger.error(f'[管理后台] 获取剩余电量失败: {e}')
        return api_error(message=f'读取数据失败: {e}', http_status=500)


# ============================================================
# 课表数据
# ============================================================

@admin_bp.route('/schedules')
@admin_required
def get_schedules():
    """
    获取课表数据

    查询参数：
        force (bool): 是否强制重新加载，默认 false

    响应示例：
        {
            "status": "success",
            "count": 30,
            "data_ready": true,
            "schedules": [...]
        }
    """
    try:
        from app.services.schedule_service import schedule_service
        force = request.args.get('force', 'false').lower() == 'true'
        schedules = schedule_service.get_schedules(force_reload=force)

        return api_success(count=len(schedules), data_ready=schedule_service.is_data_ready, schedules=schedules)
    except Exception as e:
        logger.error(f'[管理后台] 获取课表数据失败: {e}')
        return api_error(message=f'获取课表数据失败: {e}', http_status=500)


# ============================================================
# 爬虫任务
# ============================================================

@admin_bp.route('/tasks/spider', methods=['POST'])
@admin_required
def trigger_spider():
    """
    手动触发爬虫

    响应示例：
        {
            "status": "success",
            "message": "爬虫执行已启动"
        }

    如果爬虫正在运行，返回 409：
        {
            "status": "error",
            "message": "爬虫正在执行中"
        }
    """
    try:
        from app.tasks.scheduler import run_spider, get_spider_status

        # 检查爬虫是否正在执行
        spider_status = get_spider_status()
        if spider_status.get('running'):
            return api_error(message='爬虫正在执行中，请稍后再试', http_status=409)

        # 在独立线程中启动爬虫
        thread = threading.Thread(
            target=run_spider,
            kwargs={'trigger_source': 'manual'},
            daemon=True
        )
        thread.start()

        logger.info('[管理后台] 手动触发爬虫执行')
        return api_success(message='爬虫执行已启动')
    except Exception as e:
        logger.error(f'[管理后台] 触发爬虫失败: {e}')
        return api_error(message=f'触发失败: {e}', http_status=500)


@admin_bp.route('/tasks/spider/status')
@admin_required
def spider_status():
    """
    获取爬虫执行状态

    响应示例：
        {
            "status": "success",
            "spider": {
                "running": false,
                "last_run": "2024-01-01T07:00:00",
                "last_result": "success",
                "last_error": null,
                "last_exit_code": 0
            }
        }
    """
    try:
        from app.tasks.scheduler import get_spider_status
        from app.core.database import get_db as _db
        from app.model.task_process import TaskProcess as _TP
        from app.model.scheduled_crawl_task import ScheduledCrawlTask as _SCT
        status = get_spider_status()

        # 额外检测：全量爬取类任务的运行状态
        session = _db()
        try:
            from sqlalchemy import or_ as _or
            course_running = session.query(_SCT).filter(
                _or(
                    _SCT.status == 'running',
                    # pending + immediate：任务刚创建、线程尚未取下执行，前端应视为"运行中"
                    _SCT.status == 'pending',
                )
            ).first() is not None
            elec_running = session.query(_TP).filter(
                _TP.name.like('电量全量爬取%'),
                _TP.status == 'running'
            ).first() is not None
        finally:
            session.close()

        status['running_tasks'] = {
            'course_full_crawl': course_running,
            'electricity_full_crawl': elec_running,
        }

        return api_success(spider=status)
    except Exception as e:
        logger.error(f'[管理后台] 获取爬虫状态失败: {e}')
        return api_error(message=f'获取爬虫状态失败: {e}', http_status=500)


# ============================================================
# 系统配置
# ============================================================

@admin_bp.route('/system/config')
@admin_required
def get_system_config():
    """
    获取系统配置（非敏感信息）

    仅返回非敏感的配置项，不包含密码、Token、密钥等。

    响应示例：
        {
            "status": "success",
            "data": {
                "app_name": "校园信息聚合与智能推送系统",
                "version": "5.9.0",
                "debug": false,
                "host": "0.0.0.0",
                "port": 29528,
                "auth_enabled": true,
                "class_name": "ZK2401",
                "cron_expression": "0 7,13 * * *",
                ...
            }
        }
    """
    # 定义允许暴露的非敏感配置项
    safe_config_keys = [
        'APP_NAME', 'APP_VERSION', 'DEBUG', 'HOST', 'PORT',
        'AUTH_ENABLED', 'CLASS_NAME', 'CRON_EXPRESSION',
        'DAILY_PUSH_TIME', 'BEFORE_CLASS_MINUTES', 'BEFORE_END_CLASS_MINUTES',
        'JWT_ACCESS_TOKEN_EXPIRE', 'JWT_REFRESH_TOKEN_EXPIRE',
        'JWT_ADMIN_USERNAME',
        'QWEATHER_CITY_NAME', 'QWEATHER_LOCATION',
        'WEATHER_SCHEDULE_DAILY',
        'ELECTRICITY_LOW_POWER_THRESHOLD', 'ELECTRICITY_LOW_POWER_INTERVAL_HOURS',
        'ELECTRICITY_SCHEDULE_DAILY', 'ELECTRICITY_SCHEDULE_WEEKLY',
        'ELECTRICITY_SCHEDULE_WEEKLY_DAY', 'ELECTRICITY_SCHEDULE_MONTHLY',
        'ELECTRICITY_SCHEDULE_MONTHLY_DAY', 'ELECTRICITY_COOKIE_CHECK_TIME',
        'ELECTRICITY_CRAWLER_MAX_PAGES',
    ]

    config_data = {}
    for key in safe_config_keys:
        config_data[key] = current_app.config.get(key)

    return api_success(data=config_data)


@admin_bp.route('/system/reload', methods=['POST'])
@admin_required
def reload_system():
    """
    热重载配置

    重新加载课表数据、模板配置等，无需重启服务。

    响应示例：
        {
            "status": "success",
            "message": "配置重载完成",
            "details": {
                "schedules": "已重新加载",
                "templates": "已重新加载 5 个模板"
            }
        }
    """
    details = {}

    # 重新加载课表数据
    try:
        from app.services.schedule_service import schedule_service
        schedule_service.load_schedules()
        details['schedules'] = '已重新加载'
    except Exception as e:
        details['schedules'] = f'重载失败: {e}'
        logger.error(f'[管理后台] 重载课表数据失败: {e}')

    # 重新加载模板
    try:
        from app.services.template_service import template_service
        count = template_service.reload_templates()
        details['templates'] = f'已重新加载 {count} 个模板'
    except Exception as e:
        details['templates'] = f'重载失败: {e}'
        logger.error(f'[管理后台] 重载模板失败: {e}')

    logger.info(f'[管理后台] 系统配置热重载: {details}')

    return api_success(message='配置重载完成', details=details)


# ============================================================
# 数据库指纹（定义码 vs 实例码 漂移检测）
# ============================================================

@admin_bp.route('/db/fingerprint', methods=['GET'])
@admin_required
def db_fingerprint():
    """数据库指纹比对：返回定义码、实例码与结构化差异明细。"""
    from app.core.database import get_db
    from app.core.db_fingerprint import check_db_fingerprint, summarize_diff
    session = get_db()
    try:
        result = check_db_fingerprint(session)
        resp = {
            'definition_hash': result['definition_hash'],
            'instance_hash': result['instance_hash'],
            'match': result['match'],
            'summary': summarize_diff(result),
            'diff': {
                'missing_tables': result['missing_tables'],
                'extra_tables': result['extra_tables'],
                'missing_columns': result['missing_columns'],
                'extra_columns': result['extra_columns'],
                'type_changed': result['type_changed'],
                'missing_config_keys': result['missing_config_keys'],
                'extra_config_keys': result['extra_config_keys'],
                'admin': result['admin'],
            },
        }
        return jsonify({'status': 'success', 'data': resp})
    finally:
        session.close()
