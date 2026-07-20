#!/usr/bin/env python3
"""假期静默区间模型

用于「寒暑假假期模式」：在 start_date ~ end_date 闭区间内，
若紧急静默开启，则全体面向用户的推送自动静默。
日期区间范式复用 course_weeks 的 start_date/end_date（DATE 类型）。
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String

from app.core.database import Base


class HolidayPeriod(Base):
    """假期静默区间"""

    __tablename__ = "holiday_periods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="假期名称，如 2026年暑假")
    holiday_type = Column(
        String(20),
        nullable=False,
        default="custom",
        comment="假期类型: winter=寒假, summer=暑假, custom=自定义",
    )
    start_date = Column(Date, nullable=False, comment="静默开始日期（含）")
    end_date = Column(Date, nullable=False, comment="静默结束日期（含）")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用该区间")
    note = Column(String(255), nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "holiday_type": self.holiday_type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "enabled": bool(self.enabled),
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
