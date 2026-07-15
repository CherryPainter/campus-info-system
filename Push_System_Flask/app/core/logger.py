#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
全局日志管理模块
提供统一的日志记录功能，支持控制台和文件输出
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


class GlobalLogger:
    """全局日志管理类"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式确保只有一个日志实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化日志系统"""
        if GlobalLogger._initialized:
            return
        
        self.loggers = {}
        self.log_dir = None
        self.config = None
        
        GlobalLogger._initialized = True
    
    def setup(self, config_or_app):
        """
        设置日志系统
        
        Args:
            config_or_app: 可以是日志配置字典，也可以是Flask应用对象
        """
        # 如果是Flask应用对象，从中提取配置
        if hasattr(config_or_app, 'config'):
            app = config_or_app
            config = app.config.get('LOGGER_CONFIG', {})
            # 如果没有配置，使用默认配置
            if not config:
                config = {
                    'log_dir': 'logs',
                    'log_file': 'app.log',
                    'max_bytes': 10 * 1024 * 1024,
                    'backup_count': 5,
                    'console_level': 'INFO',
                    'file_level': 'DEBUG',
                    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                }
            self.config = config
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        else:
            self.config = config_or_app
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        self.log_dir = os.path.join(base_dir, self.config.get('log_dir', 'logs'))
        
        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 设置根日志器
        self._setup_root_logger()
    
    def _setup_root_logger(self):
        """设置根日志器"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # 清除已有的处理器
        root_logger.handlers.clear()
        
        # 日志格式
        log_format = self.config.get('format', 
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        formatter = logging.Formatter(log_format)
        
        # 控制台处理器
        console_level = getattr(logging, self.config.get('console_level', 'INFO'))
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # 文件处理器（支持轮转）
        log_file = os.path.join(self.log_dir, self.config.get('log_file', 'app.log'))
        file_level = getattr(logging, self.config.get('file_level', 'DEBUG'))
        max_bytes = self.config.get('max_bytes', 10 * 1024 * 1024)  # 10MB
        backup_count = self.config.get('backup_count', 5)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        
        # 减少框架日志噪音
        logging.getLogger('apscheduler').setLevel(logging.WARNING)  # APScheduler 只显示警告和错误
        logging.getLogger('werkzeug').setLevel(logging.WARNING)     # Werkzeug 也减少噪音
    
    def get_logger(self, name):
        """
        获取指定名称的日志器
        
        Args:
            name: 日志器名称，通常使用__name__
            
        Returns:
            logging.Logger: 日志器实例
        """
        if name not in self.loggers:
            self.loggers[name] = logging.getLogger(name)
        return self.loggers[name]
    
    def debug(self, message, name='app'):
        """记录DEBUG级别日志"""
        self.get_logger(name).debug(message)
    
    def info(self, message, name='app'):
        """记录INFO级别日志"""
        self.get_logger(name).info(message)
    
    def warning(self, message, name='app'):
        """记录WARNING级别日志"""
        self.get_logger(name).warning(message)
    
    def error(self, message, name='app'):
        """记录ERROR级别日志"""
        self.get_logger(name).error(message)
    
    def critical(self, message, name='app'):
        """记录CRITICAL级别日志"""
        self.get_logger(name).critical(message)
    
    def exception(self, message, name='app'):
        """记录异常信息（包含堆栈跟踪）"""
        self.get_logger(name).exception(message)


# 全局日志实例
global_logger = GlobalLogger()


def get_logger(name):
    """
    便捷函数：获取日志器
    
    Args:
        name: 日志器名称
        
    Returns:
        logging.Logger: 日志器实例
    """
    return global_logger.get_logger(name)


def setup_logger(config_or_app):
    """
    便捷函数：设置日志系统
    
    Args:
        config_or_app: 可以是日志配置字典，也可以是Flask应用对象
    """
    global_logger.setup(config_or_app)
