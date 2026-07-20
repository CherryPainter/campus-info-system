#!/usr/bin/env python3
"""
Repository 层 - 数据访问封装

职责：
- 封装数据库 CRUD 操作
- 提供类型安全的数据访问接口
- 处理数据库事务边界

禁止：
- 包含业务逻辑
- 直接处理 HTTP 请求
"""

from app.repository.electricity_repository import ElectricityRepository
from app.repository.weather_repository import WeatherRepository

__all__ = [
    "WeatherRepository",
    "ElectricityRepository",
]
