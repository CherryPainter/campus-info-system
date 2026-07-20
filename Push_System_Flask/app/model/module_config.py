#!/usr/bin/env python3
"""
模块配置模型

用于存储各模块的可修改配置项，支持：
- 天气模块配置
- 电量模块配置
- 推送模块配置
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base


class ModuleConfig(Base):
    """
    模块配置表

    存储各模块的可修改配置项，以 key-value 形式存储。
    """

    __tablename__ = "module_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    module = Column(String(50), nullable=False, comment="模块名称: weather/electricity/push/system")
    key = Column(String(100), nullable=False, comment="配置键")
    value = Column(Text, nullable=True, comment="配置值")
    value_type = Column(
        String(20), default="string", comment="值类型: string/integer/float/boolean/json"
    )
    description = Column(String(500), nullable=True, comment="配置说明")
    is_editable = Column(Boolean, default=True, comment="是否可在界面修改")
    is_sensitive = Column(Boolean, default=False, comment="是否为敏感信息（敏感信息不显示值）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    # 联合唯一索引：同一模块下 key 唯一
    __table_args__ = ({"comment": "模块配置表"},)

    def to_dict(self, show_sensitive: bool = False):
        """
        转换为字典

        Args:
            show_sensitive: 是否显示敏感信息的值
        """
        value = self.value
        if self.is_sensitive and not show_sensitive:
            value = "******"

        # 类型转换
        typed_value = value
        if value is not None and not self.is_sensitive:
            try:
                if self.value_type == "integer":
                    typed_value = int(value)
                elif self.value_type == "float":
                    typed_value = float(value)
                elif self.value_type == "boolean":
                    typed_value = value.lower() in ("true", "1", "yes")
                elif self.value_type == "json":
                    import json

                    typed_value = json.loads(value)
            except (ValueError, TypeError):
                pass

        return {
            "id": self.id,
            "module": self.module,
            "key": self.key,
            "value": typed_value,
            "value_type": self.value_type,
            "description": self.description,
            "is_editable": self.is_editable,
            "is_sensitive": self.is_sensitive,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# 默认配置定义
DEFAULT_CONFIGS = [
    # ========== 系统配置 ==========
    {
        "module": "system",
        "key": "app_name",
        "value": "校园信息聚合与智能推送系统",
        "value_type": "string",
        "description": "系统名称",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "system",
        "key": "cors_origins",
        "value": "",
        "value_type": "string",
        "description": "允许的跨域来源（逗号分隔，留空仅允许本地）。注意：CORS 在启动时注册，修改后需重启服务生效",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "system",
        "key": "holiday_mode_enabled",
        "value": "false",
        "value_type": "boolean",
        "description": "假期模式总开关：开启后，落在「假期静默区间」内的日期全体面向用户的推送自动静默（系统/安全告警不受影响）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "system",
        "key": "semester_start_date",
        "value": "",
        "value_type": "string",
        "description": "当前学期开学日（ISO 日期 YYYY-MM-DD），用于推算教学周。留空则按学期类型自动推算（秋=9月1日，春=次年3月2日）。修改后实时生效",
        "is_editable": True,
        "is_sensitive": False,
    },
    # ========== 天气模块配置 ==========
    # key 命名规则：module_key → 对应 Config 属性 QWEATHER_{KEY.upper()} 或 WEATHER_{KEY.upper()}
    #   weather.city_name        → QWEATHER_CITY_NAME（和风天气城市名，fetcher/前端展示均消费）
    #   weather.location_id      → QWEATHER_LOCATION（和风天气位置，坐标"lon,lat"或 LocationID 均可，天气 API 直接消费，修改即时生效）
    #   weather.schedule_daily   → WEATHER_SCHEDULE_DAILY（对应 Config.WEATHER_SCHEDULE_DAILY）
    # 说明：latitude/longitude 两项已于审计中移除——它们写入 WEATHER_LATITUDE/WEATHER_LONGITUDE，
    #       但 Config 从不读取这两个变量，且位置已由 location_id(QWEATHER_LOCATION) 完整覆盖，属空壳。
    {
        "module": "weather",
        "key": "city_name",
        "value": "重庆",
        "value_type": "string",
        "description": "城市名称",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "weather",
        "key": "location_id",
        "value": "101040100",
        "value_type": "string",
        "description": "和风天气城市 LocationID",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "weather",
        "key": "schedule_daily",
        "value": "07:00",
        "value_type": "string",
        "description": "天气晨报推送时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "weather",
        "key": "alert_enabled",
        "value": "true",
        "value_type": "boolean",
        "description": "是否启用天气预警推送",
        "is_editable": True,
        "is_sensitive": False,
    },
    # 夜间免打扰（安静时段）：开关 + 起止时间，全部可在界面修改，免重启生效
    {
        "module": "weather",
        "key": "quiet_hours_enabled",
        "value": "true",
        "value_type": "boolean",
        "description": "夜间免打扰：开启后安静时段内不推送任何天气消息（模块休息）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "weather",
        "key": "quiet_hours_start",
        "value": "23:00",
        "value_type": "string",
        "description": "夜间免打扰开始时间（HH:MM，24小时制）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "weather",
        "key": "quiet_hours_end",
        "value": "07:00",
        "value_type": "string",
        "description": "夜间免打扰结束时间（HH:MM，24小时制，可跨午夜）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "weather",
        "key": "daily_push_limit",
        "value": "8",
        "value_type": "integer",
        "description": "每日天气推送上限（条/天，0=不限；用于防止白天频繁打扰）",
        "is_editable": True,
        "is_sensitive": False,
    },
    # ========== 电量模块配置 ==========
    # key 命名规则：module_key → 对应 Config 属性 ELECTRICITY_{KEY.upper()}，例如：
    #   electricity.schedule_daily      → ELECTRICITY_SCHEDULE_DAILY
    #   electricity.schedule_weekly     → ELECTRICITY_SCHEDULE_WEEKLY
    #   electricity.low_power_threshold → ELECTRICITY_LOW_POWER_THRESHOLD
    {
        "module": "electricity",
        "key": "low_power_threshold",
        "value": "10.0",
        "value_type": "float",
        "description": "低电量告警阈值（度）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "low_power_interval_hours",
        "value": "4.0",
        "value_type": "float",
        "description": "低电量告警最小间隔（小时）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "schedule_daily",
        "value": "00:30",
        "value_type": "string",
        "description": "每日报告推送时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "schedule_weekly",
        "value": "00:30",
        "value_type": "string",
        "description": "每周报告推送时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "schedule_weekly_day",
        "value": "mon",
        "value_type": "string",
        "description": "每周报告推送日（mon/tue/wed/thu/fri/sat/sun）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "schedule_monthly",
        "value": "00:30",
        "value_type": "string",
        "description": "每月报告推送时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "schedule_monthly_day",
        "value": "1",
        "value_type": "integer",
        "description": "每月报告推送日（1-28）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "cookie_check_time",
        "value": "20:00",
        "value_type": "string",
        "description": "Cookie 有效性检测时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "full_crawl_day",
        "value": "0",
        "value_type": "integer",
        "description": "全量爬取星期(0=周日,1=周一,2=周二,3=周三,4=周四,5=周五,6=周六)",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "electricity",
        "key": "full_crawl_time",
        "value": "03:00",
        "value_type": "string",
        "description": "全量爬取时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    # ========== 推送模块配置 ==========
    # 说明：各模块独立 Webhook（course_webhook/weather_webhook/...）已下架——
    # 真实可用的 Webhook 配置在「Webhooks」页面（webhooks 表），此处同名配置项为空壳，已移除。
    # default_push_channel / retry_interval 等同理无消费代码，已移除，仅保留 retry_count（已接入）。
    {
        "module": "push",
        "key": "retry_count",
        "value": "3",
        "value_type": "integer",
        "description": "推送失败重试次数",
        "is_editable": True,
        "is_sensitive": False,
    },
    # ========== 课程模块配置 ==========
    # key 命名规则：对应 .env 映射为 COURSE_{KEY.upper()}
    #   course.jwxt_username         → COURSE_JWXT_USERNAME（写入 .env 后，Config.JWXT_USERNAME 需同步）
    #   course.spider_enabled        → COURSE_SPIDER_ENABLED（Config 无直接属性，由 config_service 读取）
    #   course.spider_interval_hours → COURSE_SPIDER_INTERVAL_HOURS
    #   course.schedule_daily        → COURSE_SCHEDULE_DAILY（对应 Config.DAILY_PUSH_TIME）
    #   course.push_enabled          → COURSE_PUSH_ENABLED
    #   course.enable_background     → COURSE_ENABLE_BACKGROUND（对应 Config.COURSE_ENABLE_BACKGROUND）
    # 课程爬虫配置
    {
        "module": "course",
        "key": "jwxt_username",
        "value": "",
        "value_type": "string",
        "description": "教务系统用户名",
        "is_editable": True,
        "is_sensitive": True,
    },
    {
        "module": "course",
        "key": "jwxt_password",
        "value": "",
        "value_type": "string",
        "description": "教务系统密码",
        "is_editable": True,
        "is_sensitive": True,
    },
    {
        "module": "course",
        "key": "class_name",
        "value": "ZK2401",
        "value_type": "string",
        "description": "班级名称，用于课表推送标题",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "spider_enabled",
        "value": "true",
        "value_type": "boolean",
        "description": "是否启用自动爬取课表",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "spider_schedule_mode",
        "value": "cron",
        "value_type": "string",
        "description": "爬虫调度模式：cron=定时(每天07:00/13:00) | interval=每隔N小时",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "spider_cron_expression",
        "value": "0 7,13 * * *",
        "value_type": "string",
        "description": "课表爬虫 cron 表达式（定时模式生效，标准5段：分 时 日 月 周），修改后即时生效无需重启",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "spider_interval_hours",
        "value": "6",
        "value_type": "integer",
        "description": "课表爬取间隔（小时），仅 interval 模式下生效",
        "is_editable": True,
        "is_sensitive": False,
    },
    # 课程推送配置
    {
        "module": "course",
        "key": "default_push_enabled",
        "value": "true",
        "value_type": "boolean",
        "description": "新增课程默认开启推送提醒",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "before_class_minutes",
        "value": "15",
        "value_type": "integer",
        "description": "课前提醒提前分钟数",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "before_end_class_minutes",
        "value": "10",
        "value_type": "integer",
        "description": "下课提醒提前分钟数",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "schedule_daily",
        "value": "07:00",
        "value_type": "string",
        "description": "每日课表推送时间（HH:MM）",
        "is_editable": True,
        "is_sensitive": False,
    },
    {
        "module": "course",
        "key": "push_enabled",
        "value": "true",
        "value_type": "boolean",
        "description": "是否启用课程推送",
        "is_editable": True,
        "is_sensitive": False,
    },
    # 课程图片配置
    {
        "module": "course",
        "key": "enable_background",
        "value": "true",
        "value_type": "boolean",
        "description": "生成课表图片时是否启用背景图",
        "is_editable": True,
        "is_sensitive": False,
    },
    # ========== 敏感配置（不可编辑，仅展示状态） ==========
    {
        "module": "weather",
        "key": "api_key_configured",
        "value": "false",
        "value_type": "boolean",
        "description": "和风天气 API Key 是否已配置",
        "is_editable": False,
        "is_sensitive": True,
    },
    {
        "module": "electricity",
        "key": "cookie_configured",
        "value": "false",
        "value_type": "boolean",
        "description": "电量系统 Cookie 是否已配置",
        "is_editable": False,
        "is_sensitive": True,
    },
    {
        "module": "push",
        "key": "wecom_webhook_configured",
        "value": "false",
        "value_type": "boolean",
        "description": "企业微信 Webhook 是否已配置",
        "is_editable": False,
        "is_sensitive": True,
    },
]


def init_default_configs(session):
    """
    初始化默认配置

    Args:
        session: 数据库会话
    """
    # 清理 system 模块中的旧课程相关配置
    old_course_keys = [
        "class_name",
        "daily_push_time",
        "before_class_minutes",
        "before_end_class_minutes",
    ]
    for old_key in old_course_keys:
        old_config = (
            session.query(ModuleConfig)
            .filter(ModuleConfig.module == "system", ModuleConfig.key == old_key)
            .first()
        )
        if old_config:
            session.delete(old_config)

    for config_data in DEFAULT_CONFIGS:
        # 检查是否已存在
        existing = (
            session.query(ModuleConfig)
            .filter(
                ModuleConfig.module == config_data["module"], ModuleConfig.key == config_data["key"]
            )
            .first()
        )

        if not existing:
            config = ModuleConfig(**config_data)
            session.add(config)

    session.commit()
