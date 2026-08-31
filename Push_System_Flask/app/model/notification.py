#!/usr/bin/env python3
# ruff: noqa: F401
"""近期提醒事件模型

用于存储学校日历类事件（考试报名截止、节假日放假、讲座等），供微信小程序首页/时间轴"近期提醒"卡片展示。

数据流：
- 后端管理员/脚本写入（当前未提供管理端 API，由 SQL 直接维护）
- 小程序通过 /api/miniapp/notifications/upcoming 查询未来 N 天内的活跃事件
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class Notification(Base):
    """近期提醒事件表"""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    event_date = Column(DateTime, nullable=False)
    category = Column(
        String(20),
        nullable=False,
        default="other",
    )
    remind_days = Column(Integer, nullable=False, default=30)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def to_dict(self, now=None):
        now = now or datetime.now()
        days_left = (self.event_date - now).days
        return {
            "id": self.id,
            "title": self.title,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "event_date_label": self.event_date.strftime("%m-%d") if self.event_date else None,
            "category": self.category,
            "remind_days": self.remind_days,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "description": self.description,
            "days_left": days_left,
            "is_expired": days_left < 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @staticmethod
    def get_upcoming(session, limit=5, now=None):
        now = now or datetime.now()
        candidates = (
            session.query(Notification)
            .filter(Notification.is_active.is_(True))
            .filter(Notification.event_date >= now)
            .all()
        )
        # 按各自 remind_days 窗口过滤（不同事件窗口不同）
        candidates = [e for e in candidates if (e.event_date - now).days <= e.remind_days]
        candidates.sort(key=lambda e: (e.event_date, -e.sort_order))
        return candidates[:limit]

    @staticmethod
    def get_all_active(session, now=None):
        now = now or datetime.now()
        return (
            session.query(Notification)
            .filter(Notification.is_active.is_(True))
            .filter(Notification.event_date >= now)
            .order_by(Notification.event_date.asc(), Notification.sort_order.desc())
            .all()
        )