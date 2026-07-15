#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSRF防护模块

为Session认证提供CSRF Token验证
JWT认证不需要CSRF防护（因为JWT不依赖Cookie）

使用方式：
1. 在登录时生成CSRF Token，存储在Session中
2. 在每个状态更改请求（POST/PUT/DELETE/PATCH）中验证CSRF Token
3. CSRF Token可以通过请求头 X-CSRF-Token 或表单字段 _csrf_token 传递
"""

import secrets
import functools
from flask import request, jsonify, session as flask_session, current_app
from app.core.logger import get_logger

logger = get_logger(__name__)

# CSRF Token配置
CSRF_TOKEN_LENGTH = 32
CSRF_TOKEN_SESSION_KEY = '_csrf_token'
CSRF_TOKEN_HEADER = 'X-CSRF-Token'
CSRF_TOKEN_FIELD = '_csrf_token'

# 不需要CSRF防护的路径前缀（API路径使用JWT认证，不需要CSRF）
CSRF_EXEMPT_PREFIXES = [
    '/api/',               # 所有API接口使用JWT认证，不需要CSRF
]

# 不需要CSRF防护的路径（精确匹配）
CSRF_EXEMPT_PATHS = [
    '/api/auth/login',      # 登录接口
    '/api/auth/refresh',    # 刷新Token
    '/api/auth/logout',     # 登出接口
    '/api/health',          # 健康检查
    '/health',              # 健康检查
]

# 不需要CSRF防护的请求方法（只读请求不需要CSRF）
CSRF_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def generate_csrf_token() -> str:
    """
    生成新的CSRF Token
    
    Returns:
        随机Token字符串
    """
    token = secrets.token_hex(CSRF_TOKEN_LENGTH)
    return token


def get_csrf_token() -> str:
    """
    获取当前Session的CSRF Token（如果不存在则生成新的）
    
    Returns:
        CSRF Token字符串
    """
    # 对于Flask的Session（客户端Session），直接存在flask_session中
    if CSRF_TOKEN_SESSION_KEY not in flask_session:
        flask_session[CSRF_TOKEN_SESSION_KEY] = generate_csrf_token()
    return flask_session[CSRF_TOKEN_SESSION_KEY]


def validate_csrf_token() -> bool:
    """
    验证请求中的CSRF Token
    
    Returns:
        True表示验证通过，False表示验证失败
    """
    # 对于Flask的Session（客户端Session），从flask_session中获取
    stored_token = flask_session.get(CSRF_TOKEN_SESSION_KEY)
    if not stored_token:
        logger.warning('[CSRF] Session中不存在CSRF Token')
        return False
    
    # 从请求头或表单中获取Token
    request_token = request.headers.get(CSRF_TOKEN_HEADER)
    if not request_token:
        request_token = request.form.get(CSRF_TOKEN_FIELD)
    if not request_token:
        request_token = request.json.get(CSRF_TOKEN_FIELD) if request.json else None
    
    if not request_token:
        logger.warning('[CSRF] 请求中不存在CSRF Token')
        return False
    
    if request_token != stored_token:
        logger.warning('[CSRF] CSRF Token不匹配')
        return False
    
    return True


def csrf_protect(f):
    """
    CSRF防护装饰器
    
    用于需要CSRF防护的Web端点（使用Session认证的端点）
    API端点（使用JWT认证）不需要此装饰器
    
    使用方法：
    @app.route('/web/profile', methods=['POST'])
    @csrf_protect
    def update_profile():
        ...
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 豁免路径检查
        if request.path in CSRF_EXEMPT_PATHS:
            return f(*args, **kwargs)
        
        # 安全方法检查
        if request.method.upper() in CSRF_SAFE_METHODS:
            return f(*args, **kwargs)
        
        # 验证CSRF Token
        if not validate_csrf_token():
            logger.warning(f'[CSRF] CSRF验证失败: {request.path}')
            return jsonify({
                'status': 'error',
                'message': 'CSRF validation failed'
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function


def csrf_exempt(f):
    """
    豁免CSRF防护装饰器
    
    用于API端点（使用JWT认证）或特殊情况
    
    使用方法：
    @app.route('/api/some-endpoint', methods=['POST'])
    @csrf_exempt
    def some_api():
        ...
    """
    f._csrf_exempt = True
    return f


class CSRFProtect:
    """
    CSRF防护类（可以像Flask-WTF一样使用）
    
    使用方法：
    csrf = CSRFProtect()
    csrf.init_app(app)
    """
    
    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """初始化CSRF防护"""
        self.app = app
        
        # 注册before_request处理器
        app.before_request(self._before_request)
        
        # 注册上下文处理器（为模板提供CSRF Token）
        app.context_processor(self._context_processor)
        
        logger.info('[CSRF] CSRF防护已初始化')
    
    def _before_request(self):
        """在每个请求前检查CSRF Token"""
        # 豁免路径前缀检查（API接口使用JWT，不需要CSRF）
        for prefix in CSRF_EXEMPT_PREFIXES:
            if request.path.startswith(prefix):
                return
        
        # 豁免路径检查（精确匹配）
        if request.path in CSRF_EXEMPT_PATHS:
            return
        
        # 安全方法检查
        if request.method.upper() in CSRF_SAFE_METHODS:
            return
        
        # 检查是否豁免（通过endpoint获取视图函数）
        if hasattr(request, 'endpoint') and request.endpoint:
            view_func = current_app.view_functions.get(request.endpoint)
            if view_func and hasattr(view_func, '_csrf_exempt') and view_func._csrf_exempt:
                return
        
        # 验证CSRF Token
        if not validate_csrf_token():
            logger.warning(f'[CSRF] CSRF验证失败: {request.path}')
            return jsonify({
                'status': 'error',
                'message': 'CSRF validation failed'
            }), 403
    
    def _context_processor(self):
        """为模板提供CSRF Token"""
        return {
            'csrf_token': get_csrf_token,
        }
    
    def exempt(self, view_func):
        """豁免某个视图函数的CSRF防护"""
        if isinstance(view_func, (list, tuple)):
            for f in view_func:
                f._csrf_exempt = True
            return view_func
        view_func._csrf_exempt = True
        return view_func
