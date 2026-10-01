#!/usr/bin/env python3
"""校园通知（公告）模型

面向微信小程序终端用户的校园通知中心数据模型，与 notifications 表（近期提醒/
学校日历事件）是两套独立业务，互不混用：

- notifications  : 考试报名截止、节假日等「有日期的提醒事项」，卡片式倒计时展示。
- announcements  : 有标题、正文、来源部门、附件的「公告通知」，列表 + 详情阅读。

送达方式：纯拉取（小程序进页面 / 下拉刷新时请求），不使用微信订阅消息推送。

包含四张表：
- announcements            公告主体
- announcement_attachments 公告附件（文件名/大小/下载地址）
- announcement_reads       用户已读记录（未读数、红点依据）
- announcement_favorites   用户收藏记录
"""

import re
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base

# 公告分类（与小程序端色标一一对应）
CATEGORY_LABELS = {
    "notice": "通知",
    "activity": "活动",
    "urgent": "紧急",
    "system": "系统",
}

# 公告频道（与小程序端顶部频道标签一一对应；管理端可配，默认如下）
CHANNEL_OPTIONS = ["学校要闻", "学院动态", "媒体聚焦"]

# 公告状态
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_WITHDRAWN = "withdrawn"

# 正文 <img> 的 src 提取（列表卡片封面回退链用）
_CONTENT_IMG_RE = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def extract_first_content_image(html):
    """取正文中第一张图片的 src，没有则返回 None

    用于列表卡片封面的回退链：管理员配置的 cover_url → 正文首图 → 无图。

    正文图片由富文本编辑器上传，src 形如 /api/announcement-images/<name>
    （相对路径，前端自行拼 API 域名）；也兼容管理员手工粘贴的完整 URL。
    取不到可用 src 时返回 None，由前端决定退化样式（不显示图，不占位）。
    """
    if not html:
        return None
    match = _CONTENT_IMG_RE.search(str(html))
    if not match:
        return None
    src = (match.group(1) or "").strip()
    if not src or src.startswith("data:"):
        return None
    return src


class Announcement(Base):
    """校园通知（公告）主表"""

    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, comment="公告标题")
    category = Column(
        String(20),
        nullable=False,
        default="notice",
        comment="分类：notice/activity/urgent/system",
    )
    content = Column(Text, nullable=True, comment="正文（纯文本/富文本）")
    summary = Column(String(300), nullable=True, comment="摘要（列表页展示，为空则由正文截取）")
    department = Column(String(100), nullable=True, comment="来源部门")
    channel = Column(
        String(50),
        nullable=True,
        comment="频道/栏目（学校要闻/学院动态/媒体聚焦…）；用于列表顶部频道标签筛选",
    )
    audience_type = Column(
        String(20),
        nullable=False,
        default="all",
        comment="受众范围：all/grade/class/specified（当前实现仅 all 生效）",
    )
    audience_ids = Column(String(500), nullable=True, comment="指定受众（JSON 字符串），预留")
    is_top = Column(Boolean, nullable=False, default=False, comment="是否置顶")
    status = Column(
        String(20),
        nullable=False,
        default=STATUS_DRAFT,
        comment="状态：draft/published/withdrawn",
    )
    published_at = Column(DateTime, nullable=True, comment="发布时间")
    expired_at = Column(DateTime, nullable=True, comment="过期时间（为空表示长期有效）")
    cover_url = Column(
        String(500),
        nullable=True,
        comment="封面图 URL（消息推送卡片 / 详情页展示，无图则不显示）",
    )
    view_count = Column(Integer, nullable=False, default=0, comment="阅读次数（累计）")
    created_by = Column(Integer, nullable=True, comment="创建人 user_id（管理员）")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="软删除标记")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def auto_summary(self, limit: int = 80) -> str:
        """摘要：优先取 summary 字段，否则从正文截取（先剥 HTML 再取纯文本前 N 字）

        注意：正文是富文本 HTML（可能含 <img>/<p> 等），直接截取会把标签
        当成摘要（如 '<img src=...'）。必须先用正则剥除标签，只保留纯文本。
        即使 summary 字段已有值，也做防御性 strip（历史可能存入 HTML 脏数据）。
        """
        _strip = lambda s: re.sub(r"<[^>]*>", " ", re.sub(r"<\w[\s\S]*$", "", s or "")).strip()
        if self.summary:
            text = _strip(self.summary)
            if text:
                return text[:limit]

        text = self.content or ""
        # 剥除 HTML 标签（含截断的 <img ... 无闭合 >）
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"<img\b[\s\S]*$", "", text)
        # 常见 HTML 实体还原为空格/字符，避免摘要里残留 &nbsp; 等
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def to_dict(self, with_content: bool = False):
        """序列化

        Args:
            with_content: 是否包含完整正文（列表页不带，详情页带）
        """
        data = {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "category_label": CATEGORY_LABELS.get(self.category, "通知"),
            "summary": self.auto_summary(),
            "department": self.department,
            "channel": self.channel,
            "channel_label": self.channel or "",
            "audience_type": self.audience_type,
            "is_top": bool(self.is_top),
            "status": self.status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "published_label": (
                self.published_at.strftime("%Y-%m-%d %H:%M") if self.published_at else None
            ),
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
            "view_count": self.view_count or 0,
            "cover_url": self.cover_url,
            # 卡片实际展示用图（封面回退链）：
            # 管理员配置的封面 → 正文第一张图 → None（前端无图不占位）
            "display_cover": self.cover_url or extract_first_content_image(self.content),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_content:
            # 读取侧同样清洗（B5）：修复前入库的历史正文未经过滤，只挡写入等于把存量
            # 脏数据继续下发给管理端预览（dangerouslySetInnerHTML）。清洗组件不可用时
            # 抛错而非透出原文（fail-closed）。
            from app.utils.html_sanitizer import sanitize_html

            data["content"] = sanitize_html(self.content or "") or ""
        return data


class AnnouncementAttachment(Base):
    """公告附件表"""

    __tablename__ = "announcement_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(
        Integer,
        ForeignKey("announcements.id"),
        nullable=False,
        index=True,
        comment="所属公告 ID",
    )
    file_name = Column(String(200), nullable=False, comment="原始文件名")
    file_size = Column(Integer, nullable=False, default=0, comment="文件大小（字节）")
    file_url = Column(String(500), nullable=False, comment="访问地址（相对路径或完整 URL）")
    created_at = Column(DateTime, default=datetime.now, comment="上传时间")

    def size_label(self) -> str:
        """人类可读的文件大小（对齐原型：1.2 MB / 856 KB）"""
        size = self.file_size or 0
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    def to_dict(self):
        return {
            "id": self.id,
            "announcement_id": self.announcement_id,
            "file_name": self.file_name,
            "file_size": self.file_size or 0,
            "file_size_label": self.size_label(),
            "file_url": self.file_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AnnouncementRead(Base):
    """公告已读记录（未读数 / 红点依据）"""

    __tablename__ = "announcement_reads"
    __table_args__ = (
        UniqueConstraint("announcement_id", "user_id", name="uq_announcement_read"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(Integer, nullable=False, index=True, comment="公告 ID")
    user_id = Column(Integer, nullable=False, index=True, comment="用户 ID")
    read_at = Column(DateTime, default=datetime.now, comment="首次阅读时间")


class AnnouncementFavorite(Base):
    """公告收藏记录"""

    __tablename__ = "announcement_favorites"
    __table_args__ = (
        UniqueConstraint("announcement_id", "user_id", name="uq_announcement_favorite"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(Integer, nullable=False, index=True, comment="公告 ID")
    user_id = Column(Integer, nullable=False, index=True, comment="用户 ID")
    created_at = Column(DateTime, default=datetime.now, comment="收藏时间")
