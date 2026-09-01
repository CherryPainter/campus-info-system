#!/usr/bin/env python3
"""近期提醒（NotificationEvent）管理端路由（/api/admin/notifications）

面向网页管理端，提供小程序时间轴「近期提醒」卡片对应事件数据的增删改查与启停。
全部端点需 @admin_required（JWT Bearer + admin 角色）。

数据契约（与 miniapp 共用的 Notification 模型一致）：
- 列表 / 详情返回模型 to_dict()（含 event_date_label / days_left / is_expired）
- 创建 / 更新接受：title(必填)、event_date(ISO)、category、remind_days、sort_order、is_active、description

端点列表：
- GET    /api/admin/notifications              列表（分页 / 分类 / 关键词 / 仅启用筛选）
- POST   /api/admin/notifications              创建
- GET    /api/admin/notifications/<id>         详情
- PUT    /api/admin/notifications/<id>         更新
- DELETE /api/admin/notifications/<id>         删除
- POST   /api/admin/notifications/<id>/toggle  启停（翻转 is_active）
"""

from datetime import datetime

from flask import Blueprint, g, request

from app.core.api_response import api_error, api_paginate, api_success
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.notification import Notification
from app.utils.auth_middleware import admin_required

logger = get_logger(__name__)

notification_bp = Blueprint("notification_admin", __name__)

# 允许的分类（与 miniapp NotificationEvent.category 联合约束）
VALID_CATEGORIES = {"exam", "holiday", "activity", "other"}

CATEGORY_LABELS = {
    "exam": "考试",
    "holiday": "节假日",
    "activity": "活动",
    "other": "其他",
}


def _current_user_id():
    user = g.get("current_user", {}) or {}
    try:
        return int(user.get("user_id")) if user.get("user_id") is not None else None
    except (TypeError, ValueError):
        return None


def _parse_event_date(value):
    """把前端传来的 ISO 字符串解析为 datetime，失败抛 ValueError"""
    if not value:
        raise ValueError("事件日期不能为空")
    if isinstance(value, datetime):
        return value
    try:
        # 兼容 "2026-09-10" 与 "2026-09-10T08:00:00"
        return datetime.fromisoformat(str(value))
    except ValueError:
        raise ValueError("事件日期格式不正确，应为 ISO 时间，如 2026-09-10T08:00:00")


def _build_from_payload(data: dict) -> Notification:
    """从请求体构造/更新 Notification 实例（不落库，由调用方 commit）"""
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("标题不能为空")

    category = (data.get("category") or "other").strip().lower()
    if category not in VALID_CATEGORIES:
        raise ValueError(f"分类不合法，应为 {sorted(VALID_CATEGORIES)} 之一")

    remind_days = data.get("remind_days")
    if remind_days is None:
        remind_days = 30
    try:
        remind_days = int(remind_days)
    except (TypeError, ValueError):
        raise ValueError("提前提醒天数必须为整数")
    if remind_days < 0:
        raise ValueError("提前提醒天数不能为负")

    sort_order = data.get("sort_order")
    if sort_order is None:
        sort_order = 0
    try:
        sort_order = int(sort_order)
    except (TypeError, ValueError):
        raise ValueError("排序值必须为整数")

    item = Notification(
        title=title,
        event_date=_parse_event_date(data.get("event_date")),
        category=category,
        remind_days=remind_days,
        sort_order=sort_order,
        is_active=bool(data.get("is_active", True)),
        description=(data.get("description") or "").strip() or None,
    )
    return item


# ==================== 近期提醒 CRUD ====================


@notification_bp.route("", methods=["GET"])
@notification_bp.route("/", methods=["GET"])
@admin_required
def list_notifications():
    """近期提醒列表

    查询参数：
        page (int)        页码，默认 1
        page_size (int)   每页条数，默认 20，上限 100
        category (str)    exam/holiday/activity/other，缺省全部
        keyword (str)     标题模糊匹配
        active (str)      "true" 仅启用 / "false" 仅停用 / 缺省全部
    """
    page = request.args.get("page", type=int) or 1
    page_size = min(request.args.get("page_size", type=int) or 20, 100)
    category = request.args.get("category") or None
    keyword = (request.args.get("keyword") or "").strip() or None
    active = request.args.get("active")
    if active not in (None, "true", "false"):
        active = None

    session = get_db()
    try:
        query = session.query(Notification)
        if category:
            query = query.filter(Notification.category == category)
        if keyword:
            query = query.filter(Notification.title.like(f"%{keyword}%"))
        if active == "true":
            query = query.filter(Notification.is_active.is_(True))
        elif active == "false":
            query = query.filter(Notification.is_active.is_(False))

        total = query.count()
        items = (
            query.order_by(
                Notification.event_date.asc(),
                Notification.sort_order.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        data = [n.to_dict() for n in items]
        return api_paginate(data, total, page=page, page_size=page_size)
    finally:
        session.close()


@notification_bp.route("/<int:notification_id>", methods=["GET"])
@admin_required
def get_notification(notification_id):
    """近期提醒详情"""
    session = get_db()
    try:
        item = session.get(Notification, notification_id)
    finally:
        session.close()
    if not item:
        return api_error(message="提醒不存在", http_status=404)
    return api_success(data=item.to_dict())


@notification_bp.route("", methods=["POST"])
@notification_bp.route("/", methods=["POST"])
@admin_required
def create_notification():
    """创建近期提醒"""
    data = request.get_json(silent=True) or {}
    try:
        item = _build_from_payload(data)
    except ValueError as e:
        return api_error(message=str(e), http_status=400)

    session = get_db()
    try:
        session.add(item)
        session.commit()
        return api_success(data=item.to_dict(), message="创建成功")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.error(f"[近期提醒] 创建失败: {e}")
        return api_error(message="创建失败，请稍后重试", http_status=500)
    finally:
        session.close()


@notification_bp.route("/<int:notification_id>", methods=["PUT"])
@admin_required
def update_notification(notification_id):
    """更新近期提醒"""
    data = request.get_json(silent=True) or {}
    session = get_db()
    try:
        item = session.get(Notification, notification_id)
        if not item:
            return api_error(message="提醒不存在", http_status=404)

        title = (data.get("title") or "").strip()
        if "title" in data and not title:
            return api_error(message="标题不能为空", http_status=400)
        if title:
            item.title = title

        if "category" in data:
            category = (data.get("category") or "other").strip().lower()
            if category not in VALID_CATEGORIES:
                return api_error(
                    message=f"分类不合法，应为 {sorted(VALID_CATEGORIES)} 之一",
                    http_status=400,
                )
            item.category = category

        if "event_date" in data:
            try:
                item.event_date = _parse_event_date(data.get("event_date"))
            except ValueError as e:
                return api_error(message=str(e), http_status=400)

        if "remind_days" in data:
            try:
                rd = int(data.get("remind_days"))
            except (TypeError, ValueError):
                return api_error(message="提前提醒天数必须为整数", http_status=400)
            if rd < 0:
                return api_error(message="提前提醒天数不能为负", http_status=400)
            item.remind_days = rd

        if "sort_order" in data:
            try:
                item.sort_order = int(data.get("sort_order"))
            except (TypeError, ValueError):
                return api_error(message="排序值必须为整数", http_status=400)

        if "is_active" in data:
            item.is_active = bool(data.get("is_active"))

        if "description" in data:
            item.description = (data.get("description") or "").strip() or None

        session.commit()
        return api_success(data=item.to_dict(), message="更新成功")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.error(f"[近期提醒] 更新失败: {e}")
        return api_error(message="更新失败，请稍后重试", http_status=500)
    finally:
        session.close()


@notification_bp.route("/<int:notification_id>", methods=["DELETE"])
@admin_required
def delete_notification(notification_id):
    """删除近期提醒（硬删，提醒为参考性数据，无需保留历史）"""
    session = get_db()
    try:
        item = session.get(Notification, notification_id)
        if not item:
            return api_error(message="提醒不存在", http_status=404)
        session.delete(item)
        session.commit()
        return api_success(message="已删除")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.error(f"[近期提醒] 删除失败: {e}")
        return api_error(message="删除失败，请稍后重试", http_status=500)
    finally:
        session.close()


@notification_bp.route("/<int:notification_id>/toggle", methods=["POST"])
@admin_required
def toggle_notification(notification_id):
    """启停（翻转 is_active）"""
    session = get_db()
    try:
        item = session.get(Notification, notification_id)
        if not item:
            return api_error(message="提醒不存在", http_status=404)
        item.is_active = not item.is_active
        session.commit()
        return api_success(data=item.to_dict(), message="已更新状态")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.error(f"[近期提醒] 启停失败: {e}")
        return api_error(message="操作失败，请稍后重试", http_status=500)
    finally:
        session.close()
