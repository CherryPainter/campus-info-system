#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消息模板服务 - 支持从 JSON 配置文件加载，内置模板作为兜底"""
import os
import json
from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)


# 内置默认模板（作为 JSON 文件不存在或解析失败时的兜底）
_DEFAULT_TEMPLATES = [
    {
        'id': 'course_reminder_before_class', 'name': '上课前提醒',
        'type': 'course_reminder', 'sub_type': 'before_class', 'msg_type': 'markdown',
        'content': '# 课程提醒\n\n> **课程名称**：{{course_name}}\n> **上课时间**：{{start_time}} - {{end_time}}\n> **授课教师**：{{teacher}}\n> **上课地点**：{{classroom}}\n\n请提前<font color="warning">{{minutes_before}}分钟</font>到达教室！'
    },
    {
        'id': 'course_reminder_before_end_class', 'name': '即将下课提醒',
        'type': 'course_reminder', 'sub_type': 'before_end_class', 'msg_type': 'markdown',
        'content': '# 即将下课\n\n> **当前课程**：{{course_name}}\n> **下课时间**：{{end_time}}\n\n还有<font color="warning">{{minutes_before_end}}分钟</font>下课。\n\n{{next_course_block}}'
    },
    {
        'id': 'course_reminder_after_class', 'name': '上课后确认',
        'type': 'course_reminder', 'sub_type': 'after_class', 'msg_type': 'markdown',
        'content': '# 上课确认\n\n> **课程名称**：{{course_name}}\n> **上课时间**：{{start_time}} - {{end_time}}\n\n课程已开始，请专注听讲！'
    },
    {
        'id': 'schedule_summary_daily', 'name': '每日课表',
        'type': 'schedule_summary', 'sub_type': 'daily', 'msg_type': 'markdown',
        'content': '# 今日课程安排\n\n{{courses_list}}\n\n祝学习愉快！'
    },
    {
        'id': 'schedule_summary_weekly', 'name': '每周课表',
        'type': 'schedule_summary', 'sub_type': 'weekly', 'msg_type': 'markdown',
        'content': '# 本周课程安排\n\n{{courses_list}}\n\n祝本周学习顺利！'
    },
    {
        'id': 'schedule_summary_daily_no_class', 'name': '今日无课',
        'type': 'schedule_summary', 'sub_type': 'daily_no_class', 'msg_type': 'markdown',
        'content': '# 今日课程安排\n\n> 今天没有课程安排，好好休息吧！'
    },
]


class TemplateService:
    """消息模板管理 - 支持外部 JSON 配置文件"""

    def __init__(self):
        self._templates = {}
        self._templates_path = None

    def init_app(self, app):
        # 优先从 JSON 配置文件加载
        self._templates_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'templates.json'
        )
        self._load_templates()
        logger.info(f'模板服务初始化完成，共 {len(self._templates)} 个模板')

    def _load_templates(self):
        """从 JSON 文件加载模板，失败时使用内置默认模板"""
        self._templates = {}
        loaded = False

        if self._templates_path and os.path.exists(self._templates_path):
            try:
                with open(self._templates_path, 'r', encoding='utf-8') as f:
                    templates = json.load(f)
                if isinstance(templates, list) and templates:
                    for t in templates:
                        if 'id' in t:
                            self._templates[t['id']] = t
                    loaded = True
                    logger.info(f'从配置文件加载了 {len(self._templates)} 个模板')
            except Exception as e:
                logger.warning(f'加载模板配置文件失败，使用内置默认模板: {e}')

        if not loaded:
            for t in _DEFAULT_TEMPLATES:
                self._templates[t['id']] = t
            logger.info('使用内置默认模板')

    def reload_templates(self):
        """重新加载模板（修改 JSON 后可调用，无需重启服务）"""
        self._load_templates()
        return len(self._templates)
    
    # 企业微信 markdown 消息内容最大字节数（UTF-8 编码）
    MAX_MARKDOWN_BYTES = 3900
    # 截断提示后缀
    TRUNCATE_SUFFIX = '\n\n...(内容过长已截断)'

    def render(self, template_id, data):
        """渲染模板"""
        template = self._templates.get(template_id)
        if not template:
            return None
        
        content = template['content']
        for key, value in data.items():
            placeholder = '{{' + key + '}}'
            replacement = '' if value is None else str(value)
            content = content.replace(placeholder, replacement)
        
        # markdown 类型消息截断保护（企业微信限制 4096 字节，预留安全余量）
        if template['msg_type'] == 'markdown':
            content = self._truncate_markdown(content)
        
        return {'msgtype': template['msg_type'], 'markdown': {'content': content}}
    
    def _truncate_markdown(self, content):
        """截断 markdown 内容，确保不超过企业微信消息大小限制"""
        encoded = content.encode('utf-8')
        if len(encoded) <= self.MAX_MARKDOWN_BYTES:
            return content
        
        suffix = self.TRUNCATE_SUFFIX
        suffix_bytes = len(suffix.encode('utf-8'))
        target_bytes = self.MAX_MARKDOWN_BYTES - suffix_bytes
        
        # 按字节截断，但需保证不在 UTF-8 多字节字符中间断开
        truncated = encoded[:target_bytes].decode('utf-8', errors='ignore')
        return truncated + suffix
    
    def get_template(self, template_id):
        return self._templates.get(template_id)
    
    def get_all_templates(self):
        return list(self._templates.values())


# 全局单例
template_service = TemplateService()
