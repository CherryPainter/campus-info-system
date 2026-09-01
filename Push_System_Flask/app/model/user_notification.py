#!/usr/bin/env python3
"""
个人站内通知模型

面向单个学生的站内消息（与全局公告 announcement、教学日历提醒 notification 均不同）：
- 由定时任务按用户生成：电量日报/周报/月报、低电量提醒、Cookie 失效提醒等
- 学生在小程序「我的消息」中查看，支持已读/未读
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.core.database import Base


class UserNotification(Base):
    """
    个人站内通知表

    user_id 指向 users.id（谁的通知）；category 区分通知类型；
    content 为纯文本（\n 换行，小程序 Text 直接渲染，不解析 Markdown）。
    """

    __tablename__ = "user_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="接收用户ID",
    )
    category = Column(String(50), nullable=False, index=True, comment="通知类型")
    title = Column(String(200), nullable=False, comment="通知标题")
    content = Column(Text, nullable=True, comment="通知内容（纯文本，换行分隔）")
    is_read = Column(Boolean, default=False, nullable=False, comment="是否已读")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="创建时间")

    # 复合索引：按用户+未读状态+时间倒序查列表/计数
    __table_args__ = (
        Index("idx_user_read_time", "user_id", "is_read", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<UserNotification(id={self.id}, user_id={self.user_id}, category={self.category})>"

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "is_read": bool(self.is_read),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if self.created_at
            else None,
        }
