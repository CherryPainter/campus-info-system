#!/usr/bin/env python3
"""
个人站内通知仓库

封装 user_notifications 表的数据库操作：
- 按用户写入/查询/统计/标记已读
"""

from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.model.user_notification import UserNotification


class UserNotificationRepository:
    """个人站内通知仓库类"""

    @staticmethod
    def create(
        session: Session,
        user_id: int,
        category: str,
        title: str,
        content: str | None = None,
        cover_url: str | None = None,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> UserNotification:
        """
        创建一条站内通知

        Args:
            session: 数据库会话
            user_id: 接收用户ID
            category: 通知类型（如 electricity_daily / low_power / cookie_invalid / announcement）
            title: 通知标题
            content: 通知内容（纯文本，换行分隔）
            cover_url: 封面图 URL（关联公告时展示）
            ref_type: 关联业务类型（announcement 等，NULL=系统通知）
            ref_id: 关联业务 ID（如公告 ID）

        Returns:
            UserNotification: 创建的通知对象
        """
        notification = UserNotification(
            user_id=user_id,
            category=category,
            title=title,
            content=content,
            cover_url=cover_url,
            ref_type=ref_type,
            ref_id=ref_id,
            is_read=False,
            created_at=datetime.now(),
        )
        session.add(notification)
        session.flush()
        return notification

    @staticmethod
    def list_by_user(
        session: Session,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[UserNotification]:
        """
        查询某用户的站内通知（按时间倒序）

        Args:
            session: 数据库会话
            user_id: 接收用户ID
            limit: 返回条数限制
            offset: 跳过的条数（分页）
            unread_only: 仅查未读

        Returns:
            List[UserNotification]: 通知列表
        """
        q = session.query(UserNotification).filter(UserNotification.user_id == user_id)
        if unread_only:
            q = q.filter(UserNotification.is_read.is_(False))
        return q.order_by(UserNotification.created_at.desc()).offset(offset).limit(limit).all()

    @staticmethod
    def count_by_user(
        session: Session,
        user_id: int,
        unread_only: bool = False,
    ) -> int:
        """
        统计某用户通知总数

        Args:
            session: 数据库会话
            user_id: 接收用户ID
            unread_only: 仅统计未读

        Returns:
            int: 通知数量
        """
        q = session.query(func.count(UserNotification.id)).filter(
            UserNotification.user_id == user_id
        )
        if unread_only:
            q = q.filter(UserNotification.is_read.is_(False))
        return q.scalar() or 0

    @staticmethod
    def mark_read(
        session: Session,
        user_id: int,
        notification_id: int | None = None,
    ) -> int:
        """
        标记已读

        Args:
            session: 数据库会话
            user_id: 接收用户ID
            notification_id: 指定通知ID；为 None 时全部标记已读

        Returns:
            int: 受影响行数
        """
        q = update(UserNotification).where(UserNotification.user_id == user_id)
        if notification_id is not None:
            q = q.where(UserNotification.id == notification_id)
        result = session.execute(q.values(is_read=True))
        session.flush()
        return result.rowcount or 0

    @staticmethod
    def get_by_id(
        session: Session,
        user_id: int,
        notification_id: int,
    ) -> UserNotification | None:
        """按 ID 查询指定用户的单条通知（防越权：必须同时匹配 user_id）"""
        return (
            session.query(UserNotification)
            .filter(
                UserNotification.id == notification_id,
                UserNotification.user_id == user_id,
            )
            .first()
        )
