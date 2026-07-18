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


# ============================================================
# 登录密码爆破分层封禁配置
# ============================================================
LOGIN_BRUTE_TIERS = {
    1: {
        'threshold': 3,           # 3 次密码错误触发
        'lock_seconds': 300,      # 锁定 5 分钟（仅限流，不写黑名单）
        'source': None,            # L1 不写黑名单，source 为 None
        'duration_hours': None,
        'severity': 'warning',
        'label': '疑似暴力破解',
    },
    2: {
        'threshold': 4,           # 4 次密码错误触发
        'lock_seconds': 1800,     # 锁定 30 分钟
        'source': 'login_brute_tier2',
        'duration_hours': 0.5,    # 30 分钟 = 0.5 小时
        'severity': 'warning',
        'label': '暴力破解-临时封禁',
    },
    3: {
        'threshold': 5,           # 5 次密码错误触发
        'lock_seconds': None,     # 永久封禁
        'source': 'login_brute_tier3',
        'duration_hours': None,   # None = 永久
        'severity': 'critical',
        'label': '暴力破解-永久封禁',
    },
}

# Redis key 前缀：login_brute:{ip}
_LOGIN_BRUTE_PREFIX = 'login_brute:'
_LOGIN_BRUTE_WINDOW_SECONDS = 300  # 滑动窗口 5 分钟


def _get_redis_client():
    """获取 Redis 客户端（单例缓存）；不可用时返回 None 降级为内存"""
    if not hasattr(_get_redis_client, '_client'):
        _get_redis_client._client = None
        try:
            from app.core.config import Config
            url = getattr(Config, 'REDIS_URL', '') or ''
            if url:
                import redis as redis_lib
                _get_redis_client._client = redis_lib.Redis.from_url(
                    url, decode_responses=True, health_check_interval=30
                )
                _get_redis_client._client.ping()  # 验证连接
                logger.info('[IP黑名单] Redis 已连接 (登录爆破计数)')
            else:
                logger.warning('[IP黑名单] REDIS_URL 未配置，登录爆破降级为内存字典')
        except Exception as exc:
            logger.warning(f'[IP黑名单] Redis 连接失败 ({exc})，降级为内存字典')
            _get_redis_client._client = False  # 标记"已尝试但失败"
    return _get_redis_client._client or None


# 内存降级字典（Redis 不可用时的 fallback）
_login_brute_memory: Dict[str, Dict] = {}  # {ip: {'count': int, 'first_fail': float}}


def reset_login_brute_counter(ip_address: str) -> bool:
    """重置指定 IP 的爆破计数器（正确登录时调用）"""
    try:
        rc = _get_redis_client()
        if rc is not None:
            key = f'{_LOGIN_BRUTE_PREFIX}{ip_address}'
            rc.delete(key)
        else:
            _login_brute_memory.pop(ip_address, None)
        return True
    except Exception as exc:
        logger.warning(f'[IP黑名单] 重置爆破计数失败: {exc}')
        return False


def check_login_brute_tier(ip_address: str) -> Optional[Dict[str, Any]]:
    """检查 IP 的登录爆破层级

    在每次密码校验**失败后**调用。返回值：
      - None: 未达到任何阈值，仅递增计数
      - dict: 触发了某层封禁，包含 {tier, action, lock_seconds, source, duration_hours, severity, label}
         调用方据此执行对应动作（L1 返回 429 / L2-L3 调 block_ip）

    注意：调用方需自行将 count +1 后再调本函数（或在本函数内部 +1）。
    本函数内部会自动递增计数并判断。
    """
    now = datetime.now()
    now_ts = now.timestamp()
    rc = _get_redis_client()

    if rc is not None:
        return _check_brute_redis(rc, ip_address, now, now_ts)
    else:
        return _check_brute_memory(ip_address, now, now_ts)


def _check_brute_redis(rc, ip_address: str, now: datetime, now_ts: float) -> Optional[Dict]:
    """Redis 实现的滑动窗口检测"""
    key = f'{_LOGIN_BRUTE_PREFIX}{ip_address}'

    pipe = rc.pipeline()
    # 用有序集合存时间戳实现滑动窗口
    pipe.zadd(key, {str(now_ts): now_ts})
    pipe.zremrangebyscore(key, 0, now_ts - _LOGIN_BRUTE_WINDOW_SECONDS)
    pipe.zcard(key)
    pipe.expire(key, _LOGIN_BRUTE_WINDOW_SECONDS + 10)
    results = pipe.execute()
    count = results[2]  # zcard 结果

    # 找到触发的最高层级
    triggered = None
    for tier_num in sorted(LOGIN_BRUTE_TIERS.keys(), reverse=True):
        tier_cfg = LOGIN_BRUTE_TIERS[tier_num]
        if count >= tier_cfg['threshold']:
            triggered = tier_num
            break

    if triggered is None:
        return None

    cfg = LOGIN_BRUTE_TIERS[triggered]
    return {
        'tier': triggered,
        'action': 'rate_limit' if triggered == 1 else ('temp_block' if triggered == 2 else 'perm_block'),
        'lock_seconds': cfg['lock_seconds'],
        'source': cfg['source'],
        'duration_hours': cfg['duration_hours'],
        'severity': cfg['severity'],
        'label': cfg['label'],
        'current_count': count,
    }


def _check_brute_memory(ip_address: str, now: datetime, now_ts: float) -> Optional[Dict]:
    """内存字典实现的滑动窗口检测（Redis 不可用时的降级方案）"""
    entry = _login_brute_memory.get(ip_address)

    # 清理过期条目（简单 GC：每 100 次调用清理一次）
    if not hasattr(_check_brute_memory, '_gc_counter'):
        _check_brute_memory._gc_counter = 0
    _check_brute_memory._gc_counter += 1
    if _check_brute_memory._gc_counter % 100 == 0:
        cutoff = now_ts - _LOGIN_BRUTE_WINDOW_SECONDS
        expired = [ip for ip, e in _login_brute_memory.items() if e.get('first_fail', 0) < cutoff]
        for ip in expired:
            del _login_brute_memory[ip]

    if entry is None or (now_ts - entry.get('first_fail', now_ts)) > _LOGIN_BRUTE_WINDOW_SECONDS:
        # 窗口过期或首次，重置
        entry = {'count': 0, 'first_fail': now_ts}
        _login_brute_memory[ip_address] = entry

    entry['count'] += 1
    count = entry['count']

    # 判定最高层级
    triggered = None
    for tier_num in sorted(LOGIN_BRUTE_TIERS.keys(), reverse=True):
        if count >= LOGIN_BRUTE_TIERS[tier_num]['threshold']:
            triggered = tier_num
            break

    if triggered is None:
        return None

    cfg = LOGIN_BRUTE_TIERS[triggered]
    return {
        'tier': triggered,
        'action': 'rate_limit' if triggered == 1 else ('temp_block' if triggered == 2 else 'perm_block'),
        'lock_seconds': cfg['lock_seconds'],
        'source': cfg['source'],
        'duration_hours': cfg['duration_hours'],
        'severity': cfg['severity'],
        'label': cfg['label'],
        'current_count': count,
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
    def _send_block_alert(ip_address: str, reason: str, source: str, tier_info: Optional[Dict] = None):
        """发送 IP 封禁告警通知（通过 system 适配器推送到企业微信）

        Args:
            tier_info: 可选，登录爆破分层信息 {tier, label, severity, current_count}
                     有此参数时推送文案包含层级信息
        """
        try:
            from app.services.adapter_service import adapter_service

            adapter = adapter_service.get_adapter('system')
            if adapter is None:
                logger.warning('[IP黑名单] 系统适配器未初始化，无法发送告警')
                return

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

            if tier_info:
                # 分层爆破封禁——差异化文案
                tier = tier_info['tier']
                label = tier_info['label']
                severity = tier_info['severity']
                count = tier_info.get('current_count', '?')
                sev_emoji = {'warning': '⚠️', 'critical': '🚨'}.get(severity, '📋')
                title = f'{sev_emoji} **{label}（第 {tier} 级）**'
                content = (
                    f'{title}\n\n'
                    f'> **IP地址**: `{ip_address}`\n\n'
                    f'> **累计失败**: {count} 次 / 5分钟\n\n'
                    f'> **原因**: {reason}\n\n'
                    f'> **来源**: {source}\n\n'
                    f'> **时间**: {now_str}\n\n'
                    f'> **处置状态**: 已自动{"临时" if tier == 2 else "永久"}封禁'
                )
            else:
                # 常规安全事件封禁（原有格式）
                content = (
                    f'**安全告警：IP已被封禁**\n\n'
                    f'> **IP地址**: `{ip_address}`\n\n'
                    f'> **原因**: {reason}\n\n'
                    f'> **来源**: {source}\n\n'
                    f'> **时间**: {now_str}\n\n'
                    f'> 请管理员及时处理。'
                )

            message = {
                'msgtype': 'markdown',
                'markdown': {
                    'content': content,
                },
            }
            result = adapter.send(message)
            if result and result.get('success'):
                logger.info(f'[IP黑名单] 封禁告警已发送: {ip_address}')
            else:
                logger.warning(f'[IP黑名单] 封禁告警发送失败: {result}')
        except Exception as exc:
            logger.warning(f'[IP黑名单] 发送告警通知失败: {exc}')

    @staticmethod
    def send_brute_force_alert(ip_address: str, tier_info: Dict[str, Any]):
        """推送登录爆破安全事件告警（L1 级别：未封禁但需关注）

        与 _send_block_alert 不同，此方法用于"已检测到暴力破解但尚未封禁"
        的场景（L1 限流），提醒管理员关注。
        """
        try:
            from app.services.adapter_service import adapter_service

            adapter = adapter_service.get_adapter('system')
            if adapter is None:
                return

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
            tier = tier_info['tier']
            label = tier_info['label']
            count = tier_info.get('current_count', '?')

            message = {
                'msgtype': 'markdown',
                'markdown': {
                    'content': (
                        f'⚠️ **安全预警：{label}（第 {tier} 级）**\n\n'
                        f'> **IP地址**: `{ip_address}`\n\n'
                        f'> **累计失败**: {count} 次 / 5分钟窗口\n\n'
                        f'> **当前状态**: 已触发速率限制（锁定 {tier_info["lock_seconds"]} 秒），未写入黑名单\n\n'
                        f'> **时间**: {now_str}\n\n'
                        f'> 如继续尝试将升级到第 2 级临时封禁 / 第 3 级永久封禁。'
                    ),
                },
            }
            result = adapter.send(message)
            if result and result.get('success'):
                logger.info(f'[IP黑名单] 爆破预警已发送 (L{tier}): {ip_address}')
            else:
                logger.warning(f'[IP黑名单] 爆破预警发送失败: {result}')
        except Exception as exc:
            logger.warning(f'[IP黑名单] 发送爆破预警失败: {exc}')

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
