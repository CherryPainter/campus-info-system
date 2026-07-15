#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课表管理服务

职责：
- 从数据库加载课表数据
- 提供课表查询接口
- 管理课表缓存

遵循分层架构：
- Service 层负责业务逻辑
- Repository 层负责数据库操作
"""

import threading
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from app.core.logger import get_logger
from app.core.database import get_db
from app.repository.course_repository import CourseRepository

# 使用统一日志系统
logger = get_logger(__name__)


class ScheduleService:
    """
    课表数据管理服务
    
    职责：
    - 从数据库加载课表数据
    - 提供课表查询接口
    - 管理内存缓存
    """
    
    def __init__(self):
        self._schedules: List[Dict[str, Any]] = []
        self._last_updated: Optional[datetime] = None
        self._lock = threading.Lock()
        self._refresh_timer: Optional[threading.Timer] = None
        self._data_ready: bool = False
        self._app = None
        self._refresh_interval: int = 60  # 60秒刷新
    
    def init_app(self, app) -> None:
        """
        初始化服务
        
        Args:
            app: Flask 应用实例
        """
        self._app = app
        self.load_schedules()
        self._start_auto_refresh()
        logger.info('课表服务初始化完成（数据源：数据库）')
    
    def _start_auto_refresh(self) -> None:
        """启动自动刷新定时器"""
        self._refresh_timer = threading.Timer(self._refresh_interval, self._auto_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()
    
    def _auto_refresh(self) -> None:
        """自动刷新循环"""
        self.load_schedules()
        self._refresh_timer = threading.Timer(self._refresh_interval, self._auto_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()
    
    def load_schedules(self) -> bool:
        """
        从数据库加载课表数据
        
        Returns:
            bool: 是否加载成功
        """
        try:
            session = get_db()
            try:
                # 从数据库获取所有课程
                courses = CourseRepository.get_all(session)
                
                # 转换为推送服务需要的格式
                transformed = self._transform(courses)
                
                with self._lock:
                    # 检查数据是否有变化
                    if len(transformed) != len(self._schedules):
                        self._schedules = transformed
                        self._last_updated = datetime.now()
                        logger.info(f'从数据库加载了 {len(self._schedules)} 条课表数据')
                    self._data_ready = True
                
                return True
            finally:
                session.close()
        except Exception as e:
            logger.error(f'从数据库加载课表数据失败: {e}')
            return False
    
    def _transform(self, courses: List) -> List[Dict[str, Any]]:
        """
        将数据库模型转换为推送服务需要的格式
        
        Args:
            courses: Course 模型列表
            
        Returns:
            List[Dict]: 转换后的课表数据
        """
        result = []
        
        for course in courses:
            # 计算日期（基于当前周次和星期几）
            course_date = self._calculate_date(course.week_day, course.week_number)
            if course_date is None:
                continue
            
            start_time = course.start_time or '00:00'
            end_time = course.end_time or '00:00'
            periods = course.periods or ''
            building = course.building or ''

            # 用课表规定的时间覆盖（去除任何“减10分钟”之类的调整，保证通知时间严格按课表）
            try:
                from app.api.course_routes import apply_timetable_times
                fixed = apply_timetable_times({
                    'periods': periods,
                    'period_idx': course.period_idx,
                    'start_time': start_time,
                    'end_time': end_time,
                    'extra_info': {'building': building, 'full_date': course_date.strftime('%Y-%m-%d')},
                })
                start_time = fixed.get('start_time', start_time)
                end_time = fixed.get('end_time', end_time)
            except Exception:
                pass  # 失败则退回数据库原值
            
            # 构建推送服务需要的格式
            result.append({
                'schedule_id': str(course.id),
                'day_of_week': course.week_day,
                'start_time': start_time,
                'end_time': end_time,
                'course_name': course.course_name,
                'course_code': '',
                'period_idx': course.period_idx,  # 添加节次索引
                'periods': periods,  # 添加节次列表
                'extra_info': {
                    'teacher': course.teacher or '',
                    'building': building,
                    'classroom': course.classroom or '',
                    'weeks': course.weeks or '',
                    'credits': '',
                    'full_date': course_date.strftime('%Y-%m-%d'),
                },
                '_timeInfo': {
                    'start_ts': self._get_timestamp(course_date, start_time),
                    'end_ts': self._get_timestamp(course_date, end_time),
                }
            })
        
        return result
    
    def _calculate_date(self, week_day: int, week_number: Optional[int]) -> Optional[date]:
        """
        根据星期几和周次计算日期
        
        Args:
            week_day: 星期几 (1-7)
            week_number: 周次
            
        Returns:
            Optional[date]: 计算出的日期
        """
        if week_number is None:
            # 如果没有周次，使用本周
            today = date.today()
            days_ahead = week_day - today.isoweekday()
            return today + __import__('datetime').timedelta(days=days_ahead)
        
        # 计算学期第一周周一的日期（假设第1周从9月1日开始）
        # 这里需要根据实际情况调整
        today = date.today()
        current_weekday = today.isoweekday()  # 1=周一, 7=周日
        
        # 计算本周周一
        days_since_monday = current_weekday - 1
        this_monday = today - __import__('datetime').timedelta(days=days_since_monday)
        
        # 计算目标周次的周一
        current_week_number = self._get_current_week_number()
        if current_week_number is None:
            current_week_number = 1
        
        weeks_diff = week_number - current_week_number
        target_monday = this_monday + __import__('datetime').timedelta(weeks=weeks_diff)
        
        # 计算目标日期
        target_date = target_monday + __import__('datetime').timedelta(days=week_day - 1)
        
        return target_date
    
    def _get_current_week_number(self) -> Optional[int]:
        """
        获取当前周次
        
        Returns:
            Optional[int]: 当前周次
        """
        try:
            session = get_db()
            try:
                return CourseRepository.get_week_number(session)
            finally:
                session.close()
        except Exception:
            return None
    
    def _get_timestamp(self, course_date: date, time_str: str) -> float:
        """
        获取时间戳
        
        Args:
            course_date: 日期
            time_str: 时间字符串 (HH:MM)
            
        Returns:
            float: 时间戳
        """
        try:
            parts = time_str.split(':')
            h = int(parts[0]) if len(parts) > 0 else 0
            m = int(parts[1]) if len(parts) > 1 else 0
            dt = datetime(course_date.year, course_date.month, course_date.day, h, m)
            return dt.timestamp()
        except Exception:
            return 0.0
    
    def _enrich_is_today(self, schedules: List[Dict]) -> List[Dict]:
        """
        为课表列表动态计算 is_today 字段
        
        Args:
            schedules: 课表列表
            
        Returns:
            List[Dict]: 添加了 is_today 字段的课表列表
        """
        today_str = date.today().strftime('%Y-%m-%d')
        result = []
        for s in schedules:
            enriched = dict(s)
            enriched['_timeInfo'] = dict(s['_timeInfo'])
            enriched['_timeInfo']['is_today'] = s['extra_info']['full_date'] == today_str
            result.append(enriched)
        return result
    
    @property
    def is_data_ready(self) -> bool:
        """是否曾成功加载过课表数据"""
        return self._data_ready
    
    def get_schedules(self, force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        获取所有课表
        
        Args:
            force_reload: 是否强制重新加载
            
        Returns:
            List[Dict]: 课表列表
        """
        if force_reload:
            self.load_schedules()
        with self._lock:
            schedules = list(self._schedules)
        return self._enrich_is_today(schedules)
    
    def get_today_schedules(self, force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        获取今日课表
        
        Args:
            force_reload: 是否强制重新加载
            
        Returns:
            List[Dict]: 今日课表列表
        """
        today = date.today().strftime('%Y-%m-%d')
        return [
            s for s in self.get_schedules(force_reload) 
            if s['extra_info']['full_date'] == today
        ]
    
    def get_upcoming_courses(self, minutes: int = 30, force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        获取即将开始的课程
        
        Args:
            minutes: 提前多少分钟
            force_reload: 是否强制重新加载
            
        Returns:
            List[Dict]: 即将开始的课程列表
        """
        now = datetime.now().timestamp()
        future = now + minutes * 60
        return sorted(
            [s for s in self.get_schedules(force_reload)
             if s['_timeInfo']['start_ts'] > now 
             and s['_timeInfo']['start_ts'] <= future 
             and s['_timeInfo'].get('is_today', False)],
            key=lambda x: x['_timeInfo']['start_ts']
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict: 统计数据
        """
        schedules = self.get_schedules()
        return {
            'total': len(schedules),
            'today': sum(1 for s in schedules if s['_timeInfo'].get('is_today', False)),
            'unique_courses': len(set(s['course_name'] for s in schedules if s['course_name'] != '未命名课程')),
            'unique_teachers': len(set(s['extra_info']['teacher'] for s in schedules if s['extra_info'].get('teacher'))),
            'data_ready': self._data_ready,
            'last_updated': self._last_updated.isoformat() if self._last_updated else None
        }


# 全局单例
schedule_service = ScheduleService()
