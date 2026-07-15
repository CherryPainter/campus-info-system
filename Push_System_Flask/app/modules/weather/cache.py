#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气数据内存 TTL 缓存
线程安全，不依赖 Redis
"""

import threading
import time
from typing import Any, Optional

from app.core.logger import get_logger

logger = get_logger(__name__)

# TTL 默认值常量（秒）
NOW_TTL = 1800       # 实时天气缓存 30 分钟
HOURLY_TTL = 3600    # 24h 预报缓存 60 分钟
ALERT_TTL = 600      # 天气预警缓存 10 分钟


class WeatherCache:
    """内存 TTL 缓存层

    使用 dict 存储，threading.Lock 保证线程安全。
    每个 key 对应 {'data': ..., 'expire_at': ...} 结构。

    采用单例模式，确保全局共享同一个缓存实例。
    """

    _instance: Optional['WeatherCache'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'WeatherCache':
        """单例模式：确保全局只有一个缓存实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: dict = {}
                    cls._instance._data_lock = threading.Lock()
        return cls._instance

    def __init__(self) -> None:
        # 单例模式下，__init__ 可能被多次调用，但实例数据只初始化一次
        pass

    def _make_key(self, data_type: str) -> str:
        """生成缓存 key

        Args:
            data_type: 数据类型标识，如 'now' / 'hourly' / 'alert'

        Returns:
            缓存 key 字符串
        """
        return f'weather:{data_type}'

    def get(self, data_type: str) -> Optional[Any]:
        """获取缓存数据

        Args:
            data_type: 数据类型标识

        Returns:
            缓存数据，过期或不存在时返回 None
        """
        key = self._make_key(data_type)
        with self._data_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.time() > entry.get('expire_at', 0):
                # 已过期，删除并返回 None
                del self._cache[key]
                return None
            return entry.get('data')

    def set(self, data_type: str, data: Any, ttl_seconds: int = NOW_TTL) -> None:
        """存储数据到缓存

        Args:
            data_type: 数据类型标识
            data: 要缓存的数据
            ttl_seconds: 过期时间（秒）
        """
        key = self._make_key(data_type)
        expire_at = time.time() + ttl_seconds
        with self._data_lock:
            self._cache[key] = {
                'data': data,
                'expire_at': expire_at,
            }
        logger.debug(f'[天气] 缓存已更新: {key}, TTL={ttl_seconds}s')

    def invalidate(self, data_type: str) -> None:
        """删除指定类型的缓存

        Args:
            data_type: 数据类型标识
        """
        key = self._make_key(data_type)
        with self._data_lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """清空全部缓存"""
        with self._data_lock:
            self._cache.clear()
        logger.debug('[天气] 缓存已全部清空')
