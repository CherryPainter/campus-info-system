#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程数据仓库层

负责课程表的数据库操作，遵循 Repository 模式
"""

import re
import json
import hashlib
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.model.course import Course
from app.model.course_week import CourseWeek


# ----------------------------------------------------------------------
# 课程导入时的字段补全/规范化辅助函数
# 课程表爬虫无法稳定获取教务系统内部的学期ID与课程代码，因此这里提供
# 1) 根据当前日期推导当前学期信息
# 2) 在没有真实课程代码时生成稳定的兜底代码
# 3) 将各种格式的周次/节次字符串规范化为列表，确保 JSON 列存储正确
# ----------------------------------------------------------------------

def derive_current_semester() -> Dict[str, Any]:
    """
    根据当前日期推导"当前学期"信息。

    中国高校校历（学年第一学期=秋季，第二学期=春季）：
      - 秋季学期（9月~次年1月）属于学年 {Y}-{Y+1}，term=1（第一学期）
      - 春季学期（2月~7月）属于学年 {Y-1}-{Y}，term=2（第二学期）

    semester_id 作为应用内部标识，由「起始年 + 学期」推导为稳定整数，
    例如 2025-2026 秋季 -> 20251，春季（第二学期）-> 20252。

    Returns:
        dict: {semester_id, semester_name, academic_year, term}
    """
    today = date.today()
    y, m = today.year, today.month
    if 9 <= m <= 12:
        # 秋季学期（第一学期），属学年 Y-(Y+1)
        start, term = y, 1
    elif 1 <= m <= 2:
        # 仍属上一学年秋季学期（第一学期）
        start, term = y - 1, 1
    else:  # 3 ~ 8 月为春季学期（第二学期）
        start, term = y - 1, 2
    academic_year = f"{start}-{start + 1}"
    return {
        'semester_id': int(f"{start}{term}"),
        'semester_name': f"{academic_year}-{term}",
        'academic_year': academic_year,
        'term': term,
    }


def semester_info_from_id(semester_id: int) -> Dict[str, Any]:
    """
    根据 DB 格式学期 ID（如 20251）推导学期元信息。

    与 derive_current_semester 的区别：后者按「今天」推导当前学期，
    本函数按给定的 semester_id 推导任意学期，用于历史/指定学期入库时
    补全 semester_name / academic_year / term。

    Args:
        semester_id: DB 格式学期 ID，如 20251（2025-2026 学年第 1 学期）

    Returns:
        dict: {semester_id, semester_name, academic_year, term}
    """
    s = str(semester_id)
    term = int(s[-1])
    start = int(s[:-1])
    academic_year = f"{start}-{start + 1}"
    return {
        'semester_id': semester_id,
        'semester_name': f"{academic_year}-{term}",
        'academic_year': academic_year,
        'term': term,
    }



def generate_course_code(data: Dict[str, Any]) -> str:
    """
    在没有真实课程代码时，生成稳定的兜底课程代码。
    同一门课（课程名 + 星期 + 节次列表 + 教室 + 周次）在不同爬取中应得到相同代码，
    以便去重逻辑稳定工作。

    关键：必须使用 hashlib（稳定哈希）。严禁使用内置 hash()——
    内置 hash() 受 PYTHONHASHSEED 影响，每次进程启动都会变化，
    会导致同一门课的兜底代码每次爬取都不同，去重失效、重复数据累积。

    Args:
        data: 课程数据字典（建议含 course_name / week_day / periods 或 period_idx / classroom / week_number）

    Returns:
        str: 形如 "CRAWL-01234" 的代码
    """
    name = data.get('course_name') or 'UNKNOWN'
    wd = data.get('week_day', 0)
    # 优先用节次列表（更精准），回退到单个 period_idx
    periods = data.get('periods')
    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            periods = None
    if isinstance(periods, list) and periods:
        per = ','.join(str(p) for p in periods)
    else:
        per = str(data.get('period_idx', 0))
    room = data.get('classroom') or ''
    wn = data.get('week_number') or ''
    raw = f"{name}|{wd}|{per}|{room}|{wn}"
    h = int(hashlib.md5(raw.encode('utf-8')).hexdigest(), 16) % 100000
    return f"CRAWL-{h:05d}"


def normalize_weeks(weeks) -> List[int]:
    """
    将各种格式的周次描述规范化为升序去重的周次整数列表。

    支持：
      - list: [2, 3, 4] / [ "[2,3]" ]（嵌套字符串也会解析）
      - int: 14 -> [14]
      - str: "2-5 7 9 11-18" / "1,3,5" / "[1,2]" / ""（空 -> []）
      - 单双周标记：含"单"/"双"的区间会按奇偶筛选

    Args:
        weeks: 周次原始值

    Returns:
        List[int]: 周次数字列表（可能为空）
    """
    if weeks is None:
        return []
    if isinstance(weeks, bool):
        return []
    if isinstance(weeks, int):
        return [weeks]
    if isinstance(weeks, list):
        out = []
        for x in weeks:
            if isinstance(x, int):
                out.append(x)
            elif isinstance(x, str):
                out.extend(normalize_weeks(x))
            else:
                try:
                    out.append(int(x))
                except (ValueError, TypeError):
                    pass
        return sorted(set(out))
    if isinstance(weeks, str):
        s = weeks.strip()
        if not s:
            return []
        # 先尝试 JSON 数组
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return normalize_weeks(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
        # 再按 空格/逗号 切分，逐段解析范围
        out = set()
        for part in re.split(r'[\s,，]+', s):
            part = part.strip()
            if not part:
                continue
            is_odd = '单' in part
            is_even = '双' in part
            clean = part.replace('单', '').replace('双', '').replace('周', '')
            if '-' in clean:
                try:
                    a, b = clean.split('-')
                    a, b = int(a.strip()), int(b.strip())
                    for w in range(a, b + 1):
                        if is_odd and w % 2 == 0:
                            continue
                        if is_even and w % 2 == 1:
                            continue
                        out.add(w)
                except (ValueError, IndexError):
                    pass
            else:
                try:
                    out.add(int(clean))
                except ValueError:
                    pass
        return sorted(out)
    return []


def normalize_periods(periods) -> List[int]:
    """将节次字段规范化为整数列表（与 normalize_weeks 同理，但无单双周）。"""
    return normalize_weeks(periods)


def weeks_to_bitmap(weeks: List[int], total: int = 25) -> Optional[str]:
    """
    将周次列表转换为位图字符串（长度 total，'1' 表示有课）。

    Args:
        weeks: 周次列表
        total: 位图长度（默认 25 周）

    Returns:
        str | None: 位图字符串或 None（无周次时）
    """
    if not weeks:
        return None
    bits = ['0'] * total
    for w in weeks:
        if 1 <= w <= total:
            bits[w - 1] = '1'
    return ''.join(bits)


class CourseRepository:
    """
    课程数据仓库
    
    职责：
    - 封装所有课程相关的数据库操作
    - 提供查询、创建、更新、删除方法
    - 不包含业务逻辑
    """
    
    @staticmethod
    def get_all(session: Session, week_number: Optional[int] = None) -> List[Course]:
        """
        获取所有未删除的课程
        
        Args:
            session: 数据库会话
            week_number: 可选，按周次筛选
            
        Returns:
            List[Course]: 课程列表
        """
        query = session.query(Course).filter(Course.is_deleted == False)
        if week_number is not None:
            query = query.filter(Course.week_number == week_number)
        return query.order_by(Course.week_day, Course.period_idx).all()
    
    @staticmethod
    def get_by_id(session: Session, course_id: int) -> Optional[Course]:
        """
        根据ID获取课程
        
        Args:
            session: 数据库会话
            course_id: 课程ID
            
        Returns:
            Optional[Course]: 课程对象或None
        """
        return session.query(Course).filter(Course.id == course_id).first()
    
    @staticmethod
    def get_by_week_day(
        session: Session, 
        week_day: int, 
        week_number: Optional[int] = None
    ) -> List[Course]:
        """
        获取指定星期的课程
        
        Args:
            session: 数据库会话
            week_day: 星期几 (1-7)
            week_number: 可选，周次
            
        Returns:
            List[Course]: 课程列表
        """
        query = session.query(Course).filter(Course.week_day == week_day)
        if week_number is not None:
            query = query.filter(Course.week_number == week_number)
        return query.order_by(Course.period_idx).all()
    
    @staticmethod
    def get_today_courses(session: Session, week_number: Optional[int] = None) -> List[Course]:
        """
        获取今天的课程
        
        Args:
            session: 数据库会话
            week_number: 可选，周次
            
        Returns:
            List[Course]: 今日课程列表
        """
        # 获取今天是星期几 (0=周一, 6=周日)
        today_week_day = date.today().weekday() + 1  # 转换为 1-7
        
        return CourseRepository.get_by_week_day(session, today_week_day, week_number)
    
    @staticmethod
    def create(
        session: Session,
        course_name: str,
        week_day: int,
        period_idx: int,
        teacher: Optional[str] = None,
        classroom: Optional[str] = None,
        building: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        weeks: Optional[str] = None,
        week_number: Optional[int] = None,
    ) -> Course:
        """
        创建课程
        
        Args:
            session: 数据库会话
            course_name: 课程名称
            week_day: 星期几 (1-7)
            period_idx: 节次索引 (1-12)
            teacher: 教师姓名
            classroom: 教室
            building: 教学楼
            start_time: 开始时间
            end_time: 结束时间
            weeks: 上课周次
            week_number: 当前周次
            
        Returns:
            Course: 创建的课程对象
        """
        sem = derive_current_semester()
        course = Course(
            course_code=generate_course_code({
                'course_name': course_name,
                'week_day': week_day,
                'period_idx': period_idx,
                'classroom': classroom or '',
            }),
            course_name=course_name,
            semester_id=sem['semester_id'],
            semester_name=sem['semester_name'],
            academic_year=sem['academic_year'],
            term=sem['term'],
            week_day=week_day,
            period_idx=period_idx,
            teacher=teacher,
            classroom=classroom,
            building=building,
            start_time=start_time or '',
            end_time=end_time or '',
            weeks=normalize_weeks(weeks),
            weeks_bitmap=weeks_to_bitmap(normalize_weeks(weeks)),
            week_number=week_number,
        )
        session.add(course)
        session.flush()
        return course
    
    @staticmethod
    def create_batch(session: Session, courses_data: List[Dict[str, Any]],
                      data_source: str = 'full') -> int:
        """
        批量创建课程（按课程代码去重，智能合并）

        去重策略：course_code + week_day + period_idx + week_number
        - 已存在 → 更新有变化的字段（教师/教室/楼栋/时间/周次/学期），并刷新来源/校验时间
        - 不存在 → 创建新记录，并补全所有 NOT NULL 字段
          （course_code / semester_id / semester_name / academic_year / term）

        爬虫通常不返回教务系统内部的课程代码与学期ID，因此：
          - 无 course_code 时调用 generate_course_code 生成稳定兜底代码
          - 无学期信息时调用 derive_current_semester 按当前日期推导

        Args:
            session: 数据库会话
            courses_data: 课程数据列表
            data_source: 数据来源标记（'full'=全量/指定学期爬虫, 'daily'=每日爬虫, 'admin'=手动）

        Returns:
            int: 实际创建的数量
        """
        created_count = 0
        sem = derive_current_semester()

        for data in courses_data:
            # 规范化学期、周次、节次
            weeks = normalize_weeks(data.get('weeks'))
            weeks_bitmap = weeks_to_bitmap(weeks)
            periods = normalize_periods(data.get('periods', ''))
            # 规范化 period_idx 为首节（periods[0]），避免源数据 period_idx 不一致
            # （如 [1,2] 课被标成 pidx=2）导致去重键错位、重复数据
            period_idx = periods[0] if periods else data.get('period_idx', 1)
            # 传入 periods 让兜底码基于节次列表生成，更精准且稳定
            course_code = data.get('course_code') or generate_course_code({
                'course_name': data.get('course_name'),
                'week_day': data.get('week_day'),
                'periods': periods,
                'classroom': data.get('classroom'),
                'week_number': data.get('week_number'),
            })

            # 按课程代码 + 星期 + 节次 + 周次标记去重
            existing = session.query(Course).filter(
                and_(
                    Course.course_code == course_code,
                    Course.week_day == data.get('week_day', 1),
                    Course.period_idx == period_idx,
                    Course.week_number == data.get('week_number'),
                    Course.is_deleted == False,
                )
            ).first()

            if existing:
                # 已存在：比对更新（只更新有变化的字段）
                if data.get('course_name') and data['course_name'] != existing.course_name:
                    existing.course_name = data['course_name']
                if data.get('teacher') and data['teacher'] != existing.teacher:
                    existing.teacher = data['teacher']
                if data.get('classroom') and data['classroom'] != existing.classroom:
                    existing.classroom = data['classroom']
                if data.get('building') and data['building'] != existing.building:
                    existing.building = data['building']
                if data.get('start_time') and data['start_time'] != existing.start_time:
                    existing.start_time = data['start_time']
                if data.get('end_time') and data['end_time'] != existing.end_time:
                    existing.end_time = data['end_time']
                if data.get('periods') is not None and periods and periods != existing.periods:
                    existing.periods = periods
                if weeks and weeks != existing.weeks:
                    existing.weeks = weeks
                    existing.weeks_bitmap = weeks_bitmap
                # 学期信息以最新爬取为准，保持整批一致
                existing.semester_id = data.get('semester_id') or sem['semester_id']
                existing.semester_name = data.get('semester_name') or sem['semester_name']
                existing.academic_year = data.get('academic_year') or sem['academic_year']
                existing.term = data.get('term') or sem['term']
                # 刷新来源与校验时间（v6.11.1）
                existing.data_source = data_source
                existing.last_verified_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
            else:
                # 不存在：创建新记录（补全所有 NOT NULL 字段）
                course = Course(
                    course_code=course_code,
                    course_name=data.get('course_name', ''),
                    semester_id=data.get('semester_id') or sem['semester_id'],
                    semester_name=data.get('semester_name') or sem['semester_name'],
                    academic_year=data.get('academic_year') or sem['academic_year'],
                    term=data.get('term') or sem['term'],
                    week_day=data.get('week_day', 1),
                    period_idx=period_idx,
                    periods=periods,
                    teacher=data.get('teacher', ''),
                    classroom=data.get('classroom', ''),
                    building=data.get('building', ''),
                    start_time=data.get('start_time', ''),
                    end_time=data.get('end_time', ''),
                    weeks=weeks,
                    weeks_bitmap=weeks_bitmap,
                    week_number=data.get('week_number'),
                    course_type=data.get('course_type'),
                    credit=data.get('credit'),
                    # 来源与校验时间（v6.11.1）
                    data_source=data_source,
                    last_verified_at=datetime.utcnow(),
                )
                session.add(course)
                created_count += 1

        session.flush()
        return created_count
    
    @staticmethod
    def update(
        session: Session,
        course_id: int,
        **kwargs
    ) -> Optional[Course]:
        """
        更新课程
        
        Args:
            session: 数据库会话
            course_id: 课程ID
            **kwargs: 要更新的字段
            
        Returns:
            Optional[Course]: 更新后的课程或None
        """
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return None
        
        for key, value in kwargs.items():
            if hasattr(course, key) and key not in ('id', 'created_at'):
                setattr(course, key, value)
        
        course.updated_at = datetime.utcnow()
        session.flush()
        return course
    
    @staticmethod
    def delete(session: Session, course_id: int) -> bool:
        """
        硬删除课程（从数据库中完全删除）
        
        Args:
            session: 数据库会话
            course_id: 课程ID
            
        Returns:
            bool: 是否删除成功
        """
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return False
        
        session.delete(course)
        session.flush()
        return True
    
    @staticmethod
    def restore(session: Session, course_id: int) -> bool:
        """
        恢复已删除的课程
        
        Args:
            session: 数据库会话
            course_id: 课程ID
            
        Returns:
            bool: 是否恢复成功
        """
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return False
        
        course.is_deleted = False
        course.deleted_at = None
        course.deleted_reason = None
        session.flush()
        return True
    
    @staticmethod
    def delete_all(session: Session) -> int:
        """
        删除所有课程
        
        Args:
            session: 数据库会话
            
        Returns:
            int: 删除的数量
        """
        count = session.query(Course).count()
        session.query(Course).delete()
        session.flush()
        return count
    
    @staticmethod
    def get_week_number(session: Session) -> Optional[int]:
        """
        获取当前「真实教学周次」。

        基于学期第 1 周起始日（course_weeks.week_number=1.start_date）推算：
            current_week = (today - 第1周起始日) // 7 + 1

        注意：绝不能取 courses 表里最大的 week_number 当作当前周——当学期推进
        超过数据中最大周次后，会被误判为“当前周”，导致课程被错误映射到本周，
        进而引发“今天没课却推送”的误推送（详见 2026-07-15 排查记录）。

        Returns:
            Optional[int]: 当前教学周次；无第 1 周起始日数据时回退为 MAX(week_number)
        """
        first = session.query(CourseWeek).filter(CourseWeek.week_number == 1).first()
        if first and first.start_date:
            from datetime import date as _date
            weeks_passed = (_date.today() - first.start_date).days // 7
            return weeks_passed + 1
        # 兜底：无第 1 周起始日数据，回退旧逻辑（仅作兼容，存在误推风险）
        course = session.query(Course).order_by(Course.week_number.desc()).first()
        return course.week_number if course else None
    
    @staticmethod
    def count(session: Session, week_number: Optional[int] = None) -> int:
        """
        统计课程数量
        
        Args:
            session: 数据库会话
            week_number: 可选，按周次筛选
            
        Returns:
            int: 课程数量
        """
        query = session.query(Course)
        if week_number is not None:
            query = query.filter(Course.week_number == week_number)
        return query.count()
