#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask 扩展实例"""
import os
import time
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import g

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
    current_user = g.get('current_user')
    if current_user and current_user.get('user_id'):
        return f"user:{current_user['user_id']}"
    return get_remote_address()

limiter = Limiter(
    key_func=get_identity_key,
    default_limits=[
        "60 per minute",      # 每分钟最多 60 次请求
        "10 per second",      # 每秒最多 10 次请求（防止突发攻击）
        "500 per hour",       # 每小时最多 500 次请求
    ],
    # 限流计数存储：生产使用 Redis（多 worker 生效、重启不丢状态）；
    # REDIS_URL 未配置时回退内存（兼容单机开发 / 测试）
    storage_uri=os.getenv("REDIS_URL") or "memory://",
    # 容错降级：配置了 REDIS_URL 但 Redis 连不上时（宕机 / 未启动 / 网络抖动），
    # 自动回退到进程内内存限流，而不是让整个请求 500。
    # 与 ip_blacklist_service 的 Redis 降级策略保持一致，避免限流存储故障拖垮登录等接口。
    in_memory_fallback_enabled=True,
    # 启用全局限流统计（限流响应头）
    headers_enabled=True,
)

# 预定义的限流规则（可在路由中使用）
# 使用方式：@limiter.limit(RATE_LIMITS['strict'])
RATE_LIMITS = {
    'strict': "10 per minute",       # 严格限制：登录、认证等敏感接口
    'moderate': "30 per minute",     # 中等限制：一般 API 接口
    'lenient': "100 per minute",     # 宽松限制：公开查询接口
    'burst': "200 per minute",       # 突发限制：批量操作接口
}

# APScheduler (在 tasks/scheduler.py 中初始化)
scheduler = None
