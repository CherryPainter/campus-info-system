#!/usr/bin/env python3
"""Flask 扩展实例"""

import os
import time

from flask import g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# 应用启动时间（用于计算运行时长，替代 psutil 依赖）
_app_start_time = time.time()

# 限流器配置
# 默认速率限制规则：
# - 基础限制：每分钟最多 60 次请求（主要防线）
# - 突发限制：每秒最多 10 次请求
# - 小时限制：每小时最多 3600 次请求（与分钟峰值对齐，不设更紧的人工瓶颈）


def _extract_token_for_ratelimit():
    """
    限流标识用的 token 提取（与 app.utils.auth_middleware._extract_token 同口径）。

    优先级：Authorization: Bearer <token> → access_token cookie。
    """
    from flask import request

    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    return request.cookies.get("access_token")


def get_identity_key():
    """
    获取请求身份标识（优先使用用户ID，否则使用IP地址）

    这样可以实现：
    - 已认证用户：基于用户ID的速率限制
    - 未认证用户：基于IP地址的速率限制

    重要：Flask-Limiter 在 before_request 阶段计算限流 key，而 g.current_user
    由视图装饰器（@admin_required / @student_required 等）在**更晚**的阶段才设置。
    若这里只读 g.current_user，已登录请求永远拿不到用户身份，全部退化为按 IP 计数，
    导致同一出口 IP 下所有接口（含后台 2s/5s 轮询）共享同一份配额，
    管理端挂机一段时间后必然撞上「500 per 1 hour」而报 429。
    因此这里自行解析 JWT（失败则安全退化为按 IP），保证身份感知限流真正生效。
    """
    current_user = g.get("current_user")
    if current_user and current_user.get("user_id"):
        return f"user:{current_user['user_id']}"

    token = _extract_token_for_ratelimit()
    if token:
        try:
            import jwt as _jwt
            from flask import current_app

            jwt_manager = current_app.extensions.get("jwt_manager")
            secret = getattr(jwt_manager, "secret_key", None) or current_app.config.get(
                "SECRET_KEY"
            )
            if secret:
                # 只做解码验签，不查撤销黑名单——限流仅需 user_id 维度，
                # 避免每个请求多一次 DB 查询；撤销判定由 @jwt_required /
                # @admin_required 在认证阶段负责，安全性不受影响。
                payload = _jwt.decode(token, secret, algorithms=["HS256"])
                uid = payload.get("user_id")
                if uid:
                    return f"user:{uid}"
        except Exception:
            # token 过期/无效/被撤销：不在限流层判定，交由认证层返回 401；限流退化为按 IP
            pass
    # 匿名请求：限流身份**必须用 IP**，不能用匿名会话令牌。
    #
    # 原因（重要）：匿名令牌是客户端可自行清空/轮换的（存本地 Storage，无强身份）。
    # 若用 anon:<uuid> 作全局限流 key，攻击者只需不断丢弃令牌重新领取，
    # 即可让每个请求落进一个全新桶，绕过"60/min/IP"的兜底闸门（可放大约 60 倍）。
    # 因此限流继续按 IP（有界、不可伪造），匿名令牌专职做**访问日志溯源**，
    # 二者各司其职：IP 管"挡"，anon_id 管"查"。
    return get_remote_address()


def _resolve_ratelimit_storage_uri():
    """
    解析限流计数存储地址（启动期探活一次，决定后全程使用）。

    - 未配置 REDIS_URL：使用内存（单机 / 开发 / 测试）。
    - 配置了 REDIS_URL 且 Redis 可达：使用 Redis（多 worker 共享、重启不丢状态）。
    - 配置了 REDIS_URL 但 Redis 不可达：回退内存，避免运行期每个受限请求
      都去连 Redis 失败并触发 500 / 未捕获异常。

    注意：Flask-Limiter 在构造 Limiter 时确定的 storage_uri 会优先于
    init_app 阶段的 RATELIMIT_STORAGE_URI 配置（init_app 用
    ``self._storage_uri or storage_uri_from_config``），因此必须在构造前
    解析好，不能在 init_app 里用 config 覆盖。

    与 ip_blacklist_service 的启动期 Redis 探针思路一致：启动期定一次存储
    后端，不靠请求期反复重试探测。
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("[限流] 未配置 REDIS_URL，限流计数使用内存存储")
        return "memory://"
    try:
        import redis as _redis

        client = _redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        if client.ping():
            print(f"[限流] Redis 探活成功，限流计数使用 Redis 存储（{redis_url}）")
            return redis_url
        print("[限流] Redis 探活失败，限流计数回退内存存储")
        return "memory://"
    except Exception as e:
        print(f"[限流] Redis 探活异常（{e}），限流计数回退内存存储")
        return "memory://"


# 限流计数存储：启动期探活决定（见 _resolve_ratelimit_storage_uri）
_RATELIMIT_STORAGE_URI = _resolve_ratelimit_storage_uri()

limiter = Limiter(
    key_func=get_identity_key,
    default_limits=[
        "60 per minute",  # 每分钟最多 60 次请求
        "10 per second",  # 每秒最多 10 次请求（防止突发攻击）
        # 每小时最多 3600 次请求：与「60 per minute」的峰值对齐，不再叠加成一个
        # 更紧的人工瓶颈。
        #
        # 说明：此前设为 500/hour，会把"会话心跳 + 页面轮询（2s/5s）+ 各类操作"
        # 全部塞进同一个共享桶。管理端是多页面 + 多轮询应用，活跃使用下极易超过
        # 500/小时（每 5 秒 2 个探测请求就 1440/小时），导致挂机后反复 429
        # （历史日志多次出现 ratelimit 500 per 1 hour (user:1) exceeded）。
        # 真正的抗滥用防线是「60 per minute」+「10 per second」+ IP 黑名单；
        # 小时桶不应比分钟桶更紧，否则会给正常管理员造成误伤。
        "3600 per hour",
    ],
    # 限流计数存储：由启动期探活决定（Redis 可达用 Redis，否则内存）。
    # 非阻塞探针 + 2s 超时，避免 Redis 不可达时启动被拖死。
    storage_uri=_RATELIMIT_STORAGE_URI,
    # 二次容错：即便上面选了 Redis，运行期 Redis 突然挂掉时仍回退进程内内存限流，
    # 而不是让整个请求 500。与 ip_blacklist_service 的 Redis 降级策略保持一致。
    in_memory_fallback_enabled=True,
    # 启用全局限流统计（限流响应头）
    headers_enabled=True,
)

# 预定义的限流规则（可在路由中使用）
# 使用方式：@limiter.limit(RATE_LIMITS['strict'])
RATE_LIMITS = {
    "strict": "10 per minute",  # 严格限制：登录、认证等敏感接口
    "moderate": "30 per minute",  # 中等限制：一般 API 接口
    "lenient": "100 per minute",  # 宽松限制：公开查询接口
    "burst": "200 per minute",  # 突发限制：批量操作接口
}

# APScheduler (在 tasks/scheduler.py 中初始化)
scheduler = None
