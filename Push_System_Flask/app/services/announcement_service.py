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

import os
import re
import time
from datetime import datetime

from sqlalchemy import and_, func, or_

from app.core.config import Config
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
from app.model.custom_push import CustomPush

logger = get_logger(__name__)

# ==================== 正文图片（WangEditor）引用与回收 ====================
# 富文本上传的图片存于 output/announcement-images/，与
# announcement_routes.IMAGE_SUBDIR 保持一致。
# 历史问题：编辑公告把图片从正文删掉后，磁盘文件一直留着，堆积成孤儿图
# （也是线上出现 404 坏图、触发 WangEditor 内部崩溃的来源）。
# 因此在「更新 / 删除公告」提交后自动回收不再被任何正文引用的图片。

_IMAGE_TAG_RE = re.compile(r'<img\b[^>]*?src\s*=\s*["\']([^"\']*)["\'][^>]*?>', re.IGNORECASE)

# 全量 GC 的默认保护期（小时）：年龄小于此值的文件即便无人引用也不删，
# 避免误删「刚上传、管理员还在编辑尚未保存进公告正文」的图。
DEFAULT_MIN_AGE_HOURS = 24


def _announcement_image_root():
    """正文图片存储根目录（output/announcement-images/）"""
    root = os.path.join(Config.OUTPUT_DIR, "announcement-images")
    os.makedirs(root, exist_ok=True)
    return root


def _extract_image_names(html):
    """从富文本 HTML 中提取所有 /api/announcement-images/<name> 引用的文件名集合"""
    if not html:
        return set()
    names = set()
    for m in _IMAGE_TAG_RE.finditer(html):
        src = m.group(1) or ""
        if "announcement-images/" not in src:
            continue
        name = src.split("announcement-images/")[-1].split("?")[0].split("#")[0]
        if name:
            names.add(name)
    return names


def _is_image_referenced(db, name, exclude_announcement_id=None):
    """该图片是否仍被任何未软删公告 / 自定义推送正文引用

    用 'announcement-images/<name>' 做子串匹配：'/' 边界可避免
    'abc.png' 误匹配到 'xabc.png' 这类前缀重叠的文件名。
    """
    needle = f"announcement-images/{name}"
    q = db.query(Announcement).filter(
        Announcement.is_deleted.is_(False),
        Announcement.content.like(f"%{needle}%"),
    )
    if exclude_announcement_id is not None:
        q = q.filter(Announcement.id != exclude_announcement_id)
    if q.first():
        return True
    if db.query(CustomPush).filter(CustomPush.content.like(f"%{needle}%")).first():
        return True
    return False


def _delete_unreferenced_images(db, names, exclude_announcement_id=None):
    """删除不再被任何正文引用的图片文件，返回实际删除的文件名列表"""
    deleted = []
    if not names:
        return deleted
    root = _announcement_image_root()
    for name in names:
        if not name:
            continue
        if _is_image_referenced(db, name, exclude_announcement_id):
            continue
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            deleted.append(name)
        except OSError as e:
            logger.warning(f"公告正文图片清理失败（跳过）: {name} - {e}")
    if deleted:
        logger.info(f"公告正文图片自动回收: 已删除 {len(deleted)} 张 - {deleted}")
    return deleted


def collect_referenced_announcement_images(db):
    """汇总当前所有未软删公告 / 自定义推送正文引用的图片文件名集合"""
    referenced = set()
    for (content,) in db.query(Announcement.content).filter(
        Announcement.is_deleted.is_(False), Announcement.content.isnot(None)
    ):
        referenced |= _extract_image_names(content)
    for (content,) in db.query(CustomPush.content).filter(CustomPush.content.isnot(None)):
        referenced |= _extract_image_names(content)
    return referenced


def _older_than(path, hours):
    """文件是否已超过保护期（hours<=0 表示不做年龄限制）"""
    if hours <= 0:
        return True
    try:
        return (time.time() - os.path.getmtime(path)) >= hours * 3600
    except OSError:
        return False


def list_unused_announcement_images(db, min_age_hours=DEFAULT_MIN_AGE_HOURS):
    """只统计不删除：返回无人引用且已过保护期的图片文件名列表

    保护期用于避免误删「刚上传、管理员还在编辑尚未保存」的图片。
    """
    referenced = collect_referenced_announcement_images(db)
    root = _announcement_image_root()
    out = []
    for fname in os.listdir(root):
        if fname in referenced:
            continue
        path = os.path.join(root, fname)
        if not os.path.isfile(path):
            continue
        if not _older_than(path, min_age_hours):
            continue
        out.append(fname)
    return out


def cleanup_all_unused_announcement_images(db=None, min_age_hours=DEFAULT_MIN_AGE_HOURS):
    """全量回收：删除 output/announcement-images/ 下不被任何正文引用的图片

    与「更新 / 删除时自动回收」互补——后者只处理当次改动产生的孤儿，
    本函数用于清理历史遗留孤儿图（实例间未同步、早期版本留下的、或正文里
    坏图引用被清理后残留的文件）。未传 db 时自行开启并关闭会话。

    min_age_hours：保护期，只回收年龄超过该小时数且无人引用的文件，
    防止删掉刚上传、尚未保存进公告正文的图。传 0 表示不做年龄限制。
    返回被删除的文件名列表。
    """
    owns_session = db is None
    if owns_session:
        db = get_db()
    try:
        removed = []
        root = _announcement_image_root()
        for fname in list_unused_announcement_images(db, min_age_hours):
            path = os.path.join(root, fname)
            try:
                os.remove(path)
                removed.append(fname)
            except OSError as e:
                logger.warning(f"公告正文图片全量清理失败（跳过）: {fname} - {e}")
        if removed:
            logger.info(f"公告正文图片全量回收: 已删除 {len(removed)} 张")
        return removed
    finally:
        if owns_session:
            db.close()

# 允许写入的字段（管理端创建/更新时的白名单，防止越权写 view_count 等）
_EDITABLE_FIELDS = {
    "title",
    "category",
    "channel",
    "content",
    "summary",
    "department",
    "audience_type",
    "audience_ids",
    "is_top",
    "expired_at",
    "cover_url",
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
            # 新用户公告补推：创建即发布时给近 7 天新注册学生写站内信（失败不影响主流程）
            if publish_now and item.status == STATUS_PUBLISHED:
                try:
                    from app.services.announcement_push_service import (
                        announcement_push_service,
                    )

                    announcement_push_service.push_announcement_to_new_users(item)
                except Exception as e:
                    logger.warning(f"公告创建即发布补推失败(忽略): id={item.id}: {e}")
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
            # 更新前记下旧正文引用的图片，提交后回收「本次被移除且已无人引用」的图
            old_images = _extract_image_names(item.content) if "content" in data else set()
            self._apply_updates(item, data)
            db.commit()
            db.refresh(item)
            if old_images:
                removed = old_images - _extract_image_names(item.content)
                _delete_unreferenced_images(db, removed, exclude_announcement_id=announcement_id)
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
            # 新用户公告补推：发布公告时给近 7 天新注册学生写站内信（失败不影响主流程）
            if status == STATUS_PUBLISHED:
                try:
                    from app.services.announcement_push_service import (
                        announcement_push_service,
                    )

                    announcement_push_service.push_announcement_to_new_users(item)
                except Exception as e:
                    logger.warning(f"公告发布补推失败(忽略): id={announcement_id}: {e}")
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
            # 记下正文引用的图片：软删后该公告不再计入引用，可回收其独占的图
            images = _extract_image_names(item.content)
            item.is_deleted = True
            db.commit()
            if images:
                _delete_unreferenced_images(db, images, exclude_announcement_id=announcement_id)
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

    def list_for_user(
        self,
        user_id,
        category=None,
        department=None,
        channel=None,
        keyword=None,
        page=1,
        page_size=20,
        only_unread=False,
        only_favorite=False,
    ):
        """小程序列表（仅已发布可见，带 is_read / is_favorite / 附件数）

        Args:
            department: 发布部门精确筛选（预留，当前列表页未使用）。
            channel: 频道精确筛选；缺省 / "all" / "全部" / "我的关注" 表示不按频道过滤。
                "我的关注" 由 only_favorite 处理，不在 channel 维度生效。
            keyword: 关键词搜索，匹配 title 或 summary（LIKE，前后模糊）。
            only_favorite: True 时仅返回该用户收藏过的通知（用于"我的关注"/"我的收藏"页）

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
            if department and department != "all":
                query = query.filter(Announcement.department == department)
            if channel and channel not in ("all", "全部", "我的关注"):
                query = query.filter(Announcement.channel == channel)
            if keyword:
                kw = f"%{keyword}%"
                query = query.filter(
                    or_(Announcement.title.like(kw), Announcement.summary.like(kw))
                )

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

    def count_visible(self):
        """当前对学生可见的公告总数（列表页「全部」标签计数）

        口径与 list_for_user 的可见性完全一致，但不含未读/收藏/分类等筛选。
        """
        db = get_db()
        try:
            return db.query(Announcement).filter(self._visible_filter()).count()
        finally:
            db.close()

    def list_channels(self):
        """可见公告的频道聚合（小程序顶部频道标签用）

        只统计「已发布可见且填写了频道」的公告；按公告数量倒序，
        数量相同时按频道名升序，保证标签顺序稳定（刷新不跳动）。
        未填频道的公告不进标签（仅在「我的关注」或各频道之外不可见）。

        Returns:
            [{"key": "学校要闻", "name": "学校要闻", "count": 3}, ...]
        """
        db = get_db()
        try:
            rows = (
                db.query(Announcement.channel, func.count(Announcement.id))
                .filter(self._visible_filter())
                .filter(Announcement.channel.isnot(None))
                .filter(Announcement.channel != "")
                .group_by(Announcement.channel)
                .order_by(func.count(Announcement.id).desc(), Announcement.channel.asc())
                .all()
            )
            return [
                {"key": name, "name": name, "count": int(count or 0)}
                for name, count in rows
            ]
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
        """未读数（首页红点）；匿名用户返回 0"""
        if user_id is None:
            return 0
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
