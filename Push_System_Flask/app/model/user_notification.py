#!/usr/bin/env python3
"""
个人站内通知模型

面向单个学生的站内消息（与全局公告 announcement、教学日历提醒 notification 均不同）：
- 由定时任务按用户生成：电量日报/周报/月报、低电量提醒、Cookie 失效提醒等
- 学生在小程序「我的消息」中查看，支持已读/未读
"""

import json
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.core.database import Base


class UserNotification(Base):
    """
    个人站内通知表

    user_id 指向 users.id（谁的通知）；category 区分通知类型；
    content 为纯文本（\n 换行，小程序 Text 直接渲染，不解析 Markdown）。

    payload（2026-09-22 新增）为该通知的**结构化数据**（JSON 字符串，可空）。
    存在的意义：电量周报/月报的正文虽然把「每日用电详情」逐行罗列了，但那是纯文本，
    小程序端没法点某一天跳进当天详情。把同一份数据以结构化形式存下来后，
    消息详情页就能渲染成可点击的每日行，与电量页的用电记录共用同一个详情页。
    没有 payload 的老消息仍按纯文本渲染，向后兼容。
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
    payload = Column(
        Text,
        nullable=True,
        comment="结构化数据（JSON 字符串，可空；如电量周报/月报的每日明细）",
    )
    is_read = Column(Boolean, default=False, nullable=False, comment="是否已读（进入列表即标记）")
    # 两层已读模型（2026-09-23 新增）：
    # - is_read  = 进入「我的消息」列表即全部标记已读，用于清掉「我的」页外部气泡角标；
    # - is_viewed = 点进某条详情页细看后才标记，用于卡片右上角的红点（已读≠看过）。
    is_viewed = Column(Boolean, default=False, nullable=False, comment="是否已看过（点进详情页细看）")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="创建时间")

    # 封面图与业务关联（公告类推送带封面，点击跳转公告详情）
    cover_url = Column(String(500), nullable=True, comment="封面图 URL（关联公告时展示）")
    ref_type = Column(
        String(30),
        nullable=True,
        index=True,
        comment="关联业务类型：announcement/...（NULL=系统通知）",
    )
    ref_id = Column(Integer, nullable=True, index=True, comment="关联业务 ID（如公告 ID）")

    # 复合索引：按用户+未读状态+时间倒序查列表/计数；
    # 唯一约束：同一用户同一业务关联（如某公告）只推送一次，防重复（ref 为 NULL 时不限）
    __table_args__ = (
        Index("idx_user_read_time", "user_id", "is_read", "created_at"),
        UniqueConstraint("user_id", "ref_type", "ref_id", name="uq_user_notif_ref"),
    )

    def __repr__(self) -> str:
        return f"<UserNotification(id={self.id}, user_id={self.user_id}, category={self.category})>"

    def to_dict(self) -> dict:
        """转换为字典格式（payload 解析为 dict，脏数据不抛异常）"""
        parsed_payload = None
        if self.payload:
            try:
                parsed_payload = json.loads(self.payload)
            except (ValueError, TypeError):
                parsed_payload = None
        return {
            "id": self.id,
            "user_id": self.user_id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "payload": parsed_payload,
            "is_read": bool(self.is_read),
            "is_viewed": bool(self.is_viewed),
            "cover_url": self.cover_url,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if self.created_at
            else None,
        }
