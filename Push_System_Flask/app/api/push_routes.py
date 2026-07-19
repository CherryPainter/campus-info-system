#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义推送 API 路由

端点列表：
- GET    /api/admin/push              — 获取推送列表
- POST   /api/admin/push              — 创建推送
- GET    /api/admin/push/<id>         — 获取推送详情
- PUT    /api/admin/push/<id>         — 更新推送
- DELETE /api/admin/push/<id>         — 删除推送
- POST   /api/admin/push/<id>/send    — 立即发送推送
- POST   /api/admin/push/<id>/cancel  — 取消定时推送
- GET    /api/admin/push/templates    — 获取内置模板列表
"""

import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from app.core.api_response import api_success, api_error, api_paginate

from app.utils.auth_middleware import admin_required
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.config import Config
from app.model.custom_push import CustomPush

logger = get_logger(__name__)

push_bp = Blueprint('push', __name__)


def _resolve_safe_image_path(image_path):
    """将图片路径解析为 BASE_DIR 内的安全绝对路径。

    拒绝绝对路径与包含 '..' 的路径穿越，防止读取服务器任意文件
    （如 .env、/etc/passwd）后再经企业微信 webhook 外带。
    合法返回绝对路径；非法返回 None。
    """
    if not image_path:
        return None
    if os.path.isabs(image_path):
        return None
    if '..' in image_path.replace('\\', '/').split('/'):
        return None
    full = os.path.normpath(os.path.join(Config.BASE_DIR, image_path))
    base = os.path.normpath(Config.BASE_DIR)
    if full != base and not full.startswith(base + os.sep):
        return None
    return full


# 内置消息模板
BUILTIN_TEMPLATES = [
    {
        'id': 'daily_report',
        'name': '每日报告',
        'description': '发送每日统计报告',
        'params': ['date', 'summary'],
        'example': {'date': '2024-01-01', 'summary': '今日完成10项任务'},
    },
    {
        'id': 'alert',
        'name': '告警通知',
        'description': '发送告警或异常通知',
        'params': ['level', 'message', 'time'],
        'example': {'level': '警告', 'message': '电量不足', 'time': '08:00'},
    },
    {
        'id': 'reminder',
        'name': '提醒通知',
        'description': '发送日程或任务提醒',
        'params': ['title', 'content', 'time'],
        'example': {'title': '会议提醒', 'content': '下午3点会议', 'time': '14:30'},
    },
    {
        'id': 'weather',
        'name': '天气播报',
        'description': '发送天气预报信息',
        'params': ['date', 'weather', 'temp'],
        'example': {'date': '今日', 'weather': '晴', 'temp': '18-25°C'},
    },
]


@push_bp.route('/templates', methods=['GET'])
@admin_required
def get_templates():
    """获取内置模板列表"""
    return api_success(data=BUILTIN_TEMPLATES)


@push_bp.route('', methods=['GET'])
@admin_required
def get_pushes():
    """
    获取推送列表
    
    查询参数：
        status: 按状态筛选 (pending/sent/failed/cancelled)
        push_type: 按类型筛选 (immediate/scheduled/recurring)
        page: 页码，默认1
        per_page: 每页数量，默认20
    """
    status = request.args.get('status', '')
    push_type = request.args.get('push_type', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    session = get_db()
    try:
        query = session.query(CustomPush)
        
        if status:
            query = query.filter(CustomPush.status == status)
        if push_type:
            query = query.filter(CustomPush.push_type == push_type)
        
        total = query.count()
        pushes = query.order_by(CustomPush.created_at.desc()) \
            .offset((page - 1) * per_page) \
            .limit(per_page) \
            .all()
        
        return api_success(data=[p.to_dict() for p in pushes], pagination={'total': total, 'page': page, 'per_page': per_page, 'pages': (total + per_page - 1) // per_page})
    finally:
        session.close()


@push_bp.route('', methods=['POST'])
@admin_required
def create_push():
    """
    创建推送

    请求格式：
        {
            "title": "推送标题",
            "msg_type": "text",  // text/image/template
            "content": "推送内容",  // 文本消息时必填
            "image_path": "/path/to/image.png",  // 图片消息时必填
            "template_id": "daily_report",  // 模板消息时必填
            "template_params": {"date": "2024-01-01"},  // 模板参数
            "push_type": "immediate",  // immediate/scheduled/recurring
            "scheduled_time": "2024-01-01T08:00:00",  // 定时推送时必填
            "cron_expression": "0 8 * * *"  // 周期推送时必填
        }
    """
    data = request.get_json(silent=True) or {}

    title = data.get('title', '').strip()
    msg_type = data.get('msg_type', 'text')
    content = data.get('content', '').strip()
    image_path = data.get('image_path', '').strip()
    template_id = data.get('template_id', '').strip()
    template_params = data.get('template_params', {})
    push_type = data.get('push_type', 'immediate')
    scheduled_time = data.get('scheduled_time')
    cron_expression = data.get('cron_expression', '')

    if not title:
        return api_error(message='标题不能为空', http_status=400)

    if msg_type not in ['text', 'image', 'template']:
        return api_error(message='无效的消息类型', http_status=400)

    # 根据消息类型验证必填字段
    if msg_type == 'text' and not content:
        return api_error(message='文本消息必须填写内容', http_status=400)

    if msg_type == 'image' and not image_path:
        return api_error(message='图片消息必须提供图片路径', http_status=400)

    if msg_type == 'template' and not template_id:
        return api_error(message='模板消息必须选择模板', http_status=400)

    if push_type not in ['immediate', 'scheduled', 'recurring']:
        return api_error(message='无效的推送类型', http_status=400)

    if push_type == 'scheduled' and not scheduled_time:
        return api_error(message='定时推送必须指定推送时间', http_status=400)

    if push_type == 'recurring' and not cron_expression:
        return api_error(message='周期推送必须指定cron表达式', http_status=400)

    # 验证图片路径是否存在（同时防路径穿越：仅允许 BASE_DIR 内相对路径）
    if image_path:
        safe_path = _resolve_safe_image_path(image_path)
        if not safe_path or not os.path.exists(safe_path):
            return api_error(message=f'图片文件不存在或路径非法: {image_path}', http_status=400)

    # 解析定时时间
    scheduled_dt = None
    if scheduled_time:
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
        except ValueError:
            return api_error(message='时间格式错误', http_status=400)

    user = g.get('current_user', {})

    session = get_db()
    try:
        push = CustomPush(
            title=title,
            content=content,
            msg_type=msg_type,
            image_path=image_path,
            template_id=template_id,
            template_params=json.dumps(template_params, ensure_ascii=False) if template_params else None,
            push_type=push_type,
            scheduled_time=scheduled_dt,
            cron_expression=cron_expression,
            status='pending',
            created_by=user.get('username', 'unknown'),
        )
        session.add(push)
        session.commit()

        # 如果是立即推送，直接发送
        if push_type == 'immediate':
            success = _send_push(push)
            if push.status == 'skipped':
                pass  # 假期模式静默，_send_push 已置为 skipped
            elif success:
                push.status = 'sent'
                push.sent_at = datetime.now()
            else:
                push.status = 'failed'
            session.commit()

        logger.info(f'[自定义推送] 创建推送: {title} (type={push_type}, msg_type={msg_type})')
        return api_success(message='推送创建成功', data=push.to_dict())
    finally:
        session.close()


@push_bp.route('/<int:push_id>', methods=['GET'])
@admin_required
def get_push(push_id: int):
    """获取推送详情"""
    session = get_db()
    try:
        push = session.query(CustomPush).filter(CustomPush.id == push_id).first()
        if not push:
            return api_error(message='推送不存在', http_status=404)
        
        return api_success(data=push.to_dict())
    finally:
        session.close()


@push_bp.route('/<int:push_id>', methods=['PUT'])
@admin_required
def update_push(push_id: int):
    """更新推送（仅限待发送状态）"""
    data = request.get_json(silent=True) or {}
    
    session = get_db()
    try:
        push = session.query(CustomPush).filter(CustomPush.id == push_id).first()
        if not push:
            return api_error(message='推送不存在', http_status=404)
        
        if push.status not in ['pending']:
            return api_error(message='只能修改待发送的推送', http_status=400)
        
        # 更新字段
        if 'title' in data:
            push.title = data['title'].strip()
        if 'content' in data:
            push.content = data['content'].strip()
        if 'scheduled_time' in data and data['scheduled_time']:
            push.scheduled_time = datetime.fromisoformat(data['scheduled_time'].replace('Z', '+00:00'))
        if 'cron_expression' in data:
            push.cron_expression = data['cron_expression']
        
        session.commit()
        
        return api_success(message='推送更新成功', data=push.to_dict())
    finally:
        session.close()


@push_bp.route('/<int:push_id>', methods=['DELETE'])
@admin_required
def delete_push(push_id: int):
    """删除推送"""
    session = get_db()
    try:
        push = session.query(CustomPush).filter(CustomPush.id == push_id).first()
        if not push:
            return api_error(message='推送不存在', http_status=404)
        
        session.delete(push)
        session.commit()
        
        return api_success(message='推送已删除')
    finally:
        session.close()


@push_bp.route('/<int:push_id>/send', methods=['POST'])
@admin_required
def send_push_now(push_id: int):
    """立即发送推送"""
    session = get_db()
    try:
        push = session.query(CustomPush).filter(CustomPush.id == push_id).first()
        if not push:
            return api_error(message='推送不存在', http_status=404)
        
        if push.status == 'sent':
            return api_error(message='推送已发送', http_status=400)
        
        success = _send_push(push)
        if push.status == 'skipped':
            session.commit()
            return api_success(message='假期模式静默中，未发送')
        elif success:
            push.status = 'sent'
            push.sent_at = datetime.now()
            session.commit()
            return api_success(message='推送发送成功')
        else:
            push.status = 'failed'
            session.commit()
            return api_error(message='推送发送失败', http_status=500)
    finally:
        session.close()


@push_bp.route('/<int:push_id>/cancel', methods=['POST'])
@admin_required
def cancel_push(push_id: int):
    """取消定时推送"""
    session = get_db()
    try:
        push = session.query(CustomPush).filter(CustomPush.id == push_id).first()
        if not push:
            return api_error(message='推送不存在', http_status=404)
        
        if push.status != 'pending':
            return api_error(message='只能取消待发送的推送', http_status=400)
        
        push.status = 'cancelled'
        session.commit()
        
        return api_success(message='推送已取消')
    finally:
        session.close()


def _send_push(push: CustomPush) -> bool:
    """
    发送推送

    支持三种消息类型：
    - text: 文本消息（Markdown格式）
    - image: 图片消息
    - template: 模板消息
    """
    from app.api.process_routes import create_task_process, complete_task_process

    try:
        pid = create_task_process(
            name=f'推送: {push.title}',
            task_type='custom',
            total_items=1,
            created_by=push.created_by or 'admin',
        )

        logger.info(f'[自定义推送] 发送推送: {push.title} (msg_type={push.msg_type})')

        # 假期模式：静默全体面向用户的推送（含手动自定义推送）
        from app.services.holiday_service import holiday_service
        active, period = holiday_service.is_active()
        if active:
            reason = f'假期模式静默（{period.name}）'
            logger.info(f'[自定义推送] {push.title} 假期模式静默，跳过发送')
            complete_task_process(pid, 'skipped', reason)
            push.status = 'skipped'
            push.error_message = reason
            return True

        from app.services.adapter_service import adapter_service
        # 自定义推送使用 course 适配器（课表/通用推送）
        adapter = adapter_service.get_adapter('course')

        if not adapter:
            logger.warning('[自定义推送] course 适配器未初始化，跳过发送')
            complete_task_process(pid, 'failed', error='course适配器未初始化')
            return False

        # 根据消息类型发送
        if push.msg_type == 'text':
            # 文本消息（Markdown格式）
            content = f'## {push.title}\n\n{push.content}'
            result = adapter.send({'msgtype': 'markdown', 'markdown': {'content': content}})

        elif push.msg_type == 'image':
            # 图片消息（创建时已校验，这里再做一次纵深防御）
            safe_path = _resolve_safe_image_path(push.image_path)
            if not safe_path or not os.path.exists(safe_path):
                raise Exception(f'图片文件不存在或路径非法: {push.image_path}')
            image_path = safe_path

            # 读取图片并转为base64
            import base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # 计算MD5
            import hashlib
            md5 = hashlib.md5(open(image_path, 'rb').read()).hexdigest()

            result = adapter.send({
                'msgtype': 'image',
                'image': {
                    'base64': image_data,
                    'md5': md5,
                }
            })

        elif push.msg_type == 'template':
            # 模板消息
            template_params = json.loads(push.template_params) if push.template_params else {}
            content = _render_template(push.template_id, push.title, template_params)
            result = adapter.send({'msgtype': 'markdown', 'markdown': {'content': content}})

        else:
            raise Exception(f'不支持的消息类型: {push.msg_type}')

        if result and not result.get('success'):
            raise Exception(result.get('error', '发送失败'))

        complete_task_process(pid, 'completed', f'推送成功: {push.title}')
        return True

    except Exception as e:
        logger.error(f'[自定义推送] 发送失败: {e}')
        push.error_message = str(e)
        complete_task_process(pid, 'failed', error=str(e))
        return False


def _render_template(template_id: str, title: str, params: dict) -> str:
    """
    渲染模板消息

    Args:
        template_id: 模板ID
        title: 消息标题
        params: 模板参数

    Returns:
        渲染后的Markdown内容
    """
    # 查找模板
    template = next((t for t in BUILTIN_TEMPLATES if t['id'] == template_id), None)
    if not template:
        raise Exception(f'模板不存在: {template_id}')

    # 根据模板类型构建内容
    lines = [f'## {title}', '']

    if template_id == 'daily_report':
        lines.append(f'**日期**: {params.get("date", "-")}')
        lines.append(f'**摘要**: {params.get("summary", "-")}')

    elif template_id == 'alert':
        level = params.get('level', '通知')
        color = 'red' if level in ['严重', '错误'] else 'orange' if level == '警告' else 'blue'
        lines.append(f'**级别**: <font color="{color}">{level}</font>')
        lines.append(f'**信息**: {params.get("message", "-")}')
        lines.append(f'**时间**: {params.get("time", "-")}')

    elif template_id == 'reminder':
        lines.append(f'**事项**: {params.get("title", "-")}')
        lines.append(f'**内容**: {params.get("content", "-")}')
        lines.append(f'**时间**: {params.get("time", "-")}')

    elif template_id == 'weather':
        lines.append(f'**日期**: {params.get("date", "-")}')
        lines.append(f'**天气**: {params.get("weather", "-")}')
        lines.append(f'**温度**: {params.get("temp", "-")}')

    else:
        # 通用模板：显示所有参数
        for key, value in params.items():
            lines.append(f'**{key}**: {value}')

    lines.append('')
    lines.append(f'_发送时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}_')

    return '\n'.join(lines)
