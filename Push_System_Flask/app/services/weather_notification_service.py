#!/usr/bin/env#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  ##!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(User#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    User#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_W#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_WEATHER_ALERT]
                    ),
                    UserNotification.created_at >= today_start,
#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_WEATHER_ALERT]
                    ),
                    UserNotification.created_at >= today_start,
                )
                .count()
            )
            return count
        finally:
#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_WEATHER_ALERT]
                    ),
                    UserNotification.created_at >= today_start,
                )
                .count()
            )
            return count
        finally:
            session.close()

    @staticmethod
    def _has_received_today(user_id: int#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_WEATHER_ALERT]
                    ),
                    UserNotification.created_at >= today_start,
                )
                .count()
            )
            return count
        finally:
            session.close()

    @staticmethod
    def _has_received_today(user_id: int, category: str) -> bool:
        """检查用户今天是否已经收到过指定类型#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_WEATHER_ALERT]
                    ),
                    UserNotification.created_at >= today_start,
                )
                .count()
            )
            return count
        finally:
            session.close()

    @staticmethod
    def _has_received_today(user_id: int, category: str) -> bool:
        """检查用户今天是否已经收到过指定类型的天气消息

        Args:
            user_id: 用户ID
            category: 消息#!/usr/bin/env python3
"""
天气站内通知服务

面向单个学生的天气消息推送（写入 user_notifications 表）：
- 每日天气晨报（每天 1 条，早上固定时间）
- 天气异常汇总（降雨/高温/降温/预警合并为 1 条，每天最多 1 条）

严格频率控制：
- 每个用户每天最多 2 条天气消息（晨报 + 异常汇总）
- 夜间免打扰时段不推送
- 假期模式静默
- 基于数据库去重，避免重启后重复推送
"""

from datetime import date, datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.services.user_notification_service import user_notification_service

logger = get_logger(__name__)

# 天气消息 category 常量
CATEGORY_WEATHER_DAILY = "weather_daily"          # 每日天气晨报
CATEGORY_WEATHER_ALERT = "weather_alert_summary"  # 天气异常汇总（降雨/高温/降温/预警）

# 每个用户每天最多的天气消息条数
MAX_WEATHER_MSGS_PER_DAY = 2


class WeatherNotificationService:
    """天气站内通知服务类（全静态方法）"""

    # ------------------------------------------------------------------
    # 频率控制：每日计数
    # ------------------------------------------------------------------

    @staticmethod
    def _get_today_weather_msg_count(user_id: int) -> int:
        """查询某用户今日已收到的天气消息条数

        基于 user_notifications 表统计，重启后不丢失，比内存缓存更可靠。

        Args:
            user_id: 用户ID

        Returns:
            int: 今日天气消息条数
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            today_start = datetime.combine(date.today(), datetime.min.time())
            count = (
                session.query(UserNotification)
                .filter(
                    UserNotification.user_id == user_id,
                    UserNotification.category.in_(
                        [CATEGORY_WEATHER_DAILY, CATEGORY_WEATHER_ALERT]
                    ),
                    UserNotification.created_at >= today_start,
                )
                .count()
            )
            return count
        finally:
            session.close()

    @staticmethod
    def _has_received_today(user_id: int, category: str) -> bool:
        """检查用户今天是否已经收到过指定类型的天气消息

        Args:
            user_id: 用户ID
            category: 消息类型

        Returns:
            bool: 是否已收到
        """
        from app.model.user_notification import UserNotification

        session = get