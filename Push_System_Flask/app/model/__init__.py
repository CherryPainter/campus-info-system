#!/usr/bin/env python3
"""
Model 层 - 数据模型定义

所有数据库模型使用 SQLAlchemy declarative 方式定义
时间字段使用 DateTime，布尔字段使用 Boolean，字符串字段必须指定长度
"""

# 导入 Base，确保所有模型都被注册
from app.core.database import Base
from app.model.announcement import (
    Announcement,
    AnnouncementAttachment,
    AnnouncementFavorite,
    AnnouncementRead,
)
from app.model.course import Course
from app.model.custom_push import CustomPush
from app.model.electricity import ElectricityRecord, ElectricityRemaining, ElectricityTotalCapacity
from app.model.feedback import Feedback
from app.model.holiday_period import HolidayPeriod
from app.model.ip_blacklist import IPBlacklist, IPSecurityEvent
from app.model.login_log import LoginLog
from app.model.module_config import ModuleConfig
from app.model.notification import Notification
from app.model.org_unit import OrgUnit
from app.model.push_task import PushTask
from app.model.scheduled_crawl_task import ScheduledCrawlTask
from app.model.server_session import ServerSession
from app.model.student_profile import StudentProfile
from app.model.student_roster import StudentRoster
from app.model.task_process import TaskProcess
from app.model.token_blacklist import TokenBlacklist
from app.model.user import User
from app.model.user_mfa import UserMFA
from app.model.user_notification import UserNotification
from app.model.weather import WeatherAlert, WeatherRecord
from app.model.webhook import Webhook
from app.model.wechat_account import WechatAccount

__all__ = [
    "Base",
    "WeatherRecord",
    "WeatherAlert",
    "ElectricityRecord",
    "ElectricityRemaining",
    "ElectricityTotalCapacity",
    "Course",
    "CustomPush",
    "HolidayPeriod",
    "TaskProcess",
    "ScheduledCrawlTask",
    "TokenBlacklist",
    "UserMFA",
    "User",
    "StudentProfile",
    "StudentRoster",
    "WechatAccount",
    "UserNotification",
    "LoginLog",
    "ModuleConfig",
    "Notification",
    "OrgUnit",
    "Webhook",
    "PushTask",
    "Announcement",
    "AnnouncementAttachment",
    "AnnouncementRead",
    "AnnouncementFavorite",
    "IPBlacklist",
    "IPSecurityEvent",
    "ServerSession",
]
