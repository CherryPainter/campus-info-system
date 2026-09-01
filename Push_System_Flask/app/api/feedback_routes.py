#!/usr/bin/env python3
"""意见与反馈蓝图

两个蓝图共用同一套业务逻辑，仅鉴权与路径前缀不同：
- miniapp_bp  (/api/miniapp)   : 学生提交、查看「我的反馈」
- admin_bp    (/api/admin)      : 管理员列表 / 详情 / 标记处理 / 回复
- 图片上传走 miniapp（学生端），公共访问路由在 app/api/routes.py

接口总览：
  学生侧（@student_required）
    POST   /api/miniapp/feedback             提交反馈
    GET    /api/miniapp/feedback            我的反馈列表（分页）
    GET    /api/miniapp/feedback/<id>       反馈详情
    POST   /api/miniapp/feedback/upload     上传反馈截图（字段 file）
  管理侧（@admin_required）
    GET    /api/admin/feedback               全部反馈列表（分页/按状态筛选）
    GET    /api/admin/feedback/count         各状态计数 + 未解决总数（菜单角标用）
    GET    /api/admin/feedback/<id>          反馈详情
    POST   /api/admin/feedback/<id>/resolve  标记状态（pending/processing/resolved）
    POST   /api/admin/feedback/<id>/reply    回复（并置为已解决/处理中）
"""

import os
import json

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import desc, func

from app.core.api_response import api_error, api_success
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.feedback import (
    Feedback,
    FEEDBACK_TYPES,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_RESOLVED,
)
from app.utils.auth_middleware import admin_required
from app.utils.student_auth import student_required
from app.utils.file_upload_security import (
    FileUploadError,
    generate_secure_filename,
    validate_filename,
    validate_file_size,
)

logger = get_logger(__name__)

miniapp_bp = Blueprint("miniapp_feedback", __name__)
admin_bp = Blueprint("admin_feedback", __name__)

# ============ 图片上传（与公告正文图片同套约定）============
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
IMAGE_MAX_SIZE = 20 * 1024 * 1024
IMAGE_SUBDIR = "feedback-images"


def _image_root():
    from app.core.config import Config

    root = os.path.join(Config.OUTPUT_DIR, IMAGE_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


# ==================== 学生侧 ====================

@miniapp_bp.route("/feedback", methods=["POST"])
@student_required
def feedback_create():
    """提交反馈

    请求体（JSON）：
        type    (str, 必填): bug/suggest/consult/other
        content (str, 必填): 反馈内容（纯文本）
        contact (str, 选填): 联系方式
        images  (list[str], 选填): 截图 URL 列表（先调 /upload 拿到 URL）
    """
    user_id = int(g_user_id())
    data = request.get_json(silent=True) or {}
    ftype = (data.get("type") or "other").strip()
    content = (data.get("content") or "").strip()
    contact = (data.get("contact") or "").strip()
    images = data.get("images") or []

    if ftype not in FEEDBACK_TYPES:
        return api_error(message="反馈类型无效", http_status=400)
    if not content:
        return api_error(message="反馈内容不能为空", http_status=400)
    if len(content) > 2000:
        return api_error(message="反馈内容过长（上限 2000 字）", http_status=400)
    if isinstance(images, list):
        images = [str(x) for x in images if x][:9]
    else:
        images = []

    db = get_db()
    try:
        fb = Feedback(
            user_id=user_id,
            type=ftype,
            content=content,
            contact=contact or None,
            images=json.dumps(images, ensure_ascii=False),
            status=STATUS_PENDING,
        )
        db.add(fb)
        db.commit()
        db.refresh(fb)
        logger.info(f"用户 {user_id} 提交反馈 id={fb.id} type={ftype}")
        return api_success(data={"id": fb.id}, message="提交成功")
    finally:
        db.close()


@miniapp_bp.route("/feedback", methods=["GET"])
@student_required
def feedback_mine():
    """我的反馈列表（分页）

    查询参数：page / page_size
    """
    user_id = int(g_user_id())
    page = request.args.get("page", type=int) or 1
    page_size = min(request.args.get("page_size", type=int) or 20, 50)
    page = max(1, page)

    db = get_db()
    try:
        query = db.query(Feedback).filter(Feedback.user_id == user_id)
        total = query.count()
        rows = (
            query.order_by(desc(Feedback.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [r.to_dict(with_reply=False) for r in rows]
        return api_success(data={"items": items, "total": total, "page": page, "page_size": page_size})
    finally:
        db.close()


@miniapp_bp.route("/feedback/<int:feedback_id>", methods=["GET"])
@student_required
def feedback_detail_mine(feedback_id):
    """反馈详情（仅本人）"""
    user_id = int(g_user_id())
    db = get_db()
    try:
        fb = db.query(Feedback).filter(
            Feedback.id == feedback_id, Feedback.user_id == user_id
        ).first()
        if not fb:
            return api_error(message="反馈不存在", http_status=404)
        return api_success(data={"feedback": fb.to_dict()})
    finally:
        db.close()


@miniapp_bp.route("/feedback/upload", methods=["POST"])
@student_required
def feedback_upload():
    """反馈截图上传（WangEditor v5 约定返回格式）

    multipart/form-data，字段名 file，存 output/feedback-images/。
    返回 {"errno":0,"data":{"url":"/api/feedback-images/<name>",...}}
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"errno": 1, "message": "未选择文件"}), 400
    try:
        original_name = validate_filename(file.filename)
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in IMAGE_EXTS:
            return jsonify({"errno": 1, "message": f"不支持的图片类型: {ext}"}), 400
        validate_file_size(file, IMAGE_MAX_SIZE)
        stored_name = generate_secure_filename(file, original_name)
    except FileUploadError as e:
        return jsonify({"errno": 1, "message": str(e)}), 400

    root = _image_root()
    abs_path = os.path.join(root, stored_name)
    try:
        file.seek(0)
        file.save(abs_path)
    except Exception as e:
        logger.error(f"反馈截图落盘失败: {e}")
        return jsonify({"errno": 1, "message": "图片保存失败"}), 500

    # EXIF orientation 校正（与管理端公告图片一致，保证多端显示一致）
    try:
        from PIL import Image, ImageOps

        with Image.open(abs_path) as img:
            transposed = ImageOps.exif_transpose(img)
            if transposed is not None and transposed is not img:
                save_kwargs = {}
                fmt = (img.format or "").upper()
                if fmt == "JPEG":
                    save_kwargs["quality"] = 95
                transposed.save(abs_path, format=fmt or None, **save_kwargs)
    except Exception as e:
        logger.warning(f"反馈截图 EXIF 校正失败（保留原图）: {stored_name} - {e}")

    url = f"/api/feedback-images/{stored_name}"
    logger.info(f"反馈截图已上传: {stored_name}")
    return jsonify({"errno": 0, "data": {"url": url, "alt": original_name, "href": ""}})


# ==================== 管理侧 ====================

@admin_bp.route("/feedback", methods=["GET"])
@admin_required
def feedback_admin_list():
    """全部反馈列表（分页 / 按状态筛选）

    查询参数：status(pending/processing/resolved) / page / page_size
    """
    status = request.args.get("status") or None
    page = request.args.get("page", type=int) or 1
    page_size = min(request.args.get("page_size", type=int) or 20, 50)
    page = max(1, page)

    db = get_db()
    try:
        query = db.query(Feedback)
        if status:
            query = query.filter(Feedback.status == status)
        total = query.count()
        rows = (
            query.order_by(desc(Feedback.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [r.to_dict(with_reply=False) for r in rows]
        return api_success(data={"items": items, "total": total, "page": page, "page_size": page_size})
    finally:
        db.close()


@admin_bp.route("/feedback/count", methods=["GET"])
@admin_required
def feedback_admin_count():
    """反馈计数（供管理端菜单角标）

    返回各状态数量与「未解决=待处理+处理中」总数，单次 GROUP BY 查询，轻量。
    """
    db = get_db()
    try:
        rows = (
            db.query(Feedback.status, func.count(Feedback.id))
            .group_by(Feedback.status)
            .all()
        )
        counts = {STATUS_PENDING: 0, STATUS_PROCESSING: 0, STATUS_RESOLVED: 0}
        for status, c in rows:
            if status in counts:
                counts[status] = c
        pending = counts[STATUS_PENDING]
        processing = counts[STATUS_PROCESSING]
        resolved = counts[STATUS_RESOLVED]
        return api_success(
            data={
                "pending": pending,
                "processing": processing,
                "resolved": resolved,
                "total": pending + processing + resolved,
                "unresolved": pending + processing,
            }
        )
    finally:
        db.close()


@admin_bp.route("/feedback/<int:feedback_id>", methods=["GET"])
@admin_required
def feedback_admin_detail(feedback_id):
    """反馈详情"""
    db = get_db()
    try:
        fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if not fb:
            return api_error(message="反馈不存在", http_status=404)
        return api_success(data={"feedback": fb.to_dict()})
    finally:
        db.close()


@admin_bp.route("/feedback/<int:feedback_id>/resolve", methods=["POST"])
@admin_required
def feedback_resolve(feedback_id):
    """标记处理状态（pending/processing/resolved）

    请求体（JSON）：{"status": "resolved"}
    """
    admin_id = int(g_user_id())
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if new_status not in (STATUS_PENDING, STATUS_PROCESSING, STATUS_RESOLVED):
        return api_error(message="状态无效", http_status=400)

    db = get_db()
    try:
        fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if not fb:
            return api_error(message="反馈不存在", http_status=404)
        fb.status = new_status
        db.commit()
        logger.info(f"管理员 {admin_id} 将反馈 {feedback_id} 置为 {new_status}")
        return api_success(data={"feedback": fb.to_dict()})
    finally:
        db.close()


@admin_bp.route("/feedback/<int:feedback_id>/reply", methods=["POST"])
@admin_required
def feedback_reply(feedback_id):
    """回复反馈（并置为已解决）

    请求体（JSON）：{"reply": "已修复，感谢反馈"}
    """
    admin_id = int(g_user_id())
    data = request.get_json(silent=True) or {}
    reply = (data.get("reply") or "").strip()
    if not reply:
        return api_error(message="回复内容不能为空", http_status=400)

    from datetime import datetime

    db = get_db()
    try:
        fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if not fb:
            return api_error(message="反馈不存在", http_status=404)
        fb.reply = reply
        fb.replied_by = admin_id
        fb.replied_at = datetime.now()
        fb.status = STATUS_RESOLVED
        db.commit()
        logger.info(f"管理员 {admin_id} 回复反馈 {feedback_id}")
        return api_success(data={"feedback": fb.to_dict()})
    finally:
        db.close()


def g_user_id():
    """从 flask g 取当前用户 id（同时兼容 student / admin 上下文）"""
    from flask import g

    return g.current_user["user_id"]
