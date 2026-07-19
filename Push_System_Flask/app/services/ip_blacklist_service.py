#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP黑名单管理服务
提供IP封禁、解封、查询、自动检测等接口
"""

import json
import time
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
# 登录失败「信号感知」分层配置（滑动窗口 5 分钟）
# ============================================================
# 设计原则：登录失败信号高度歧义——可能是攻击，也可能是真人忘密码、
# 或校园网 NAT 下多人各自输错叠加。因此按"信号维度"分别判定，
# 避免一刀切把"失败 N 次"都咬死为"暴力破解"，并避免对共享 IP 永久封禁。
LOGIN_FAIL_WINDOW_SECONDS = 300  # 滑动窗口：5 分钟

# 维度一：账号级（同一 IP 对该账号失败次数）→ 限流该 IP，不锁账号、不影响其他 IP
# 关键点：计数 key 带 IP，故攻击者从某 IP 试错只限流该 IP，admin 从自己 IP 登录不受影响
ACCOUNT_FAIL_TIERS = {
    1: {
        'threshold': 5,            # 同一 IP 对同一账号 5 分钟内失败 5 次
        'action': 'rate_limit',    # 仅限流该 (IP,账号)，不锁账号
        'lock_seconds': 1800,      # 限流窗口 30 分钟（窗口内自然失效）
        'severity': 'warning',
        'label': '该IP对该账号尝试次数过多(限流)',
    },
}

# 维度二：IP 跨账号（同一 IP 窗口内失败涉及的【不同账号】数）→ 疑似撞库/枚举
IP_CROSS_ACCOUNT_TIERS = {
    1: {
        'threshold': 3,            # 3 个不同账号失败
        'action': 'rate_limit',    # 仅限流（不封禁，避免共享 IP 连坐）
        'lock_seconds': 300,
        'severity': 'warning',
        'label': '疑似撞库/枚举(限流)',
    },
    2: {
        'threshold': 5,            # 5 个不同账号失败
        'action': 'temp_block',    # 临时封禁该 IP（非永久）
        'lock_seconds': 3600,
        'duration_hours': 1,       # 封禁 1 小时
        'source': 'login_brute_tier2',
        'severity': 'critical',
        'label': '疑似撞库/枚举(临时封禁)',
    },
}

# 维度三：IP 枚举（同一 IP 窗口内"用户名不存在"涉及的【不同用户名】数）→ 枚举探测
IP_ENUM_TIERS = {
    1: {
        'threshold': 8,            # 8 个不同不存在的用户名
        'action': 'rate_limit',
        'lock_seconds': 600,
        'severity': 'warning',
        'label': '用户名枚举探测(限流)',
    },
}

# 维度四：IP 总量（同一 IP 窗口内登录失败总次数，含空参数/异常客户端）→ 纯限流
IP_VOLUME_TIERS = {
    1: {
        'threshold': 30,           # 5 分钟内 30 次失败
        'action': 'rate_limit',
        'lock_seconds': 120,
        'severity': 'info',
        'label': '登录失败频率过高(限流)',
    },
}

# 维度五：账号遭多 IP 围攻（同一账号窗口内失败的【不同来源 IP】数）→ 提升账号风险等级
# 用于防护 admin 等重点账号被分布式爆破：账号本身永不锁、也【不封禁攻击源 IP】
# （5 个 IP 可能是 NAT / 公司出口 / 校园网，封 IP 会误伤正常用户）；
# 改为标记账号为高风险：若账号已启用 MFA 则强制 MFA 挑战（攻击者无 TOTP 被拦），
# 未启用 MFA 则仅依赖其他维度(维度一/四)限流，避免误伤。
ACCOUNT_CROSS_IP_TIERS = {
    1: {
        'threshold': 5,            # 5 个不同来源 IP 在窗口内试同一账号
        'action': 'account_risk',  # 提升账号风险等级（不封 IP，避免 NAT/校园网误伤）
        'lock_seconds': 0,
        'source': 'login_account_target',
        'severity': 'critical',
        'label': '账号遭多IP围攻(风险升级,未封IP)',
        'risk_level': 'HIGH',
    },
}

# Redis key 前缀
_AFAIL_PREFIX = 'login_afail:'       # ZSET member=timestamp，按 (IP,账号)
_ACFAILIP_PREFIX = 'login_afailip:'  # ZSET member=ip（不同来源IP数），按账号
_IPXA_PREFIX = 'login_ipxa:'         # ZSET member=username（不同账号数），按 IP
_IENUM_PREFIX = 'login_ienum:'       # ZSET member=username（不同不存在用户名数），按 IP
_IVOL_PREFIX = 'login_ivol:'         # ZSET member=timestamp（总量），按 IP
_ARISK_PREFIX = 'login_arisk:'      # 账号高风险标记（member='risk'），按账号，窗口到期自动清除

def log_redis_status() -> None:
    """
    启动时主动探测 Redis 连接状态并打印明确日志，避免静默降级导致无从判断。
    - REDIS_URL 为空：明确提示使用进程内存（开发/单机）
    - 配置但连不上：WARNING 提示降级内存（限流/登录爆破跨进程不生效）
    - 连接成功：INFO 提示已连接
    仅用于日志可见性，不改变限流器/登录爆破的实际存储策略（实际可用性由
    _get_redis_client 的冷却期机制决定，Redis 恢复后可自动重连）。
    """
    from app.core.config import Config
    url = getattr(Config, 'REDIS_URL', '') or ''
    if not url:
        logger.info('[Redis] 未配置 REDIS_URL，限流与登录爆破使用进程内存（开发/单机，重启会丢失计数）')
        return
    try:
        import redis as redis_lib
        import socket
        client = redis_lib.Redis.from_url(
            url, decode_responses=True,
            socket_family=socket.AF_INET, socket_connect_timeout=2
        )
        client.ping()
        logger.info(f'[Redis] 已连接: {url}（限流与登录爆破计数持久化）')
    except Exception as exc:
        logger.warning(f'[Redis] 连接失败（{exc}），限流与登录爆破降级为进程内存（仅本进程生效，多 worker 不共享）')


# Redis 不可用冷却期（秒）：探测/连接失败后在此期间直接降级为内存、不再建连，
# 避免每次请求阻塞；冷却期过后允许重试一次，从而实现"启动期无 Redis / 运行期
# Redis 挂掉"在 Redis 恢复后自动重连（无需重启进程）。
REDIS_UNAVAILABLE_COOLDOWN = 60


def _get_redis_client():
    """获取 Redis 客户端（单例缓存）；不可用时返回 None 降级为内存。

    可用性采用"冷却期"策略：探测/连接失败后进入冷却期（REDIS_UNAVAILABLE_COOLDOWN），
    冷却期内直接返回 None（零阻塞降级）；冷却期过后重新探测一次。这样：
    - 启动期无 Redis、运行期 Redis 挂掉 → 冷却期降级，Redis 恢复后自动重连（无需重启）
    - 已建立的有效 client 实例由 redis-py 连接池在运行期连接断开时自动重连
    """
    cached = getattr(_get_redis_client, '_client', None)
    # 已有有效 client：直接返回（连接池自动重连处理运行期断开）
    if cached is not False and cached is not None:
        return cached
    # 上次失败仍在冷却期内：直接降级，不重连（零阻塞）
    if getattr(_get_redis_client, '_unavailable_until', 0) > time.time():
        return None
    # 需要（重新）探测
    now = time.time()
    try:
        from app.core.config import Config
        url = getattr(Config, 'REDIS_URL', '') or ''
        if not url:
            logger.warning('[IP黑名单] REDIS_URL 未配置，登录爆破降级为内存字典')
            _get_redis_client._client = False
            _get_redis_client._unavailable_until = now + REDIS_UNAVAILABLE_COOLDOWN
        else:
            import redis as redis_lib
            import socket
            client = redis_lib.Redis.from_url(
                url, decode_responses=True, health_check_interval=30,
                socket_family=socket.AF_INET,
                socket_connect_timeout=2, socket_timeout=2
            )
            client.ping()  # 验证连接（带 2s 超时，避免无限制阻塞）
            _get_redis_client._client = client
            _get_redis_client._unavailable_until = 0
            logger.info('[IP黑名单] Redis 已连接 (登录爆破计数)')
    except Exception as exc:
        logger.warning(
            f'[IP黑名单] Redis 连接失败 ({exc})，降级为内存字典'
            f'（{REDIS_UNAVAILABLE_COOLDOWN}s 内不再重试）'
        )
        _get_redis_client._client = False
        _get_redis_client._unavailable_until = time.time() + REDIS_UNAVAILABLE_COOLDOWN
    return _get_redis_client._client or None


# 内存降级字典（Redis 不可用时的 fallback）：full_key -> {member: ts}
_login_fail_memory: Dict[str, Dict[str, float]] = {}


def _win_add(rc, prefix: str, key: str, member: str, now_ts: float) -> int:
    """滑动窗口增量写入，返回窗口内计数。rc=None 走内存。

    member 语义：
      - 账号级 / 总量：member = 时间戳字符串（每次唯一）
      - 跨账号 / 枚举：member = 用户名（天然去重，ZCARD=不同账号数）
    """
    full = f'{prefix}{key}'
    cutoff = now_ts - LOGIN_FAIL_WINDOW_SECONDS
    if rc is not None:
        pipe = rc.pipeline()
        pipe.zadd(full, {member: now_ts})
        pipe.zremrangebyscore(full, 0, cutoff)
        pipe.zcard(full)
        pipe.expire(full, LOGIN_FAIL_WINDOW_SECONDS + 10)
        return pipe.execute()[2]
    # 内存降级
    d = _login_fail_memory.setdefault(full, {})
    for m in list(d.keys()):
        if d[m] < cutoff:
            del d[m]
    d[member] = now_ts
    return len(d)


def _win_del(rc, prefix: str, key: str) -> None:
    """删除整个键（账号计数重置）"""
    full = f'{prefix}{key}'
    if rc is not None:
        rc.delete(full)
    else:
        _login_fail_memory.pop(full, None)


def _win_zrem(rc, prefix: str, key: str, member: str) -> None:
    """从集合中移除某个 member（如登录成功后移除该账号）"""
    full = f'{prefix}{key}'
    if rc is not None:
        rc.zrem(full, member)
    else:
        _login_fail_memory.get(full, {}).pop(member, None)


def _win_members(rc, prefix: str, key: str, now_ts: float) -> List[str]:
    """返回窗口内的 member 列表（用于"账号遭多IP围攻"维度取攻击源 IP）"""
    full = f'{prefix}{key}'
    cutoff = now_ts - LOGIN_FAIL_WINDOW_SECONDS
    if rc is not None:
        return list(rc.zrange(full, 0, -1))
    d = _login_fail_memory.get(full, {})
    return [m for m, ts in d.items() if ts >= cutoff]


def _match_tier(tiers: Dict[int, Dict], count: int) -> Optional[int]:
    """返回触发的最高层级（达到阈值的最大 tier），未触发返回 None"""
    triggered = None
    for n in sorted(tiers.keys(), reverse=True):
        if count >= tiers[n]['threshold']:
            triggered = n
            break
    return triggered


def reset_login_counters(ip_address: str, username: str) -> bool:
    """登录成功后重置计数：清除该账号计数，并从 IP 跨账号集合中移除该账号"""
    try:
        rc = _get_redis_client()
        # 维度一按 (IP,账号) 计数：key 形如 'ip:username'，需与写入保持一致
        if username:
            _win_del(rc, _AFAIL_PREFIX, f'{ip_address}:{username}')
            _win_del(rc, _AFAIL_PREFIX, username)  # 兼容升级前旧版 key
        _win_del(rc, _ACFAILIP_PREFIX, username)
        if username:
            _win_del(rc, _ARISK_PREFIX, username)  # 清除账号高风险标记
            _win_zrem(rc, _IPXA_PREFIX, ip_address, username)
        return True
    except Exception as exc:
        logger.warning(f'[IP黑名单] 重置登录计数失败: {exc}')
        return False


def evaluate_login_failure(
    ip_address: str,
    username: str,
    kind: str,
) -> Optional[Dict[str, Any]]:
    """评估一次登录失败信号，返回应执行的处置决策（或 None 表示无需拦截）。

    Args:
        ip_address: 客户端 IP
        username: 尝试的用户名（空参数时可为 ''）
        kind: 'password'（密码错/账号存在）| 'notfound'（用户名不存在）| 'empty'（空参数）

    Returns:
        决策 dict（按严重程度取最高优先级）：
        {
          'level', 'scope'('ip_account'|'ip'|'account_target'),
          'action'('rate_limit'|'temp_block'),
          'lock_seconds', 'source', 'duration_hours', 'severity', 'label', 'current_count'
        }
        或 None。
    """
    now_ts = datetime.now().timestamp()
    rc = _get_redis_client()
    results: List[Dict[str, Any]] = []

    # 维度一：账号级（同一 IP 对该账号失败次数）→ 限流该 IP，不锁账号、不影响其他 IP
    if kind == 'password' and username:
        cnt = _win_add(rc, _AFAIL_PREFIX, f'{ip_address}:{username}', str(now_ts), now_ts)
        t = _match_tier(ACCOUNT_FAIL_TIERS, cnt)
        if t:
            cfg = ACCOUNT_FAIL_TIERS[t]
            results.append({
                'level': t, 'scope': 'ip_account', 'action': 'rate_limit',
                'lock_seconds': cfg['lock_seconds'], 'source': None,
                'duration_hours': None, 'severity': cfg['severity'],
                'label': cfg['label'], 'current_count': cnt,
            })

    # 维度二：IP 跨账号（不同账号失败数）
    if username:
        cnt = _win_add(rc, _IPXA_PREFIX, ip_address, username, now_ts)
        t = _match_tier(IP_CROSS_ACCOUNT_TIERS, cnt)
        if t:
            cfg = IP_CROSS_ACCOUNT_TIERS[t]
            results.append({
                'level': t, 'scope': 'ip', 'action': cfg['action'],
                'lock_seconds': cfg['lock_seconds'], 'source': cfg.get('source'),
                'duration_hours': cfg.get('duration_hours'),
                'severity': cfg['severity'], 'label': cfg['label'], 'current_count': cnt,
            })

    # 维度三：IP 枚举（用户名不存在涉及的不同用户名）
    if kind == 'notfound' and username:
        cnt = _win_add(rc, _IENUM_PREFIX, ip_address, username, now_ts)
        t = _match_tier(IP_ENUM_TIERS, cnt)
        if t:
            cfg = IP_ENUM_TIERS[t]
            results.append({
                'level': t, 'scope': 'ip', 'action': cfg['action'],
                'lock_seconds': cfg['lock_seconds'], 'source': 'login_enum',
                'duration_hours': None, 'severity': cfg['severity'],
                'label': cfg['label'], 'current_count': cnt,
            })

    # 维度四：IP 总量限流（所有失败，含空参数）
    cnt = _win_add(rc, _IVOL_PREFIX, ip_address, str(now_ts), now_ts)
    t = _match_tier(IP_VOLUME_TIERS, cnt)
    if t:
        cfg = IP_VOLUME_TIERS[t]
        results.append({
            'level': t, 'scope': 'ip', 'action': cfg['action'],
            'lock_seconds': cfg['lock_seconds'], 'source': 'login_rate_limit',
            'duration_hours': None, 'severity': cfg['severity'],
            'label': cfg['label'], 'current_count': cnt,
        })

    # 维度五：账号遭多 IP 围攻（同一账号窗口内失败的【不同来源 IP】数）
    # 处置：提升账号风险等级（不封 IP，避免 NAT/校园网误伤）；由 login() 在密码正确时强制 MFA 挑战
    if kind == 'password' and username:
        cnt = _win_add(rc, _ACFAILIP_PREFIX, username, ip_address, now_ts)
        t = _match_tier(ACCOUNT_CROSS_IP_TIERS, cnt)
        if t:
            cfg = ACCOUNT_CROSS_IP_TIERS[t]
            # 标记账号为高风险（窗口到期自动清除）；与是否触发限流无关，确保风险状态持久
            _win_add(rc, _ARISK_PREFIX, username, 'risk', now_ts)
            results.append({
                'level': t, 'scope': 'account_target', 'action': 'account_risk',
                'lock_seconds': cfg['lock_seconds'], 'source': cfg['source'],
                'duration_hours': cfg.get('duration_hours'),
                'severity': cfg['severity'], 'label': cfg['label'],
                'risk_level': cfg.get('risk_level'),
                'current_count': cnt,
            })

    if not results:
        return None

    # 优先级：temp_block(多IP围攻/跨账号) > rate_limit(单IP限流)
    _pri = {'temp_block': 2, 'rate_limit': 1}.get
    results.sort(key=lambda r: _pri(r['action'], 0), reverse=True)
    return results[0]


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
    def is_account_high_risk(username: str) -> bool:
        """账号是否处于高风险（遭多 IP 围攻）。高风险由 login() 在密码正确时触发 MFA 强制挑战。

        风险标记由 evaluate_login_failure 维度五写入，窗口到期（5分钟）自动清除。
        """
        if not username:
            return False
        try:
            rc = _get_redis_client()
            now_ts = datetime.now().timestamp()
            # 标记以 member='risk' 写入 _ARISK_PREFIX:<username>，窗口内存在即高风险
            return bool(_win_members(rc, _ARISK_PREFIX, username, now_ts))
        except Exception as exc:
            logger.warning(f'[IP黑名单] 查询账号高风险失败（降级为否）: {exc}')
            return False

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

        # 检查是否需要自动封禁（自动封禁一律限时，到期自动解除，避免误判永久拉黑）
        should_block, block_reason, block_source, block_dur = IPBlacklistService._check_auto_block(session, ip_address)
        if should_block:
            IPBlacklistService.block_ip(
                session=session,
                ip_address=ip_address,
                reason=f'{block_reason}: {block_source}',
                source=block_source,
                created_by='auto-detect',
                duration_hours=block_dur,
            )
            event.is_blocked = True
            session.flush()

        session.commit()
        return event

    @staticmethod
    def _check_auto_block(session: Session, ip_address: str) -> Tuple[bool, str, str, Optional[int]]:
        """检查是否需要自动封禁该IP

        Returns:
            (should_block, reason, source, duration_hours) 四元组。
            duration_hours 从对应阈值配置的 block_duration_hours 读取（限时封禁，
            到期自动解除），None 表示永久。红线：自动封禁一律限时，避免误判把正常
            IP 永久拉黑；只有管理员手动封禁才可永久。
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
                rate_cfg.get('block_duration_hours'),
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
                sec_cfg.get('block_duration_hours'),
            )

        return False, '', '', None

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
                sev_label = {'warning': '警告', 'critical': '严重'}.get(severity, '提示')
                title = f'**{label}（第 {tier} 级 · {sev_label}）**'
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
    def send_login_security_alert(ip_address: str, dec: Dict[str, Any], blocked: bool = False):
        """推送登录安全信号告警（限流/锁定/封禁均可能触发）

        Args:
            dec: evaluate_login_failure 返回的决策 dict
            blocked: 是否已对该 IP 执行封禁（影响文案）
        """
        try:
            from app.services.adapter_service import adapter_service

            adapter = adapter_service.get_adapter('system')
            if adapter is None:
                return

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
            sev = dec.get('severity', 'warning')
            sev_label = {'warning': '警告', 'critical': '严重', 'info': '提示'}.get(sev, '提示')
            if dec.get('scope') == 'account_target':
                scope_cn = '账号(多IP围攻)'
            elif dec.get('scope') == 'ip_account':
                scope_cn = '该IP-账号'
            else:
                scope_cn = 'IP'
            title = f'**{dec["label"]}（第 {dec["level"]} 级 · {sev_label}）**'

            if dec.get('scope') == 'account_target':
                status_cn = '已提升账号风险等级(未封禁攻击源IP，依赖 MFA/限流防护)'
            elif blocked:
                status_cn = '已临时封禁该 IP'
            else:
                status_cn = '已限流，未写入黑名单'

            content = (
                f'{title}\n\n'
                f'> **IP地址**: `{ip_address}`\n\n'
                f'> **信号维度**: {scope_cn}\n\n'
                f'> **累计失败**: {dec.get("current_count", "?")} 次 / 5分钟窗口\n\n'
                f'> **时间**: {now_str}\n\n'
                f'> **处置状态**: {status_cn}\n'
            )
            message = {
                'msgtype': 'markdown',
                'markdown': {'content': content},
            }
            result = adapter.send(message)
            if result and result.get('success'):
                logger.info(f'[IP黑名单] 登录安全告警已发送: {ip_address}')
            else:
                logger.warning(f'[IP黑名单] 登录安全告警发送失败: {result}')
        except Exception as exc:
            logger.warning(f'[IP黑名单] 发送登录安全告警失败: {exc}')

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
