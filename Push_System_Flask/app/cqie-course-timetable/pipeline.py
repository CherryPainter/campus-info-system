#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整合课程表获取和处理的主程序
使用原始 get_course.py 来获取数据，然后用我们的新系统来处理
"""
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CONFIG
from logger import get_logger
from course_processing.process_course_data import CourseProcessor
try:
    from course_processing.csv_to_image import CsvToImage
except ImportError:
    CsvToImage = None


def _send_status_alert(content: str):
    """通过状态 Webhook 发送告警（env-only，失败静默，不依赖 Flask 上下文）。

    复用后端配置的 WECOM_STATUS_WEBHOOK（Config.get_status_webhooks），
    用于课程数据空结果护栏等运维告警。任何异常都被吞掉，绝不影响主流程。
    """
    try:
        from app.core.config import Config
        import requests
        webhooks = Config.get_status_webhooks()
        if not webhooks:
            return
        for url in webhooks:
            try:
                requests.post(
                    url,
                    json={'msgtype': 'markdown', 'markdown': {'content': content}},
                    timeout=10,
                )
            except Exception:
                pass
    except Exception:
        pass


def extract_course_data_from_json(course_table_json):
    """
    从 course_table.json 结构中提取课程表数据
    """
    day_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    headers = [''] + day_names
    
    course_rows = []
    rows = course_table_json.get('rows', [])
    
    # 课程表从第1行开始（原始数据中没有单独的表头行），直到"课程列表："之前
    for row in rows:  # 注意：从第1行开始，不是 rows[1:]
        if len(row) == 0:
            continue
        first_cell = str(row[0]).strip()
        
        # 如果遇到课程列表，就停止
        if '课程列表' in first_cell or '实践专周' in first_cell:
            break
        
        # 只有有效的节次才加入（接受"第一节"到"第十二节"）
        if first_cell.startswith('第') and len(first_cell) <= 4:  # "第一节"到"第十二节"
            # 确保有完整的8个单元格（节次 + 7天）
            padded = row[:8]
            while len(padded) < 8:
                padded.append('')
            course_rows.append(padded)
    
    return {
        'headers': headers,
        'rows': course_rows
    }


def save_to_database(processed_dir: str, logger, semester_id: int = None, scope_label: str = None, data_source: str = 'full', create_task_process: bool = True) -> int:
    """
    将处理后的课程数据保存到数据库

    直接使用爬虫处理好的时间（课表规定的时间、不同楼栋不同时间表等逻辑）
    每条课程记录存储为一条（不再拆分节次），时间用爬虫计算好的 start_time/end_time

    Args:
        processed_dir: 处理后的数据目录
        logger: 日志记录器
        semester_id: 可选，指定学期的 DB 格式 ID（如 20251）。
                     提供时会用该学期信息覆盖按当前日期推导的学期，
                     保证历史/指定学期爬取的数据被正确打上学期限签。
        scope_label: 可选，进程名称的后缀标签，用于区分「全量爬取」与「指定学期爬取」。
                     例如全量时传 '全部学期'（名称=课程全量爬取·全部学期），
                     指定学期时留空（名称自动取 课程全量爬取·学期{semester_id}）。

    Returns:
        int: 成功时返回导入的课程记录条数（0 表示无数据可导入）；
             导入阶段发生异常时返回 -1。
    """
    # 导入进程管理模块
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # 学期元信息（若提供 semester_id 则按其推导，否则交给 create_batch 按当前日期推导）
    sem_info = None
    if semester_id:
        from app.repository.course_repository import semester_info_from_id
        sem_info = semester_info_from_id(semester_id)
    
    from app.api.process_routes import create_task_process, update_task_progress, complete_task_process
    
    # 创建任务进程记录
    # 注意：此路径服务于「全量爬取 / 指定学期爬取」（crawl_task_service 调用），
    # 使用独立 task_type='course_full_crawl'，与课表爬虫（scheduler.run_spider，task_type='spider'）区分，
    # 避免两者在「进程管理-执行历史」里类型标签撞型都显示「爬虫」。
    # 名称按 scope_label 区分：全量→「课程全量爬取·全部学期」，指定学期→「课程全量爬取·学期{id}」。
    # create_task_process=False 时（每日爬虫入库）不创建独立进程记录——每日爬虫已有自己的
    # 'spider' 进程，再生成 'course_full_crawl' 会污染执行历史。
    process_id = None
    if create_task_process:
        if scope_label:
            _crawl_name = f'课程全量爬取·{scope_label}'
        elif semester_id:
            _crawl_name = f'课程全量爬取·学期{semester_id}'
        else:
            _crawl_name = '课程全量爬取（未指定学期）'
        process_id = create_task_process(
            name=_crawl_name,
            task_type='course_full_crawl',
            total_items=0,  # 稍后更新
            created_by='system'
        )

    try:
        # 导入数据库相关模块 - 设置正确的 Python 路径
        from app.core.database import get_db
        from app.repository.course_repository import CourseRepository
        from app.model.course_week import CourseWeek

        # 读取处理后的数据
        processed_file = os.path.join(processed_dir, 'processed_course_table.json')
        if not os.path.exists(processed_file):
            logger.warning(f"未找到处理后的数据文件: {processed_file}")
            return 0

        with open(processed_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        courses_data = data.get('courses', [])
        week_number = data.get('week_number', 1)

        # ---- 空结果护栏（v6.11.1）----
        # 文件存在但 courses 为空：可能是解析退化（教务系统渲染/选择器变化）。
        # create_batch 为 upsert 模式、只更新不删除，因此此处 return 0 不会清空库；
        # 这里仅「拒绝可疑入库」并发出告警，提示管理员关注解析是否异常。
        if not courses_data:
            from datetime import datetime as _dt
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
                _alert += f'\n\n注意：数据库该周已有 {_existing} 条历史课程，疑似解析退化，请检查爬虫。'
                logger.error(f'[空结果护栏] {data_source} 产出 0 条课程，但数据库该周已有 {_existing} 条，疑似解析退化，已拒绝入库。')
            else:
                logger.warning(f'[空结果护栏] {data_source} 产出 0 条课程，已拒绝入库（不覆盖现有数据）。')
            _send_status_alert(_alert)
            if process_id is not None:
                complete_task_process(process_id, 'completed', '空结果护栏：拒绝入库')
            return 0

        # 更新总项目数
        total_courses = len(courses_data)
        if process_id is not None:
            update_task_progress(process_id, 0, total_courses, '开始处理课程数据...')

        # 星期映射
        week_day_map = {
            '星期一': 1, '星期二': 2, '星期三': 3, '星期四': 4,
            '星期五': 5, '星期六': 6, '星期日': 7, '星期天': 7,
        }

        # 转换数据格式 - 直接使用爬虫处理好的时间
        transformed_data = []
        for idx, course_data in enumerate(courses_data):
            week_day_str = course_data.get('week_day', '')
            week_day = week_day_map.get(week_day_str, 1)

            # 解析 period_name 获取所有节次（用于前端合并显示）
            period_name = course_data.get('period_name', '')
            period_idx = course_data.get('period_idx', 1)
            periods = parse_period_name(period_name, period_idx)

            # 直接使用爬虫处理好的时间（课表规定的时间，不再做减10分钟调整）
            start_time = course_data.get('start_time', '')
            end_time = course_data.get('end_time', '')

            transformed_data.append({
                'course_code': course_data.get('course_code'),
                'course_name': course_data.get('course_name', ''),
                'teacher': course_data.get('teacher', ''),
                'classroom': course_data.get('classroom', ''),
                'building': course_data.get('building', ''),
                'week_day': week_day,
                'period_idx': period_idx,  # 存储起始节次
                'periods': periods,         # 存储所有节次列表（如 [1, 2] 或 [5, 6, 7, 8]）
                'start_time': start_time,
                'end_time': end_time,
                'weeks': course_data.get('weeks', ''),
                'week_number': course_data.get('week_number') or week_number,
                # 指定学期时显式携带学期元信息，确保入库打签正确
                'semester_id': sem_info['semester_id'] if sem_info else None,
                'semester_name': sem_info['semester_name'] if sem_info else None,
                'academic_year': sem_info['academic_year'] if sem_info else None,
                'term': sem_info['term'] if sem_info else None,
            })

            # 每处理10条更新一次进度
            if process_id is not None and ((idx + 1) % 10 == 0 or idx == total_courses - 1):
                update_task_progress(process_id, idx + 1, total_courses, f'已处理 {idx + 1}/{total_courses} 条课程...')

        # 保存到数据库
        if process_id is not None:
            update_task_progress(process_id, total_courses, total_courses, '正在保存到数据库...')
        session = get_db()
        week_start = week_end = None
        try:
            created_count, updated_count = CourseRepository.create_batch(session, transformed_data, data_source=data_source)

            # 计算并存储周日期范围
            all_dates = [cd.get('date', '') for cd in courses_data if cd.get('date')]
            if all_dates:
                from datetime import datetime as dt
                parsed_dates = []
                for d in all_dates:
                    try:
                        parsed_dates.append(dt.strptime(d, '%Y-%m-%d').date())
                    except Exception:
                        pass
                if parsed_dates:
                    week_start = min(parsed_dates)  # 周一
                    # 计算周日（周一 + 6天）
                    from datetime import timedelta
                    week_end = week_start + timedelta(days=6)

                    # ---- Fix B (v6.11.5)：补全第 1 周锚点 ----
                    # 若数据最早周次 > 1（如用户数据从第 2 周开始），原逻辑只 upsert 当前周
                    # (top-level week_number) 的 CourseWeek，CourseWeek.week_number==1 不存在，
                    # get_week_number 会回退 MAX(week_number) 造成课表错周（"0 条课表数据"）。
                    # 用日历反推第 1 周起始日并 upsert 以恢复锚点；当 week_number==1 时
                    # week1_start == week_start，行为与原逻辑完全一致（幂等）。
                    week1_start = week_start - timedelta(days=7 * (week_number - 1))
                    week1_end = week1_start + timedelta(days=6)
                    _week1 = session.query(CourseWeek).filter(CourseWeek.week_number == 1).first()
                    if _week1:
                        _week1.start_date = week1_start
                        _week1.end_date = week1_end
                    else:
                        session.add(CourseWeek(
                            week_number=1,
                            start_date=week1_start,
                            end_date=week1_end,
                        ))

                    # 更新或创建当前周次记录（保留原行为）
                    existing_week = session.query(CourseWeek).filter(
                        CourseWeek.week_number == week_number
                    ).first()

                    if existing_week:
                        existing_week.start_date = week_start
                        existing_week.end_date = week_end
                    else:
                        week_record = CourseWeek(
                            week_number=week_number,
                            start_date=week_start,
                            end_date=week_end,
                        )
                        session.add(week_record)

            session.commit()
            _range = f' (第{week_number}周: {week_start} ~ {week_end})' if (week_start and week_end) else f' (第{week_number}周)'
            logger.info(f"[数据库] 成功保存课程记录到数据库（新增 {created_count} / 更新 {updated_count}）{_range}")

            # 完成任务进程
            if process_id is not None:
                complete_task_process(
                    process_id, 'completed',
                    f'成功导入 {created_count} 条课程记录（新增 {created_count} / 更新 {updated_count}）',
                )
            return created_count
        finally:
            session.close()

    except Exception as e:
        logger.error(f"[数据库] 保存课程数据失败: {e}")
        # 标记任务失败
        if process_id is not None:
            complete_task_process(process_id, 'failed', error=str(e))
        return -1


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
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12,
    }
    
    if not period_name:
        return [default_period]
    
    # 方法1: 匹配 "第X、Y、Z节" 格式
    # 先匹配开头的 "第X"
    match = re.match(r'第([一二三四五六七八九十]+)节?', period_name)
    if match:
        periods = []
        first_num = chinese_num_map.get(match.group(1))
        if first_num:
            periods.append(first_num)
        
        # 匹配后续的 "、X" 格式
        remaining = period_name[match.end():]
        additional_matches = re.findall(r'、([一二三四五六七八九十]+)', remaining)
        for m in additional_matches:
            num = chinese_num_map.get(m)
            if num:
                periods.append(num)
        
        if periods:
            return periods
    
    # 方法2: 直接匹配所有中文数字（备用）
    all_nums = re.findall(r'[一二三四五六七八九十]+', period_name)
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
    logger = get_logger('main')
    logger.info("="*60)
    logger.info("课程表处理程序启动")
    logger.info("="*60)
    
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        raw_dir = os.path.join(current_dir, 'output', 'course-data', 'raw')
        processed_dir = os.path.join(current_dir, 'output', 'course-data', 'processed')
        
        # 1. 读取课程表数据
        schedule_path = os.path.join(current_dir, 'course_table.json')
        raw_schedule_path = os.path.join(raw_dir, 'course_table.json')
        
        course_table_json = None
        
        if os.path.exists(schedule_path):
            logger.info(f"读取课程表: {schedule_path}")
            with open(schedule_path, 'r', encoding='utf-8') as f:
                course_table_json = json.load(f)
        elif os.path.exists(raw_schedule_path):
            logger.info(f"读取课程表: {raw_schedule_path}")
            with open(raw_schedule_path, 'r', encoding='utf-8') as f:
                course_table_json = json.load(f)
        else:
            logger.error("未找到 course_table.json! 请先运行 get_course.py 获取课程表")
            return 1
        
        # 2. 提取和转换数据
        course_data = extract_course_data_from_json(course_table_json)
        logger.info(f"解析到 {len(course_data['rows'])} 节课程")
        
        # 保存中间数据
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, 'course_data.json'), 'w', encoding='utf-8') as f:
            json.dump(course_data, f, ensure_ascii=False, indent=2)
        
        # 3. 处理课程数据
        logger.info("处理课程数据...")
        processor = CourseProcessor()
        processed = processor.run(course_data, raw_dir, processed_dir)
        
        if not processed:
            logger.error("处理失败!")
            return 1
        
        # 4. 保存到数据库
        logger.info("保存课程数据到数据库...")
        save_to_database(processed_dir, logger)
        
        # 5. 生成图片
        csv_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv') and '_week' in f]
        if csv_files:
            csv_files.sort(key=lambda x: os.path.getmtime(os.path.join(processed_dir, x)), reverse=True)
            latest_csv = os.path.join(processed_dir, csv_files[0])
            
            converter = CsvToImage(latest_csv)
            img_path = converter.run()
            
            if img_path:
                logger.info(f"[成功] 课程表图片生成成功: {img_path}")
            else:
                logger.error("生成图片失败!")
        
        logger.info("="*60)
        logger.info("所有任务完成!")
        logger.info("="*60)
        return 0
        
    except Exception as e:
        logger.error(f"程序出错: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
