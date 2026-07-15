#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送规则服务"""
import json
from datetime import datetime
from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)

# 触发器时间窗口（秒）：每分钟检查一次，窗口扩大到 90 秒以容忍 APScheduler 线程抖动
# 同时用 _triggered_keys 防止在同一窗口内重复触发
_TRIGGER_WINDOW_SECONDS = 90


class RuleService:
    """推送规则引擎"""
    
    def __init__(self):
        self._rules = []
        self._app = None
        # 防重复触发：key = (rule_id, schedule_id_or_date, push_ts_minute)
        # minute 精度已经足够（同一分钟内不会重复推送）
        self._triggered_keys: set = set()
        self._triggered_keys_ts: dict = {}  # key → 触发时间，用于定期清理
    
    def init_app(self, app):
        self._app = app
        self._init_rules()
        logger.info(f'推送规则服务初始化完成，共 {len(self._rules)} 条规则')
    
    def _get_config_minutes(self, config_key: str, env_key: str, default: int) -> int:
        """
        动态读取提醒分钟数配置，优先级：数据库 > app.config > 默认值
        
        每次 check_conditions 都重新读取，确保前端改配置立刻生效，无需重启。
        """
        try:
            from app.services.config_service import get_config_service
            val = get_config_service().get('course', config_key, None)
            if val is not None:
                return int(val)
        except Exception:
            pass
        if self._app:
            return int(self._app.config.get(env_key, default))
        return default

    def _get_daily_push_time(self) -> str:
        """动态读取每日课表推送时间"""
        try:
            from app.services.config_service import get_config_service
            val = get_config_service().get('course', 'schedule_daily', None)
            if val:
                return val
        except Exception:
            pass
        if self._app:
            return self._app.config.get('DAILY_PUSH_TIME', '07:00')
        return '07:00'

    def _init_rules(self):
        """初始化规则结构（不缓存动态配置值，每次运行时读取）"""
        self._rules = [
            {
                'id': 'before_class', 'type': 'before_class', 'name': '上课前推送',
                'enabled': True, 'priority': 1,
                # minutes 不在此处固化，每次检查时动态读取
            },
            {
                'id': 'daily_schedule', 'type': 'daily_schedule', 'name': '每日课表推送',
                'enabled': True, 'priority': 2,
                # time 不在此处固化，每次检查时动态读取
            },
            {
                'id': 'before_end_class', 'type': 'before_end_class', 'name': '即将下课推送',
                'enabled': True, 'priority': 1,
                # minutes 不在此处固化，每次检查时动态读取
            },
            {
                'id': 'weekly_schedule', 'type': 'weekly_schedule', 'name': '每周课表推送',
                'enabled': True, 'priority': 3, 'time': '08:00', 'day_of_week': 1
            },
            {
                'id': 'after_class', 'type': 'after_class', 'name': '上课后推送',
                'enabled': False, 'priority': 4, 'minutes': 5
            },
        ]
        self._rules.sort(key=lambda r: r['priority'])

    def _clean_triggered_keys(self, now_ts: float):
        """清理超过 2 小时的触发记录，防止内存无限增长"""
        cutoff = now_ts - 7200
        expired = [k for k, ts in self._triggered_keys_ts.items() if ts < cutoff]
        for k in expired:
            self._triggered_keys.discard(k)
            del self._triggered_keys_ts[k]

    def _mark_triggered(self, key: str, now_ts: float):
        self._triggered_keys.add(key)
        self._triggered_keys_ts[key] = now_ts

    def _is_triggered(self, key: str) -> bool:
        return key in self._triggered_keys
    
    def check_conditions(self, current_time, schedules):
        """检查触发条件"""
        tasks = []
        today = current_time.strftime('%Y-%m-%d')
        today_schedules = [s for s in schedules if s['extra_info']['full_date'] == today]
        now_ts = current_time.timestamp()

        # 定期清理防重复触发记录
        self._clean_triggered_keys(now_ts)

        # 动态读取最新配置（每次检查都重新读，确保前端改参数立刻生效）
        before_class_minutes = self._get_config_minutes('before_class_minutes', 'BEFORE_CLASS_MINUTES', 15)
        before_end_class_minutes = self._get_config_minutes('before_end_class_minutes', 'BEFORE_END_CLASS_MINUTES', 10)
        daily_push_time = self._get_daily_push_time()

        for rule in self._rules:
            if not rule['enabled']:
                continue
            # 注入动态配置值（不修改原 rule dict，避免并发问题）
            effective_rule = dict(rule)
            if rule['id'] == 'before_class':
                effective_rule['minutes'] = before_class_minutes
            elif rule['id'] == 'before_end_class':
                effective_rule['minutes'] = before_end_class_minutes
            elif rule['id'] == 'daily_schedule':
                effective_rule['time'] = daily_push_time

            handler = getattr(self, f'_check_{rule["type"]}', None)
            if handler:
                result = handler(current_time, today_schedules, schedules, effective_rule)
                if result:
                    tasks.extend(result if isinstance(result, list) else [result])
        
        if tasks:
            logger.info(f'规则检查完成，生成 {len(tasks)} 个推送任务 '
                         f'(课前{before_class_minutes}min, 下课前{before_end_class_minutes}min)')
        return tasks
    
    def _merge_courses_for_push(self, courses):
        """
        为推送合并课程
        
        将同一课程（名称、教师、教室相同）的连续节次合并为一个推送任务。
        如果数据库中已有 period_name（如"第一至四节"），则直接使用合并后的数据。
        
        Returns:
            合并后的课程列表（每个合并课程只保留第一条记录，但使用合并后的时间）
        """
        if not courses:
            return courses
        
        # 按课程名称、教师、教室分组
        groups = {}
        for c in courses:
            key = (
                c.get('course_name', ''),
                c.get('extra_info', {}).get('teacher', ''),
                c.get('extra_info', {}).get('building', '') + c.get('extra_info', {}).get('classroom', ''),
            )
            if key not in groups:
                groups[key] = []
            groups[key].append(c)
        
        merged = []
        for key, group in groups.items():
            # 按节次排序
            group = sorted(group, key=lambda x: x.get('period_idx', 0))

            # 收集该课程所有节次，拼成一个代表记录，再按“每2节=1门大课”拆分
            all_periods = []
            rep = None
            for c in group:
                if '至' in c.get('period_name', ''):
                    rep = dict(c)
                p = c.get('periods')
                if isinstance(p, (list, tuple)):
                    all_periods.extend(int(x) for x in p if str(x).isdigit())
                elif isinstance(p, str) and p:
                    try:
                        all_periods.extend(int(x) for x in json.loads(p) if str(x).isdigit())
                    except Exception:
                        pass
                elif c.get('period_idx'):
                    all_periods.append(int(c['period_idx']))
            if rep is None:
                rep = dict(group[0])
            if all_periods:
                rep['periods'] = sorted(set(all_periods))

            # 按课表规定时间填充，并拆成 1-2 / 3-4 这样的单组大课（去除减10分钟）
            from app.api.course_routes import split_course_to_big_classes
            merged.extend(split_course_to_big_classes(rep))

        return merged
    
    def _check_before_class(self, now, today_schedules, all_schedules, rule):
        """上课前推送规则 - 只提醒大课"""
        tasks = []
        now_ts = now.timestamp()
        minutes = rule['minutes']
        
        # 合并课程（避免重复推送同一门课的多个节次）
        merged_schedules = self._merge_courses_for_push(today_schedules)
        
        for s in merged_schedules:
            # 只提醒大课（两节连上的课）或单节课
            if not self._is_big_class(s, today_schedules):
                continue
            push_ts = s['_timeInfo']['start_ts'] - minutes * 60
            # 防重复触发 key：rule_id + schedule_id + 推送时间点（分钟精度）
            dedup_key = f"before_class|{s['schedule_id']}|{int(push_ts // 60)}"
            if self._is_triggered(dedup_key):
                continue
            # 扩大触发窗口为 _TRIGGER_WINDOW_SECONDS（默认90秒），容忍调度抖动
            if now_ts >= push_ts and now_ts - push_ts < _TRIGGER_WINDOW_SECONDS:
                self._mark_triggered(dedup_key, now_ts)
                tasks.append({
                    'rule_id': rule['id'], 'rule_name': rule['name'],
                    'schedule_id': s['schedule_id'], 'trigger_time': now,
                    'task_type': 'course_reminder', 'sub_type': 'before_class',
                    'course_info': s,
                    'trigger_condition': {'minutes_before': minutes}
                })
                logger.info(f'[课前提醒] 触发: {s.get("course_name")} 提前{minutes}分钟 '
                            f'(push_ts={int(push_ts)}, now_ts={int(now_ts)}, diff={int(now_ts-push_ts)}s)')
        return tasks
    
    def _check_daily_schedule(self, now, today_schedules, all_schedules, rule):
        """每日课表推送规则"""
        h, m = map(int, rule['time'].split(':'))
        now_ts = now.timestamp()
        # 计算今日推送时间戳
        from datetime import datetime as _dt
        push_dt = _dt(now.year, now.month, now.day, h, m)
        push_ts = push_dt.timestamp()
        dedup_key = f"daily_schedule|{now.strftime('%Y-%m-%d')}|{h:02d}{m:02d}"
        if self._is_triggered(dedup_key):
            return None
        if now_ts >= push_ts and now_ts - push_ts < _TRIGGER_WINDOW_SECONDS:
            self._mark_triggered(dedup_key, now_ts)
            
            # 合并课程（避免重复推送同一门课的多个节次）
            merged_schedules = self._merge_courses_for_push(today_schedules)
            
            return {
                'rule_id': rule['id'], 'rule_name': rule['name'],
                'trigger_time': now, 'task_type': 'schedule_summary',
                'sub_type': 'daily_no_class' if not merged_schedules else 'daily',
                'course_info': merged_schedules,
                'trigger_condition': {'daily_time': rule['time']}
            }
        return None
    
    def _check_before_end_class(self, now, today_schedules, all_schedules, rule):
        """即将下课推送规则 - 只提醒大课"""
        tasks = []
        now_ts = now.timestamp()
        minutes = rule['minutes']
        sorted_schedules = sorted(today_schedules, key=lambda x: x['_timeInfo']['start_ts'])
        for i, s in enumerate(sorted_schedules):
            # 只提醒大课（两节连上的课）或单节课
            if not self._is_big_class(s, today_schedules):
                continue
            push_ts = s['_timeInfo']['end_ts'] - minutes * 60
            # 防重复触发 key
            dedup_key = f"before_end_class|{s['schedule_id']}|{int(push_ts // 60)}"
            if self._is_triggered(dedup_key):
                continue
            # 扩大触发窗口
            if now_ts >= push_ts and now_ts - push_ts < _TRIGGER_WINDOW_SECONDS:
                self._mark_triggered(dedup_key, now_ts)
                task = {
                    'rule_id': rule['id'], 'rule_name': rule['name'],
                    'schedule_id': s['schedule_id'], 'trigger_time': now,
                    'task_type': 'course_reminder', 'sub_type': 'before_end_class',
                    'course_info': s,
                    'trigger_condition': {'minutes_before_end': minutes}
                }
                if i + 1 < len(sorted_schedules):
                    task['next_course_info'] = sorted_schedules[i + 1]
                tasks.append(task)
                logger.info(f'[下课提醒] 触发: {s.get("course_name")} 提前{minutes}分钟下课 '
                            f'(push_ts={int(push_ts)}, now_ts={int(now_ts)}, diff={int(now_ts-push_ts)}s)')
        return tasks
    
    def _check_weekly_schedule(self, now, today_schedules, all_schedules, rule):
        """每周课表推送规则"""
        if now.isoweekday() != rule.get('day_of_week', 1):
            return None
        h, m = map(int, rule['time'].split(':'))
        now_ts = now.timestamp()
        from datetime import datetime as _dt
        push_dt = _dt(now.year, now.month, now.day, h, m)
        push_ts = push_dt.timestamp()
        dedup_key = f"weekly_schedule|{now.strftime('%Y-%m-%d')}"
        if self._is_triggered(dedup_key):
            return None
        if now_ts >= push_ts and now_ts - push_ts < _TRIGGER_WINDOW_SECONDS:
            self._mark_triggered(dedup_key, now_ts)
            return {
                'rule_id': rule['id'], 'rule_name': rule['name'],
                'trigger_time': now, 'task_type': 'schedule_summary',
                'sub_type': 'weekly', 'course_info': all_schedules,
                'trigger_condition': {'weekly_time': rule['time']}
            }
        return None
    
    def _check_after_class(self, now, today_schedules, all_schedules, rule):
        """上课后推送规则"""
        tasks = []
        now_ts = now.timestamp()
        minutes = rule.get('minutes', 5)
        for s in today_schedules:
            push_ts = s['_timeInfo']['start_ts'] + minutes * 60
            dedup_key = f"after_class|{s['schedule_id']}|{int(push_ts // 60)}"
            if self._is_triggered(dedup_key):
                continue
            if now_ts >= push_ts and now_ts - push_ts < _TRIGGER_WINDOW_SECONDS:
                self._mark_triggered(dedup_key, now_ts)
                tasks.append({
                    'rule_id': rule['id'], 'rule_name': rule['name'],
                    'schedule_id': s['schedule_id'], 'trigger_time': now,
                    'task_type': 'course_reminder', 'sub_type': 'after_class',
                    'course_info': s,
                    'trigger_condition': {'minutes_after': minutes}
                })
        return tasks
    
    def check_conditions_force(self, current_time, schedules, rule_type=''):
        """强制检查触发条件（忽略时间窗口，用于手动触发）
        
        Args:
            current_time: 当前时间
            schedules: 课表列表
            rule_type: 指定规则类型（为空则检查所有规则）
        """
        tasks = []
        today = current_time.strftime('%Y-%m-%d')
        today_schedules = [s for s in schedules if s['extra_info']['full_date'] == today]
        
        for rule in self._rules:
            if not rule['enabled']:
                continue
            # 如果指定了规则类型，只检查该类型
            if rule_type and rule['type'] != rule_type:
                continue
            handler = getattr(self, f'_check_{rule["type"]}_force', None)
            if handler:
                result = handler(current_time, today_schedules, schedules, rule)
                if result:
                    tasks.extend(result if isinstance(result, list) else [result])
        
        logger.info(f'强制规则检查完成，生成 {len(tasks)} 个推送任务')
        return tasks
    
    def _check_before_class_force(self, now, today_schedules, all_schedules, rule):
        """强制模式：为每门今日即将开始的大课生成提醒（不检查时间窗口）"""
        tasks = []
        now_ts = now.timestamp()
        minutes = self._get_config_minutes('before_class_minutes', 'BEFORE_CLASS_MINUTES', 15)
        # 只提醒尚未开始的大课
        for s in today_schedules:
            if not self._is_big_class(s, today_schedules):
                continue
            if s['_timeInfo']['start_ts'] > now_ts:
                tasks.append({
                    'rule_id': rule['id'], 'rule_name': rule['name'],
                    'schedule_id': s['schedule_id'], 'trigger_time': now,
                    'task_type': 'course_reminder', 'sub_type': 'before_class',
                    'course_info': s,
                    'trigger_condition': {'minutes_before': minutes}
                })
        return tasks
    
    def _check_daily_schedule_force(self, now, today_schedules, all_schedules, rule):
        """强制模式：生成今日课表推送（不检查是否为配置的推送时间）"""
        daily_push_time = self._get_daily_push_time()
        return {
            'rule_id': rule['id'], 'rule_name': rule['name'],
            'trigger_time': now, 'task_type': 'schedule_summary',
            'sub_type': 'daily_no_class' if not today_schedules else 'daily',
            'course_info': today_schedules,
            'trigger_condition': {'daily_time': daily_push_time}
        }
    
    def _check_before_end_class_force(self, now, today_schedules, all_schedules, rule):
        """强制模式：为每门尚未下课的大课生成提醒"""
        tasks = []
        now_ts = now.timestamp()
        minutes = self._get_config_minutes('before_end_class_minutes', 'BEFORE_END_CLASS_MINUTES', 10)
        sorted_schedules = sorted(today_schedules, key=lambda x: x['_timeInfo']['start_ts'])
        for i, s in enumerate(sorted_schedules):
            # 只提醒尚未下课的大课
            if not self._is_big_class(s, today_schedules):
                continue
            if s['_timeInfo']['end_ts'] > now_ts:
                task = {
                    'rule_id': rule['id'], 'rule_name': rule['name'],
                    'schedule_id': s['schedule_id'], 'trigger_time': now,
                    'task_type': 'course_reminder', 'sub_type': 'before_end_class',
                    'course_info': s,
                    'trigger_condition': {'minutes_before_end': minutes}
                }
                if i + 1 < len(sorted_schedules):
                    task['next_course_info'] = sorted_schedules[i + 1]
                tasks.append(task)
        return tasks
    
    def _check_weekly_schedule_force(self, now, today_schedules, all_schedules, rule):
        """强制模式：生成本周课表推送"""
        return {
            'rule_id': rule['id'], 'rule_name': rule['name'],
            'trigger_time': now, 'task_type': 'schedule_summary',
            'sub_type': 'weekly', 'course_info': all_schedules,
            'trigger_condition': {'weekly_time': rule['time']}
        }
    
    def _check_after_class_force(self, now, today_schedules, all_schedules, rule):
        """强制模式：为每门已开始的课程生成确认"""
        tasks = []
        now_ts = now.timestamp()
        minutes = rule.get('minutes', 5)
        for s in today_schedules:
            if s['_timeInfo']['start_ts'] <= now_ts:
                tasks.append({
                    'rule_id': rule['id'], 'rule_name': rule['name'],
                    'schedule_id': s['schedule_id'], 'trigger_time': now,
                    'task_type': 'course_reminder', 'sub_type': 'after_class',
                    'course_info': s,
                    'trigger_condition': {'minutes_after': minutes}
                })
        return tasks
    
    def get_rules(self):
        """返回规则列表（注入当前动态配置值，用于前端展示）"""
        before_class_minutes = self._get_config_minutes('before_class_minutes', 'BEFORE_CLASS_MINUTES', 15)
        before_end_class_minutes = self._get_config_minutes('before_end_class_minutes', 'BEFORE_END_CLASS_MINUTES', 10)
        daily_push_time = self._get_daily_push_time()
        result = []
        for rule in self._rules:
            r = dict(rule)
            if rule['id'] == 'before_class':
                r['minutes'] = before_class_minutes
            elif rule['id'] == 'before_end_class':
                r['minutes'] = before_end_class_minutes
            elif rule['id'] == 'daily_schedule':
                r['time'] = daily_push_time
            elif rule['id'] == 'weekly_schedule':
                r['time'] = rule.get('time', '08:00')
                r['day_of_week'] = rule.get('day_of_week', 1)
            elif rule['id'] == 'after_class':
                r['minutes'] = rule.get('minutes', 5)
            result.append(r)
        return result
    
    def _is_big_class(self, course, today_schedules):
        """
        判断是否是上大课（两节连上的课）
        
        大课定义：同一课程（名称、教师、教室相同）有两节或以上连续的节次
        例如：1,2节 或 3,4节 或 5,6节
        
        Args:
            course: 当前课程记录
            today_schedules: 今日所有课程
            
        Returns:
            bool: 是否是大课
        """
        # 找出同一课程的所有节次
        same_course = [
            c for c in today_schedules
            if c.get('course_name') == course.get('course_name')
            and c.get('extra_info', {}).get('teacher') == course.get('extra_info', {}).get('teacher')
            and c.get('extra_info', {}).get('classroom') == course.get('extra_info', {}).get('classroom')
        ]
        
        # 获取所有节次索引
        periods = [c.get('period_idx', 0) for c in same_course]
        
        # 如果只有一节，不是大课
        if len(periods) < 2:
            return True  # 单节课也需要提醒
        
        # 检查是否有连续的节次
        periods = sorted(set(periods))  # 去重并排序
        for i in range(len(periods) - 1):
            # 如果相邻两个节次连续（差值为1），就是大课
            if periods[i + 1] - periods[i] == 1:
                return True
        
        return True  # 默认也提醒


# 全局单例
rule_service = RuleService()
