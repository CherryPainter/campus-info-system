#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP黑名单管理服务
提供IP封禁、解封、查询、自动检测等接口
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from app.model.ip_blacklist import IPBlacklist, IPSecurityEvent
from app.core.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 自动封禁阈值配置
# ============================================================
AUTO_BLOCK_THRESHOLDS = {
    'rate_limit': {          # 短时间内大量请求（疑似 DDoS / 扫描）
        'window_seconds': 60,
        'request_count': 100,  # 60秒内超过100次请求
        'block_duration_hours': 24,
    },
    'security_violation': {   # 安全违规次数（SQL注入/XSS等）
        'window_seconds': 300,
        'violation_count': 5,   # 5分钟内超过5次安全违规
        'block_duration_hours': 72,
    },
    'large_request': {        # 大请求检测
        'window_seconds': 60,
        'count': 10,            # 60秒内超过10次大请求
        'block_duration_hours': 12,
    },
    'file_upload_abuse': {     # 文件上传滥用
        'window_seconds': 300,
        'count': 20,             # 5分钟内超过20次文件上传
        'block_duration_hours': 48,
    },
}


class IPBlacklistService:
    """IP黑名单管理服务"""

    @staticmethod
    def is_ip_blocked(session: Session, ip_address: str) -> bool:
        """检查IP是否在黑名单中且未过期"""
        now = datetime.now()
        blocked = session.query(IPBlacklist).filter(
            and_(
                IPBlacklist.ip_address == ip_address,
                IPBlacklist.is_active == True,
            )
        ).first()

        if not blocked:
            return False

        # 检查是否已过期
        if blocked.expires_at and blocked.expires_at < now:
            blocked.is_active = False
            session.commit()
            logger.info(f'[IP黑名单] IP {ip_address} 封禁已自动解除（过期）')
            return False

        return True

    @staticmethod
    def block_ip(
        session: Session,
        ip_address: str,
        reason: str = '',
        source: str = 'manual',
        request_count: int = 0,
        duration_hours: Optional[int] = None,
        created_by: str = 'system',
        note: str = '',
    ) -> IPBlacklist:
        """将IP加入黑名单

        Args:
            session: 数据库会话
            ip_address: IP地址
            reason: 封禁原因
            source: 来源 (manual/auto/ddos/rate_limit)
            request_count: 触发时的请求数
            duration_hours: 封禁时长（小时），None=永久
            created_by: 操作人
            note: 备注

        Returns:
            创建或更新的黑名单记录
        """
        # 检查是否已在黑名单中
        existing = session.query(IPBlacklist).filter(
            IPBlacklist.ip_address == ip_address
        ).first()

        if existing:
            # 更新现有记录
            if reason:
                existing.reason = reason
            existing.request_count = max(existing.request_count or 0, request_count)
            existing.is_active = True
            if duration_hours:
                existing.expires_at = datetime.now() + timedelta(hours=duration_hours)
            existing.note = note or existing.note
            existing.updated_at = datetime.now()
        else:
            expires_at = None
            if duration_hours:
                expires_at = datetime.now() + timedelta(hours=duration_hours)

            existing = IPBlacklist(
                ip_address=ip_address,
                reason=reason,
                source=source,
                is_active=True,
                request_count=request_count,
                blocked_at=datetime.now(),
                expires_at=expires_at,
                created_by=created_by,
                note=note,
            )
            session.add(existing)

        session.flush()
        session.commit()
        logger.warning(f'[IP黑名单] IP {ip_address} 已被加入黑名单 | 原因: {reason} | 来源: {source}')

        # 发送告警通知
        IPBlacklistService._send_block_alert(ip_address, reason, source)

        return existing

    @staticmethod
    def unblock_ip(session: Session, ip_address: str, unblocked_by: str = 'system') -> bool:
        """从黑名单中移除IP"""
        record = session.query(IPBlacklist).filter(
            IPBlacklist.ip_address == ip_address
        ).first()

        if not record:
            return False

        record.is_active = False
        session.commit()
        logger.info(f'[IP黑名单] IP {ip_address} 已被移出黑名单 | 操作人: {unblocked_by}')
        return True

    @staticmethod
    def get_blacklist(
        session: Session,
        only_active: bool = True,
        page: int = 1,
        per_page: int = 20,
    ) -> Tuple[List[IPBlacklist], int]:
        """获取黑名单列表"""
        query = session.query(IPBlacklist)
        if only_active:
            query = query.filter(IPBlacklist.is_active == True)

        total = query.count()
        records = query.order_by(desc(IPBlacklist.blocked_at)).offset(
            (page - 1) * per_page
        ).limit(per_page).all()

        return records, total

    @staticmethod
    def get_security_events(
        session: Session,
        ip_address: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        only_pending: bool = False,
        hours: int = 24,
        page: int = 1,
        per_page: int = 50,
    ) -> Tuple[List[IPSecurityEvent], int]:
        """获取安全事件列表"""
        since = datetime.now() - timedelta(hours=hours)
        query = session.query(IPSecurityEvent).filter(
            IPSecurityEvent.created_at >= since
        )

        if ip_address:
            query = query.filter(IPSecurityEvent.ip_address == ip_address)
        if event_type:
            query = query.filter(IPSecurityEvent.event_type == event_type)
        if severity:
            query = query.filter(IPSecurityEvent.severity == severity)
        # 仅显示未处理（未封禁且未忽略）的事件
        if only_pending:
            query = query.filter(
                and_(
                    IPSecurityEvent.is_blocked == False,
                    IPSecurityEvent.is_ignored == False,
                )
            )

        total = query.count()
        events = query.order_by(desc(IPSecurityEvent.created_at)).offset(
            (page - 1) * per_page
        ).limit(per_page).all()

        return events, total

    @staticmethod
    def ignore_event(session: Session, event_id: int) -> bool:
        """将安全事件标记为已忽略（不再需要处置）"""
        event = session.query(IPSecurityEvent).filter(
            IPSecurityEvent.id == event_id
        ).first()
        if not event:
            return False
        event.is_ignored = True
        session.commit()
        logger.info(f'[IP黑名单] 安全事件 {event_id} 已标记为忽略 | IP: {event.ip_address}')
        return True

    @staticmethod
    def ban_event_ip(
        session: Session,
        event_id: int,
        reason: str = '',
        duration_hours: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """封禁安全事件对应的 IP，并标记事件已封禁

        Returns:
            (success, message)
        """
        event = session.query(IPSecurityEvent).filter(
            IPSecurityEvent.id == event_id
        ).first()
        if not event:
            return False, '事件不存在'

        ip_address = event.ip_address
        final_reason = reason or f'安全事件处置：{event.event_type}'

        IPBlacklistService.block_ip(
            session=session,
            ip_address=ip_address,
            reason=final_reason,
            source='manual',
            created_by='admin',
            duration_hours=duration_hours,
            note=f'来自安全事件 #{event_id} 的处置',
        )
        event.is_blocked = True
        session.commit()
        logger.warning(f'[IP黑名单] 安全事件 {event_id} 对应 IP {ip_address} 已被封禁')
        return True, f'IP {ip_address} 已加入黑名单'

    @staticmethod
    def record_event(
        session: Session,
        ip_address: str,
        event_type: str,
        path: str = '',
        method: str = '',
        user_agent: str = '',
        detail: str = '',
        severity: str = 'warning',
    ) -> IPSecurityEvent:
        """记录安全事件"""
        event = IPSecurityEvent(
            ip_address=ip_address,
            event_type=event_type,
            path=path[:500],
            method=method[:10],
            user_agent=(user_agent or '')[:500],
            detail=detail,
            severity=severity,
            created_at=datetime.now(),
        )
        session.add(event)
        session.flush()

        # 检查是否需要自动封禁
        should_block, block_reason, block_source = IPBlacklistService._check_auto_block(session, ip_address)
        if should_block:
            IPBlacklistService.block_ip(
                session=session,
                ip_address=ip_address,
                reason=f'{block_reason}: {block_source}',
                source=block_source,
                created_by='auto-detect',
            )
            event.is_blocked = True
            session.flush()

        session.commit()
        return event

    @staticmethod
    def _check_auto_block(session: Session, ip_address: str) -> Tuple[bool, str, str]:
        """检查是否需要自动封禁该IP

        Returns:
            (should_block, reason, source) 三元组
        """
        now = datetime.now()

        # 检查速率限制阈值
        rate_cfg = AUTO_BLOCK_THRESHOLDS['rate_limit']
        since_rate = now - timedelta(seconds=rate_cfg['window_seconds'])
        recent_requests = session.query(func.count(IPSecurityEvent.id)).filter(
            and_(
                IPSecurityEvent.ip_address == ip_address,
                IPSecurityEvent.event_type.in_(['rate_limit_exceeded', 'request']),
                IPSecurityEvent.created_at >= since_rate,
            )
        ).scalar() or 0

        if recent_requests >= rate_cfg['request_count']:
            return (
                True,
                f'{rate_cfg["window_seconds"]}秒内{recent_requests}次请求(阈值{rate_cfg["request_count"]})',
                'auto_ddos_detect',
            )

        # 检查安全违规阈值
        sec_cfg = AUTO_BLOCK_THRESHOLDS['security_violation']
        since_sec = now - timedelta(seconds=sec_cfg['window_seconds'])
        violations = session.query(func.count(IPSecurityEvent.id)).filter(
            and_(
                IPSecurityEvent.ip_address == ip_address,
                IPSecurityEvent.event_type.in_(['sql_injection', 'xss', 'suspicious_path', 'path_traversal']),
                IPSecurityEvent.created_at >= since_sec,
            )
        ).scalar() or 0

        if violations >= sec_cfg['violation_count']:
            return (
                True,
                f'{sec_cfg["window_seconds"]}秒内{violations}次安全违规(阈值{sec_cfg["violation_count"]})',
                'auto_security_violation',
            )

        return False, '', ''

    @staticmethod
    def _send_block_alert(ip_address: str, reason: str, source: str):
        """发送IP封禁告警通知（通过适配器服务推送到企业微信）"""
        try:
            from app.services.adapter_service import adapter_service
            
            # 使用系统适配器发送告警
            adapter = adapter_service.get_adapter('system')
            if adapter is None:
                logger.warning('[IP黑名单] 系统适配器未初始化，无法发送告警')
                return
            
            message = {
                'msgtype': 'markdown',
                'markdown': {
                    'content': (
                        f'**安全告警：IP已被封禁**\n\n'
                        f'**IP地址**: `{ip_address}`\n\n'
                        f'**原因**: {reason}\n\n'
                        f'**来源**: {source}\n\n'
                        f'**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n'
                        f'请管理员及时处理。'
                    )
                }
            }
            result = adapter.send(message)
            if result and result.get('success'):
                logger.info(f'[IP黑名单] 封禁告警已发送: {ip_address}')
            else:
                logger.warning(f'[IP黑名单] 封禁告警发送失败: {result}')
        except Exception as exc:
            logger.warning(f'[IP黑名单] 发送告警通知失败: {exc}')

    @staticmethod
    def cleanup_expired(session: Session) -> int:
        """清理已过期的黑名单记录"""
        now = datetime.now()
        expired = session.query(IPBlacklist).filter(
            and_(
                IPBlacklist.is_active == True,
                IPBlacklist.expires_at != None,
                IPBlacklist.expires_at < now,
            )
        ).all()

        count = len(expired)
        for record in expired:
            record.is_active = False

        if count > 0:
            session.commit()
            logger.info(f'[IP黑名单] 已清理 {count} 条过期封禁记录')

        # 清理30天前的安全事件
        cutoff = now - timedelta(days=30)
        old_events = session.query(IPSecurityEvent).filter(
            IPSecurityEvent.created_at < cutoff
        ).delete(synchronize_session=False)
        session.commit()

        return count
