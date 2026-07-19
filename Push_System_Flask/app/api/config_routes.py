#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块配置 API 路由

端点列表：
- GET    /api/admin/config                    — 获取所有模块配置（分组）
- GET    /api/admin/config/<module>           — 获取指定模块配置
- PUT    /api/admin/config/<module>/<key>     — 更新配置项
- POST   /api/admin/config/init               — 初始化默认配置
"""

import os
from flask import Blueprint, request, jsonify, g
from app.core.api_response import api_success, api_error, api_paginate
from datetime import datetime

from app.utils.auth_middleware import admin_required
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.module_config import ModuleConfig, init_default_configs, DEFAULT_CONFIGS

logger = get_logger(__name__)

config_bp = Blueprint('config', __name__)


# 模块名称映射
MODULE_NAMES = {
    'system': '系统配置',
    'weather': '天气模块',
    'electricity': '电量模块',
    'push': '推送模块',
    'course': '课程模块',
}


@config_bp.route('', methods=['GET'])
@admin_required
def get_all_configs():
    """
    获取所有模块配置（按模块分组）

    响应示例：
        {
            "status": "success",
            "data": {
                "system": { "name": "系统配置", "configs": [...] },
                "weather": { "name": "天气模块", "configs": [...] },
                ...
            }
        }
    """
    session = get_db()
    try:
        configs = session.query(ModuleConfig).order_by(ModuleConfig.module, ModuleConfig.key).all()

        # 按模块分组
        grouped = {}
        for config in configs:
            module = config.module
            if module not in grouped:
                grouped[module] = {
                    'name': MODULE_NAMES.get(module, module),
                    'configs': []
                }
            grouped[module]['configs'].append(config.to_dict())

        return api_success(data=grouped)
    finally:
        session.close()


@config_bp.route('/<module>', methods=['GET'])
@admin_required
def get_module_configs(module: str):
    """
    获取指定模块的配置

    Args:
        module: 模块名称 (system/weather/electricity/push)
    """
    session = get_db()
    try:
        configs = session.query(ModuleConfig).filter(ModuleConfig.module == module).all()

        if not configs:
            return api_error(message=f'模块 {module} 不存在或没有配置项', http_status=404)

        return api_success(data={'module': module, 'name': MODULE_NAMES.get(module, module), 'configs': [c.to_dict() for c in configs]})
    finally:
        session.close()


@config_bp.route('/<module>/<key>', methods=['PUT'])
@admin_required
def update_config(module: str, key: str):
    """
    更新配置项

    请求体：
        {
            "value": "新值"
        }

    注意：
        - 只能更新 is_editable=true 的配置项
        - 敏感配置不能通过此接口修改
    """
    data = request.get_json(silent=True) or {}
    new_value = data.get('value')

    if new_value is None:
        return api_error(message='缺少 value 参数', http_status=400)

    session = get_db()
    try:
        config = session.query(ModuleConfig).filter(
            ModuleConfig.module == module,
            ModuleConfig.key == key
        ).first()

        if not config:
            return api_error(message='配置项不存在', http_status=404)

        if not config.is_editable:
            return api_error(message='此配置项不可修改', http_status=403)

        if config.is_sensitive:
            return api_error(message='敏感配置不能通过此接口修改', http_status=403)

        # 类型验证
        try:
            if config.value_type == 'integer':
                int(new_value)
            elif config.value_type == 'float':
                float(new_value)
            elif config.value_type == 'boolean':
                if str(new_value).lower() not in ('true', 'false', '1', '0', 'yes', 'no'):
                    raise ValueError('无效的布尔值')
            elif key == 'spider_cron_expression':
                # 标准 cron 5 段：分 时 日 月 周，允许 * , - / 数字 与 ? 占位
                parts = str(new_value).strip().split()
                if len(parts) != 5:
                    raise ValueError('cron 表达式需为 5 段：分 时 日 月 周')
                import re
                allowed = re.compile(r'^[\d*,/\-?]+$')
                if not all(allowed.match(p) for p in parts):
                    raise ValueError('cron 表达式含非法字符')
        except ValueError as e:
            return api_error(message=f'值类型错误: {e}', http_status=400)

        # 更新值
        config.value = str(new_value)
        config.updated_at = datetime.now()
        session.commit()

        # 同时写入 .env 文件，使配置永久生效
        try:
            env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
            # 数据库 key → .env 变量名 映射表
            # 规则：默认 MODULE_KEY 全大写，但部分 Config 属性有特殊命名需显式映射
            ENV_KEY_MAP = {
                # 系统模块（此前因默认命名 SYSTEM_* 与实际 Config 属性名不一致而失效，已修正）
                ('system', 'app_name'):                'APP_NAME',
                ('system', 'cors_origins'):            'ALLOWED_ORIGINS',
                # 课程模块
                ('course', 'schedule_daily'):          'DAILY_PUSH_TIME',
                ('course', 'before_class_minutes'):    'BEFORE_CLASS_MINUTES',
                ('course', 'before_end_class_minutes'):'BEFORE_END_CLASS_MINUTES',
                ('course', 'class_name'):              'CLASS_NAME',
                ('course', 'enable_background'):       'COURSE_ENABLE_BACKGROUND',
                ('course', 'spider_enabled'):          'COURSE_SPIDER_ENABLED',
                ('course', 'spider_interval_hours'):   'COURSE_SPIDER_INTERVAL_HOURS',
                ('course', 'spider_cron_expression'):  'CRON_EXPRESSION',
                ('course', 'push_enabled'):            'COURSE_PUSH_ENABLED',
                ('course', 'default_push_enabled'):    'COURSE_DEFAULT_PUSH_ENABLED',
                ('course', 'jwxt_username'):           'JWXT_USERNAME',
                ('course', 'jwxt_password'):           'JWXT_PASSWORD',
                # 天气模块
                ('weather', 'schedule_daily'):         'WEATHER_SCHEDULE_DAILY',
                ('weather', 'city_name'):              'QWEATHER_CITY_NAME',
                ('weather', 'location_id'):            'QWEATHER_LOCATION',
                ('weather', 'alert_enabled'):          'WEATHER_ALERT_ENABLED',
                ('weather', 'latitude'):               'WEATHER_LATITUDE',
                ('weather', 'longitude'):              'WEATHER_LONGITUDE',
                # 电量模块
                ('electricity', 'schedule_daily'):         'ELECTRICITY_SCHEDULE_DAILY',
                ('electricity', 'schedule_weekly'):        'ELECTRICITY_SCHEDULE_WEEKLY',
                ('electricity', 'schedule_weekly_day'):    'ELECTRICITY_SCHEDULE_WEEKLY_DAY',
                ('electricity', 'schedule_monthly'):       'ELECTRICITY_SCHEDULE_MONTHLY',
                ('electricity', 'schedule_monthly_day'):   'ELECTRICITY_SCHEDULE_MONTHLY_DAY',
                ('electricity', 'cookie_check_time'):      'ELECTRICITY_COOKIE_CHECK_TIME',
                ('electricity', 'low_power_threshold'):    'ELECTRICITY_LOW_POWER_THRESHOLD',
                ('electricity', 'low_power_interval_hours'): 'ELECTRICITY_LOW_POWER_INTERVAL_HOURS',
                ('electricity', 'full_crawl_day'):           'ELECTRICITY_FULL_CRAWL_DAY',
                ('electricity', 'full_crawl_time'):          'ELECTRICITY_FULL_CRAWL_TIME',
            }
            env_key = ENV_KEY_MAP.get((module, key), f"{module.upper()}_{key.upper()}")
            
            # 读取现有 .env 内容
            env_vars = {}
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            env_vars[k] = v
            
            # 更新值
            env_vars[env_key] = str(new_value)
            
            # 写回 .env 文件
            with open(env_file, 'w', encoding='utf-8') as f:
                for k, v in env_vars.items():
                    f.write(f'{k}={v}\n')
            
            logger.info(f'[配置管理] 配置已写入 .env: {env_key} = {new_value}')
        except Exception as e:
            logger.warning(f'[配置管理] 写入 .env 失败: {e}')

        # 重新加载配置和定时任务
        try:
            from app.core.config import Config
            from app.tasks.scheduler import reload_scheduler
            from app import get_current_app
            
            # 重新加载配置
            Config.reload()
            logger.info(f'[配置管理] Config 类已重新加载')
            
            # 同步更新 Flask 的 app.config
            app = get_current_app()
            if app:
                # 先将 Config 类的属性同步到 app.config
                for attr in dir(Config):
                    if not attr.startswith('_') and attr.isupper():
                        value = getattr(Config, attr)
                        if not callable(value):
                            app.config[attr] = value
                
                # 重新加载定时任务（针对调度器相关的参数变更）
                if module in ('course', 'electricity', 'weather') and key in (
                    'spider_enabled', 'spider_interval_hours', 'spider_schedule_mode',
                    'spider_cron_expression',
                    'schedule_daily', 'schedule_weekly', 'schedule_weekly_day',
                    'schedule_monthly', 'schedule_monthly_day',
                    'cookie_check_time', 'low_power_interval_hours',
                    'full_crawl_day', 'full_crawl_time',
                ):
                    reload_scheduler(app)
                    logger.info(f'[配置管理] 定时任务已重新加载 (触发参数: {module}.{key})')
                
                # 如果修改了课程提醒分钟数或每日推送时间，重置规则引擎的触发缓存
                # （规则引擎已改为动态读取，无需重新 _init_rules，但需要清空去重缓存避免漏发）
                if module == 'course' and key in ('before_class_minutes', 'before_end_class_minutes', 'schedule_daily'):
                    try:
                        from app.services.rule_service import rule_service
                        rule_service._triggered_keys.clear()
                        rule_service._triggered_keys_ts.clear()
                        logger.info(f'[配置管理] 规则引擎触发缓存已清空 ({module}.{key} = {new_value})')
                    except Exception as re:
                        logger.warning(f'[配置管理] 清空规则缓存失败: {re}')
        except Exception as e:
            logger.error(f'[配置管理] 重新加载配置失败: {e}', exc_info=True)

        logger.info(f'[配置管理] 更新配置: {module}.{key} = {new_value}')

        return api_success(message='配置已更新、保存并重新加载', data=config.to_dict())
    finally:
        session.close()


@config_bp.route('/init', methods=['POST'])
@admin_required
def init_configs():
    """
    初始化默认配置

    将默认配置写入数据库，已存在的配置不会被覆盖。
    """
    session = get_db()
    try:
        init_default_configs(session)

        return api_success(message='默认配置已初始化')
    except Exception as e:
        logger.error(f'[配置管理] 初始化失败: {e}')
        return api_error(message=str(e), http_status=500)
    finally:
        session.close()


@config_bp.route('/schema', methods=['GET'])
@admin_required
def get_config_schema():
    """
    获取配置模式定义

    返回所有可配置项的定义，用于前端动态生成表单。
    """
    return api_success(data=DEFAULT_CONFIGS)
