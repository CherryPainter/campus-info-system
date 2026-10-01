#!/usr/bin/env python3
"""用户意见与反馈模型

小程序端学生提交的「意见与反馈」数据模型（反向通道：学生 → 管理员），
与消息中心（管理员 → 学生推送）是完全不同的业务方向，独立成表、独立管理。

包含一张表：
- feedbacks  反馈主体（类型/内容/截图/处理状态/管理员回复）

图片存储：反馈截图存 output/feedback-images/，访问走公共路由
GET /api/feedback-images/<name>（无需鉴权，小程序与管理端均可加载）。
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
)

from app.core.database import Base

# 反馈类型（与小程序端下拉选项一一对应）
FEEDBACK_TYPES = {
    "bug": "功能异常",
    "suggest": "功能建议",
    "consult": "咨询求助",
    "other": "其他",
}

# 反馈处理状态
STATUS_PENDING = "pending"      # 待处理
STATUS_PROCESSING = "processing"  # 处理中
STATUS_RESOLVED = "resolved"    # 已解决


class Feedback(Base):
    """用户意见与反馈主表"""

    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, comment="提交用户 id（学生）")
    type = Column(
        String(20),
        nullable=False,
        default="other",
        comment="反馈类型：bug/suggest/consult/other",
    )
    content = Column(Text, nullable=False, comment="反馈内容（纯文本）")
    contact = Column(String(100), nullable=True, comment="联系方式（选填，手机/微信/邮箱）")
    images = Column(Text, nullable=True, comment="截图 URL 列表（JSON 字符串）")
    status = Column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
        comment="处理状态：pending/processing/resolved",
    )
    reply = Column(Text, nullable=True, comment="管理员回复内容")
    replied_by = Column(Integer, nullable=True, comment="回复管理员 user_id")
    replied_at = Column(DateTime, nullable=True, comment="回复时间")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def to_dict(self, with_reply: bool = True) -> dict:
        """序列化为 dict（列表/详情共用）

        Args:
            with_reply: 是否包含管理员回复（列表项可省略以减重）

        截图 URL（B1）：库里的值可能是历史形态（裸文件名 / 相对路径 / 已带过期签名的
        完整 URL），此处一律归一化为**当前有效**的签名 URL 再输出 —— 签名只在输出时生成，
        所以 TTL 到期后重新拉一次列表就拿到新签名，不会把图片签成死链。
        归一化的唯一入口是 `signed_feedback_image_url`，勿在此另写拼接逻辑。
        """
        import json

        from app.utils.signed_url import signed_feedback_image_url

        images = []
        if self.images:
            try:
                images = json.loads(self.images)
            except (json.JSONDecodeError, TypeError):
                images = []
        # 非列表（历史脏数据）按空处理，与改动前的行为一致
        images = [signed_feedback_image_url(u) for u in images] if isinstance(images, list) else []

        data = {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "type_label": FEEDBACK_TYPES.get(self.type, self.type),
            "content": self.content,
            "contact": self.contact or "",
            "images": images,
            "status": self.status,
            "status_label": {
                STATUS_PENDING: "待处理",
                STATUS_PROCESSING: "处理中",
                STATUS_RESOLVED: "已解决",
            }.get(self.status, self.status),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else "",
        }
        if with_reply:
            data["reply"] = self.reply or ""
            data["replied_at"] = (
                self.replied_at.strftime("%Y-%m-%d %H:%M:%S") if self.replied_at else ""
            )
        return data
