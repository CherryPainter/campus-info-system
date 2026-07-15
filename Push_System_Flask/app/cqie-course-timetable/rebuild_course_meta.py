#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性维护脚本：依据数据库 courses 表已有学期重建 course_meta.json。

全量爬取（_crawl_all_semesters）依赖 course_meta.json 提供学期列表。
若因历史原因该文件只含 1 个学期（例如 _extract_semesters 解析回退后覆盖式写盘），
全量爬取就会「假全量」。本脚本读取数据库真实存在的 semester_id，推导
eams_id 与学期名，合并写入 course_meta.json，使下一次全量爬取覆盖全部学期。

用法：
    python rebuild_course_meta.py
"""
import json
import os
import sys

import pymysql

# 与 app/core/config.py 保持一致（本地开发库）
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': 'push_system',
    'charset': 'utf8mb4',
}


def semester_id_to_name(semester_id: int) -> str:
    """20251 -> '2025-2026-1'"""
    year = semester_id // 10
    term = semester_id % 10
    return f"{year}-{year + 1}-{term}"


def main():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT semester_id FROM courses WHERE semester_id > 0")
            rows = cur.fetchall()
    finally:
        conn.close()

    semester_ids = sorted({int(r[0]) for r in rows if r[0] and int(r[0]) > 0})
    if not semester_ids:
        print("未从 courses 表读取到任何有效学期，退出")
        sys.exit(1)

    semesters = []
    for sid in semester_ids:
        eams_id = str(sid)[-3:]
        name = semester_id_to_name(sid)
        semesters.append({'id': eams_id, 'name': name})

    current_id = semester_ids[-1]  # 取最新学期为当前
    current_eams = str(current_id)[-3:]
    current_name = semester_id_to_name(current_id)

    meta = {
        'current_semester_id': current_eams,
        'current_semester_name': current_name,
        'weeks': list(range(1, 21)),
        'semesters': semesters,
    }

    here = os.path.dirname(os.path.abspath(__file__))
    raw_data_dir = os.path.join(here, 'output', 'course-data', 'raw')
    os.makedirs(raw_data_dir, exist_ok=True)
    meta_path = os.path.join(raw_data_dir, 'course_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"已重建 course_meta.json -> {meta_path}")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
