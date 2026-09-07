#!/usr/bin/env python3
"""反馈截图（output/feedback-images/）孤儿回收

存储与引用
----------
反馈截图上传后落盘 output/feedback-images/，引用以「URL 列表的 JSON 字符串」
存在 feedbacks.images 字段（见 Feedback 模型）。

与公告正文图的关键差异
----------------------
反馈**没有删除接口、也没有编辑正文的接口**，所以孤儿来源只有一个：
用户上传了截图，但最终没提交反馈（或提交失败）。这些文件永远不会被
任何 feedbacks.images 引用，只能靠 GC 回收。

安全要点（保护期）
------------------
刚上传的截图，用户可能还在填写反馈内容、尚未提交。若此时 GC 把它删掉，
就会出现「用户点提交，图却 404」。因此回收必须带保护期（默认 24 小时）：
只删「无任何引用」**且**「已超过保护期」的文件。

与公告图回收配合使用见 run_image_gc()。
"""

import json
import os
import time

from app.core.config import Config
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.feedback import Feedback

logger = get_logger(__name__)

# 与 feedback_routes.IMAGE_SUBDIR 保持一致
_IMAGE_SUBDIR = "feedback-images"

# 默认保护期（小时）：小于此年龄的文件即便无人引用也不删，避免误伤在途上传
DEFAULT_MIN_AGE_HOURS = 24


def _feedback_image_root():
    """反馈截图存储根目录（output/feedback-images/）"""
    root = os.path.join(Config.OUTPUT_DIR, _IMAGE_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def _extract_names(images_json):
    """从 feedbacks.images（URL 列表的 JSON 字符串）提取引用的文件名集合"""
    if not images_json:
        return set()
    try:
        urls = json.loads(images_json)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(urls, list):
        return set()
    names = set()
    for u in urls:
        if not isinstance(u, str) or f"{_IMAGE_SUBDIR}/" not in u:
            continue
        # 取最后一段文件名，去掉 ?query / #hash
        name = u.split(f"{_IMAGE_SUBDIR}/")[-1].split("?")[0].split("#")[0]
        if name:
            names.add(name)
    return names


def collect_referenced_feedback_images(db):
    """汇总所有反馈引用的截图文件名集合"""
    referenced = set()
    for (images_json,) in db.query(Feedback.images).filter(Feedback.images.isnot(None)):
        referenced |= _extract_names(images_json)
    return referenced


def _older_than(path, hours):
    """文件是否已超过保护期（hours<=0 表示不做年龄限制）"""
    if hours <= 0:
        return True
    try:
        return (time.time() - os.path.getmtime(path)) >= hours * 3600
    except OSError:
        return False


def list_unused_feedback_images(db, min_age_hours=DEFAULT_MIN_AGE_HOURS):
    """只统计不删除：返回无人引用且已过保护期的截图文件名列表"""
    referenced = collect_referenced_feedback_images(db)
    root = _feedback_image_root()
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


def cleanup_unused_feedback_images(db=None, min_age_hours=DEFAULT_MIN_AGE_HOURS):
    """回收无人引用且已过保护期的反馈截图

    未传 db 时自行开启并关闭会话。返回被删除的文件名列表。
    """
    owns_session = db is None
    if owns_session:
        db = get_db()
    try:
        removed = []
        root = _feedback_image_root()
        for fname in list_unused_feedback_images(db, min_age_hours):
            path = os.path.join(root, fname)
            try:
                os.remove(path)
                removed.append(fname)
            except OSError as e:
                logger.warning(f"反馈截图清理失败（跳过）: {fname} - {e}")
        if removed:
            logger.info(f"反馈截图回收: 已删除 {len(removed)} 张")
        return removed
    finally:
        if owns_session:
            db.close()


def run_image_gc(db=None, min_age_hours=DEFAULT_MIN_AGE_HOURS):
    """统一入口：一次回收「公告正文图」+「反馈截图」两类孤儿

    供定时任务 / 手动调用。两类回收都带保护期，避免误删在途上传。
    返回 {"announcement": [...], "feedback": [...]}。

    db：可选。传入则由调用方管理会话（测试注入、或复用现有会话）；
        不传则两个回收各自开启并关闭自己的会话。

    注意：公告图的主要自动回收在「更新/删除公告提交后」即时完成，
    这里的全量 GC 只是兜底（清理历史遗留、或正文坏图引用被清后的残留）。
    """
    from app.services.announcement_service import cleanup_all_unused_announcement_images

    result = {"announcement": [], "feedback": []}
    try:
        result["announcement"] = cleanup_all_unused_announcement_images(
            db=db, min_age_hours=min_age_hours
        )
    except Exception as e:  # 一类失败不影响另一类
        logger.warning(f"公告正文图全量回收异常（已跳过）: {e}")
    try:
        result["feedback"] = cleanup_unused_feedback_images(db=db, min_age_hours=min_age_hours)
    except Exception as e:
        logger.warning(f"反馈截图回收异常（已跳过）: {e}")

    total = len(result["announcement"]) + len(result["feedback"])
    if total:
        logger.info(
            f"图片孤儿回收完成: 公告 {len(result['announcement'])} 张、"
            f"反馈 {len(result['feedback'])} 张"
        )
    return result
