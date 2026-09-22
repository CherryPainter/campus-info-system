#!/usr/bin/env python3
"""校园通知（公告）管理端路由（/api/admin/announcements）

面向网页管理端，提供公告的增删改查、发布/撤回、附件上传与下载。
全部端点需 @admin_required（JWT Bearer + admin 角色）。

端点列表：
- GET    /api/admin/announcements                        公告列表（分页/状态/分类/标题关键词）
- POST   /api/admin/announcements                        创建（默认草稿，publish=true 直接发布）
- GET    /api/admin/announcements/<id>                   详情（含附件）
- PUT    /api/admin/announcements/<id>                   更新内容
- POST   /api/admin/announcements/<id>/publish           发布
- POST   /api/admin/announcements/<id>/withdraw          撤回
- DELETE /api/admin/announcements/<id>                   删除（软删）
- POST   /api/admin/announcements/<id>/attachments       上传附件（multipart/form-data，字段名 file）
- GET    /api/admin/announcements/attachment/<att_id>    下载附件
- DELETE /api/admin/announcements/attachment/<att_id>    删除附件（同时清理磁盘文件）

附件存储：Config.OUTPUT_DIR/announcements/<sha256>.<ext>，DB 仅存相对路径，
客户端通过 download_url 接口下载，不暴露磁盘路径。
"""

import os

from flask import Blueprint, g, request, send_file

from app.core.api_response import api_error, api_paginate, api_success
from app.core.config import Config
from app.core.logger import get_logger
from app.services.announcement_service import announcement_service
from app.utils.auth_middleware import admin_required
from app.utils.file_upload_security import (
    FileUploadError,
    generate_secure_filename,
    validate_filename,
    validate_file_size,
)
import re

logger = get_logger(__name__)

announcement_bp = Blueprint("announcement", __name__)


# ==================== 防御性 HTML 清洗 ====================

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TRUNCATED_IMG_RE = re.compile(r"<img\b[\s\S]*$", re.IGNORECASE)


def _strip_html(value):
    """剥除 HTML 标签，仅保留纯文本。防御性使用：防止富文本 HTML 误入纯文本字段
    （如 summary）。非破坏性：只剥标签，保留内文（如 '<p>你好</p>' → '你好'）。
    容错：处理历史脏数据中截断的 <img 标签（缺闭合 >）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    # 1) 剥除完整的 HTML 标签
    value = _HTML_TAG_RE.sub("", value)
    # 2) 剥除截断的 <img ...（无闭合 >，到字符串末尾）
    value = _TRUNCATED_IMG_RE.sub("", value)
    return value.strip()

# 附件允许的扩展名（文档 + 图片 + 压缩包，显式白名单）
ALLOWED_ATTACHMENT_EXTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".zip",
    ".rar",
    ".7z",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
}
# 附件大小上限 20MB
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024
# 附件存储子目录（相对 output/）
ATTACHMENT_SUBDIR = "announcements"


def _attachment_root():
    """附件存储根目录（不存在则创建）"""
    root = os.path.join(Config.OUTPUT_DIR, ATTACHMENT_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def _resolve_stored_path(file_url):
    """把 DB 中的相对路径解析为磁盘绝对路径，并防止路径穿越"""
    root = _attachment_root()
    target = os.path.abspath(os.path.join(Config.OUTPUT_DIR, file_url or ""))
    if not target.startswith(os.path.abspath(root)):
        return None
    return target


def _current_user_id():
    user = g.get("current_user", {}) or {}
    try:
        return int(user.get("user_id")) if user.get("user_id") is not None else None
    except (TypeError, ValueError):
        return None


# ==================== 公告 CRUD ====================


@announcement_bp.route("", methods=["GET"])
@announcement_bp.route("/", methods=["GET"])
@admin_required
def list_announcements():
    """公告列表

    查询参数：
        page (int)      页码，默认 1
        page_size (int) 每页条数，默认 20，上限 100
        status (str)    draft/published/withdrawn，缺省全部
        category (str)  notice/activity/urgent/system，缺省全部
        keyword (str)   标题模糊匹配
    """
    page = request.args.get("page", type=int) or 1
    page_size = request.args.get("page_size", type=int) or 20
    status = request.args.get("status") or None
    category = request.args.get("category") or None
    keyword = (request.args.get("keyword") or "").strip() or None

    items, total = announcement_service.list_admin(
        page=page, page_size=page_size, status=status, category=category, keyword=keyword
    )
    return api_paginate(items, total, page=page, page_size=page_size)


@announcement_bp.route("/<int:announcement_id>", methods=["GET"])
@admin_required
def get_announcement(announcement_id):
    """公告详情（含附件列表）"""
    data = announcement_service.get_admin_detail(announcement_id)
    if not data:
        return api_error(message="公告不存在", http_status=404)
    # 读路径防御：剥除脏数据（如历史误存的 <img> 混入 summary），
    # 保证编辑页回填到表单的字段是纯文本。
    if isinstance(data, dict) and isinstance(data.get("summary"), str):
        data["summary"] = _strip_html(data["summary"])
    return api_success(data=data)


@announcement_bp.route("", methods=["POST"])
@announcement_bp.route("/", methods=["POST"])
@admin_required
def create_announcement():
    """创建公告

    请求体：
        title (必填), category, content, summary, department,
        audience_type, is_top, expired_at, publish (bool，true 则直接发布)
    """
    data = request.get_json(silent=True) or {}
    # 防御性：summary 是纯文本字段，剥除误塞进来的 HTML（如 <img>）
    data["summary"] = _strip_html(data.get("summary") or "")
    publish_now = bool(data.get("publish"))
    try:
        item = announcement_service.create(
            data, created_by=_current_user_id(), publish_now=publish_now
        )
    except ValueError as e:
        return api_error(message=str(e), http_status=400)
    return api_success(data=item, message="创建成功")


@announcement_bp.route("/<int:announcement_id>", methods=["PUT"])
@admin_required
def update_announcement(announcement_id):
    """更新公告内容（不改变发布状态）"""
    data = request.get_json(silent=True) or {}
    # 防御性：summary 剥 HTML
    data["summary"] = _strip_html(data.get("summary") or "")
    try:
        item = announcement_service.update(announcement_id, data)
    except ValueError as e:
        return api_error(message=str(e), http_status=400)
    if not item:
        return api_error(message="公告不存在", http_status=404)
    return api_success(data=item, message="更新成功")


@announcement_bp.route("/<int:announcement_id>/publish", methods=["POST"])
@admin_required
def publish_announcement(announcement_id):
    """发布公告"""
    item = announcement_service.set_status(announcement_id, "published")
    if not item:
        return api_error(message="公告不存在", http_status=404)
    return api_success(data=item, message="已发布")


@announcement_bp.route("/<int:announcement_id>/withdraw", methods=["POST"])
@admin_required
def withdraw_announcement(announcement_id):
    """撤回公告（学生端立即不可见）"""
    item = announcement_service.set_status(announcement_id, "withdrawn")
    if not item:
        return api_error(message="公告不存在", http_status=404)
    return api_success(data=item, message="已撤回")


@announcement_bp.route("/<int:announcement_id>", methods=["DELETE"])
@admin_required
def delete_announcement(announcement_id):
    """删除公告（软删，保留附件文件）"""
    ok = announcement_service.delete(announcement_id)
    if not ok:
        return api_error(message="公告不存在", http_status=404)
    return api_success(message="已删除")


# ==================== 附件 ====================

# 富文本编辑器正文图片（WangEditor v5）专用：与公告附件分离存储
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
IMAGE_MAX_SIZE = 20 * 1024 * 1024
IMAGE_SUBDIR = "announcement-images"


def _image_root():
    """正文图片存储根目录（不存在则创建）"""
    root = os.path.join(Config.OUTPUT_DIR, IMAGE_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


@announcement_bp.route("/upload-image", methods=["POST"])
@admin_required
def upload_editor_image():
    """富文本编辑器图片上传（WangEditor v5 约定）

    multipart/form-data，字段名 file，图片存 output/announcement-images/。
    返回 WangEditor 固定格式：{"errno":0,"data":{"url","alt","href"}}。

    图片访问走公共路由 GET /api/announcement-images/<name>（无需鉴权，
    学生端正文渲染 RichText 也能直接加载）。
    """
    from flask import jsonify

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
        logger.error(f"公告正文图片落盘失败: {e}")
        return jsonify({"errno": 1, "message": "图片保存失败"}), 500

    # EXIF orientation 校正：iOS/部分安卓相机写入的 EXIF orientation 标记
    # 会让浏览器/img 标签自动旋转显示，但小程序 RichText/某些 webview
    # 不读 EXIF，导致同一张图在不同端显示方向不一致。
    # 此处用 Pillow 自动旋转并保存（去掉 orientation 标记），所有端显示一致。
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
                logger.info(f"公告正文图片已 EXIF 校正: {stored_name}")
    except Exception as e:
        logger.warning(f"EXIF 校正失败（保留原图）: {stored_name} - {e}")

    url = f"/api/announcement-images/{stored_name}"
    logger.info(f"公告正文图片已上传: {stored_name}")
    return jsonify({"errno": 0, "data": {"url": url, "alt": original_name, "href": ""}})


# 公告封面（独立于正文图，存 output/announcement-covers/，走公开路由 /api/announcement-covers/<name>）
COVER_SUBDIR = "announcement-covers"


def _cover_root():
    """封面存储根目录（不存在则创建）"""
    root = os.path.join(Config.OUTPUT_DIR, COVER_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


@announcement_bp.route("/upload-cover", methods=["POST"])
@admin_required
def upload_cover():
    """公告封面上传（管理端）

    存 output/announcement-covers/，复用正文图的安全校验（扩展名白名单 + 大小上限
    + sha256 重命名）与 EXIF 校正。返回 {url} 供表单提交时写入 announcement.cover_url。
    封面经公开路由 GET /api/announcement-covers/<name> 加载（学生端无鉴权）。
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return api_error(message="未选择文件", http_status=400)

    try:
        original_name = validate_filename(file.filename)
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in IMAGE_EXTS:
            return api_error(message=f"不支持的图片类型: {ext}", http_status=400)
        validate_file_size(file, IMAGE_MAX_SIZE)
        stored_name = generate_secure_filename(file, original_name)
    except FileUploadError as e:
        return api_error(message=str(e), http_status=400)

    root = _cover_root()
    abs_path = os.path.join(root, stored_name)
    try:
        file.seek(0)
        file.save(abs_path)
    except Exception as e:
        logger.error(f"公告封面落盘失败: {e}")
        return api_error(message="图片保存失败", http_status=500)

    # EXIF orientation 校正：与正文图一致，保证多端显示方向一致
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
                logger.info(f"公告封面已 EXIF 校正: {stored_name}")
    except Exception as e:
        logger.warning(f"封面 EXIF 校正失败（保留原图）: {stored_name} - {e}")

    url = f"/api/announcement-covers/{stored_name}"
    logger.info(f"公告封面已上传: {stored_name}")
    return api_success(data={"url": url}, message="上传成功")


@announcement_bp.route("/<int:announcement_id>/attachments", methods=["POST"])
@admin_required
def upload_attachment(announcement_id):
    """上传附件（multipart/form-data，字段名 file）

    安全策略：扩展名白名单 + 20MB 上限 + sha256 重命名落盘（不使用用户提供的文件名做路径）。
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return api_error(message="未选择文件", http_status=400)

    try:
        original_name = validate_filename(file.filename)
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in ALLOWED_ATTACHMENT_EXTS:
            return api_error(message=f"不支持的附件类型: {ext}", http_status=400)
        validate_file_size(file, MAX_ATTACHMENT_SIZE)
        stored_name = generate_secure_filename(file, original_name)
    except FileUploadError as e:
        return api_error(message=str(e), http_status=400)

    root = _attachment_root()
    abs_path = os.path.join(root, stored_name)
    try:
        file.seek(0)
        file.save(abs_path)
        file_size = os.path.getsize(abs_path)
    except Exception as e:
        logger.error(f"公告附件落盘失败: {e}")
        return api_error(message="附件保存失败", http_status=500)

    rel_path = f"{ATTACHMENT_SUBDIR}/{stored_name}"
    record = announcement_service.add_attachment(
        announcement_id, original_name, file_size, rel_path
    )
    if not record:
        return api_error(message="公告不存在", http_status=404)
    record["download_url"] = f"/api/admin/announcements/attachment/{record['id']}"
    logger.info(f"公告附件已上传: announcement_id={announcement_id}, file={original_name}")
    return api_success(data=record, message="上传成功")


@announcement_bp.route("/attachment/<int:attachment_id>", methods=["GET"])
@admin_required
def download_attachment(attachment_id):
    """下载附件（管理端）"""
    att = announcement_service.get_attachment(attachment_id)
    if not att:
        return api_error(message="附件不存在", http_status=404)
    abs_path = _resolve_stored_path(att["file_url"])
    if not abs_path or not os.path.exists(abs_path):
        return api_error(message="附件文件已丢失", http_status=404)
    return send_file(abs_path, as_attachment=True, download_name=att["file_name"])


@announcement_bp.route("/attachment/<int:attachment_id>", methods=["DELETE"])
@admin_required
def remove_attachment(attachment_id):
    """删除附件（先删记录，再清理磁盘文件）"""
    att = announcement_service.get_attachment(attachment_id)
    if not att:
        return api_error(message="附件不存在", http_status=404)
    file_url = announcement_service.delete_attachment(attachment_id)
    if file_url:
        abs_path = _resolve_stored_path(file_url)
        if abs_path and os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except Exception as e:
                logger.warning(f"附件文件清理失败（记录已删）: {e}")
    return api_success(message="附件已删除")
