"""反馈截图（output/feedback-images/）孤儿回收的单元测试

反馈没有删除/编辑接口，孤儿来自「用户上传了截图但没提交反馈」。
因此回收必须带保护期，避免删掉用户马上要提交的图。

覆盖点：
- _extract_names：从 feedbacks.images（JSON URL 列表）提取文件名
- collect_referenced_feedback_images：汇总所有反馈的引用
- cleanup_unused_feedback_images：只删无人引用的文件
- 保护期：保护期内的新文件不删
- run_image_gc：统一入口同时回收公告图 + 反馈图

用 SQLite 内存库 + 临时目录，不依赖 MySQL / 生产数据。
"""

import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Config
from app.core.database import Base
from app.model.announcement import Announcement
from app.model.custom_push import CustomPush
from app.model.feedback import Feedback
from app.services import feedback_image_gc as gc


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OUTPUT_DIR", str(tmp_path), raising=False)
    engine = create_engine("sqlite:///:memory:")
    # custom_pushes 也要建：run_image_gc 的公告图回收会查该表（判断是否被推送引用）
    Base.metadata.create_all(
        engine,
        tables=[Feedback.__table__, Announcement.__table__, CustomPush.__table__],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _feedback(db, images):
    row = Feedback(user_id=1, type="bug", content="测试反馈", images=json.dumps(images))
    db.add(row)
    db.commit()
    return row


def _touch(path):
    with open(path, "wb") as f:
        f.write(b"x")


# -------------------- 文件名提取 --------------------

def test_extract_names():
    raw = json.dumps(
        [
            "/api/feedback-images/aaa.png",
            "https://yuetang.cloud/api/feedback-images/bbb.jpg?v=1",
            "/other/ccc.png",
        ]
    )
    assert gc._extract_names(raw) == {"aaa.png", "bbb.jpg"}


def test_extract_names_invalid():
    assert gc._extract_names("") == set()
    assert gc._extract_names(None) == set()
    assert gc._extract_names("not-json") == set()
    assert gc._extract_names(json.dumps({"a": 1})) == set()  # 非列表


# -------------------- 引用汇总 --------------------

def test_collect_referenced(db):
    _feedback(db, ["/api/feedback-images/used.png"])
    _feedback(db, ["/api/feedback-images/used2.png", "/api/feedback-images/used3.png"])
    assert gc.collect_referenced_feedback_images(db) == {
        "used.png",
        "used2.png",
        "used3.png",
    }


# -------------------- 实际删除 --------------------

def test_cleanup_only_orphans(db, tmp_path):
    root = os.path.join(str(tmp_path), "feedback-images")
    os.makedirs(root, exist_ok=True)
    orphan = os.path.join(root, "orphan.png")
    keep = os.path.join(root, "keep.png")
    _touch(orphan)
    _touch(keep)

    _feedback(db, ["/api/feedback-images/keep.png"])

    removed = gc.cleanup_unused_feedback_images(db, min_age_hours=0)

    assert removed == ["orphan.png"]
    assert not os.path.exists(orphan), "孤儿截图应被删除"
    assert os.path.exists(keep), "被引用截图必须保留"


def test_grace_period_protects_fresh_upload(db, tmp_path):
    """刚上传、用户可能还没提交的截图，保护期内不能删"""
    root = os.path.join(str(tmp_path), "feedback-images")
    os.makedirs(root, exist_ok=True)
    fresh = os.path.join(root, "fresh.png")
    _touch(fresh)

    assert gc.list_unused_feedback_images(db, min_age_hours=24) == []
    assert gc.cleanup_unused_feedback_images(db, min_age_hours=24) == []
    assert os.path.exists(fresh)

    # 关掉保护期才删
    assert gc.cleanup_unused_feedback_images(db, min_age_hours=0) == ["fresh.png"]
    assert not os.path.exists(fresh)


# -------------------- 统一入口 --------------------

def test_run_image_gc_covers_both(db, tmp_path):
    """run_image_gc 同时回收公告图与反馈图两类孤儿"""
    ann_root = os.path.join(str(tmp_path), "announcement-images")
    fb_root = os.path.join(str(tmp_path), "feedback-images")
    os.makedirs(ann_root, exist_ok=True)
    os.makedirs(fb_root, exist_ok=True)
    _touch(os.path.join(ann_root, "ann-orphan.png"))
    _touch(os.path.join(fb_root, "fb-orphan.png"))

    result = gc.run_image_gc(db, min_age_hours=0)

    assert "ann-orphan.png" in result["announcement"]
    assert "fb-orphan.png" in result["feedback"]
    assert not os.path.exists(os.path.join(ann_root, "ann-orphan.png"))
    assert not os.path.exists(os.path.join(fb_root, "fb-orphan.png"))


def test_run_image_gc_keeps_referenced(db, tmp_path):
    fb_root = os.path.join(str(tmp_path), "feedback-images")
    os.makedirs(fb_root, exist_ok=True)
    keep = os.path.join(fb_root, "referenced.png")
    _touch(keep)
    _feedback(db, ["/api/feedback-images/referenced.png"])

    result = gc.run_image_gc(db, min_age_hours=0)

    assert "referenced.png" not in result["feedback"]
    assert os.path.exists(keep)
