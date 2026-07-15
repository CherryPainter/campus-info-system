#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务进程管理 API 路由

端点列表：
- GET    /api/admin/processes              — 获取进程列表
- GET    /api/admin/processes/<id>         — 获取进程详情
- POST   /api/admin/processes/<id>/stop    — 停止进程
- DELETE /api/admin/processes/<id>         — 删除进程记录
- GET    /api/admin/processes/running      — 获取运行中进程
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, g
from app.core.api_response import api_success, api_error, api_paginate

from app.utils.auth_middleware import admin_required, jwt_required
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.task_process import TaskProcess
from app.core.task_state import TaskStatus
from app.services import unified_task_service as uts

logger = get_logger(__name__)

process_bp = Blueprint('process', __name__)


@process_bp.route('', methods=['GET'])
@admin_required
def get_processes():
    """
    获取进程列表
    
    查询参数：
        status: 按状态筛选 (running/completed/failed/cancelled)
        task_type: 按类型筛选
        page: 页码，默认1
        per_page: 每页数量，默认20
    """
    from datetime import timedelta
    status = request.args.get('status', '')
    task_type = request.args.get('task_type', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    session = get_db()
    try:
        query = session.query(TaskProcess)
        
        # 只查询一个月内的记录
        one_month_ago = datetime.now() - timedelta(days=30)
        query = query.filter(TaskProcess.started_at >= one_month_ago)
        
        # 构建筛选查询（用于统计）
        stats_query = session.query(TaskProcess).filter(TaskProcess.started_at >= one_month_ago)
        if status:
            query = query.filter(TaskProcess.status == status)
            stats_query = stats_query.filter(TaskProcess.status == status)
        if task_type:
            query = query.filter(TaskProcess.task_type == task_type)
            stats_query = stats_query.filter(TaskProcess.task_type == task_type)
        
        total = query.count()
        processes = query.order_by(TaskProcess.started_at.desc()) \
            .offset((page - 1) * per_page) \
            .limit(per_page) \
            .all()
        
        # 计算全局统计（基于所有符合条件的数据）
        all_processes = stats_query.all()
        completed_count = len([p for p in all_processes if p.status == 'completed'])
        failed_count = len([p for p in all_processes if p.status == 'failed'])
        running_count = len([p for p in all_processes if p.status == 'running'])
        
        # 计算平均耗时（只包含已完成的任务）
        completed_processes = [p for p in all_processes if p.status == 'completed' and p.duration > 0]
        avg_duration = 0
        if completed_processes:
            total_duration = sum(p.duration for p in completed_processes)
            avg_duration = total_duration / len(completed_processes)
        
        return api_success(data=[p.to_dict() for p in processes], pagination={'total': total, 'page': page, 'per_page': per_page, 'pages': (total + per_page - 1) // per_page}, stats={'total': total, 'completed': completed_count, 'failed': failed_count, 'running': running_count, 'avg_duration': avg_duration})
    finally:
        session.close()


@process_bp.route('/scheduled', methods=['GET'])
@admin_required
def get_scheduled_tasks():
    """获取已注册的定时任务计划（将要进行的任务）"""
    try:
        from app.tasks.scheduler import get_scheduler_jobs
        jobs = get_scheduler_jobs()
        return api_success(data=jobs, count=len(jobs))
    except Exception as e:
        logger.error(f'[进程管理] 获取定时任务计划失败: {e}')
        return api_error(message=str(e), http_status=500)


@process_bp.route('/rules', methods=['GET'])
@admin_required
def get_dynamic_rules():
    """获取课程推送动态规则配置（实时从后端配置读取）"""
    try:
        from app.services.rule_service import rule_service
        rules = rule_service.get_rules()
        
        # 转换为前端需要的格式
        rule_type_map = {
            'before_class': 'course_reminder',
            'daily_schedule': 'daily_schedule',
            'before_end_class': 'before_end_class',
            'weekly_schedule': 'weekly_schedule',
            'after_class': 'after_class',
        }
        
        formatted_rules = []
        for rule in rules:
            r_type = rule_type_map.get(rule.get('id'), rule.get('id', ''))
            
            # 构建 trigger_desc
            if rule['id'] == 'before_class':
                trigger_desc = f'上课前 {rule.get("minutes", 15)} 分钟'
            elif rule['id'] == 'before_end_class':
                trigger_desc = f'下课前 {rule.get("minutes", 10)} 分钟'
            elif rule['id'] == 'daily_schedule':
                trigger_desc = f'每天 {rule.get("time", "07:00")}（有课时）'
            elif rule['id'] == 'weekly_schedule':
                trigger_desc = f'每周一 {rule.get("time", "08:00")}'
            elif rule['id'] == 'after_class':
                trigger_desc = f'下课后 {rule.get("minutes", 5)} 分钟'
            else:
                trigger_desc = rule.get('name', '')
            
            formatted_rules.append({
                'id': r_type,
                'name': rule.get('name', ''),
                'type': 'course',
                'trigger_desc': trigger_desc,
                'status': 'enabled' if rule.get('enabled', True) else 'disabled',
                'priority': rule.get('priority', 1),
                'rule_id': rule.get('id'),
            })
        
        return api_success(data=formatted_rules, count=len(formatted_rules))
    except Exception as e:
        logger.error(f'[进程管理] 获取动态规则配置失败: {e}')
        return api_error(message=str(e), http_status=500)


@process_bp.route('/running', methods=['GET'])
@jwt_required
def get_running_processes():
    """获取运行中的进程（所有已登录用户均可访问，用于前端轮询任务状态）"""
    session = get_db()
    try:
        processes = uts.get_running()
        
        return api_success(data=[p.to_dict() for p in processes], count=len(processes))
    finally:
        session.close()


@process_bp.route('/<int:process_id>', methods=['GET'])
@admin_required
def get_process(process_id: int):
    """获取进程详情"""
    session = get_db()
    try:
        process = session.query(TaskProcess).filter(TaskProcess.id == process_id).first()
        if not process:
            return api_error(message='进程不存在', http_status=404)
        
        return api_success(data=process.to_dict())
    finally:
        session.close()


@process_bp.route('/<int:process_id>/stop', methods=['POST'])
@admin_required
def stop_process(process_id: int):
    """停止进程"""
    session = get_db()
    try:
        process = session.query(TaskProcess).filter(TaskProcess.id == process_id).first()
        if not process:
            return api_error(message='进程不存在', http_status=404)
        
        if process.status != 'running':
            return api_error(message='进程不在运行中', http_status=400)
        
        # 使用平台适配工具终止进程
        if process.pid:
            from app.utils.platform_utils import kill_process
            success, msg = kill_process(process.pid, force=True)
            logger.info(f'[进程管理] 终止进程 {process.pid}: {msg}')
        
        # 无论进程是否存在，都更新数据库状态
        process.status = TaskStatus.CANCELLED
        process.completed_at = datetime.now()
        if process.started_at:
            process.duration = (process.completed_at - process.started_at).total_seconds()
        process.message = '手动停止'
        session.commit()
        
        return api_success(message='进程已停止')
    finally:
        session.close()


@process_bp.route('/<int:process_id>', methods=['DELETE'])
@admin_required
def delete_process(process_id: int):
    """删除进程记录"""
    session = get_db()
    try:
        process = session.query(TaskProcess).filter(TaskProcess.id == process_id).first()
        if not process:
            return api_error(message='进程不存在', http_status=404)
        
        # 如果进程还在运行，先停止
        if process.status == 'running' and process.pid:
            from app.utils.platform_utils import kill_process
            kill_process(process.pid, force=True)
        
        session.delete(process)
        session.commit()
        
        return api_success(message='进程记录已删除')
    finally:
        session.close()


# ============ 进程管理工具函数 ============

def create_task_process(name: str, task_type: str, total_items: int = 0, created_by: str = 'system') -> int:
    """
    创建任务进程记录（委托 UnifiedTaskService，统一任务写入入口）

    Args:
        name: 任务名称
        task_type: 任务类型
        total_items: 总项目数
        created_by: 创建人

    Returns:
        int: 创建的进程ID
    """
    return uts.create_process(name, task_type, total_items=total_items, created_by=created_by)


def update_task_progress(process_id: int, processed: int, total: int = None, message: str = None):
    """
    更新任务进度（委托 UnifiedTaskService）
    """
    uts.update_progress(process_id, processed, total=total, message=message)


def complete_task_process(process_id: int, status: str = TaskStatus.COMPLETED, message: str = None, error: str = None):
    """
    完成任务进程（委托 UnifiedTaskService）

    Args:
        process_id: 进程ID
        status: 完成状态 (completed/failed)
        message: 状态信息
        error: 错误信息
    """
    uts.complete_process(process_id, status=status, message=message, error=error)
