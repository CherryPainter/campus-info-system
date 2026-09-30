#!/usr/bin/env python3
"""公告频道（受管）模型

频道用于小程序端公告列表顶部的「栏目标签」（学校要闻 / 学院动态 / 媒体聚焦…）。
早期频道是硬编码常量（CHANNEL_OPTIONS），编辑器无法选、管理端无法增删，
导致标签永远为空。现改为受管表：

- 管理端可增删改、排序、启停；
- 编辑器从受管频道中选（不再自由输入，避免脏值）；
- 小程序 list_channels() 只展示「启用中」的频道，并按其下可见公告数稳定排序。

announcement.channel 仍存频道名字符串，与 announcement_channels.name 一一对应。
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class AnnouncementChannel(Base):
    """公告频道（受管）"""

    __tablename__ = "announcement_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(
        String(50),
        nullable=False,
        unique=True,
        comment="频道名称（与 announcement.channel 值对应，唯一）",
    )
    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="排序（升序，越小越靠前）",
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否启用：停用后小程序端不再展示该频道标签（公告仍可在『全部』中看到）",
    )
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "sort_order": self.sort_order,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
