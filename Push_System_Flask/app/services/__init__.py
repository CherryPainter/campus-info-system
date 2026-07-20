#!/usr/bin/env python3
"""服务层初始化"""

from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)


def init_services(app):
    """初始化所有服务模块"""
    from app.services.adapter_service import adapter_service
    from app.services.delivery_service import delivery_service
    from app.services.rule_service import rule_service
    from app.services.schedule_service import schedule_service
    from app.services.task_service import task_service
    from app.services.template_service import template_service

    schedule_service.init_app(app)
    rule_service.init_app(app)
    task_service.init_app(app)
    delivery_service.init_app(app)
    template_service.init_app(app)
    adapter_service.init_app(app)

    logger.info("所有服务模块初始化完成")
