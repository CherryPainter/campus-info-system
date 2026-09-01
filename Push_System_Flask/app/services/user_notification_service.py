#!/usr/bin/env python3
"""
个人站内通知服务

面向单个学生的站内消息（替代企业微信的电量用户推送）：
- 定时任务按用户生成电量日报/周报/月报、低电量提醒、Cookie 失效提醒
- 学生在小程序「我的消息」页查看
"""

from app.core.database import get_db
from app.core.logger import get_logger
from app.repository.user_notification_repository import UserNotificationRepository

logger = get_logger(__name__)


class UserNotificationService:
    """个人站内通知服务类"""

    @staticmethod
    def create(
        user_id: int,
        category: str,
        title: str,
        content: str | None = None,
    ) -> bool:
        """
        给指定用户写入一条站内通知（纯文本，换行分隔）

        Args:
            user_id: 接收用户ID
            category: 通知类型（electricity_daily / electricity_weekly /
                      electricity_monthly / low_power / cookie_invalid / fetch_error）
            title: 通知标题
            content: 通知内容

        Returns:
            bool: 是否写入成功
        """
        try:
            session = get_db()
            try:
                UserNotificationRepository.create(
                    session=session,
                    user_id=user_id,
                    category=category,
                    title=title,
                    content=content,
                )
                session.commit()
                logger.info(f"[UserNotification] 已写入站内通知 user_id={user_id} category={category}")
                return True
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as exc:
            logger.error(f"[UserNotification] 写入站内通知失败 user_id={user_id}: {exc}")
            return False

    @staticmethod
    def list_notifications(
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[dict]:
        """
        查询某用户的站内通知列表（时间倒序）

        Returns:
            List[Dict]: 通知 dict 列表
        """
        session = get_db()
        try:
            records = UserNotificationRepository.list_by_user(
                session,
                user_id=user_id,
                limit=limit,
                offset=offset,
                unread_only=unread_only,
            )
            return [r.to_dict() for r in records]
        finally:
            session.close()

    @staticmethod
    def unread_count(user_id: int) -> int:
        """查询某用户的未读通知数"""
        session = get_db()
        try:
            return UserNotificationRepository.count_by_user(
                session, user_id=user_id, unread_only=True
            )
        finally:
            session.close()

    @staticmethod
    def mark_read(user_id: int, notification_id: int | None = None) -> int:
        """
        标记已读

        Args:
            user_id: 接收用户ID
            notification_id: 指定通知ID；None 时全部标记已读

        Returns:
            int: 受影响行数
        """
        session = get_db()
        try:
            affected = UserNotificationRepository.mark_read(
                session, user_id=user_id, notification_id=notification_id
            )
            session.commit()
            return affected
        except Exception as exc:
            session.rollback()
            logger.error(f"[UserNotification] 标记已读失败 user_id={user_id}: {exc}")
            return 0
        finally:
            session.close()


# 模块级单例
user_notification_service = UserNotificationService()
