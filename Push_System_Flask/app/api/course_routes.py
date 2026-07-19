#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程管理 API 路由

提供课程表的增删改查和图形化展示接口
"""

from flask import Blueprint, request, jsonify, g
from app.core.api_response import api_success, api_error, api_paginate
from datetime import datetime
import re
import json

from app.utils.auth_middleware import jwt_required, admin_required
from app.core.logger import get_logger
from app.core.database import get_db
from app.model.course import Course
from app.model.scheduled_crawl_task import ScheduledCrawlTask
from app.repository.course_repository import generate_course_code, derive_current_semester, semester_info_from_id
from app.services import crawl_task_service as crawl_svc

logger = get_logger(__name__)
course_bp = Blueprint('course', __name__, url_prefix='/course')


# 爬虫有两套时间表，根据楼栋选择
# 第一套（first）：启智楼、雏鹰楼、语慧楼、思源楼、讯达楼、盛德楼
# 第二套（second）：艺教楼、图书馆、理工楼、鸿志楼、明远楼

# 第一套时间表
FIRST_SCHEDULE = {
    1: ('08:10', '08:55'),   # 第一节
    2: ('09:05', '09:50'),   # 第二节
    3: ('10:10', '10:55'),   # 第三节
    4: ('11:05', '11:50'),   # 第四节
    5: ('14:10', '14:55'),   # 第五节
    6: ('15:05', '15:50'),   # 第六节
    7: ('16:10', '16:55'),   # 第七节
    8: ('17:05', '17:50'),   # 第八节
    9: ('18:50', '19:35'),   # 第九节
    10: ('19:35', '20:20'),  # 第十节
    11: ('20:30', '21:15'),  # 第十一节
    12: ('21:15', '22:00'),  # 第十二节
}

# 第二套时间表
SECOND_SCHEDULE = {
    1: ('08:10', '08:55'),   # 第一节
    2: ('09:05', '09:50'),   # 第二节
    3: ('10:30', '11:15'),   # 第三节
    4: ('11:25', '12:10'),   # 第四节
    5: ('14:10', '14:55'),   # 第五节
    6: ('15:05', '15:50'),   # 第六节
    7: ('16:30', '17:15'),   # 第七节
    8: ('17:25', '18:10'),   # 第八节
    9: ('18:50', '19:35'),   # 第九节
    10: ('19:35', '20:20'),  # 第十节
    11: ('20:30', '21:15'),  # 第十一节
    12: ('21:15', '22:00'),  # 第十二节
}

# 第一套教学楼
FIRST_SCHEDULE_BUILDINGS = ['启智楼', '雏鹰楼', '语慧楼', '思源楼', '讯达楼', '盛德楼', 'S01', 'S02', 'J01', 'J04', 'J14', 'J15']

def get_schedule_by_building(building: str) -> dict:
    """根据楼栋获取对应的时间表"""
    if building in FIRST_SCHEDULE_BUILDINGS:
        return FIRST_SCHEDULE
    return SECOND_SCHEDULE


_CN_NUM = {
    1: '一', 2: '二', 3: '三', 4: '四', 5: '五',
    6: '六', 7: '七', 8: '八', 9: '九', 10: '十',
    11: '十一', 12: '十二',
}


def _normalize_periods(periods):
    """把 periods 字段统一成 int 列表；支持 list / JSON 字符串 / None"""
    if periods is None:
        return []
    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            return []
    if not isinstance(periods, (list, tuple)):
        return []
    out = []
    for p in periods:
        try:
            out.append(int(p))
        except (TypeError, ValueError):
            continue
    return out


def apply_timetable_times(course: dict) -> dict:
    """
    用课表规定的时间覆盖课程的 start_time / end_time（去除任何“减10分钟”之类的调整）。

    - 依据课程自身的 periods 列表 + 楼栋，从 FIRST/SECOND_SCHEDULE 取权威时间。
    - 同时修正 _timeInfo 的时间戳（基于 extra_info.full_date），使提醒触发时间也准确。
    - 缺少 periods / building 信息时原样返回，不破坏既有数据。
    """
    if not isinstance(course, dict):
        return course

    periods = _normalize_periods(course.get('periods'))
    if not periods:
        pidx = course.get('period_idx')
        if pidx:
            periods = [int(pidx)]
    if not periods:
        return course

    building = (course.get('extra_info') or {}).get('building', '') or ''
    sch = get_schedule_by_building(building)
    nums = [n for n in periods if n in sch]
    if not nums:
        return course

    lo, hi = min(nums), max(nums)
    start_time = sch[lo][0]
    end_time = sch[hi][1]

    course = dict(course)
    course['start_time'] = start_time
    course['end_time'] = end_time

    # 同步修正 period_name 为中文“第X、Y节”形式（更准确反映实际节次）
    if lo in _CN_NUM and hi in _CN_NUM:
        if lo == hi:
            course['period_name'] = f"第{_CN_NUM[lo]}节"
        else:
            course['period_name'] = f"第{_CN_NUM[lo]}、{_CN_NUM[hi]}节"

    ti = course.get('_timeInfo')
    full_date = (course.get('extra_info') or {}).get('full_date')
    if ti and full_date:
        try:
            y, m, d = map(int, str(full_date).split('-'))
            sh, sm = map(int, start_time.split(':'))
            eh, em = map(int, end_time.split(':'))
            course['_timeInfo'] = {
                'start_ts': datetime(y, m, d, sh, sm).timestamp(),
                'end_ts': datetime(y, m, d, eh, em).timestamp(),
                **{k: v for k, v in ti.items() if k not in ('start_ts', 'end_ts')},
            }
        except Exception:
            pass
    return course


def split_course_to_big_classes(course: dict) -> list:
    """
    将跨多组大课的课程（如 1-4节）按“每2节=1门大课”拆成多条。

    返回 list[dict]，每条为一组大课（periods 为相邻2节），时间已按课表规定填充。
    """
    periods = _normalize_periods(course.get('periods'))
    if not periods:
        pidx = course.get('period_idx')
        if pidx:
            periods = [int(pidx)]
    if not periods:
        return [apply_timetable_times(course)]

    periods = sorted(set(periods))
    chunks = [periods[i:i + 2] for i in range(0, len(periods), 2)]
    if len(chunks) <= 1:
        return [apply_timetable_times(course)]

    results = []
    for idx, chunk in enumerate(chunks):
        c = dict(course)
        c['period_idx'] = chunk[0]
        c['periods'] = chunk
        c = apply_timetable_times(c)
        orig_id = str(course.get('schedule_id') or course.get('id') or '')
        c['schedule_id'] = f"{orig_id}#p{chunk[0]}-{chunk[-1]}"
        results.append(c)
    return results


def parse_weeks(weeks_str: str) -> set:
    """
    解析上课周次字符串，返回周次集合
    
    支持格式：
      - 单个数字: "14" -> {14}
      - 范围: "1-16" -> {1,2,3,...,16}
      - 逗号分隔: "1,3,5" -> {1,3,5}
      - 混合: "1-4,8,12-16" -> {1,2,3,4,8,12,13,14,15,16}
      - 空字符串: "" -> set() (表示所有周都有课)
    
    Args:
        weeks_str: 上课周次字符串
        
    Returns:
        set: 周次集合
    """
    if not weeks_str or not weeks_str.strip():
        return set()  # 空表示所有周
    
    result = set()
    parts = weeks_str.replace('，', ',').split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            # 范围: "1-16"
            try:
                start, end = part.split('-')
                start_num = int(start.strip())
                end_num = int(end.strip())
                result.update(range(start_num, end_num + 1))
            except (ValueError, IndexError):
                pass
        else:
            # 单个数字: "14"
            try:
                result.add(int(part))
            except ValueError:
                pass
    
    return result


def is_course_in_week(course_weeks, target_week: int) -> bool:
    """
    判断课程在指定周次是否有课
    
    支持两种格式：
      - JSON列表格式: [1, 2, 3, 14, 15, 16]
      - 旧字符串格式: "1-16" 或 "1,3,5"
    
    Args:
        course_weeks: 课程的上课周次（字符串或列表）
        target_week: 目标周次
        
    Returns:
        bool: 是否有课
    """
    if not course_weeks:
        return True  # 没有填写周次，默认所有周都有课
    
    # 如果是列表（JSON格式）
    if isinstance(course_weeks, list):
        if not course_weeks:
            return True  # 空列表表示所有周
        return target_week in course_weeks
    
    # 如果是字符串（旧格式 或 JSON 数组字符串）
    if isinstance(course_weeks, str):
        s = course_weeks.strip()
        if not s:
            return True  # 空字符串表示所有周

        # 去除可能被二次转义的外层引号（数据库 TEXT 列存储 list 时常见，
        # 例如存成 "[18]" 或 '"[18]"'，首字符是引号而非 [）
        if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
            s = s[1:-1].strip()

        # 优先尝试 JSON 数组格式，如 "[19]" 或 "[2, 3, 4, ..., 18]"
        # （数据库以字符串存储 list 时会出现这种形式，parse_weeks 无法识别）
        if s.startswith('['):
            try:
                import json as _json
                parsed = _json.loads(s)
                # 防御二次编码：json.loads 后仍可能是字符串
                if isinstance(parsed, str):
                    parsed = _json.loads(parsed)
                if isinstance(parsed, list):
                    if not parsed:
                        return True  # 空列表表示所有周
                    return target_week in parsed
            except (ValueError, TypeError):
                pass

        weeks = parse_weeks(s)
        if not weeks:
            return True  # 解析为空，默认所有周都有课

        return target_week in weeks

    return True


# 默认使用第二套（兼容旧数据）
PERIOD_TIME_MAP = SECOND_SCHEDULE


@course_bp.route('/list', methods=['GET'])
@jwt_required
def get_courses():
    """获取课程列表"""
    week_day = request.args.get('week_day', type=int)
    week_number = request.args.get('week_number', type=int)
    semester_id = request.args.get('semester_id', type=int)

    session = get_db()
    try:
        # 查询所有课程（排除已删除的），按 weeks 字段过滤
        query = session.query(Course).filter(Course.is_deleted == False)
        # 学期过滤：未指定时默认当前学期
        if semester_id is None:
            semester_id = _get_current_semester_id()
        if semester_id is not None:
            query = query.filter(Course.semester_id == semester_id)
        if week_day:
            query = query.filter(Course.week_day == week_day)
        
        courses = query.order_by(Course.week_day, Course.period_idx).all()
        
        # 按 weeks 字段过滤
        if week_number:
            courses = [c for c in courses if is_course_in_week(c.weeks or '', week_number)]
        
        # 合并同一天、同一课程名、同一教室的记录（多条节次合并为一条）
        merged = {}
        for c in courses:
            key = f"{c.week_day}_{c.course_name}_{c.classroom}_{c.week_number}"
            if key in merged:
                # 合并节次（支持 JSON 列表格式）
                existing = merged[key]
                # 获取现有节次（兼容旧格式和新格式）
                existing_periods_list = existing.get('periods', [])
                if isinstance(existing_periods_list, str):
                    existing_periods_list = [int(p) for p in existing_periods_list.split(',') if p.strip().isdigit()]
                elif not isinstance(existing_periods_list, list):
                    existing_periods_list = [existing.get('period_idx', c.period_idx)]
                
                # 获取新课程节次（兼容旧格式和新格式）
                new_periods_list = c.periods or []
                if isinstance(new_periods_list, str):
                    new_periods_list = [int(p) for p in new_periods_list.split(',') if p.strip().isdigit()]
                elif not isinstance(new_periods_list, list):
                    new_periods_list = [c.period_idx]
                
                # 合并并排序
                all_periods = sorted(set(existing_periods_list + new_periods_list))
                existing['periods'] = all_periods
                # 处理空列表情况，使用课程的 period_idx 作为默认值
                existing['period_idx'] = min(all_periods) if all_periods else c.period_idx
                # 更新结束时间
                if c.end_time and c.end_time > existing.get('end_time', ''):
                    existing['end_time'] = c.end_time
            else:
                merged[key] = c.to_dict()
        
        return api_success(data=list(merged.values()))
    finally:
        session.close()


def get_current_week_number() -> int:
    """
    根据学期日期范围自动计算当前周次
    
    第二学期：3月2日 - 7月19日
    第一学期：9月1日 - 1月25日
    
    Returns:
        int: 当前周次（1-25）
    """
    from datetime import date, timedelta
    
    today = date.today()
    year = today.year
    
    # 第二学期：3月2日开始
    spring_start = date(year, 3, 2)
    spring_end = date(year, 7, 19)
    
    # 第一学期：9月1日开始
    fall_start = date(year, 9, 1)
    fall_end = date(year + 1, 1, 25)  # 跨年
    
    # 判断当前属于哪个学期
    if spring_start <= today <= spring_end:
        # 第二学期
        days_diff = (today - spring_start).days
        week_number = days_diff // 7 + 1
    elif fall_start <= today <= fall_end:
        # 第一学期
        days_diff = (today - fall_start).days
        week_number = days_diff // 7 + 1
    elif today > spring_end and today < fall_start:
        # 暑假：按开学日起继续推算（可能超出教学周范围），由前端 inBreak / 假期模式接管展示
        days_diff = (today - spring_start).days
        week_number = days_diff // 7 + 1
    elif today < spring_start:
        # 寒假：按上一学年秋季学期起推算
        prev_fall_start = date(year - 1, 9, 1)
        days_diff = (today - prev_fall_start).days
        week_number = days_diff // 7 + 1
    else:
        # 其他情况，默认第1周
        week_number = 1
    
    return max(1, min(week_number, 25))


def get_current_period_and_status(building: str = '') -> dict:
    """
    获取当前节次和上课状态
    
    注意：
    - is_ongoing 仅表示当前时间落在某个节次的时间范围内
    - 是否真的"正在上课"需要结合课表数据判断（is_current_course）
    
    Args:
        building: 楼栋名称，用于选择对应的时间表
        
    Returns:
        dict: {
            'current_period': int,  # 当前节次（1-12），0表示还没开始，13表示已结束
            'is_ongoing': bool,     # 当前时间是否在某个节次的时间范围内
            'is_class_time': bool,  # 当前是否是上课时间段
            'current_week_day': int, # 今天星期几（1-7）
        }
    """
    from datetime import datetime
    
    now = datetime.now()
    current_time = now.hour * 60 + now.minute
    current_week_day = now.isoweekday()  # 1=周一, 7=周日
    
    # 根据楼栋选择时间表
    schedule = get_schedule_by_building(building)
    
    # 检查当前在哪一节
    for period in range(1, 13):
        start_str, end_str = schedule.get(period, ('', ''))
        if not start_str or not end_str:
            continue
        
        # 解析时间
        try:
            start_h, start_m = map(int, start_str.split(':'))
            end_h, end_m = map(int, end_str.split(':'))
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            
            # 如果当前时间在该节次范围内
            if start_minutes <= current_time <= end_minutes:
                return {
                    'current_period': period,
                    'is_ongoing': True,
                    'is_class_time': True,
                    'current_week_day': current_week_day,
                }
        except (ValueError, IndexError):
            continue
    
    # 检查当前时间在哪个节次之间（用于确定应该显示哪个节次）
    for period in range(1, 13):
        start_str, end_str = schedule.get(period, ('', ''))
        if not start_str:
            continue
        
        try:
            start_h, start_m = map(int, start_str.split(':'))
            start_minutes = start_h * 60 + start_m
            
            # 如果当前时间在第一节之前
            if period == 1 and current_time < start_minutes:
                return {
                    'current_period': 0,
                    'is_ongoing': False,
                    'is_class_time': False,
                    'current_week_day': current_week_day,
                }
            
            # 如果当前时间在某个节次之前
            if current_time < start_minutes:
                # 返回上一节作为当前节次（表示处于两节之间或之前）
                return {
                    'current_period': period - 1,
                    'is_ongoing': False,
                    'is_class_time': False,
                    'current_week_day': current_week_day,
                }
        except (ValueError, IndexError):
            continue
    
    # 所有节次都结束了
    return {
        'current_period': 13,
        'is_ongoing': False,
        'is_class_time': False,
        'current_week_day': current_week_day,
    }


@course_bp.route('/timetable', methods=['GET'])
@jwt_required
def get_timetable():
    """
    获取图形化课程表数据
    
    直接返回课程列表，前端根据 periods 字段自行渲染表格
    支持按周次筛选，自动判断当前周
    后端计算当前上课状态，前端只负责展示
    """
    from datetime import date
    from sqlalchemy import distinct
    from app.model.course_week import CourseWeek
    
    week_number = request.args.get('week_number', type=int)
    semester_id = request.args.get('semester_id', type=int)

    session = get_db()
    try:
        # 获取所有周次信息（含日期范围）
        weeks_info = session.query(CourseWeek).order_by(CourseWeek.week_number).all()
        available_weeks = [w.to_dict() for w in weeks_info]

        # 学期过滤：未显式指定时默认取当前学期（保证与历史行为一致）
        if semester_id is None:
            semester_id = _get_current_semester_id()

        # 当前学期判断：用于决定默认周次 / 是否展示"正在上课"
        current_semester_id = _get_current_semester_id()
        is_current_semester = (
            semester_id is not None
            and current_semester_id is not None
            and semester_id == current_semester_id
        )

        # 如果没有指定周次，自动计算默认周
        if week_number is None:
            if is_current_semester:
                # 本学期：使用真实当前周
                week_number = get_current_week_number()
            else:
                # 非本学期：定位第一个有课的周（1..25），找不到则回退到第 1 周
                week_courses = session.query(Course).filter(
                    Course.is_deleted == False,
                    Course.semester_id == semester_id
                ).all()
                first_week = None
                for w in range(1, 26):
                    if any(is_course_in_week(c.weeks or '', w) for c in week_courses):
                        first_week = w
                        break
                week_number = first_week if first_week is not None else 1

        # 查询所有课程（排除已删除的，不按 week_number 过滤，因为 week_number 只是数据导入时的标记）
        # 按 weeks 字段过滤：只返回在当前周次有课的课程
        query = session.query(Course).filter(Course.is_deleted == False)
        if semester_id is not None:
            query = query.filter(Course.semester_id == semester_id)
        courses = query.order_by(Course.week_day, Course.period_idx).all()
        if week_number:
            courses = [c for c in courses if is_course_in_week(c.weeks or '', week_number)]
        
        from datetime import datetime
        
        # 计算当前时间
        now = datetime.now()
        current_time = now.hour * 60 + now.minute
        current_week_day = now.isoweekday()
        
        # 计算当前上课状态（使用默认时间表，因为可能有多个楼栋的课程）
        current_status = get_current_period_and_status()
        
        # 标记正在上课的课程
        courses_with_status = []
        has_current_course = False
        
        for c in courses:
            course_dict = c.to_dict()
            is_current_course = False

            # 仅本学期才计算"正在上课"实时状态；查看历史学期时不展示该高亮
            if is_current_semester and c.week_day == current_week_day:
                # 根据课程所在的楼栋选择时间表
                building = course_dict.get('building', '')
                schedule = get_schedule_by_building(building)
                
                # 解析课程的节次（支持 JSON 列表格式和旧字符串格式）
                periods_data = c.periods or []
                if isinstance(periods_data, list):
                    course_periods = [int(p) for p in periods_data if isinstance(p, (int, str)) and str(p).strip().isdigit()]
                elif isinstance(periods_data, str):
                    course_periods = [int(p) for p in periods_data.split(',') if p.strip().isdigit()]
                else:
                    course_periods = [c.period_idx]
                
                # 精确检查：当前时间是否在课程的某个节次的时间范围内
                for period in course_periods:
                    if period < 1 or period > 12:
                        continue
                    start_str, end_str = schedule.get(period, ('', ''))
                    if not start_str or not end_str:
                        continue
                    
                    try:
                        start_h, start_m = map(int, start_str.split(':'))
                        end_h, end_m = map(int, end_str.split(':'))
                        start_min = start_h * 60 + start_m
                        end_min = end_h * 60 + end_m
                        
                        # 精确判断：当前时间必须在该节次的时间范围内
                        if start_min <= current_time <= end_min:
                            is_current_course = True
                            has_current_course = True
                            break
                    except (ValueError, IndexError):
                        continue
            
            course_dict['is_current_course'] = is_current_course
            courses_with_status.append(course_dict)
        
        # 更新 current_status，确保和我们新计算的一致
        current_status['has_current_course'] = has_current_course
        current_status['current_week_day'] = current_week_day
        
        return api_success(data={'courses': courses_with_status, 'periods': PERIOD_TIME_MAP, 'week_number': week_number, 'available_weeks': available_weeks, 'current_status': current_status})
    finally:
        session.close()


@course_bp.route('', methods=['POST'])
@admin_required
def create_or_update_course():
    """创建或更新课程"""
    data = request.get_json()
    if not data:
        return api_error(message='请求数据为空', http_status=400)
    
    required_fields = ['course_name', 'week_day', 'period_idx']
    for field in required_fields:
        if field not in data:
            return api_error(message=f'缺少必填字段: {field}', http_status=400)
    
    session = get_db()
    try:
        # 解析节次：支持单个数字、逗号分隔字符串、数组
        period_input = data['period_idx']
        if isinstance(period_input, str):
            # 逗号分隔的字符串，如 "1,2"
            periods = [int(p.strip()) for p in period_input.split(',') if p.strip().isdigit()]
        elif isinstance(period_input, list):
            periods = [int(p) for p in period_input]
        else:
            periods = [int(period_input)]
        
        # 获取起始和结束节次
        start_period = min(periods)
        end_period = max(periods)
        
        # 获取起始和结束时间
        start_time = data.get('start_time', '')
        end_time = data.get('end_time', '')
        
        # 根据楼栋选择时间表
        building = data.get('building', '')
        schedule = get_schedule_by_building(building)
        
        # 如果前端没传时间，从对应时间表获取
        if not start_time:
            default_start, _ = schedule.get(start_period, ('', ''))
            start_time = default_start
        if not end_time:
            _, default_end = schedule.get(end_period, ('', ''))
            end_time = default_end
        
        # periods 字段：逗号分隔的节次列表（用于日志）
        periods_str = ','.join(str(p) for p in periods)
        
        # periods 和 weeks 需要转换为列表格式（兼容前端传入的字符串）
        periods_list = periods
        
        weeks_raw = data.get('weeks', '')
        weeks_list = []
        if isinstance(weeks_raw, list):
            weeks_list = weeks_raw
        elif isinstance(weeks_raw, str):
            if weeks_raw.strip():
                weeks_list = [int(x.strip()) for x in weeks_raw.split(',') if x.strip().isdigit()]
        
        # 获取推送状态，默认开启
        push_enabled = data.get('push_enabled', True)
        
        # 判断是否是编辑模式
        is_edit = data.get('is_edit', False)
        old_course_id = data.get('old_course_id')
        
        if is_edit and old_course_id:
            # 编辑模式：先找到原课程，获取其原始的课程名、教室、星期等信息
            old_course = session.query(Course).filter(Course.id == old_course_id).first()
            if not old_course:
                return api_error(message='原课程不存在', http_status=404)
            
            # 找到所有属于同一课程组的记录（同一天、同一课程名、同一教室）
            old_courses = session.query(Course).filter(
                Course.week_day == old_course.week_day,
                Course.course_name == old_course.course_name,
                Course.classroom == old_course.classroom,
                Course.week_number == old_course.week_number
            ).all()
            
            old_ids = [c.id for c in old_courses]
            old_periods = set(c.period_idx for c in old_courses)
            new_periods = set(periods)
            
            # 计算需要删除、保留和新增的节次
            to_delete = old_periods - new_periods
            to_keep = old_periods & new_periods
            to_add = new_periods - old_periods
            
            # 删除不需要的节次
            for c in old_courses:
                if c.period_idx in to_delete:
                    session.delete(c)
            
            # 更新保留的节次
            updated_courses = []
            for c in old_courses:
                if c.period_idx in to_keep:
                    c.course_name = data['course_name']
                    c.teacher = data.get('teacher', '')
                    c.classroom = data.get('classroom', '')
                    c.building = building
                    c.week_day = data['week_day']
                    c.periods = periods_list
                    c.start_time = start_time
                    c.end_time = end_time
                    c.weeks = weeks_list
                    c.week_number = data.get('week_number')
                    c.push_enabled = push_enabled
                    c.data_source = 'admin'  # v6.11.2：后台编辑标记为手动课，爬虫不覆盖
                    c.updated_at = datetime.utcnow()
                    updated_courses.append(c)
            
            # 新增需要的节次
            added_courses = []
            for p in to_add:
                course = Course(
                    course_name=data['course_name'],
                    teacher=data.get('teacher', ''),
                    classroom=data.get('classroom', ''),
                    building=building,
                    week_day=data['week_day'],
                    period_idx=p,
                    periods=periods_list,
                    start_time=start_time,
                    end_time=end_time,
                    weeks=weeks_list,
                    week_number=data.get('week_number'),
                    push_enabled=push_enabled,
                    data_source='admin',  # v6.11.2：后台新增节次标记为手动课
                semester_id=old_course.semester_id,
                semester_name=old_course.semester_name,
                academic_year=old_course.academic_year,
                term=old_course.term,
                )
                session.add(course)
                added_courses.append(course)
            
            session.commit()
            
            all_courses = updated_courses + added_courses
            logger.info(f'[课程] 更新课程: {data["course_name"]} (更新{len(updated_courses)}条, 新增{len(added_courses)}条, 删除{len(to_delete)}条, 推送: {push_enabled and "开启" or "关闭"})')
            return api_success(message='课程更新成功', data=[c.to_dict() for c in all_courses])
        else:
            # 创建模式：为每个节次创建一条记录
            created_courses = []
        
        # 处理 periods 和 weeks 为列表格式
        periods_list = periods
        weeks_list = data.get('weeks', '')
        if isinstance(weeks_list, str):
            if weeks_list.strip():
                weeks_list = [int(x.strip()) for x in weeks_list.split(',') if x.strip().isdigit()]
            else:
                weeks_list = []
        
        # 学期归属：优先使用前端传入的当前查看学期，其次回退到 course_meta 当前学期，
        # 最后按今天日期推导。避免手动建课与爬取课程学期错配导致"自建课程看不见"。
        req_semester_id = data.get('semester_id')
        _sem = None
        if req_semester_id:
            try:
                _sem = semester_info_from_id(int(req_semester_id))
            except (ValueError, TypeError):
                _sem = None
        if _sem is None:
            _cid = _get_current_semester_id()
            if _cid is not None:
                _sem = semester_info_from_id(_cid)
        if _sem is None:
            _sem = derive_current_semester()

        for p in periods:
            course = Course(
                course_code=data.get('course_code') or generate_course_code({
                    'course_name': data['course_name'],
                    'week_day': data['week_day'],
                    'period_idx': p,
                    'classroom': data.get('classroom', ''),
                }),
                course_name=data['course_name'],
                teacher=data.get('teacher', ''),
                classroom=data.get('classroom', ''),
                building=building,
                week_day=data['week_day'],
                period_idx=p,
                periods=periods_list,
                start_time=start_time,
                end_time=end_time,
                weeks=weeks_list,
                week_number=data.get('week_number'),
                push_enabled=push_enabled,
                data_source='admin',  # v6.11.2：后台自建课程标记为手动课，爬虫不覆盖
                semester_id=_sem['semester_id'],
                semester_name=_sem['semester_name'],
                academic_year=_sem['academic_year'],
                term=_sem['term'],
            )
            session.add(course)
            created_courses.append(course)

        session.commit()

        logger.info(f'[课程] 创建课程: {data["course_name"]} (节次: {periods_str}, 共{len(created_courses)}条)')
        return api_success(message=f'成功创建 {len(created_courses)} 条课程记录', data=[c.to_dict() for c in created_courses])
    finally:
        session.close()


@course_bp.route('/<int:course_id>', methods=['PUT'])
@admin_required
def update_course(course_id: int):
    """更新课程"""
    data = request.get_json()
    if not data:
        return api_error(message='请求数据为空', http_status=400)
    
    session = get_db()
    try:
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return api_error(message='课程不存在', http_status=404)
        
        # 更新字段
        if 'course_name' in data:
            course.course_name = data['course_name']
        if 'teacher' in data:
            course.teacher = data['teacher']
        if 'classroom' in data:
            course.classroom = data['classroom']
        if 'building' in data:
            course.building = data['building']
        if 'week_day' in data:
            course.week_day = data['week_day']
        if 'period_idx' in data:
            # 兼容前端传入的逗号分隔字符串（如 "1,2"）或数组：取首个节次作为本行 period_idx
            period_input = data['period_idx']
            if isinstance(period_input, str) and ',' in period_input:
                _pl = [int(p.strip()) for p in period_input.split(',') if p.strip().isdigit()]
                first_period = _pl[0] if _pl else course.period_idx
            elif isinstance(period_input, list):
                first_period = int(period_input[0]) if period_input else course.period_idx
            else:
                first_period = int(period_input)
            course.period_idx = first_period
            # 更新时间
            start_time, end_time = PERIOD_TIME_MAP.get(first_period, ('', ''))
            course.start_time = start_time
            course.end_time = end_time
        if 'start_time' in data:
            course.start_time = data['start_time']
        if 'end_time' in data:
            course.end_time = data['end_time']
        if 'periods' in data:
            periods_raw = data['periods']
            if isinstance(periods_raw, list):
                course.periods = periods_raw
            elif isinstance(periods_raw, str):
                if periods_raw.strip():
                    course.periods = [int(x.strip()) for x in periods_raw.split(',') if x.strip().isdigit()]
                else:
                    course.periods = []
        if 'weeks' in data:
            weeks_raw = data['weeks']
            if isinstance(weeks_raw, list):
                course.weeks = weeks_raw
            elif isinstance(weeks_raw, str):
                if weeks_raw.strip():
                    course.weeks = [int(x.strip()) for x in weeks_raw.split(',') if x.strip().isdigit()]
                else:
                    course.weeks = []
        if 'week_number' in data:
            course.week_number = data['week_number']
        
        # v6.11.2：后台编辑标记为手动课，使爬虫后续不再覆盖本次人工修正
        course.data_source = 'admin'
        course.updated_at = datetime.utcnow()
        session.commit()
        
        logger.info(f'[课程] 更新课程: {course.course_name}')
        return api_success(message='课程更新成功', data=course.to_dict())
    finally:
        session.close()


@course_bp.route('/<int:course_id>', methods=['DELETE'])
@admin_required
def delete_course(course_id: int):
    """硬删除课程（从数据库中完全删除）"""
    
    session = get_db()
    try:
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return api_error(message='课程不存在', http_status=404)
        
        course_name = course.course_name
        session.delete(course)
        session.commit()
        
        logger.info(f'[课程] 硬删除课程: {course_name}')
        return api_success(message='课程已删除')
    finally:
        session.close()


@course_bp.route('/<int:course_id>/toggle-push', methods=['POST'])
@admin_required
def toggle_push(course_id: int):
    """切换课程推送状态（开启/关闭推送提醒）"""
    data = request.get_json(silent=True) or {}
    push_enabled = data.get('push_enabled', True)
    
    session = get_db()
    try:
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return api_error(message='课程不存在', http_status=404)
        
        course.push_enabled = push_enabled
        session.commit()
        
        status = '开启' if push_enabled else '关闭'
        logger.info(f'[课程] {status}推送提醒: {course.course_name}')
        return api_success(message=f'已{status}推送提醒')
    finally:
        session.close()


@course_bp.route('/import', methods=['POST'])
@admin_required
def import_courses():
    """
    从爬虫数据导入课程
    
    从 cqie-course-timetable 模块的 JSON 文件导入课程
    """
    import os
    import json
    
    from app.repository.course_repository import CourseRepository
    
    data_file = request.json.get('file_path') if request.json else None
    if not data_file:
        # 默认使用最新处理后的数据
        data_file = os.path.join(
            os.path.dirname(__file__), '..', 'cqie-course-timetable',
            'output', 'course-data', 'processed', 'processed_course_table.json'
        )
    
    if not os.path.exists(data_file):
        return api_error(message='课程数据文件不存在', http_status=404)
    
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        courses_data = data.get('courses', [])
        week_number = data.get('week_number', 1)

        # 学期归属：与爬取管道保持一致，优先使用 course_meta 的当前学期，
        # 避免手动"导入"按钮创建的课程学期错配导致不显示
        _sem_id = _get_current_semester_id()
        _sem = semester_info_from_id(_sem_id) if _sem_id else derive_current_semester()
        
        # 星期映射
        week_day_map = {
            '星期一': 1, '星期二': 2, '星期三': 3, '星期四': 4,
            '星期五': 5, '星期六': 6, '星期日': 7, '星期天': 7,
        }
        
        # 转换数据格式
        transformed_data = []
        for course_data in courses_data:
            week_day_str = course_data.get('week_day', '')
            week_day = week_day_map.get(week_day_str, 1)
            
            # 解析 period_name 获取所有节次（如 "第一、二节" -> [1, 2]）
            period_name = course_data.get('period_name', '')
            periods: list = []
            period_idx = course_data.get('period_idx', 1)
            
            # 中文数字到阿拉伯数字的映射
            cn_num_map = {
                '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            }
            
            def parse_cn_num(cn_str: str) -> int:
                """解析中文数字"""
                if cn_str in cn_num_map:
                    return cn_num_map[cn_str]
                try:
                    return int(cn_str)
                except ValueError:
                    return 0
            
            if period_name:
                # 匹配 "第一、二节" 格式（支持中文数字）
                match = re.match(r'第([一二三四五六七八九十\d]+)、([一二三四五六七八九十\d]+)节', period_name)
                if match:
                    first = parse_cn_num(match.group(1))
                    second = parse_cn_num(match.group(2))
                    if first > 0 and second > 0 and first <= second:
                        periods = list(range(first, second + 1))
                        period_idx = first
                else:
                    # 匹配 "第一节" 格式（支持中文数字）
                    single_match = re.match(r'第([一二三四五六七八九十\d]+)节', period_name)
                    if single_match:
                        period_idx = parse_cn_num(single_match.group(1))
                        if period_idx > 0:
                            periods = [period_idx]
            
            # 如果解析失败，使用 period_idx（爬虫返回的是结束节次，需要推断起始节次）
            if not periods and period_idx > 0:
                # 根据结束时间推断课程时长（通常是2节连堂）
                start_time = course_data.get('start_time', '')
                end_time = course_data.get('end_time', '')
                if start_time and end_time:
                    # 尝试从时间段判断节数
                    hour_diff = int(end_time.split(':')[0]) - int(start_time.split(':')[0])
                    if hour_diff >= 2:
                        # 2小时以上通常是2节课
                        periods = [period_idx - 1, period_idx]
                    else:
                        periods = [period_idx]
            
            # weeks 保持原始字符串（如 "2-5 7 9 11-18"），交给仓库层统一规范化
            weeks_str = course_data.get('weeks', '')

            transformed_data.append({
                'course_code': course_data.get('course_code'),
                'course_name': course_data.get('course_name', ''),
                'teacher': course_data.get('teacher', ''),
                'classroom': course_data.get('classroom', ''),
                'building': course_data.get('building', ''),
                'week_day': week_day,
                'period_idx': period_idx,
                'periods': periods,
                'start_time': course_data.get('start_time', ''),
                'end_time': course_data.get('end_time', ''),
                'weeks': weeks_str,
                'week_number': week_number,
                'semester_id': _sem['semester_id'],
                'semester_name': _sem['semester_name'],
                'academic_year': _sem['academic_year'],
                'term': _sem['term'],
            })
        
        session = get_db()
        try:
            created_count, updated_count = CourseRepository.create_batch(session, transformed_data)
            session.commit()

            logger.info(f'[课程] 导入 {created_count} 门（新增 {created_count} / 更新 {updated_count}）')
            return api_success(
                message=f'成功导入 {created_count} 门课程（新增 {created_count} / 更新 {updated_count}）',
                data={'imported_count': created_count, 'created_count': created_count, 'updated_count': updated_count},
            )
        finally:
            session.close()
    except Exception as e:
        logger.error(f'[课程] 导入失败: {e}')
        return api_error(message=f'导入失败: {e}', http_status=500)


# ============================================================
# 学期和周次管理 API
# ============================================================

def _semester_name_to_id(name: str):
    """将学期名称（如 '2025-2026-2'）转换为 DB 使用的 semester_id（20252）。

    规则：取起始年份 * 10 + 学期序号。'2025-2026-2' -> 2025*10+2 = 20252。
    返回 None 表示无法解析。
    """
    try:
        parts = name.split('-')
        year = int(parts[0])
        term = int(parts[-1])
        return year * 10 + term
    except (ValueError, IndexError, AttributeError):
        return None


def _get_current_semester_id():
    """读取 course_meta.json 的当前学期名称，转换为 DB 格式 semester_id。

    若 course_meta.json 缺失（首次部署、爬虫尚未成功运行），回退到按当前
    日期推导的学期，避免上层过滤拿到 None 而显示空白课表。
    """
    import json as _json
    import os as _os
    meta_path = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        '..', 'cqie-course-timetable', 'output', 'course-data', 'raw', 'course_meta.json'
    )
    if not _os.path.exists(meta_path):
        return derive_current_semester()['semester_id']
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = _json.load(f)
        name = meta.get('current_semester_name')
        if name:
            return _semester_name_to_id(name)
    except Exception:
        return derive_current_semester()['semester_id']
    return derive_current_semester()['semester_id']


@course_bp.route('/semesters', methods=['GET'])
@jwt_required
def get_semesters():
    """
    获取可选学期列表
    
    从爬虫保存的 course_meta.json 中读取学期列表
    如果文件不存在或读取失败，返回空列表
    """
    try:
        import json
        import os
        
        # 读取 course_meta.json
        meta_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'cqie-course-timetable', 'output', 'course-data', 'raw', 'course_meta.json'
        )
        
        if not os.path.exists(meta_path):
            # course_meta.json 缺失（首次部署/爬虫未成功）：用日期推导当前学期兜底，
            # 保证前端学期下拉至少有"本学期"可选，不至于完全空白。
            inferred = derive_current_semester()
            db_id = inferred['semester_id']
            return api_success(data={'semesters': [{'id': db_id, 'eams_id': str(db_id)[-3:], 'name': inferred['semester_name'], 'is_current': True}], 'current_semester_id': db_id, 'current_semester_name': inferred['semester_name'], 'weeks': list(range(1, 21)), 'message': '学期信息由系统按当前日期推断（爬虫尚未成功运行，course_meta.json 缺失）'}, http_status=200)
        
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        
        # 只保留最近6个学期
        all_semesters = meta.get('semesters', [])
        semesters_raw = all_semesters[:6] if len(all_semesters) > 6 else all_semesters

        # 转换为前端需要的结构：id 使用 DB 格式（YYYYT），并附带 eams_id 供爬虫使用
        current_semester_id = meta.get('current_semester_id')
        current_semester_name = meta.get('current_semester_name')
        weeks = meta.get('weeks', [])

        semesters = []
        for s in semesters_raw:
            s_name = s.get('name', '')
            s_eams_id = s.get('id')
            s_db_id = _semester_name_to_id(s_name)
            semesters.append({
                'id': s_db_id,
                'eams_id': s_eams_id,
                'name': s_name,
                'is_current': str(s_eams_id) == str(current_semester_id),
            })

        return api_success(data={'semesters': semesters, 'current_semester_id': _semester_name_to_id(current_semester_name), 'current_semester_name': current_semester_name, 'weeks': weeks}, http_status=200)
    except Exception as e:
        logger.error(f'[课程] 获取学期列表失败: {e}')
        return api_error(message=f'获取学期列表失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks', methods=['POST'])
@admin_required
def create_crawl_task():
    """
    创建课程爬取预约任务

    请求体：
    {
        "scope": "semester" | "all",          # 爬取范围：指定学期 / 全量
        "semester_id": 20251,                  # scope=semester 时必填（DB 格式）
        "eams_id": "251",                      # 可选，缺省按 semester_id 反查
        "schedule_type": "immediate" | "scheduled",
        "scheduled_at": "2026-07-08T10:00:00", # schedule_type=scheduled 时必填
        "week": 1,                             # 可选指定周次
        "name": "可选任务名"
    }

    返回创建后的任务信息；若 schedule_type=immediate，会立即在后台线程启动爬取。
    """
    try:
        data = request.get_json() or {}
        created_by = getattr(g, 'user', None)
        created_by = created_by.username if created_by else 'system'

        task_dict = crawl_svc.create_crawl_task(data, created_by=created_by)

        # 立即执行：直接起后台线程（响应更快），调度器仍作为兜底
        if task_dict['schedule_type'] == 'immediate':
            import threading
            thread = threading.Thread(
                target=crawl_svc._run_scheduled_crawl,
                args=(task_dict['id'],),
                daemon=True
            )
            thread.start()
            logger.info(f'[课程] 立即爬取任务已创建并启动: id={task_dict["id"]}')

        return api_success(message='爬取任务已创建', data=task_dict, http_status=201)
    except ValueError as e:
        return api_error(message=str(e), http_status=400)
    except Exception as e:
        logger.error(f'[课程] 创建爬取任务失败: {e}')
        return api_error(message=f'创建爬取任务失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks', methods=['GET'])
@jwt_required
def list_crawl_tasks():
    """获取爬取预约任务列表（供进程管理模块展示与增删改查）"""
    try:
        session = get_db()
        try:
            status = request.args.get('status', '')
            scope = request.args.get('scope', '')
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)

            query = session.query(ScheduledCrawlTask)
            if status:
                query = query.filter(ScheduledCrawlTask.status == status)
            if scope:
                query = query.filter(ScheduledCrawlTask.scope == scope)

            total = query.count()
            tasks = query.order_by(ScheduledCrawlTask.created_at.desc()) \
                .offset((page - 1) * per_page).limit(per_page).all()

            return api_success(data=[t.to_dict() for t in tasks], pagination={'total': total, 'page': page, 'per_page': per_page, 'pages': (total + per_page - 1) // per_page})
        finally:
            session.close()
    except Exception as e:
        logger.error(f'[课程] 获取爬取任务列表失败: {e}')
        return api_error(message=f'获取爬取任务列表失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks/<int:task_id>', methods=['GET'])
@jwt_required
def get_crawl_task(task_id):
    """获取单个爬取预约任务详情"""
    try:
        session = get_db()
        try:
            task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
            if not task:
                return api_error(message='任务不存在', http_status=404)
            return api_success(data=task.to_dict(), http_status=200)
        finally:
            session.close()
    except Exception as e:
        logger.error(f'[课程] 获取爬取任务详情失败: {e}')
        return api_error(message=f'获取爬取任务详情失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks/<int:task_id>', methods=['PUT'])
@admin_required
def update_crawl_task(task_id):
    """更新爬取预约任务（仅 pending 状态可改：范围/学期/预约时间）"""
    try:
        data = request.get_json() or {}
        session = get_db()
        try:
            task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
            if not task:
                return api_error(message='任务不存在', http_status=404)
            if task.status != 'pending':
                return api_error(message='仅待执行（pending）任务可编辑', http_status=400)

            if 'scope' in data:
                scope = data['scope']
                if scope not in ('semester', 'all'):
                    return api_error(message='scope 必须为 semester 或 all', http_status=400)
                task.scope = scope
                if scope == 'all':
                    task.semester_id = None
                    task.eams_id = None
            if 'semester_id' in data and task.scope == 'semester':
                task.semester_id = int(data['semester_id'])
                task.eams_id = data.get('eams_id') or crawl_svc._resolve_eams_id(task.semester_id)
            if 'week' in data:
                task.week = int(data['week']) if data['week'] else None
            if 'schedule_type' in data:
                task.schedule_type = data['schedule_type']
            if 'scheduled_at' in data:
                sa = data['scheduled_at']
                if sa:
                    dt = datetime.fromisoformat(sa.replace('Z', '+00:00'))
                    task.scheduled_at = dt.replace(tzinfo=None) if dt.tzinfo else dt
                else:
                    task.scheduled_at = None
            if 'name' in data:
                task.name = data['name']

            session.commit()
            return api_success(message='任务已更新', data=task.to_dict(), http_status=200)
        finally:
            session.close()
    except Exception as e:
        logger.error(f'[课程] 更新爬取任务失败: {e}')
        return api_error(message=f'更新爬取任务失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks/<int:task_id>', methods=['DELETE'])
@admin_required
def delete_crawl_task(task_id):
    """删除爬取预约任务（running 状态会先取消）"""
    try:
        session = get_db()
        try:
            task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
            if not task:
                return api_error(message='任务不存在', http_status=404)
            if task.status == 'running':
                task.status = 'cancelled'
                task.completed_at = datetime.now()
                task.message = '删除时取消'
                session.commit()
                return api_success(message='任务正在执行，已标记为取消', http_status=200)
            session.delete(task)
            session.commit()
            return api_success(message='任务已删除', http_status=200)
        finally:
            session.close()
    except Exception as e:
        logger.error(f'[课程] 删除爬取任务失败: {e}')
        return api_error(message=f'删除爬取任务失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks/<int:task_id>/cancel', methods=['POST'])
@admin_required
def cancel_crawl_task(task_id):
    """取消爬取预约任务（pending/running -> cancelled）"""
    try:
        session = get_db()
        try:
            task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
            if not task:
                return api_error(message='任务不存在', http_status=404)
            if task.status in ('completed', 'failed', 'cancelled'):
                return api_error(message=f'任务已处于 {task.status} 状态，无法取消', http_status=400)
            task.status = 'cancelled'
            task.completed_at = datetime.now()
            task.message = '用户取消'
            session.commit()
            return api_success(message='任务已取消', http_status=200)
        finally:
            session.close()
    except Exception as e:
        logger.error(f'[课程] 取消爬取任务失败: {e}')
        return api_error(message=f'取消爬取任务失败: {e}', http_status=500)


@course_bp.route('/crawl-tasks/<int:task_id>/run', methods=['POST'])
@admin_required
def run_crawl_task_now(task_id):
    """立即执行一个 pending 的预约任务（忽略预约时间）"""
    try:
        session = get_db()
        try:
            task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
            if not task:
                return api_error(message='任务不存在', http_status=404)
            if task.status != 'pending':
                return api_error(message=f'任务状态为 {task.status}，无法立即执行', http_status=400)
        finally:
            session.close()

        import threading
        thread = threading.Thread(
            target=crawl_svc._run_scheduled_crawl,
            args=(task_id,),
            daemon=True
        )
        thread.start()
        return api_success(message='任务已立即启动', http_status=200)
    except Exception as e:
        logger.error(f'[课程] 立即执行爬取任务失败: {e}')
        return api_error(message=f'立即执行失败: {e}', http_status=500)
