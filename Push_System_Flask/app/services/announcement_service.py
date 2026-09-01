#!/usr/bin/env python3
"""校园通知（公告）业务服务

职责：公告的增删改查、发布/撤回、附件管理，以及面向小程序端的
可见性过滤、已读标记、收藏切换、未读统计。

设计约定：
- 送达方式为纯拉取，本服务不涉及任何消息推送。
- 小程序端可见性 = status=published 且未软删 且已到发布时间 且未过期。
- 排序统一为「置顶优先 → 发布时间倒序」，与小程序列表页、管理端列表一致。
- 所有 DB 会话由本服务自行开启与关闭，路由层不持有 session。
"""

from datetime import datetime

from sqlalchemy import and_, or_

from app.core.database import get_db
from app.core.logger import get_logger
from app.model.announcement import (
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUS_WITHDRAWN,
    Announcement,
    AnnouncementAttachment,
    AnnouncementFavorite,
    AnnouncementRead,
)

logger = get_logger(__name__)

# 允许写入的字段（管理端创建/更新时的白名单，防止越权写 view_count 等）
_EDITABLE_FIELDS = {
    "title",
    "category",
    "content",
    "summary",
    "department",
    "audience_type",
    "audience_ids",
    "is_top",
    "expired_at",
}

_VALID_CATEGORIES = {"notice", "activity", "urgent", "system"}


def _with_download_url(items, scope="miniapp"):
    """给附件列表补下载地址（客户端只认接口路径，不暴露磁盘存储路径）"""
    prefix = "/api/miniapp/announcements/attachment" if scope == "miniapp" else (
        "/api/admin/announcements/attachment"
    )
    for it in items:
        it["download_url"] = f"{prefix}/{it['id']}"
    return items


def _parse_datetime(value):
    """宽松解析前端传来的时间字符串，失败返回 None"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    # 去掉毫秒部分
    if "." in text:
        text = text.split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class AnnouncementService:
    """公告服务（单例，无内部状态）"""

    # ==================== 内部工具 ====================

    @staticmethod
    def _visible_filter(now=None):
        """小程序端可见性条件：已发布、未软删、已到发布时间、未过期"""
        now = now or datetime.now()
        return and_(
            Announcement.is_deleted.is_(False),
            Announcement.status == STATUS_PUBLISHED,
            or_(Announcement.published_at.is_(None), Announcement.published_at <= now),
            or_(Announcement.expired_at.is_(None), Announcement.expired_at > now),
        )

    @staticmethod
    def _apply_updates(item: Announcement, data: dict):
        """按白名单套用字段更新"""
        for key in _EDITABLE_FIELDS:
            if key not in data:
                continue
            value = data[key]
            if key == "is_top":
                setattr(item, key, bool(value))
            elif key == "expired_at":
                setattr(item, key, _parse_datetime(value))
            elif key == "category":
                category = str(value or "notice").strip()
                setattr(item, key, category if category in _VALID_CATEGORIES else "notice")
            elif key == "audience_type":
                setattr(item, key, str(value or "all").strip() or "all")
            else:
                setattr(item, key, None if value is None else str(value))

    # ==================== 管理端 ====================

    def list_admin(self, page=1, page_size=20, status=None, category=None, keyword=None):
        """管理端列表（含草稿/撤回，带附件数）

        Returns:
            (items, total)
        """
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 20), 100))
        db = get_db()
        try:
            query = db.query(Announcement).filter(Announcement.is_deleted.is_(False))
            if status:
                query = query.filter(Announcement.status == status)
            if category:
                query = query.filter(Announcement.category == category)
            if keyword:
                query = query.filter(Announcement.title.like(f"%{keyword}%"))
            total = query.count()
            rows = (
                query.order_by(
                    Announcement.is_top.desc(),
                    Announcement.created_at.desc(),
                    Announcement.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            items = []
            for row in rows:
                data = row.to_dict(with_content=True)
                data["attachment_count"] = (
                    db.query(AnnouncementAttachment)
                    .filter(AnnouncementAttachment.announcement_id == row.id)
                    .count()
                )
                data["read_count"] = (
                    db.query(AnnouncementRead)
                    .filter(AnnouncementRead.announcement_id == row.id)
                    .count()
                )
                items.append(data)
            return items, total
        finally:
            db.close()

    def get_admin_detail(self, announcement_id):
        """管理端详情（含附件列表）"""
        db = get_db()
        try:
            item = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id, Announcement.is_deleted.is_(False))
                .first()
            )
            if not item:
                return None
            data = item.to_dict(with_content=True)
            data["attachments"] = _with_download_url(
                [
                    a.to_dict()
                    for a in db.query(AnnouncementAttachment)
                    .filter(AnnouncementAttachment.announcement_id == announcement_id)
                    .order_by(AnnouncementAttachment.id.asc())
                    .all()
                ],
                scope="admin",
            )
            return data
        finally:
            db.close()

    def create(self, data: dict, created_by=None, publish_now=False):
        """创建公告（默认草稿；publish_now=True 直接发布）"""
        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")

        db = get_db()
        try:
            item = Announcement(title=title, created_by=created_by)
            self._apply_updates(item, data)
            item.title = title
            if publish_now:
                item.status = STATUS_PUBLISHED
                item.published_at = _parse_datetime(data.get("published_at")) or datetime.now()
            else:
                item.status = STATUS_DRAFT
            db.add(item)
            db.commit()
            db.refresh(item)
            logger.info(f"公告已创建: id={item.id}, title={item.title}, status={item.status}")
            return item.to_dict(with_content=True)
        finally:
            db.close()

    def update(self, announcement_id, data: dict):
        """更新公告内容（不改变发布状态）"""
        db = get_db()
        try:
            item = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id, Announcement.is_deleted.is_(False))
                .first()
            )
            if not item:
                return None
            if "title" in data:
                title = str(data.get("title") or "").strip()
                if not title:
                    raise ValueError("标题不能为空")
            self._apply_updates(item, data)
            db.commit()
            db.refresh(item)
            logger.info(f"公告已更新: id={announcement_id}")
            return item.to_dict(with_content=True)
        finally:
            db.close()

    def set_status(self, announcement_id, status):
        """发布 / 撤回"""
        if status not in (STATUS_PUBLISHED, STATUS_WITHDRAWN, STATUS_DRAFT):
            raise ValueError("状态非法")
        db = get_db()
        try:
            item = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id, Announcement.is_deleted.is_(False))
                .first()
            )
            if not item:
                return None
            item.status = status
            if status == STATUS_PUBLISHED and not item.published_at:
                item.published_at = datetime.now()
            db.commit()
            db.refresh(item)
            logger.info(f"公告状态变更: id={announcement_id} -> {status}")
            return item.to_dict(with_content=True)
        finally:
            db.close()

    def delete(self, announcement_id):
        """软删除"""
        db = get_db()
        try:
            item = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id, Announcement.is_deleted.is_(False))
                .first()
            )
            if not item:
                return False
            item.is_deleted = True
            db.commit()
            logger.info(f"公告已删除（软删）: id={announcement_id}")
            return True
        finally:
            db.close()

    def add_attachment(self, announcement_id, file_name, file_size, file_url):
        """登记附件记录（文件落盘由路由层完成）"""
        db = get_db()
        try:
            exists = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id, Announcement.is_deleted.is_(False))
                .first()
            )
            if not exists:
                return None
            att = AnnouncementAttachment(
                announcement_id=announcement_id,
                file_name=file_name,
                file_size=int(file_size or 0),
                file_url=file_url,
            )
            db.add(att)
            db.commit()
            db.refresh(att)
            return att.to_dict()
        finally:
            db.close()

    def delete_attachment(self, attachment_id):
        """删除附件记录，返回被删记录的存储路径（供路由层清理文件）"""
        db = get_db()
        try:
            att = (
                db.query(AnnouncementAttachment)
                .filter(AnnouncementAttachment.id == attachment_id)
                .first()
            )
            if not att:
                return None
            file_url = att.file_url
            db.delete(att)
            db.commit()
            return file_url
        finally:
            db.close()

    def get_attachment(self, attachment_id, require_visible=False):
        """取附件记录

        Args:
            require_visible: True 时额外校验所属公告对学生端可见（防越权下载草稿附件）
        """
        db = get_db()
        try:
            att = (
                db.query(AnnouncementAttachment)
                .filter(AnnouncementAttachment.id == attachment_id)
                .first()
            )
            if not att:
                return None
            if require_visible:
                visible = (
                    db.query(Announcement)
                    .filter(Announcement.id == att.announcement_id)
                    .filter(self._visible_filter())
                    .first()
                )
                if not visible:
                    return None
            return att.to_dict()
        finally:
            db.close()

    # ==================== 小程序端 ====================

    def list_for_user(self, user_id, category=None, page=1, page_size=20, only_unread=False, only_favorite=False):
        """小程序列表（仅已发布可见，带 is_read / is_favorite / 附件数）

        Args:
            only_favorite: True 时仅返回该用户收藏过的通知（用于"我的收藏"页）

        Returns:
            (items, total)
        """
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 20), 50))
        db = get_db()
        try:
            query = db.query(Announcement).filter(self._visible_filter())
            if category and category != "all":
                query = query.filter(Announcement.category == category)

            # 仅收藏：先用 AnnouncementFavorite 取该用户全部收藏 id，再过滤
            if only_favorite:
                fav_ids = {
                    f.announcement_id
                    for f in db.query(AnnouncementFavorite.announcement_id)
                    .filter(AnnouncementFavorite.user_id == user_id)
                    .all()
                }
                if not fav_ids:
                    return [], 0
                query = query.filter(Announcement.id.in_(fav_ids))

            read_ids = {
                r.announcement_id
                for r in db.query(AnnouncementRead.announcement_id)
                .filter(AnnouncementRead.user_id == user_id)
                .all()
            }
            if only_unread and read_ids:
                query = query.filter(~Announcement.id.in_(read_ids))

            total = query.count()
            rows = (
                query.order_by(
                    Announcement.is_top.desc(),
                    Announcement.published_at.desc(),
                    Announcement.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            ids = [r.id for r in rows]
            fav_ids = set()
            att_counts = {}
            if ids:
                fav_ids = {
                    f.announcement_id
                    for f in db.query(AnnouncementFavorite.announcement_id)
                    .filter(
                        AnnouncementFavorite.user_id == user_id,
                        AnnouncementFavorite.announcement_id.in_(ids),
                    )
                    .all()
                }
                for att in (
                    db.query(AnnouncementAttachment.announcement_id)
                    .filter(AnnouncementAttachment.announcement_id.in_(ids))
                    .all()
                ):
                    att_counts[att.announcement_id] = att_counts.get(att.announcement_id, 0) + 1

            items = []
            for row in rows:
                data = row.to_dict()
                data["is_read"] = row.id in read_ids
                data["is_favorite"] = row.id in fav_ids
                data["attachment_count"] = att_counts.get(row.id, 0)
                items.append(data)
            return items, total
        finally:
            db.close()

    def detail_for_user(self, user_id, announcement_id, mark_read=True):
        """小程序详情：含正文、附件、相关推荐；顺带写已读并自增阅读数"""
        db = get_db()
        try:
            item = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id)
                .filter(self._visible_filter())
                .first()
            )
            if not item:
                return None

            data = item.to_dict(with_content=True)
            data["attachments"] = _with_download_url(
                [
                    a.to_dict()
                    for a in db.query(AnnouncementAttachment)
                    .filter(AnnouncementAttachment.announcement_id == announcement_id)
                    .order_by(AnnouncementAttachment.id.asc())
                    .all()
                ],
                scope="miniapp",
            )

            # 相关推荐：同分类最近 3 条（排除自身）
            related = (
                db.query(Announcement)
                .filter(self._visible_filter())
                .filter(
                    Announcement.category == item.category,
                    Announcement.id != announcement_id,
                )
                .order_by(Announcement.published_at.desc(), Announcement.id.desc())
                .limit(3)
                .all()
            )
            data["related"] = [
                {
                    "id": r.id,
                    "title": r.title,
                    "category": r.category,
                    "published_label": (
                        r.published_at.strftime("%Y-%m-%d") if r.published_at else None
                    ),
                }
                for r in related
            ]

            data["is_favorite"] = (
                db.query(AnnouncementFavorite)
                .filter(
                    AnnouncementFavorite.user_id == user_id,
                    AnnouncementFavorite.announcement_id == announcement_id,
                )
                .first()
                is not None
            )

            already_read = (
                db.query(AnnouncementRead)
                .filter(
                    AnnouncementRead.user_id == user_id,
                    AnnouncementRead.announcement_id == announcement_id,
                )
                .first()
            )
            if mark_read and not already_read:
                db.add(
                    AnnouncementRead(announcement_id=announcement_id, user_id=user_id)
                )
                item.view_count = (item.view_count or 0) + 1
                db.commit()
                data["view_count"] = item.view_count
            data["is_read"] = True if mark_read else already_read is not None
            return data
        finally:
            db.close()

    def toggle_favorite(self, user_id, announcement_id):
        """收藏 / 取消收藏，返回操作后的收藏状态；公告不可见时返回 None"""
        db = get_db()
        try:
            item = (
                db.query(Announcement)
                .filter(Announcement.id == announcement_id)
                .filter(self._visible_filter())
                .first()
            )
            if not item:
                return None
            row = (
                db.query(AnnouncementFavorite)
                .filter(
                    AnnouncementFavorite.user_id == user_id,
                    AnnouncementFavorite.announcement_id == announcement_id,
                )
                .first()
            )
            if row:
                db.delete(row)
                db.commit()
                return False
            db.add(AnnouncementFavorite(announcement_id=announcement_id, user_id=user_id))
            db.commit()
            return True
        finally:
            db.close()

    def unread_count(self, user_id):
        """未读数（首页红点）"""
        db = get_db()
        try:
            read_ids = [
                r.announcement_id
                for r in db.query(AnnouncementRead.announcement_id)
                .filter(AnnouncementRead.user_id == user_id)
                .all()
            ]
            query = db.query(Announcement).filter(self._visible_filter())
            if read_ids:
                query = query.filter(~Announcement.id.in_(read_ids))
            return query.count()
        finally:
            db.close()

    def mark_read(self, user_id, announcement_id):
        """显式标记已读（详情页底部「标记已读」按钮）"""
        db = get_db()
        try:
            exists = (
                db.query(AnnouncementRead)
                .filter(
                    AnnouncementRead.user_id == user_id,
                    AnnouncementRead.announcement_id == announcement_id,
                )
                .first()
            )
            if exists:
                return True
            db.add(AnnouncementRead(announcement_id=announcement_id, user_id=user_id))
            db.commit()
            return True
        finally:
            db.close()

    def mark_all_read(self, user_id):
        """把当前对用户可见的公告全部标记已读（消息页「全部已读」联动）"""
        db = get_db()
        try:
            rows = (
                db.query(Announcement.id)
                .filter(self._visible_filter())
                .all()
            )
            visible_ids = [r.id for r in rows]
            if not visible_ids:
                return 0
            read_ids = {
                r.announcement_id
                for r in db.query(AnnouncementRead.announcement_id)
                .filter(
                    AnnouncementRead.user_id == user_id,
                    AnnouncementRead.announcement_id.in_(visible_ids),
                )
                .all()
            }
            pending = [aid for aid in visible_ids if aid not in read_ids]
            for aid in pending:
                db.add(AnnouncementRead(announcement_id=aid, user_id=user_id))
            if pending:
                db.commit()
            return len(pending)
        finally:
            db.close()


# 全局单例
announcement_service = AnnouncementService()
