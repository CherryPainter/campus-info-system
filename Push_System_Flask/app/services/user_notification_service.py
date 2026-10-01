#!/usr/bin/env python3
"""
个人站内通知服务

面向单个学生的站内消息（替代企业微信的电量用户推送）：
- 定时任务按用户生成电量日报/周报/月报、低电量提醒、Cookie 失效提醒
- 学生在小程序「我的消息」页查看
"""

from datetime import datetime

from app.core.database import get_db
from app.core.logger import get_logger
from app.model.user_notification import UserNotification
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
        cover_url: str | None = None,
        ref_type: str | None = None,
        ref_id: int | None = None,
        payload: dict | None = None,
    ) -> bool:
        """
        给指定用户写入一条站内通知（纯文本，换行分隔）

        Args:
            user_id: 接收用户ID
            category: 通知类型（electricity_daily / electricity_weekly /
                      electricity_monthly / low_power / cookie_invalid / fetch_error / announcement）
            title: 通知标题
            content: 通知内容
            cover_url: 封面图 URL（关联公告时展示）
            ref_type: 关联业务类型（announcement 等，NULL=系统通知）
            ref_id: 关联业务 ID（如公告 ID）
            payload: 结构化数据（dict，可空）。供小程序渲染可交互内容，
                     如电量周报/月报的每日明细（可点进当天详情）。

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
                    cover_url=cover_url,
                    ref_type=ref_type,
                    ref_id=ref_id,
                    payload=payload,
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
    def upsert_feedback_notification(
        user_id: int,
        category: str,
        title: str,
        content: str | None = None,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> bool:
        """按 (user_id, ref_type, ref_id) 去重，给指定用户 upsert 一条站内通知。

        专用於反馈状态通知：同一反馈只保留一条，管理员反复改状态 / 回复时，
        不会因 user_notifications 的唯一约束被静默丢弃；而是更新为最新内容，
        并重置 is_read / is_viewed 重新冒泡为未读 / 未看（学生端会再次看到）。

        Returns:
            bool: 是否成功
        """
        try:
            session = get_db()
            try:
                existing = (
                    session.query(UserNotification)
                    .filter(
                        UserNotification.user_id == user_id,
                        UserNotification.ref_type == ref_type,
                        UserNotification.ref_id == ref_id,
                    )
                    .first()
                )
                now = datetime.now()
                if existing is not None:
                    existing.category = category
                    existing.title = title
                    existing.content = content
                    existing.is_read = False
                    existing.is_viewed = False
                    existing.created_at = now
                else:
                    session.add(
                        UserNotification(
                            user_id=user_id,
                            category=category,
                            title=title,
                            content=content,
                            ref_type=ref_type,
                            ref_id=ref_id,
                            is_read=False,
                            is_viewed=False,
                            created_at=now,
                        )
                    )
                session.commit()
                logger.info(
                    f"[UserNotification] 已upsert站内通知 user_id={user_id} ref_type={ref_type} ref_id={ref_id}"
                )
                return True
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as exc:
            logger.error(
                f"[UserNotification] upsert站内通知失败 user_id={user_id} ref_type={ref_type} ref_id={ref_id}: {exc}"
            )
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
    def get_notification(user_id: int, notification_id: int) -> dict | None:
        """
        查询单条站内通知详情

        必须同时按 id 与 user_id 过滤：id 由客户端传入，若不校验归属会出现
        越权读取他人消息（IDOR）。查不到时返回 None，由路由层转 404。

        Args:
            user_id: 当前登录用户ID（取自 JWT，不接受客户端传参）
            notification_id: 通知ID

        Returns:
            Optional[Dict]: 通知 dict；不存在或不属于该用户时返回 None
        """
        from app.model.user_notification import UserNotification

        session = get_db()
        try:
            record = (
                session.query(UserNotification)
                .filter(
                    UserNotification.id == notification_id,
                    UserNotification.user_id == user_id,
                )
                .first()
            )
            return record.to_dict() if record else None
        finally:
            session.close()

    @staticmethod
    def unread_count(user_id: int) -> int:
        """查询某用户的未读通知数（is_read 口径，外部气泡角标用）"""
        session = get_db()
        try:
            return UserNotificationRepository.count_by_user(
                session, user_id=user_id, unread_only=True
            )
        finally:
            session.close()

    @staticmethod
    def unviewed_count(user_id: int) -> int:
        """查询某用户的未看过通知数（is_viewed 口径，消息列表卡片红点用）"""
        session = get_db()
        try:
            return UserNotificationRepository.count_by_user(
                session, user_id=user_id, unviewed_only=True
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

    @staticmethod
    def mark_viewed(user_id: int, notification_id: int | None = None) -> int:
        """
        标记通知已看过（点进详情页细看）

        两层已读模型：is_read=进入列表已读（清外部气泡），is_viewed=点进详情已看（清卡片红点）。
        此处只处理 is_viewed，同时把 is_read 一并置 True（看过必然已读）。

        Args:
            user_id: 接收用户ID
            notification_id: 指定通知ID；None 时该用户全部标记已看
                             （消息页「全部已读」按钮批量清红点用）

        Returns:
            int: 受影响行数
        """
        session = get_db()
        try:
            affected = UserNotificationRepository.mark_viewed(
                session, user_id=user_id, notification_id=notification_id
            )
            session.commit()
            return affected
        except Exception as exc:
            session.rollback()
            logger.error(f"[UserNotification] 标记已看失败 user_id={user_id}: {exc}")
            return 0
        finally:
            session.close()


# 模块级单例
user_notification_service = UserNotificationService()
