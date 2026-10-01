#!/usr/bin/env python3
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
from datetime import datetime

from flask import Blueprint, g, request

from app.core.api_response import api_error, api_success
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.ip_blacklist import IPBlacklist
from app.services.ip_blacklist_service import IPBlacklistService
from app.utils.auth_middleware import admin_required
from app.utils.security import get_client_ip, ip_in_admin_whitelist

logger = get_logger(__name__)


def _reject_unblockable_ip(ip_address: str):
    """校验该 IP 是否允许手动封禁；返回错误文案，允许则返回 None。

    三类必须拒绝（都是「封了会把自己或服务锁死」，属运维可用性事故）：
    1. **本机/保留地址**（回环、未指定、组播、保留）：不是外部来源，封禁没有防护意义，
       却可能打断服务自身的本地调用；
    2. **管理员白名单** `REGION_BLOCK_EXCEPTIONS`：该名单的既定语义就是「防止误锁自己」，
       拦截层也已对其中 IP 永久放行，写入层面再挡一道，避免出现「看着被封、实际没封」的
       迷惑记录；
    3. **当前请求来源 IP**：一旦命中，全局 before_request 会拦下所有 `/api/*`
       （仅登录两个路径白名单放行）→ 管理员当场失去整个后台，甚至无法自行解封
       （解封接口同样被拦）。这条最容易被误操作触发，必须硬拦。
    """
    try:
        ip = ipaddress.ip_address(ip_address)
    except ValueError:
        return "无效的IP地址格式"

    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return (
            f"不能封禁本机或保留地址（{ip_address}）：这类地址不构成外部来源，"
            "封禁没有防护意义，还可能打断服务自身的本地调用"
        )

    if ip_in_admin_whitelist(str(ip)):
        return (
            f"不能封禁管理员白名单内的地址（{ip_address}）："
            "该名单配置在 REGION_BLOCK_EXCEPTIONS，用于防止误锁自己；"
            "如确需封禁，请先从该配置中移除"
        )

    client_ip = get_client_ip()
    if client_ip and str(ip) == str(ipaddress.ip_address(client_ip)):
        return (
            f"不能封禁当前请求来源 IP（{ip_address}）：封禁后所有管理接口都会被拦截，"
            "包括本条解封接口，你将无法自行恢复"
        )

    return None

# 创建蓝图
ip_blacklist_bp = Blueprint("ip_blacklist", __name__)


# ============================================================
# IP黑名单管理
# ============================================================


@ip_blacklist_bp.route("", methods=["GET"])
@admin_required
def get_blacklist():
    """获取IP黑名单列表"""
    session = None
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        only_active = request.args.get("only_active", "true").lower() == "true"

        session = get_db()
        records, total = IPBlacklistService.get_blacklist(
            session=session,
            only_active=only_active,
            page=page,
            per_page=per_page,
        )

        return api_success(
            data={
                "records": [r.to_dict() for r in records],
                "total": total,
                "page": page,
                "per_page": per_page,
            },
            http_status=200,
        )
    except Exception as exc:
        logger.error(f"获取黑名单列表失败: {exc}")
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("", methods=["POST"])
@admin_required
def add_to_blacklist():
    """手动添加IP到黑名单"""
    session = None
    try:
        data = request.get_json()
        ip_address = data.get("ip_address", "").strip()
        reason = data.get("reason", "手动封禁")
        duration_hours = data.get("duration_hours", None)
        note = data.get("note", "")

        if not ip_address:
            return api_error(message="缺少 ip_address 参数", http_status=400)

        # 验证IP格式（简单验证）
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            return api_error(message="无效的IP地址格式", http_status=400)

        # 自锁围栏：本机/保留地址、管理员白名单、当前请求来源 IP 一律拒绝
        unblockable = _reject_unblockable_ip(ip_address)
        if unblockable:
            logger.warning(f"[IP黑名单] 拒绝封禁 {ip_address}: {unblockable}")
            return api_error(message=unblockable, http_status=400)

        session = get_db()
        record = IPBlacklistService.block_ip(
            session=session,
            ip_address=ip_address,
            reason=reason,
            source="manual",
            created_by=g.get("admin_user", "admin"),
            duration_hours=duration_hours,
            note=note,
        )
        session.commit()

        return api_success(
            message=f"IP {ip_address} 已加入黑名单", data=record.to_dict(), http_status=201
        )
    except Exception as exc:
        logger.error(f"添加IP到黑名单失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/<ip_address>", methods=["DELETE"])
@admin_required
def remove_from_blacklist(ip_address):
    """从黑名单移除IP"""
    session = None
    try:
        session = get_db()
        success = IPBlacklistService.unblock_ip(
            session=session,
            ip_address=ip_address,
            unblocked_by=g.get("admin_user", "admin"),
        )
        session.commit()

        if success:
            return api_success(message=f"IP {ip_address} 已从黑名单移除", http_status=200)
        else:
            return api_error(message=f"IP {ip_address} 不在黑名单中", http_status=404)
    except Exception as exc:
        logger.error(f"从黑名单移除IP失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/<ip_address>/toggle", methods=["PUT"])
@admin_required
def toggle_blacklist(ip_address):
    """启用/禁用黑名单记录"""
    session = None
    try:
        data = request.get_json()
        active = data.get("active", True)

        session = get_db()
        record = session.query(IPBlacklist).filter(IPBlacklist.ip_address == ip_address).first()

        if not record:
            return api_error(message=f"IP {ip_address} 不在黑名单中", http_status=404)

        record.is_active = active
        session.commit()

        return api_success(
            message=f"IP {ip_address} 已{('启用' if active else '禁用')}",
            data=record.to_dict(),
            http_status=200,
        )
    except Exception as exc:
        logger.error(f"切换黑名单状态失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/<ip_address>/update", methods=["PUT"])
@admin_required
def update_blacklist(ip_address):
    """更新黑名单记录（封禁期限、原因、备注）"""
    session = None
    try:
        data = request.get_json(silent=True) or {}

        session = get_db()
        record = session.query(IPBlacklist).filter(IPBlacklist.ip_address == ip_address).first()

        if not record:
            return api_error(message=f"IP {ip_address} 不在黑名单中", http_status=404)

        # 逐字段更新（只传的才改）
        if "reason" in data and data["reason"] is not None:
            record.reason = str(data["reason"]).strip() or record.reason
        if "duration_hours" in data:
            dh = data["duration_hours"]
            if dh is None or dh == 0:
                record.expires_at = None  # 永久
            elif isinstance(dh, int | float) and dh > 0:
                from datetime import timedelta

                record.expires_at = datetime.now() + timedelta(hours=float(dh))
        if "note" in data and data["note"] is not None:
            record.note = str(data["note"]).strip() or record.note
        if "is_active" in data:
            record.is_active = bool(data["is_active"])

        record.updated_at = datetime.now()
        session.commit()

        return api_success(
            message=f"IP {ip_address} 已更新",
            data=record.to_dict(),
            http_status=200,
        )
    except Exception as exc:
        logger.error(f"更新黑名单记录失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/events", methods=["GET"])
@admin_required
def get_security_events():
    """获取安全事件列表"""
    session = None
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        event_type = request.args.get("event_type", None)
        severity = request.args.get("severity", None)
        only_pending = request.args.get("only_pending", "false").lower() == "true"

        session = get_db()
        events, total = IPBlacklistService.get_security_events(
            session=session,
            event_type=event_type,
            severity=severity,
            only_pending=only_pending,
            page=page,
            per_page=per_page,
        )

        return api_success(
            data={
                "events": [e.to_dict() for e in events],
                "total": total,
                "page": page,
                "per_page": per_page,
            },
            http_status=200,
        )
    except Exception as exc:
        logger.error(f"获取安全事件列表失败: {exc}")
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/events/<int:event_id>/ignore", methods=["POST"])
@admin_required
def ignore_security_event(event_id: int):
    """将安全事件标记为已忽略（无需封禁）"""
    session = None
    try:
        session = get_db()
        success = IPBlacklistService.ignore_event(session=session, event_id=event_id)
        if success:
            return api_success(message=f"事件 {event_id} 已标记为忽略", http_status=200)
        return api_error(message=f"事件 {event_id} 不存在", http_status=404)
    except Exception as exc:
        logger.error(f"忽略安全事件失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/events/<int:event_id>/ban", methods=["POST"])
@admin_required
def ban_security_event(event_id: int):
    """封禁安全事件对应的 IP"""
    session = None
    try:
        data = request.get_json(silent=True) or {}
        reason = data.get("reason", "")
        duration_hours = data.get("duration_hours", None)

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
        logger.error(f"封禁安全事件 IP 失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()


@ip_blacklist_bp.route("/cleanup", methods=["POST"])
@admin_required
def cleanup_expired():
    """清理过期记录"""
    session = None
    try:
        session = get_db()
        cleaned_count = IPBlacklistService.cleanup_expired(session)
        session.commit()

        return api_success(
            message=f"已清理 {cleaned_count} 条过期记录",
            data={"cleaned_count": cleaned_count},
            http_status=200,
        )
    except Exception as exc:
        logger.error(f"清理过期记录失败: {exc}")
        if session:
            session.rollback()
        return api_error(message=str(exc), http_status=500)
    finally:
        if session:
            session.close()
