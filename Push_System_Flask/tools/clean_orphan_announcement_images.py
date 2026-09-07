#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理公告 / 自定义推送正文里「指向缺失文件的 <img> 引用」。

背景
----
管理端富文本（WangEditor）上传的图片存于 `output/announcement-images/`，该目录
按项目规则**不进 git、不跨实例共享**。当某张图片在服务器磁盘上缺失（被删 / 实例间
未同步），对应公告 content 里仍残留 `<img src="/api/announcement-images/xxx.jpg">`。
这类孤儿图片会：
  1. 浏览器/小程序渲染时 404（坏图）；
  2. 触发 WangEditor 5.1.x 在空闲回调遍历节点时抛
     "Cannot read properties of undefined (reading 'startTime')" 内部崩溃。

本脚本扫描 DB 中公告 / 自定义推送的 content，找出所有指向
`/api/announcement-images/<name>` 的 <img>，逐一核对
`<OUTPUT_DIR>/announcement-images/<name>` 是否存在；不存在则移除该 <img> 标签
（并顺手清掉因此产生的空 <p></p>）。

安全策略
--------
- **默认 DRY RUN**：只打印将清理哪些公告 / 图片，**不写库**。
- 真正执行需显式开启：环境变量 `APPLY=1` 或命令行 `--apply`。
- 仅处理未软删的记录（announcements.is_deleted = False）。
- 请在**生产服务器**运行（连真实库 + 真实 output 目录）。沙箱环境连不到生产库、
  且本地 output 不含生产文件，结果不可信。

用法
----
    # 预览（默认，不改库）
    python tools/clean_orphan_announcement_images.py

    # 真正执行
    APPLY=1 python tools/clean_orphan_announcement_images.py
    # 或
    python tools/clean_orphan_announcement_images.py --apply
"""

import os
import re
import sys

# 把项目根目录加入 sys.path，确保能 import app.*
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.core.config import Config

# 必须先 load_config() 再 import db_manager（其单例在导入时建引擎，依赖已加载的配置）
Config.load_config()

from app.core.database import db_manager  # noqa: E402
from app.model.announcement import Announcement  # noqa: E402
from app.model.custom_push import CustomPush  # noqa: E402
from app.services.announcement_service import (  # noqa: E402
    cleanup_all_unused_announcement_images,
    list_unused_announcement_images,
)

# 匹配 <img ... src="..." ...> （不区分大小写）
IMG_TAG_RE = re.compile(r'<img\b[^>]*?src\s*=\s*["\']([^"\']*)["\'][^>]*?>', re.IGNORECASE)


def _extract_image_name(src: str):
    """从 <img src> 提取 announcement-images 下的文件名；非该路径返回 None。"""
    if not src or "announcement-images/" not in src:
        return None
    name = src.split("announcement-images/")[-1]
    # 去掉查询串 / 锚点
    name = name.split("?")[0].split("#")[0]
    return name or None


def _clean_empty_paragraphs(html: str) -> str:
    """移除因删图产生的空段落，避免正文留下大片空白。"""
    html = re.sub(r"<p>\s*</p>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<p>\s*<br\s*/?>\s*</p>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<p>\s*&nbsp;\s*</p>", "", html, flags=re.IGNORECASE)
    return html


def _scan_content(content: str, image_root: str):
    """返回 (new_content, removed_names)。removed_names 为空表示无需改动。"""
    if not content:
        return content, []
    removed = []
    new_content = content
    for m in IMG_TAG_RE.finditer(content):
        name = _extract_image_name(m.group(1))
        if not name:
            continue
        file_path = os.path.join(image_root, name)
        if not os.path.exists(file_path):
            tag = m.group(0)
            new_content = new_content.replace(tag, "")
            removed.append(name)
    if removed:
        new_content = _clean_empty_paragraphs(new_content)
    return new_content, removed


def main():
    apply = os.getenv("APPLY", "0") == "1" or "--apply" in sys.argv[1:]
    image_root = os.path.join(Config.OUTPUT_DIR, "announcement-images")
    mode = "APPLY（将写库）" if apply else "DRY RUN（仅预览，不改库）"
    print(f"== 孤儿图片清理 [{mode}] ==")
    print(f"   图片根目录: {image_root}")
    print(f"   根目录存在: {os.path.isdir(image_root)}")
    print()

    session = db_manager.create_session()
    try:
        total_changed = 0
        total_removed = 0

        # ---- 公告 ----
        announcements = (
            session.query(Announcement)
            .filter(
                Announcement.content.isnot(None),
                Announcement.content.like("%announcement-images/%"),
                Announcement.is_deleted == False,  # noqa: E712
            )
            .all()
        )
        for a in announcements:
            new_content, removed = _scan_content(a.content, image_root)
            if not removed:
                continue
            total_changed += 1
            total_removed += len(removed)
            print(f"[公告 #{a.id}] 《{a.title}》  将移除 {len(removed)} 张坏图:")
            for name in removed:
                print(f"    - {name}")
            if apply:
                a.content = new_content

        # ---- 自定义推送 ----
        pushes = (
            session.query(CustomPush)
            .filter(
                CustomPush.content.isnot(None),
                CustomPush.content.like("%announcement-images/%"),
            )
            .all()
        )
        for p in pushes:
            new_content, removed = _scan_content(p.content, image_root)
            if not removed:
                continue
            total_changed += 1
            total_removed += len(removed)
            print(f"[推送 #{p.id}]  将移除 {len(removed)} 张坏图:")
            for name in removed:
                print(f"    - {name}")
            if apply:
                p.content = new_content

        if apply and total_changed:
            session.commit()
            print(f"\n已提交：{total_changed} 条记录、共 {total_removed} 张坏图引用被清理。")
        else:
            print(f"\n预览结束：{total_changed} 条记录含坏图、共 {total_removed} 张待清理（未写库）。")
            if total_changed and not apply:
                print("如需真正执行，请加环境变量 APPLY=1 或参数 --apply 后重跑。")

        # ---- 第二步：回收磁盘上的孤儿图片文件 ----
        # 顺序很重要：必须先把正文里的坏图 <img> 引用清掉（上一步），
        # 这些文件才会变成"无人引用"，进而被 GC 删除。
        print()
        unused = list_unused_announcement_images(session)
        if not unused:
            print("磁盘孤儿图：无（output/announcement-images/ 下所有图片都被正文引用）。")
        else:
            tag = "已删除" if apply else "将被删除"
            print(f"磁盘孤儿图：{len(unused)} 张未被任何正文引用：")
            for name in unused:
                print(f"    - {name}")
            if apply:
                removed = cleanup_all_unused_announcement_images(session)
                print(f"{tag} {len(removed)} 张孤儿图文件。")
            else:
                print(f"（dry-run，{tag}；加 APPLY=1 / --apply 才会真正删除）")
                if total_changed:
                    print("注意：清掉正文坏图引用后还会有更多文件变为孤儿，实际删除数可能多于上面列表。")
    finally:
        session.close()


if __name__ == "__main__":
    main()
