#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP黑名单管理 API 路由蓝图
提供IP黑名单的CRUD接口和安全事件查询接口

所有端点都需要 @admin_required 认证

端点列表：
- GET    /api/admin/ip-blacklist                    — 获取黑名单列表
- POST   /api/admin/ip-blacklist                    — 手动添加IP到黑名单
- DELETE /api/admin/ip-blacklist/<ip_address>       — 从黑名单移除IP
- PUT    /api/admin/ip-blacklist/<ip_address>/toggle — 启用/禁用黑名单记录
- GET    /api/admin/ip-blacklist/events             — 获取安全事件列表
- POST   /api/admin/ip-blacklist/cleanup            — 清理过期记录
"""

import ipaddress
from flask import Blueprint, request, jsonify, g
from app.core.api_response import api_success, api_error, api_paginate
from sqlalchemy import func

from app.utils.auth_middleware import admin_required
from app.core.logger import get_logger
from app.core.database import get_db
from app.model.ip_blacklist import IPBlacklist, IPSecurityEvent
from app.services.ip_blacklist_service import IPBlacklistService

logger = get_logger(__name__)

# 创建蓝图
ip_blacklist_bp = Blueprint('ip_blacklist', __name__)


# ============================================================
# IP黑名单管理
# ============================================================

@ip_blacklist_bp.route('', methods=['GET'])
@admin_required
def get_blacklist():
    """获取IP黑名单列表"""
    session = None
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        only_active = request.args.get('only_active', 'true').lower() == 'true'

        session = get_db()
        records, total = IPBlacklistService.get_blacklist(
            session=session,
            only_active=only_active,
            page=page,
            per_page=per_page,
        )

        return api_success(data={'records': [r.to_dict() for r in records], 'total': total, 'page': page, 'per_page': per_page}, http_status=200)
    except Exception as exc:
        logger.error(f'获取黑名单列表失败: {exc}')
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('', methods=['POST'])
@admin_required
def add_to_blacklist():
    """手动添加IP到黑名单"""
    session = None
    try:
        data = request.get_json()
        ip_address = data.get('ip_address', '').strip()
        reason = data.get('reason', '手动封禁')
        duration_hours = data.get('duration_hours', None)
        note = data.get('note', '')

        if not ip_address:
            return api_error(message='缺少 ip_address 参数', http_status=400)

        # 验证IP格式（简单验证）
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            return api_error(message='无效的IP地址格式', http_status=400)

        session = get_db()
        record = IPBlacklistService.block_ip(
            session=session,
            ip_address=ip_address,
            reason=reason,
            source='manual',
            created_by=g.get('admin_user', 'admin'),
            duration_hours=duration_hours,
            note=note,
        )
        session.commit()

        return api_success(message=f'IP {ip_address} 已加入黑名单', data=record.to_dict(), http_status=201)
    except Exception as exc:
        logger.error(f'添加IP到黑名单失败: {exc}')
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('/<ip_address>', methods=['DELETE'])
@admin_required
def remove_from_blacklist(ip_address):
    """从黑名单移除IP"""
    session = None
    try:
        session = get_db()
        success = IPBlacklistService.unblock_ip(
            session=session,
            ip_address=ip_address,
            unblocked_by=g.get('admin_user', 'admin'),
        )
        session.commit()

        if success:
            return api_success(message=f'IP {ip_address} 已从黑名单移除', http_status=200)
        else:
            return api_error(message=f'IP {ip_address} 不在黑名单中', http_status=404)
    except Exception as exc:
        logger.error(f'从黑名单移除IP失败: {exc}')
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('/<ip_address>/toggle', methods=['PUT'])
@admin_required
def toggle_blacklist(ip_address):
    """启用/禁用黑名单记录"""
    session = None
    try:
        data = request.get_json()
        active = data.get('active', True)

        session = get_db()
        record = session.query(IPBlacklist).filter(
            IPBlacklist.ip_address == ip_address
        ).first()

        if not record:
            return api_error(message=f'IP {ip_address} 不在黑名单中', http_status=404)

        record.is_active = active
        session.commit()

        return api_success(message=f"IP {ip_address} 已{('启用' if active else '禁用')}", data=record.to_dict(), http_status=200)
    except Exception as exc:
        logger.error(f'切换黑名单状态失败: {exc}')
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('/events', methods=['GET'])
@admin_required
def get_security_events():
    """获取安全事件列表"""
    session = None
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        event_type = request.args.get('event_type', None)
        severity = request.args.get('severity', None)
        only_pending = request.args.get('only_pending', 'false').lower() == 'true'

        session = get_db()
        events, total = IPBlacklistService.get_security_events(
            session=session,
            event_type=event_type,
            severity=severity,
            only_pending=only_pending,
            page=page,
            per_page=per_page,
        )

        return api_success(data={'events': [e.to_dict() for e in events], 'total': total, 'page': page, 'per_page': per_page}, http_status=200)
    except Exception as exc:
        logger.error(f'获取安全事件列表失败: {exc}')
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('/events/<int:event_id>/ignore', methods=['POST'])
@admin_required
def ignore_security_event(event_id: int):
    """将安全事件标记为已忽略（无需封禁）"""
    session = None
    try:
        session = get_db()
        success = IPBlacklistService.ignore_event(session=session, event_id=event_id)
        if success:
            return api_success(message=f'事件 {event_id} 已标记为忽略', http_status=200)
        return api_error(message=f'事件 {event_id} 不存在', http_status=404)
    except Exception as exc:
        logger.error(f'忽略安全事件失败: {exc}')
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('/events/<int:event_id>/ban', methods=['POST'])
@admin_required
def ban_security_event(event_id: int):
    """封禁安全事件对应的 IP"""
    session = None
    try:
        data = request.get_json(silent=True) or {}
        reason = data.get('reason', '')
        duration_hours = data.get('duration_hours', None)

        session = get_db()
        success, message = IPBlacklistService.ban_event_ip(
            session=session,
            event_id=event_id,
            reason=reason,
            duration_hours=duration_hours,
        )
        if success:
            return api_success(message=message, http_status=200)
        return api_error(message=message, http_status=404)
    except Exception as exc:
        logger.error(f'封禁安全事件 IP 失败: {exc}')
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route('/cleanup', methods=['POST'])
@admin_required
def cleanup_expired():
    """清理过期记录"""
    session = None
    try:
        session = get_db()
        cleaned_count = IPBlacklistService.cleanup_expired(session)
        session.commit()

        return api_success(message=f'已清理 {cleaned_count} 条过期记录', data={'cleaned_count': cleaned_count}, http_status=200)
    except Exception as exc:
        logger.error(f'清理过期记录失败: {exc}')
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()
