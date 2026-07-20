#!/usr/bin/env python3
"""
整合课程表获取和处理的主程序
使用原始 get_course.py 来获取数据，然后用我们的新系统来处理
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from course_processing.process_course_data import CourseProcessor
from logger import get_logger

try:
    from course_processing.csv_to_image import CsvToImage
except ImportError:
    CsvToImage = None


# 告警函数已迁至系统侧 app/services/notification_service.py（send_status_alert），
# 爬虫不再自带告警逻辑（v6.14 爬虫越权收回阶段2）。空结果护栏改用系统侧实现。


def extract_course_data_from_json(course_table_json):
    """
    从 course_table.json 结构中提取课程表数据
    """
    day_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    headers = [""] + day_names

    course_rows = []
    rows = course_table_json.get("rows", [])

    # 课程表从第1行开始（原始数据中没有单独的表头行），直到"课程列表："之前
    for row in rows:  # 注意：从第1行开始，不是 rows[1:]
        if len(row) == 0:
            continue
        first_cell = str(row[0]).strip()

        # 如果遇到课程列表，就停止
        if "课程列表" in first_cell or "实践专周" in first_cell:
            break

        # 只有有效的节次才加入（接受"第一节"到"第十二节"）
        if first_cell.startswith("第") and len(first_cell) <= 4:  # "第一节"到"第十二节"
            # 确保有完整的8个单元格（节次 + 7天）
            padded = row[:8]
            while len(padded) < 8:
                padded.append("")
            course_rows.append(padded)

    return {"headers": headers, "rows": course_rows}


def save_to_database(
    processed_dir: str,
    logger,
    semester_id: int = None,
    data_source: str = "full",
) -> tuple[int, int]:
    """
    系统侧：将爬虫产出的 processed_course_table.json 导入数据库（仅落库）。

    边界收紧（v6.14）：本函数不再由爬虫子进程内部调用，改为系统侧在子进程
    成功返回后调用（executors.run_spider / crawl_task_service._crawl_one_semester）。
    爬虫子进程（pipeline.main）只负责产出 JSON 与图片，不再落库、不再写
    周次表、不再标记进程、不再发告警——"系统夺回控制权"。

    教学周判定现已彻底脱离 course_weeks 表：开学日来自配置 system.semester_start_date
    （或按 term 推算），由 teaching_week_service 统一推算；进程标记由调用方负责；
    空结果护栏告警复用 notification_service.send_status_alert（阶段2收口）。

    Args:
        processed_dir: 处理后的数据目录
        logger: 日志记录器
        semester_id: 可选，指定学期的 DB 格式 ID（如 20251），用于数据打签
        data_source: 数据来源标记（'full'=全量/指定学期, 'daily'=每日爬虫）

    Returns:
        Tuple[int, int]: (新建数, 更新数)。
            无数据可导入（文件缺失 / 空结果护栏触发）时返回 (0, 0)；
            导入阶段发生异常时返回 (-1, 0)。
    """
    # 学期元信息（若提供 semester_id 则按其推导，否则交给 create_batch 按当前日期推导）
    sem_info = None
    if semester_id:
        from app.repository.course_repository import semester_info_from_id

        sem_info = semester_info_from_id(semester_id)

    from app.core.database import get_db
    from app.repository.course_repository import CourseRepository

    # 读取处理后的数据
    processed_file = os.path.join(processed_dir, "processed_course_table.json")
    if not os.path.exists(processed_file):
        logger.warning(f"未找到处理后的数据文件: {processed_file}")
        return 0, 0

    with open(processed_file, encoding="utf-8") as f:
        data = json.load(f)

    courses_data = data.get("courses", [])
    week_number = data.get("week_number", 1)

    # ---- 空结果护栏（v6.11.1）----
    # 文件存在但 courses 为空：可能是解析退化。create_batch 为 upsert 模式不删除，
    # 此处拒绝可疑入库并发告警，不覆盖现有数据。
    if not courses_data:
        _alert_empty_result(logger, data_source, week_number)
        return 0, 0

    # 星期映射
    week_day_map = {
        "星期一": 1,
        "星期二": 2,
        "星期三": 3,
        "星期四": 4,
        "星期五": 5,
        "星期六": 6,
        "星期日": 7,
        "星期天": 7,
    }

    # 转换数据格式 - 直接使用爬虫处理好的时间
    transformed_data = []
    for course_data in courses_data:
        week_day_str = course_data.get("week_day", "")
        week_day = week_day_map.get(week_day_str, 1)

        # 解析 period_name 获取所有节次（用于前端合并显示）
        period_name = course_data.get("period_name", "")
        period_idx = course_data.get("period_idx", 1)
        periods = parse_period_name(period_name, period_idx)

        # 直接使用爬虫处理好的时间（课表规定的时间，不再做减10分钟调整）
        start_time = course_data.get("start_time", "")
        end_time = course_data.get("end_time", "")

        transformed_data.append(
            {
                "course_code": course_data.get("course_code"),
                "course_name": course_data.get("course_name", ""),
                "teacher": course_data.get("teacher", ""),
                "classroom": course_data.get("classroom", ""),
                "building": course_data.get("building", ""),
                "week_day": week_day,
                "period_idx": period_idx,  # 存储起始节次
                "periods": periods,  # 存储所有节次列表（如 [1, 2] 或 [5, 6, 7, 8]）
                "start_time": start_time,
                "end_time": end_time,
                "weeks": course_data.get("weeks", ""),
                "week_number": course_data.get("week_number") or week_number,
                # 指定学期时显式携带学期元信息，确保入库打签正确
                "semester_id": sem_info["semester_id"] if sem_info else None,
                "semester_name": sem_info["semester_name"] if sem_info else None,
                "academic_year": sem_info["academic_year"] if sem_info else None,
                "term": sem_info["term"] if sem_info else None,
            }
        )

    session = get_db()
    try:
        created_count, updated_count = CourseRepository.create_batch(
            session, transformed_data, data_source=data_source
        )
        session.commit()
        logger.info(
            f"[数据库] 成功保存课程记录到数据库（新增 {created_count} / 更新 {updated_count}）(第{week_number}周)"
        )
        return created_count, updated_count
    except Exception as e:
        session.rollback()
        logger.error(f"[数据库] 保存课程数据失败: {e}")
        return -1, 0
    finally:
        session.close()


def _alert_empty_result(logger, data_source: str, week_number: int):
    """空结果护栏：检查该周是否已有历史课程，发企微告警提示解析退化（不入库）。"""
    from datetime import datetime as _dt

    from app.core.database import get_db
    from app.repository.course_repository import CourseRepository

    _alert = (
        f'**课程数据空结果护栏**\n\n'
        f'来源：{data_source}\n\n'
        f'时间：{_dt.now().strftime("%Y-%m-%d %H:%M")}\n\n'
        f'说明：爬虫产出 0 条课程（week={week_number}），已拒绝入库，未覆盖现有数据。'
    )
    _existing = 0
    try:
        _chk_session = get_db()
        try:
            _existing = CourseRepository.count(_chk_session, week_number)
        finally:
            _chk_session.close()
    except Exception:
        _existing = -1
    if _existing and _existing > 0:
        _alert += (
            f"\n\n注意：数据库该周已有 {_existing} 条历史课程，疑似解析退化，请检查爬虫。"
        )
        logger.error(
            f"[空结果护栏] {data_source} 产出 0 条课程，但数据库该周已有 {_existing} 条，疑似解析退化，已拒绝入库。"
        )
    else:
        logger.warning(
            f"[空结果护栏] {data_source} 产出 0 条课程，已拒绝入库（不覆盖现有数据）。"
        )
    try:
        from app.services.notification_service import send_status_alert

        send_status_alert(_alert)
    except Exception as _ne:
        logger.warning(f"[空结果护栏] 告警发送失败（已忽略）: {_ne}")


def parse_period_name(period_name: str, default_period: int) -> list:
    """
    解析节次名称，返回节次列表

    Examples:
        "第一节" -> [1]
        "第一、二节" -> [1, 2]
        "第三、四、五节" -> [3, 4, 5]
        "第一、二、三、四节" -> [1, 2, 3, 4]

    Args:
        period_name: 节次名称
        default_period: 默认节次

    Returns:
        list: 节次索引列表
    """
    import re

    # 中文数字映射
    chinese_num_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
    }

    if not period_name:
        return [default_period]

    # 方法1: 匹配 "第X、Y、Z节" 格式
    # 先匹配开头的 "第X"
    match = re.match(r"第([一二三四五六七八九十]+)节?", period_name)
    if match:
        periods = []
        first_num = chinese_num_map.get(match.group(1))
        if first_num:
            periods.append(first_num)

        # 匹配后续的 "、X" 格式
        remaining = period_name[match.end() :]
        additional_matches = re.findall(r"、([一二三四五六七八九十]+)", remaining)
        for m in additional_matches:
            num = chinese_num_map.get(m)
            if num:
                periods.append(num)

        if periods:
            return periods

    # 方法2: 直接匹配所有中文数字（备用）
    all_nums = re.findall(r"[一二三四五六七八九十]+", period_name)
    if all_nums:
        periods = []
        for num_str in all_nums:
            num = chinese_num_map.get(num_str)
            if num and 1 <= num <= 12:
                periods.append(num)
        if periods:
            return periods

    return [default_period]


def main():
    logger = get_logger("main")
    logger.info("=" * 60)
    logger.info("课程表处理程序启动")
    logger.info("=" * 60)

    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        raw_dir = os.path.join(current_dir, "output", "course-data", "raw")
        processed_dir = os.path.join(current_dir, "output", "course-data", "processed")

        # 1. 读取课程表数据
        schedule_path = os.path.join(current_dir, "course_table.json")
        raw_schedule_path = os.path.join(raw_dir, "course_table.json")

        course_table_json = None

        if os.path.exists(schedule_path):
            logger.info(f"读取课程表: {schedule_path}")
            with open(schedule_path, encoding="utf-8") as f:
                course_table_json = json.load(f)
        elif os.path.exists(raw_schedule_path):
            logger.info(f"读取课程表: {raw_schedule_path}")
            with open(raw_schedule_path, encoding="utf-8") as f:
                course_table_json = json.load(f)
        else:
            logger.error("未找到 course_table.json! 请先运行 get_course.py 获取课程表")
            return 1

        # 2. 提取和转换数据
        course_data = extract_course_data_from_json(course_table_json)
        logger.info(f"解析到 {len(course_data['rows'])} 节课程")

        # 保存中间数据
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, "course_data.json"), "w", encoding="utf-8") as f:
            json.dump(course_data, f, ensure_ascii=False, indent=2)

        # 3. 处理课程数据
        logger.info("处理课程数据...")
        processor = CourseProcessor()
        processed = processor.run(course_data, raw_dir, processed_dir)

        if not processed:
            logger.error("处理失败!")
            return 1

        # 4. 产出数据契约（系统侧接管落库 / 周次锚点 / 进程标记 / 告警，
        #    见 executors.run_spider 与 crawl_task_service._crawl_one_semester）
        logger.info("课程数据 JSON 已产出，落库由系统侧统一调度（save_to_database 由执行器调用）")

        # 5. 生成图片（图片生成依赖 matplotlib 环境，仍留在爬虫子进程，阶段2 子命令化）
        csv_files = [f for f in os.listdir(processed_dir) if f.endswith(".csv") and "_week" in f]
        if csv_files:
            csv_files.sort(
                key=lambda x: os.path.getmtime(os.path.join(processed_dir, x)), reverse=True
            )
            latest_csv = os.path.join(processed_dir, csv_files[0])

            converter = CsvToImage(latest_csv)
            img_path = converter.run()

            if img_path:
                logger.info(f"[成功] 课程表图片生成成功: {img_path}")
            else:
                logger.error("生成图片失败!")

        logger.info("=" * 60)
        logger.info("所有任务完成!")
        logger.info("=" * 60)
        return 0

    except Exception as e:
        logger.error(f"程序出错: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
