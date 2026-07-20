#!/usr/bin/env python3
"""
统一的日志配置模块
为所有脚本提供一致的日志记录功能
"""

import logging
import os
import sys
from datetime import datetime

from config import CONFIG


class Logger:
    """
    日志记录器类
    提供统一的日志配置和记录功能
    使用单例模式确保全局只有一个日志记录器实例
    """

    _instance = None

    def __new__(cls):
        """
        单例模式，确保全局只有一个日志记录器实例
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup_logger()
        return cls._instance

    def _setup_logger(self):
        """
        设置日志记录器
        配置日志格式、输出路径和处理器
        """
        # 获取日志配置
        log_config = CONFIG.get(
            "log",
            {
                "level": "INFO",
                "format": "%(asctime)s - %(levelname)s - %(module)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        )

        # 确保日志目录存在 - 使用绝对路径确保统一
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_root = os.path.join(script_dir, CONFIG["spider"]["output_dir"])
        log_dir = os.path.join(output_root, "logs")
        os.makedirs(log_dir, exist_ok=True)

        # 创建日志记录器
        self.logger = logging.getLogger("CourseSpider")
        self.logger.setLevel(getattr(logging, log_config["level"]))

        # 清空现有的处理器，避免重复添加
        self.logger.handlers.clear()

        # 日志格式
        formatter = logging.Formatter(log_config["format"], datefmt=log_config["datefmt"])

        # 生成当前时间字符串，格式：YYYY-MM-DD_HH-MM-SS
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # 主日志文件
        main_log_file = os.path.join(log_dir, f"course_spider_{current_time}.log")

        # 备份旧日志文件到历史目录
        self._backup_old_logs(log_dir)

        # 文件处理器，每次运行生成一个新文件
        file_handler = logging.FileHandler(filename=main_log_file, encoding="utf-8", mode="w")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # 控制台处理器 - 修复中文乱码问题
        stream_handler = logging.StreamHandler(
            stream=open(sys.stdout.fileno(), "w", encoding="utf-8")
        )
        stream_handler.setFormatter(formatter)
        self.logger.addHandler(stream_handler)

        self.logger.info("日志系统初始化完成")
        self.logger.info(f"主日志文件: {main_log_file}")

    def _backup_old_logs(self, log_dir):
        """
        备份旧日志文件到历史目录

        Args:
            log_dir (str): 日志目录
        """
        # 创建历史目录结构，按时间戳归档
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_history_dir = os.path.join(log_dir, "history", timestamp)
        os.makedirs(log_history_dir, exist_ok=True)

        # 遍历日志目录中的所有日志文件
        for file_name in os.listdir(log_dir):
            if file_name.endswith(".log") and "course_spider_" in file_name:
                file_path = os.path.join(log_dir, file_name)
                # 移动文件到历史目录
                try:
                    backup_file_path = os.path.join(log_history_dir, file_name)
                    os.rename(file_path, backup_file_path)
                    self.logger.info(f"历史日志文件已备份到: {backup_file_path}")
                except Exception as e:
                    self.logger.error(f"备份日志文件失败: {e}")

    def get_logger(self, module_name=None):
        """
        获取日志记录器

        Args:
            module_name (str): 模块名称，用于区分不同模块的日志

        Returns:
            logging.Logger: 日志记录器
        """
        if module_name:
            return logging.getLogger(f"CourseSpider.{module_name}")
        return self.logger


# 创建全局日志记录器实例
logger = Logger().get_logger()


# 便捷函数
def get_logger(module_name=None):
    """
    获取指定模块的日志记录器

    Args:
        module_name (str): 模块名称

    Returns:
        logging.Logger: 日志记录器
    """
    return Logger().get_logger(module_name)
