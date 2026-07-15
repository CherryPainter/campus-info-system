#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送执行服务"""
import json
import threading
from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)
from app.services.task_service import task_service
from app.services.template_service import template_service
from app.services.adapter_service import adapter_service
from app.services import unified_task_service as uts
from app.core.task_state import TaskType


class DeliveryService:
    """推送执行引擎"""

    def __init__(self):
        self._running = False
        self._timer = None
        self._interval = 10  # 10秒检查一次
        self._status_webhook = None
        self._task_process_map = {}  # task_id -> process_id 映射，用于更新执行历史
    
    def init_app(self, app):
        self._app = app
        self._running = True
        self._status_webhook = app.config.get('WECOM_STATUS_WEBHOOK')
        self._start_processing()
        logger.info('推送执行服务初始化完成')
    
    def _start_processing(self):
        """启动处理循环"""
        if not self._running:
            return
        try:
            self._process_pending_tasks()
        except Exception as e:
            logger.error(f'处理推送任务异常: {e}')
        self._timer = threading.Timer(self._interval, self._start_processing)
        self._timer.daemon = True
        self._timer.start()
    
    def _create_push_process(self, task):
        """为推送任务创建执行历史记录（TaskProcess），委托 UnifiedTaskService"""
        try:
            rule_name = task.get('rule_name', '课程推送')
            course_info = task.get('course_info', {})

            # 构建任务名称
            if isinstance(course_info, dict) and course_info.get('course_name'):
                name = f"{rule_name} - {course_info['course_name']}"
            elif isinstance(course_info, list) and course_info:
                name = f"{rule_name} - {len(course_info)}门课程"
            else:
                name = rule_name

            process_id = uts.create_process(
                name, TaskType.COURSE, total_items=1,
                created_by='system', pid=None, message='推送任务准备中...'
            )
            logger.info(f'[推送执行] 创建进程记录: {name} (process_id={process_id})')
            return process_id
        except Exception as e:
            logger.warning(f'[推送执行] 创建进程记录失败: {e}')
            return None
    
    def _update_push_process(self, process_id, status, message=None, error=None, progress=None):
        """更新推送任务的执行历史记录（委托 UnifiedTaskService）"""
        if not process_id:
            return
        try:
            uts.complete_process(process_id, status=status, message=message, error=error, progress=progress)
            logger.info(f'[推送执行] 更新进程记录: process_id={process_id}, status={status}')
        except Exception as e:
            logger.warning(f'[推送执行] 更新进程记录失败: {e}')

    def _process_pending_tasks(self):
        """处理待推送任务"""
        if not self._running:
            return
        
        pending = task_service.get_pending_tasks(10)
        if not pending:
            return
        
        for task in pending:
            try:
                task_service.update_status(task['task_id'], 'processing')
                
                # 创建执行历史记录
                process_id = self._create_push_process(task)
                self._task_process_map[task['task_id']] = process_id
                
                if process_id:
                    self._update_push_process(process_id, 'running', message='正在推送消息...')
                
                # 图片任务
                if task.get('task_type') == 'image' and task.get('image_path'):
                    self._send_image(task, process_id)
                    continue
                
                # 消息任务
                template_id = f"{task['task_type']}_{task['sub_type']}"
                data = self._prepare_data(task)
                message = template_service.render(template_id, data)
                
                if message:
                    # 根据任务类型选择对应的 adapter
                    adapter_name = self._get_adapter_name_for_task(task)
                    adapter = adapter_service.get_adapter(adapter_name)
                    if adapter:
                        result = adapter.send(message)
                        if result.get('success'):
                            task_service.update_status(task['task_id'], 'success', result)
                            self._update_push_process(process_id, 'completed', message='推送成功', progress=100)
                        else:
                            task_service.update_status(task['task_id'], 'retrying', {'error': result.get('error')})
                            self._update_push_process(process_id, 'failed', message='推送失败', error=result.get('error'))
                    else:
                        task_service.update_status(task['task_id'], 'failed', {'error': f'No adapter for {adapter_name}'})
                        self._update_push_process(process_id, 'failed', message='推送失败', error=f'No adapter for {adapter_name}')
                        self._notify_delivery_failure(task, f'No adapter for {adapter_name}')
                else:
                    task_service.update_status(task['task_id'], 'failed', {'error': 'Template not found'})
                    self._update_push_process(process_id, 'failed', message='推送失败', error='Template not found')
                    self._notify_delivery_failure(task, 'Template not found')
            except Exception as e:
                logger.error(f'处理任务 {task["task_id"]} 失败: {e}')
                task_service.update_status(task['task_id'], 'retrying', {'error': str(e)})
                process_id = self._task_process_map.get(task['task_id'])
                self._update_push_process(process_id, 'failed', message='推送异常', error=str(e))
    
    def _get_adapter_name_for_task(self, task):
        """根据任务类型获取对应的 adapter 名称"""
        task_type = task.get('task_type', '')
        sub_type = task.get('sub_type', '')
        
        # 课表相关（包括课表图片）
        if task_type in ('schedule', 'course', 'image') and sub_type in ('daily', 'daily_no_class', 'weekly', 'weekly_image', 'course_reminder', 'before_end_class', 'after_class'):
            return 'course'
        # 天气相关
        if task_type in ('weather',):
            return 'weather'
        # 电量相关
        if task_type in ('electricity',):
            return 'electricity'
        # 系统/爬虫相关
        if task_type in ('system', 'spider'):
            return 'system'
        
        # 默认使用 course（课表是最主要的推送）
        return 'course'
    
    def _send_image(self, task, process_id=None):
        """发送图片任务"""
        adapter_name = self._get_adapter_name_for_task(task)
        adapter = adapter_service.get_adapter(adapter_name)
        if not adapter:
            task_service.update_status(task['task_id'], 'failed', {'error': 'No adapter available'})
            self._update_push_process(process_id, 'failed', message='推送失败', error='No adapter available')
            self._notify_delivery_failure(task, 'No adapter available')
            return
        if not hasattr(adapter, 'send_image'):
            task_service.update_status(task['task_id'], 'failed', {'error': 'Adapter does not support image'})
            self._update_push_process(process_id, 'failed', message='推送失败', error='Adapter does not support image')
            self._notify_delivery_failure(task, 'Adapter does not support image')
            return
        result = adapter.send_image(task['image_path'])
        if result.get('success'):
            task_service.update_status(task['task_id'], 'success', result)
            self._update_push_process(process_id, 'completed', message='图片推送成功', progress=100)
        else:
            error_detail = result.get('error', 'Unknown error')
            logger.error(f"图片任务 {task['task_id']} 发送失败: adapter={adapter_name}, error={error_detail}, result={result}")
            # 检查重试次数，超过上限直接标记 failed
            retry_count = task.get('retry_count', 0) + 1
            if retry_count >= task.get('max_retries', 3):
                logger.error(f"图片任务 {task['task_id']} 重试超限，标记为 failed")
                task_service.update_status(task['task_id'], 'failed', {'error': result.get('error', 'Max retries exceeded')})
                self._update_push_process(process_id, 'failed', message='推送失败', error=result.get('error', 'Max retries exceeded'))
                self._notify_delivery_failure(task, result.get('error', 'Max retries exceeded'))
            else:
                task_service.update_status(task['task_id'], 'retrying', {'error': result.get('error')})
                self._update_push_process(process_id, 'running', message=f'重试中 ({retry_count}/{task.get("max_retries", 3)})')
    
    def _notify_delivery_failure(self, task, error_msg):
        """推送任务失败告警"""
        if not self._status_webhook:
            logger.warning(f'推送任务失败但无状态 webhook 配置，无法告警: {task["task_id"]}')
            return
        try:
            import requests as req
            from datetime import datetime
            message = {
                'msgtype': 'markdown',
                'markdown': {
                    'content': (
                        f'**推送任务失败告警**\n\n'
                        f'时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n'
                        f'任务ID：{task["task_id"][:16]}...\n\n'
                        f'任务类型：{task.get("task_type", "unknown")} / {task.get("sub_type", "unknown")}\n\n'
                        f'错误信息：{error_msg}'
                    )
                }
            }
            req.post(self._status_webhook, json=message, timeout=10)
        except Exception as e:
            logger.error(f'发送推送失败告警异常: {e}')

    def _prepare_data(self, task):
        """准备模板数据"""
        if task['task_type'] == 'course_reminder':
            course = task['course_info']
            data = {
                'course_name': course['course_name'],
                'start_time': course['start_time'],
                'end_time': course['end_time'],
                'teacher': course.get('extra_info', {}).get('teacher', ''),
                'classroom': f"{course.get('extra_info', {}).get('building', '')}{course.get('extra_info', {}).get('classroom', '')}".strip(),
                'minutes_before': task.get('trigger_condition', {}).get('minutes_before', ''),
                'minutes_before_end': task.get('trigger_condition', {}).get('minutes_before_end', ''),
            }
            # 下节课信息
            next_course = task.get('next_course_info')
            if next_course:
                data['next_course_block'] = (
                    f"**下节课**：{next_course['course_name']}\n"
                    f"**时间**：{next_course['start_time']} - {next_course['end_time']}\n"
                    f"**地点**：{next_course.get('extra_info', {}).get('building', '')}{next_course.get('extra_info', {}).get('classroom', '')}".strip()
                )
            else:
                data['next_course_block'] = ''
            return data
        
        elif task['task_type'] == 'schedule_summary':
            courses = task['course_info']
            if isinstance(courses, list):
                # 合并同一课程（名称、教师、教室相同）
                merged_courses = self._merge_courses(courses)
                # 按开始时间排序
                sorted_courses = sorted(merged_courses, key=lambda x: x['start_time'])
                lines = []
                for i, c in enumerate(sorted_courses, 1):
                    teacher = c.get('extra_info', {}).get('teacher', '')
                    classroom = f"{c.get('extra_info', {}).get('building', '')}{c.get('extra_info', {}).get('classroom', '')}".strip()
                    # 使用引用格式，与课程通知样式一致
                    line = f"> **课程名称**：{c['course_name']}\n> **上课时间**：{c['start_time']} - {c['end_time']}"
                    if teacher:
                        line += f"\n> **授课教师**：{teacher}"
                    if classroom:
                        line += f"\n> **上课地点**：{classroom}"
                    lines.append(line)
                data = {'courses_list': '\n\n'.join(lines) if lines else '暂无课程'}
            else:
                data = {'courses_list': '暂无课程信息'}
            return data
        
        return {}
    
    def _merge_courses(self, courses):
        """
        合并同一课程的多节课程记录（用于每日课表推送展示）
        
        规则：
        - 同一课程（名称、教师、教室相同）归为一组
        - 按“每2节=1门大课”拆成 1-2 / 3-4 这样的独立条目，时间严格采用课表规定时间
          （不再做“提前10分钟下课”之类的调整，用户要求通知只推课表规定的时间）
        """
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

            # 收集该课程所有节次，拼成一个代表记录，再按大课拆分
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

            # 按课表规定时间填充，并拆成单组大课（去除减10分钟）
            from app.api.course_routes import split_course_to_big_classes
            merged.extend(split_course_to_big_classes(rep))

        return merged
    
    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()


# 全局单例
delivery_service = DeliveryService()
