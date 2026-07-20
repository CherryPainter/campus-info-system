#!/usr/bin/env python3
"""自定义推送模型"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class CustomPush(Base):
    """自定义推送"""

    __tablename__ = "custom_pushes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False, comment="推送标题")
    content = Column(Text, nullable=True, comment="推送内容（文本消息时使用）")
    msg_type = Column(
        String(20), default="text", comment="消息类型: text文本, image图片, template模板"
    )
    image_path = Column(String(500), nullable=True, comment="图片路径（图片消息时使用）")
    template_id = Column(String(50), nullable=True, comment="模板ID（模板消息时使用）")
    template_params = Column(Text, nullable=True, comment="模板参数JSON（模板消息时使用）")
    push_type = Column(
        String(20),
        default="immediate",
        comment="推送类型: immediate立即, scheduled定时, recurring周期",
    )
    scheduled_time = Column(DateTime, nullable=True, comment="定时推送时间")
    cron_expression = Column(String(50), nullable=True, comment="周期推送cron表达式")
    status = Column(
        String(20),
        default="pending",
        comment="状态: pending待发送, sent已发送, failed失败, cancelled已取消",
    )
    sent_at = Column(DateTime, nullable=True, comment="实际发送时间")
    error_message = Column(Text, nullable=True, comment="错误信息")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    created_by = Column(String(50), nullable=True, comment="创建人")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "msg_type": self.msg_type,
            "image_path": self.image_path,
            "template_id": self.template_id,
            "template_params": self.template_params,
            "push_type": self.push_type,
            "scheduled_time": self.scheduled_time.isoformat() if self.scheduled_time else None,
            "cron_expression": self.cron_expression,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }
