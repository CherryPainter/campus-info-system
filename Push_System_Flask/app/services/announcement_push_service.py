#!/usr/bin/env python3
"""
新用户公告补推服务

需求：发布校园公告时，除了学生端「通知公告」页主动拉取外，还要在「我的消息」
（个人站内信）里给近 7 天新注册的学生留一条推送，让新用户不必主动翻公告也能
收到近期通知（替代原先只发企业微信群、学生端无感的问题）。

两条触发路径，互补覆盖「注册时间 ≤ 7 天」语义：
1) 发布时补推（push_announcement_to_new_users）：公告发布瞬间，给当前已注册
   且 created_at 在近 7 天内的学生写站内信。
2) 注册时补推（push_recent_announcements_to_new_user）：学生微信首次登录（用户
   创建）瞬间，把近 7 天已发布的公告补写进站内信——覆盖「公告先于注册、用户
   注册后 7 天内应收到」的场景。

幂等：以 (user_id, ref_type='announcement', ref_id=公告ID) 去重（模型层
UniqueConstraint 兜底 + 本服务写前存在性检查），重复触发不会刷屏。
"""

from datetime import datetime, timedelta

from sqlalchemy import or_

from app.core.database import get_db
from app.core.logger import get_logger
from app.model.announcement import Announcement, STATUS_PUBLISHED
from app.model.user import User
from app.model.user_notification import UserNotification
from app.repository.user_notification_repository import UserNotificationRepository

logger = get_logger(__name__)

# 新用户定向推送窗口（天）
NEW_USER_WINDOW_DAYS = 7

REF_ANNOUNCEMENT = "announcement"


def _cutoff() -> datetime:
    """近 7 天的时间下界（naive，与 users.created_at 同口径）"""
    return datetime.now() - timedelta(days=NEW_USER_WINDOW_DAYS)


def push_announcement_to_new_users(announcement: Announcement) -> int:
    """
    公告发布时，给近 7 天新注册的学生写一条站内信

    Args:
        announcement: 已发布的 Announcement 对象（内存属性即可，不重新查库）

    Returns:
        int: 实际写入的条数
    """
    if announcement is None or announcement.status != STATUS_PUBLISHED:
        return 0

    cutoff = _cutoff()
    db = get_db()
    try:
        # 已为该公告推送过的学生（去重，避免重复发布/并发重复写）
        notified = {
            uid
            for (uid,) in db.query(UserNotification.user_id)
            .filter(
                UserNotification.ref_type == REF_ANNOUNCEMENT,
                UserNotification.ref_id == announcement.id,
            )
            .all()
        }

        # 近 7 天注册且在用的学生
        candidates = (
            db.query(User)
            .filter(
                User.role == "student",
                User.is_active.is_(True),
                User.created_at >= cutoff,
            )
            .all()
        )

        cover_url = announcement.cover_url
        title = announcement.title
        content = announcement.auto_summary() or announcement.summary or ""
        pushed = 0
        for u in candidates:
            if u.id in notified:
                continue
            UserNotificationRepository.create(
                session=db,
                user_id=u.id,
                category=REF_ANNOUNCEMENT,
                title=title,
                content=content,
                cover_url=cover_url,
                ref_type=REF_ANNOUNCEMENT,
                ref_id=announcement.id,
            )
            pushed += 1
        if pushed:
            db.commit()
            logger.info(
                f"[公告补推] 公告 id={announcement.id} 已向 {pushed} 名近 7 天新注册学生推送站内信"
            )
        return pushed
    except Exception as e:
        db.rollback()
        logger.error(f"[公告补推] 发布时补推失败 announcement_id={announcement.id}: {e}")
        return 0
    finally:
        db.close()


def push_recent_announcements_to_new_user(user_id: int) -> int:
    """
    学生首次注册（用户创建）时，把近 7 天已发布的公告补写进站内信

    Args:
        user_id: 新注册学生 user_id

    Returns:
        int: 实际写入的条数
    """
    if not user_id:
        return 0

    now = datetime.now()
    cutoff = _cutoff()
    db = get_db()
    try:
        # 该用户已收到的公告推送（去重）
        got = {
            rid
            for (rid,) in db.query(UserNotification.ref_id)
            .filter(
                UserNotification.user_id == user_id,
                UserNotification.ref_type == REF_ANNOUNCEMENT,
            )
            .all()
        }

        announcements = (
            db.query(Announcement)
            .filter(
                Announcement.status == STATUS_PUBLISHED,
                Announcement.is_deleted.is_(False),
                Announcement.published_at >= cutoff,
                or_(
                    Announcement.expired_at.is_(None),
                    Announcement.expired_at > now,
                ),
            )
            .order_by(Announcement.published_at.desc())
            .all()
        )

        pushed = 0
        for a in announcements:
            if a.id in got:
                continue
            UserNotificationRepository.create(
                session=db,
                user_id=user_id,
                category=REF_ANNOUNCEMENT,
                title=a.title,
                content=a.auto_summary() or a.summary or "",
                cover_url=a.cover_url,
                ref_type=REF_ANNOUNCEMENT,
                ref_id=a.id,
            )
            pushed += 1
        if pushed:
            db.commit()
            logger.info(
                f"[公告补推] 新用户 user_id={user_id} 已补收近 7 天 {pushed} 条公告站内信"
            )
        return pushed
    except Exception as e:
        db.rollback()
        logger.error(f"[公告补推] 注册时补推失败 user_id={user_id}: {e}")
        return 0
    finally:
        db.close()


# 模块级单例（与项目其他服务一致，便于路由/钩子处直接 import 调用）
class AnnouncementPushService:
    """公告新用户补推服务类（方法均为静态，无内部状态）"""

    push_announcement_to_new_users = staticmethod(push_announcement_to_new_users)
    push_recent_announcements_to_new_user = staticmethod(
        push_recent_announcements_to_new_user
    )


announcement_push_service = AnnouncementPushService()
