#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 路由蓝图

所有端点统一使用 JWT Bearer Token 认证：
- @jwt_required: 需要登录即可访问
- @admin_required: 需要管理员权限
- 无装饰器: 公开端点（如健康检查）
"""
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, g
from app.core.api_response import api_success, api_error, api_paginate

from app.utils.security import get_client_ip
from app.utils.auth_middleware import jwt_required, admin_required
from app.core.logger import get_logger
from app.services.schedule_service import schedule_service
from app.services.rule_service import rule_service
from app.services.task_service import task_service
from app.services.template_service import template_service
from app.services.adapter_service import adapter_service
from app.tasks.scheduler import run_spider, get_spider_status

logger = get_logger(__name__)

api_bp = Blueprint('api', __name__)


@api_bp.route('/')
def index():
    """服务信息（公开）"""
    return api_success(message='Course Push System API', your_ip=get_client_ip(), version=current_app.config['APP_VERSION'], endpoints={'health': '/api/health', 'auth_login': 'POST /api/auth/login', 'trigger': 'POST /api/trigger', 'status': '/api/status', 'schedules': '/api/schedules', 'rules': '/api/rules', 'tasks': '/api/tasks'})


@api_bp.route('/health')
def health():
    """健康检查（无限制）"""
    return api_success(status='healthy', service='course-push-system', timestamp=int(datetime.now().timestamp()), version=current_app.config['APP_VERSION'])


@api_bp.route('/status')
@jwt_required
def status():
    """系统状态（需 JWT 认证）"""
    return api_success(service='Course Push System', version=current_app.config['APP_VERSION'], auth_enabled=current_app.config['AUTH_ENABLED'], data_ready=schedule_service.is_data_ready, schedule_stats=schedule_service.get_statistics(), task_stats=task_service.get_statistics(), adapter_status=adapter_service.get_all_status())


@api_bp.route('/trigger', methods=['POST'])
@jwt_required
def trigger():
    """手动触发推送（需 JWT 认证）

    查询参数:
        force: bool - 为 true 时忽略时间窗口检查，强制触发所有适用规则（默认 false）
        type: str - 指定规则类型（before_class/daily_schedule/before_end_class/weekly_schedule/after_class）
    """
    force = request.args.get('force', 'false').lower() == 'true'
    rule_type = request.args.get('type', '')

    schedules = schedule_service.get_schedules()
    if not schedules and not schedule_service.is_data_ready:
        return api_error(message='Schedule data not ready yet, please wait for spider to run', tasks_created=0, http_status=503)

    if force:
        tasks = rule_service.check_conditions_force(datetime.now(), schedules, rule_type=rule_type)
    else:
        tasks = rule_service.check_conditions(datetime.now(), schedules)

    if not tasks:
        return api_success(message='No trigger conditions met', tasks_created=0)

    created = task_service.create_tasks(tasks)
    user = g.get('current_user', {})
    logger.info(f'Manual trigger by {user.get("username")} (force={force}, type={rule_type}): {len(created)} task(s) created')

    return api_success(message=f'Trigger executed, {len(created)} task(s) created', tasks_created=len(created))


@api_bp.route('/schedules')
@jwt_required
def get_schedules():
    """获取课表（需 JWT 认证）"""
    force = request.args.get('force', 'false').lower() == 'true'
    schedules = schedule_service.get_schedules(force_reload=force)
    return api_success(count=len(schedules), data_ready=schedule_service.is_data_ready, schedules=schedules)


@api_bp.route('/schedules/today')
@jwt_required
def get_today_schedules():
    """获取今日课表（需 JWT 认证）"""
    schedules = schedule_service.get_today_schedules()
    return api_success(count=len(schedules), data_ready=schedule_service.is_data_ready, schedules=schedules)


@api_bp.route('/schedules/statistics')
@jwt_required
def get_statistics():
    """获取课表统计（需 JWT 认证）"""
    stats = schedule_service.get_statistics()
    return api_success(**stats)


@api_bp.route('/rules')
@jwt_required
def get_rules():
    """获取推送规则（需 JWT 认证）"""
    return api_success(rules=rule_service.get_rules())


@api_bp.route('/tasks')
@jwt_required
def get_tasks():
    """获取任务统计（需 JWT 认证）"""
    return api_success(**task_service.get_statistics())


@api_bp.route('/templates')
@jwt_required
def get_templates():
    """获取消息模板（需 JWT 认证）"""
    return api_success(templates=template_service.get_all_templates())


@api_bp.route('/templates/reload', methods=['POST'])
@admin_required
def reload_templates():
    """重新加载模板配置文件（需管理员权限）"""
    count = template_service.reload_templates()
    return api_success(message=f'Reloaded {count} templates')


@api_bp.route('/spider/run', methods=['POST'])
@admin_required
def run_spider_api():
    """手动触发爬虫（需管理员权限）"""
    spider_status = get_spider_status()
    if spider_status.get('running'):
        return api_error(message='Spider is already running', http_status=409)

    import threading
    thread = threading.Thread(target=run_spider, kwargs={'trigger_source': 'manual'}, daemon=True)
    thread.start()

    return api_success(message='Spider execution started')


@api_bp.route('/spider/status')
@jwt_required
def spider_status():
    """查询爬虫执行状态（需 JWT 认证）"""
    status = get_spider_status()
    return api_success(spider=status)
