"""公告正文图片「自动回收」逻辑的单元测试

背景：编辑公告把图片从正文删掉后，磁盘文件原本一直残留成孤儿图（线上 404
坏图、触发 WangEditor 内部崩溃的来源）。现改为「更新 / 删除公告提交后自动
回收不再被任何正文引用的图片」。

覆盖点：
- _extract_image_names：从富文本 HTML 提取 /api/announcement-images/<name>
- _is_image_referenced：是否被任何未软删公告 / 自定义推送正文引用（含前缀重叠边界）
- _delete_unreferenced_images：只删无人引用的文件，被引用的必须保留
- cleanup_all_unused_announcement_images：全量回收孤儿文件

用 SQLite 内存库 + 临时图片目录，不依赖 MySQL / 生产数据。
"""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Config
from app.core.database import Base
from app.model.announcement import Announcement
from app.model.custom_push import CustomPush
from app.services import announcement_service as svc


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """SQLite 内存会话 + 临时图片目录（把 Config.OUTPUT_DIR 指到 tmp_path）"""
    monkeypatch.setattr(Config, "OUTPUT_DIR", str(tmp_path), raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Announcement.__table__, CustomPush.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _img(name):
    """构造一条引用指定图片的富文本"""
    return f'<img src="/api/announcement-images/{name}" style="max-width:100%;"/>'


def _touch(path):
    with open(path, "wb") as f:
        f.write(b"x")


# -------------------- 图片名提取 --------------------

def test_extract_image_names():
    html = (
        "<p>hello</p>"
        '<img src="/api/announcement-images/aaa.png" />'
        '<img src="https://yuetang.cloud/api/announcement-images/bbb.jpg?v=1#x" />'
        '<img src="/other/dir/ccc.png" />'
    )
    assert svc._extract_image_names(html) == {"aaa.png", "bbb.jpg"}


def test_extract_image_names_empty():
    assert svc._extract_image_names("") == set()
    assert svc._extract_image_names(None) == set()


# -------------------- 引用判定 --------------------

def test_referenced_by_announcement(db):
    db.add(Announcement(title="A", content=_img("used.png")))
    db.commit()
    assert svc._is_image_referenced(db, "used.png") is True
    assert svc._is_image_referenced(db, "orphan.png") is False


def test_referenced_by_custom_push(db):
    db.add(CustomPush(title="P", content=_img("pushed.png")))
    db.commit()
    assert svc._is_image_referenced(db, "pushed.png") is True


def test_soft_deleted_announcement_not_counted(db):
    """软删公告不再计入引用 → 其独占图片可被回收"""
    row = Announcement(title="A", content=_img("deleted.png"))
    row.is_deleted = True
    db.add(row)
    db.commit()
    assert svc._is_image_referenced(db, "deleted.png") is False


def test_no_prefix_false_positive(db):
    """边界：'abc.png' 不能被 'xabc.png' 这类重叠文件名误判为已引用"""
    db.add(Announcement(title="A", content=_img("xabc.png")))
    db.commit()
    assert svc._is_image_referenced(db, "xabc.png") is True
    assert svc._is_image_referenced(db, "abc.png") is False


def test_exclude_announcement_id(db):
    """exclude_announcement_id 用于排除本次正在更新的公告自身"""
    row = Announcement(title="A", content=_img("self.png"))
    db.add(row)
    db.commit()
    assert svc._is_image_referenced(db, "self.png", exclude_announcement_id=None) is True
    assert svc._is_image_referenced(db, "self.png", exclude_announcement_id=row.id) is False


# -------------------- 实际删除 --------------------

def test_delete_only_orphans(db, tmp_path):
    root = os.path.join(str(tmp_path), "announcement-images")
    os.makedirs(root, exist_ok=True)
    orphan = os.path.join(root, "orphan.png")
    keep = os.path.join(root, "keep.png")
    _touch(orphan)
    _touch(keep)

    # keep.png 被另一条公告引用；orphan.png 无人引用
    db.add(Announcement(title="A", content=_img("keep.png")))
    db.commit()

    deleted = svc._delete_unreferenced_images(db, {"orphan.png", "keep.png"})

    assert deleted == ["orphan.png"]
    assert not os.path.exists(orphan), "孤儿图应被删除"
    assert os.path.exists(keep), "被引用图片必须保留"


def test_delete_skips_missing_file(db, tmp_path):
    """文件已不存在时不应报错，也不应计入删除列表"""
    assert svc._delete_unreferenced_images(db, {"never-existed.png"}) == []


# -------------------- 全量回收 --------------------

def test_cleanup_all_unused(db, tmp_path):
    root = os.path.join(str(tmp_path), "announcement-images")
    os.makedirs(root, exist_ok=True)
    orphan = os.path.join(root, "orphan2.png")
    keep = os.path.join(root, "keep2.png")
    _touch(orphan)
    _touch(keep)

    db.add(Announcement(title="A", content=_img("keep2.png")))
    db.commit()

    # 测试文件是刚创建的，用 min_age_hours=0 关闭保护期以便验证删除逻辑
    removed = svc.cleanup_all_unused_announcement_images(db, min_age_hours=0)

    assert "orphan2.png" in removed
    assert "keep2.png" not in removed
    assert not os.path.exists(orphan)
    assert os.path.exists(keep)


def test_cleanup_respects_grace_period(db, tmp_path):
    """保护期内的新文件即便无人引用也不删（避免误删刚上传、尚未保存的图）"""
    root = os.path.join(str(tmp_path), "announcement-images")
    os.makedirs(root, exist_ok=True)
    fresh = os.path.join(root, "fresh.png")
    _touch(fresh)

    # 24 小时保护期内：不删
    assert svc.list_unused_announcement_images(db, min_age_hours=24) == []
    assert svc.cleanup_all_unused_announcement_images(db, min_age_hours=24) == []
    assert os.path.exists(fresh)

    # 关掉保护期：应被删除
    assert svc.cleanup_all_unused_announcement_images(db, min_age_hours=0) == ["fresh.png"]
    assert not os.path.exists(fresh)
