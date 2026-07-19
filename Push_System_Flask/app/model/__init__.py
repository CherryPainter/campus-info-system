#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Model 层 - 数据模型定义

所有数据库模型使用 SQLAlchemy declarative 方式定义
时间字段使用 DateTime，布尔字段使用 Boolean，字符串字段必须指定长度
"""

# 导入 Base，确保所有模型都被注册
from app.core.database import Base

from app.model.weather import WeatherRecord, WeatherAlert
from app.model.electricity import ElectricityRecord, ElectricityRemaining, ElectricityTotalCapacity
from app.model.course import Course
from app.model.course_week import CourseWeek
from app.model.custom_push import CustomPush
from app.model.holiday_period import HolidayPeriod
from app.model.task_process import TaskProcess
from app.model.scheduled_crawl_task import ScheduledCrawlTask
from app.model.token_blacklist import TokenBlacklist
from app.model.user_mfa import UserMFA
from app.model.user import User
from app.model.login_log import LoginLog
from app.model.module_config import ModuleConfig
from app.model.webhook import Webhook
from app.model.push_task import PushTask

__all__ = [
    'Base',
    'WeatherRecord',
    'WeatherAlert',
    'ElectricityRecord',
    'ElectricityRemaining',
    'ElectricityTotalCapacity',
    'Course',
    'CourseWeek',
    'CustomPush',
    'HolidayPeriod',
    'TaskProcess',
    'ScheduledCrawlTask',
    'TokenBlacklist',
    'UserMFA',
    'User',
    'LoginLog',
    'ModuleConfig',
    'Webhook',
    'PushTask',
]
