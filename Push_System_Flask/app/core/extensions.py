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
# - 基础限制：每分钟最多 60 次请求
# - 突发限制：每秒最多 10 次请求
# - 小时限制：每小时最多 500 次请求


def get_identity_key():
    """
    获取请求身份标识（优先使用用户ID，否则使用IP地址）

    这样可以实现：
    - 已认证用户：基于用户ID的速率限制
    - 未认证用户：基于IP地址的速率限制
    """
    current_user = g.get("current_user")
    if current_user and current_user.get("user_id"):
        return f"user:{current_user['user_id']}"
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
        "500 per hour",  # 每小时最多 500 次请求
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
