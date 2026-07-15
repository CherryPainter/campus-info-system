from flask import jsonify


def api_success(data=None, message='', http_status=200, status='success', **extra):
    """统一成功响应。自定义键（mfa_token/user/count/source/updates 等）通过 **extra 传入。
    health/module-status 类接口可用 status='healthy'/'ok'/'enabled'/'disabled' 保留原 status 值。"""
    payload = {'status': status}
    if data is not None:
        payload['data'] = data
    if message:
        payload['message'] = message
    payload.update(extra)
    return jsonify(payload), http_status


def api_error(message='', http_status=400, code=None, data=None, **extra):
    """统一错误响应。http_status 传 HTTP 状态码（如 404/401/403）。code 为业务码（可选）。"""
    payload = {'status': 'error', 'message': message}
    if code is not None:
        payload['code'] = code
    if data is not None:
        payload['data'] = data
    payload.update(extra)
    return jsonify(payload), http_status


def api_paginate(items, total, page=1, page_size=20, **extra):
    pages = (total + page_size - 1) // page_size if page_size else 0
    payload = {
        'status': 'success',
        'data': items,
        'pagination': {'total': total, 'page': page, 'page_size': page_size, 'pages': pages},
    }
    payload.update(extra)
    return jsonify(payload), 200
