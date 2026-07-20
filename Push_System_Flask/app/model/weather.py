#!/usr/bin/env python3
"""
天气模块数据模型

存储天气相关数据：实时天气记录、天气预警
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.core.database import Base


class WeatherRecord(Base):
    """
    天气记录表

    存储实时天气和逐小时预报数据
    """

    __tablename__ = "weather_records"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    record_type = Column(
        String(20), nullable=False, index=True, comment="记录类型: now实时/hourly逐时"
    )
    city_name = Column(String(50), nullable=False, default="重庆", comment="城市名称")
    temp = Column(Float, nullable=True, comment="温度(°C)")
    feels_like = Column(Float, nullable=True, comment="体感温度(°C)")
    text = Column(String(50), nullable=True, comment="天气状况")
    humidity = Column(Integer, nullable=True, comment="相对湿度(%)")
    wind_dir = Column(String(20), nullable=True, comment="风向")
    wind_scale = Column(String(10), nullable=True, comment="风力等级")
    precip = Column(Float, nullable=True, comment="降水量(mm)")
    pop = Column(Integer, nullable=True, comment="降水概率(%)")
    pressure = Column(Integer, nullable=True, comment="气压(hPa)")
    vis = Column(Float, nullable=True, comment="能见度(km)")
    cloud = Column(Integer, nullable=True, comment="云量(%)")
    fx_time = Column(DateTime, nullable=True, comment="预报时间(逐时预报用)")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def __repr__(self) -> str:
        return f"<WeatherRecord(id={self.id}, type={self.record_type}, city={self.city_name}, temp={self.temp})>"

    def to_dict(self) -> dict:
        """转换为字典格式（兼容前端字段名）"""
        return {
            "id": self.id,
            "record_type": self.record_type,
            "city_name": self.city_name,
            "temp": self.temp,
            "feels_like": self.feels_like,
            "text": self.text,
            "humidity": self.humidity,
            "wind_dir": self.wind_dir,
            "wind_scale": self.wind_scale,
            "precip": self.precip,
            "pop": self.pop,
            "pressure": self.pressure,
            "vis": self.vis,
            "cloud": self.cloud,
            "time": self.fx_time.isoformat() if self.fx_time else None,  # 前端使用 time 字段
            "fx_time": self.fx_time.isoformat() if self.fx_time else None,  # 保留兼容
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "update_time": self.updated_at.isoformat() if self.updated_at else None,  # 数据更新时间
        }


class WeatherAlert(Base):
    """
    天气预警表

    存储天气预警信息
    """

    __tablename__ = "weather_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    alert_id = Column(String(100), nullable=False, unique=True, index=True, comment="预警唯一标识")
    city_name = Column(String(50), nullable=False, default="重庆", comment="城市名称")
    headline = Column(String(200), nullable=False, comment="预警标题")
    event_type = Column(String(50), nullable=False, comment="预警类型")
    severity = Column(String(20), nullable=False, comment="严重程度")
    color_code = Column(String(20), nullable=False, comment="颜色代码")
    description = Column(Text, nullable=True, comment="预警描述")
    start_time = Column(DateTime, nullable=True, comment="开始时间")
    end_time = Column(DateTime, nullable=True, comment="结束时间")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否生效")
    is_pushed = Column(
        Boolean, nullable=False, default=False, comment="是否已推送过（预警去重依据）"
    )
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def __repr__(self) -> str:
        return f"<WeatherAlert(id={self.id}, type={self.event_type}, severity={self.severity})>"

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "city_name": self.city_name,
            "headline": self.headline,
            "event_type": self.event_type,
            "severity": self.severity,
            "color_code": self.color_code,
            "description": self.description,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "is_active": self.is_active,
            "is_pushed": self.is_pushed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
