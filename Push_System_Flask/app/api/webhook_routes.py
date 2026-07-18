#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webhook 管理 API 路由

端点列表：
- GET    /api/admin/webhooks              — 获取所有 webhook
- POST   /api/admin/webhooks              — 创建 webhook
- GET    /api/admin/webhooks/<id>         — 获取单个 webhook
- PUT    /api/admin/webhooks/<id>         — 更新 webhook
- DELETE /api/admin/webhooks/<id>         — 删除 webhook
- POST   /api/admin/webhooks/<id>/test    — 测试 webhook
- POST   /api/admin/webhooks/reload       — 重载适配器配置
"""

from flask import Blueprint, request, jsonify
from app.core.api_response import api_success, api_error, api_paginate
import requests

from app.utils.auth_middleware import admin_required
from app.core.database import get_db
from app.core.logger import get_logger
from app.model.webhook import Webhook
from app.services.adapter_service import adapter_service

logger = get_logger(__name__)

webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route('', methods=['GET'])
@admin_required
def get_webhooks():
    """
    获取所有 webhook 列表
    
    查询参数：
        enabled_only: true 只返回启用的
    """
    enabled_only = request.args.get('enabled_only', 'false').lower() == 'true'
    
    session = get_db()
    try:
        if enabled_only:
            webhooks = Webhook.get_enabled_webhooks(session)
        else:
            webhooks = Webhook.get_all_webhooks(session)
        
        return api_success(data=[w.to_dict() for w in webhooks], count=len(webhooks))
    finally:
        session.close()


@webhook_bp.route('', methods=['POST'])
@admin_required
def create_webhook():
    """
    创建新 webhook
    
    请求体：
        {
            "name": "班级群",
            "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
            "modules": "course,weather",  // course,weather,electricity,system
            "description": "可选描述"
        }
    """
    data = request.get_json(silent=True) or {}
    
    # 验证必填字段
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    
    if not name:
        return api_error(message='名称不能为空', http_status=400)
    if not url:
        return api_error(message='URL 不能为空', http_status=400)
    if not url.startswith('https://'):
        return api_error(message='URL 必须以 https:// 开头', http_status=400)
    
    # 验证 modules
    modules = data.get('modules', 'course')
    valid_modules = {'all', 'course', 'weather', 'electricity', 'system'}
    module_list = [m.strip() for m in modules.split(',') if m.strip()]
    invalid = set(module_list) - valid_modules
    if invalid:
        return api_error(message=f'无效的模块: {invalid}', http_status=400)
    
    session = get_db()
    try:
        webhook = Webhook.create(
            session=session,
            name=name,
            url=url,
            modules=modules,
            description=data.get('description', '').strip() or None,
        )
        
        logger.info(f'[Webhook] 创建成功: {name} ({modules})')
        
        return api_success(message='Webhook 创建成功', data=webhook.to_dict(), http_status=201)
    finally:
        session.close()


@webhook_bp.route('/<int:webhook_id>', methods=['GET'])
@admin_required
def get_webhook(webhook_id: int):
    """获取单个 webhook 详情"""
    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not webhook:
            return api_error(message='Webhook 不存在', http_status=404)
        
        return api_success(data=webhook.to_dict())
    finally:
        session.close()


@webhook_bp.route('/<int:webhook_id>', methods=['PUT'])
@admin_required
def update_webhook(webhook_id: int):
    """
    更新 webhook
    
    请求体（可选字段）：
        {
            "name": "新名称",
            "url": "新 URL",
            "modules": "course,weather",
            "is_enabled": true/false,
            "description": "描述"
        }
    """
    data = request.get_json(silent=True) or {}
    
    # 验证 URL 格式
    if 'url' in data:
        url = data['url'].strip()
        if not url.startswith('https://'):
            return api_error(message='URL 必须以 https:// 开头', http_status=400)
        data['url'] = url
    
    # 验证 modules
    if 'modules' in data:
        valid_modules = {'all', 'course', 'weather', 'electricity', 'system'}
        module_list = [m.strip() for m in data['modules'].split(',') if m.strip()]
        invalid = set(module_list) - valid_modules
        if invalid:
            return api_error(message=f'无效的模块: {invalid}', http_status=400)
    
    session = get_db()
    try:
        success = Webhook.update(session, webhook_id, **data)
        if not success:
            return api_error(message='Webhook 不存在', http_status=404)
        
        webhook = Webhook.get_by_id(session, webhook_id)
        logger.info(f'[Webhook] 更新成功: ID={webhook_id}')
        
        return api_success(message='Webhook 更新成功', data=webhook.to_dict())
    finally:
        session.close()


@webhook_bp.route('/<int:webhook_id>', methods=['DELETE'])
@admin_required
def delete_webhook(webhook_id: int):
    """删除 webhook"""
    session = get_db()
    try:
        success = Webhook.delete(session, webhook_id)
        if not success:
            return api_error(message='Webhook 不存在', http_status=404)
        
        logger.info(f'[Webhook] 删除成功: ID={webhook_id}')
        
        return api_success(message='Webhook 已删除')
    finally:
        session.close()


@webhook_bp.route('/<int:webhook_id>/test', methods=['POST'])
@admin_required
def test_webhook(webhook_id: int):
    """
    测试 webhook
    
    发送一条测试消息到指定 webhook
    """
    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not webhook:
            return api_error(message='Webhook 不存在', http_status=404)
        
        # 更新测试状态为 pending
        webhook.update_test_status(session, 'pending')
        
        # 发送测试消息
        test_message = {
            'msgtype': 'markdown',
            'markdown': {
                'content': f'**测试消息**\n\nWebhook: {webhook.name}\n时间: 刚刚\n\n> 如果收到此消息，说明 webhook 配置正确'
            }
        }
        
        try:
            resp = requests.post(webhook.url, json=test_message, timeout=10)
            try:
                data = resp.json()
            except ValueError:
                data = {'raw': resp.text[:200]}

            # 企业微信返回 HTTP 200 + JSON {errcode, errmsg}；
            # 其他通用 webhook 仅以 HTTP 状态码判断。
            if resp.status_code != 200:
                error_msg = f'HTTP {resp.status_code}'
                webhook.update_test_status(session, 'failed')
                logger.warning(f'[Webhook] 测试失败: {webhook.name} - {error_msg}')
                return api_error(
                    message=f'测试失败: {error_msg}',
                    data={'webhook_response': data},
                    http_status=400,
                )

            errcode = data.get('errcode')
            if errcode is not None and errcode != 0:
                error_msg = data.get('errmsg', '未知错误')
                webhook.update_test_status(session, 'failed')
                logger.warning(f'[Webhook] 测试失败: {webhook.name} - {error_msg}')
                return api_error(
                    message=f'测试失败: {error_msg}',
                    data={'webhook_response': data},
                    http_status=400,
                )

            # 成功（errcode=0，或无 errcode 字段的通用 webhook）
            webhook.update_test_status(session, 'success')
            logger.info(f'[Webhook] 测试成功: {webhook.name}')
            return api_success(
                message='测试消息发送成功',
                data={'webhook_response': data},
            )

        except Exception as e:
            webhook.update_test_status(session, 'failed')
            logger.error(f'[Webhook] 测试异常: {webhook.name} - {e}')
            return api_error(message=f'测试异常: {str(e)}', http_status=500)
    
    finally:
        session.close()


@webhook_bp.route('/reload', methods=['POST'])
@admin_required
def reload_adapters():
    """
    重载适配器配置
    
    从数据库重新加载 webhook 配置到适配器服务
    """
    try:
        adapter_service.reload_webhooks()
        logger.info('[Webhook] 适配器配置已重载')
        
        return api_success(message='适配器配置已重载', data=adapter_service.get_all_status())
    except Exception as e:
        logger.error(f'[Webhook] 重载适配器失败: {e}')
        return api_error(message=f'重载失败: {str(e)}', http_status=500)
