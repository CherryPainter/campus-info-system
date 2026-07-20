#!/usr/bin/env python3
"""
配置服务
支持从数据库读取配置，优先于 .env 文件
"""

import os
from typing import Any

from dotenv import load_dotenv

from app.core.logger import get_logger
from app.model.module_config import DEFAULT_CONFIGS, ModuleConfig

logger = get_logger(__name__)

# 加载 .env 文件
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class ConfigService:
    """配置服务"""

    def __init__(self):
        self._cache: dict[str, dict[str, Any]] = {}
        self._env_loaded = False

    def _load_env_config(self):
        """加载 .env 配置"""
        if self._env_loaded:
            return

        # 从环境变量构建配置字典
        for config in DEFAULT_CONFIGS:
            module = config["module"]
            key = config["key"]
            if module not in self._cache:
                self._cache[module] = {}

            # .env 的键格式: MODULE_KEY (全大写)
            env_key = f"{module.upper()}_{key.upper()}"
            env_value = os.getenv(env_key)

            if env_value is not None:
                # 类型转换
                value_type = config.get("value_type", "string")
                if value_type == "integer":
                    self._cache[module][key] = int(env_value)
                elif value_type == "float":
                    self._cache[module][key] = float(env_value)
                elif value_type == "boolean":
                    self._cache[module][key] = env_value.lower() in ("true", "1", "yes")
                else:
                    self._cache[module][key] = env_value
            else:
                # 使用默认值
                self._cache[module][key] = config.get("value", "")

        self._env_loaded = True

    def get(self, module: str, key: str, default: Any = None) -> Any:
        """
        获取配置值
        优先级：数据库 > .env > 默认值
        """
        from app.core.database import get_db

        session = get_db()
        try:
            # 优先从数据库读取
            config = (
                session.query(ModuleConfig)
                .filter(ModuleConfig.module == module, ModuleConfig.key == key)
                .first()
            )

            if config and config.value is not None:
                # 类型转换
                if config.value_type == "integer":
                    return int(config.value)
                elif config.value_type == "float":
                    return float(config.value)
                elif config.value_type == "boolean":
                    return config.value.lower() in ("true", "1", "yes")
                return config.value

            # 从 .env 读取
            self._load_env_config()
            if module in self._cache and key in self._cache[module]:
                return self._cache[module][key]

            return default
        finally:
            session.close()

    def get_module_config(self, module: str) -> dict[str, Any]:
        """获取模块的所有配置"""
        from app.core.database import get_db

        session = get_db()
        try:
            configs = session.query(ModuleConfig).filter(ModuleConfig.module == module).all()

            result = {}
            for config in configs:
                result[config.key] = config.value
            return result
        finally:
            session.close()


# 全局单例
_config_service: ConfigService | None = None


def get_config_service() -> ConfigService:
    """获取配置服务单例"""
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    return _config_service
