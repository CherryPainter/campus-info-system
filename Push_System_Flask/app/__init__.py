#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask 应用工厂"""
import os
import sys
from flask import Flask, redirect, request, jsonify
from flask_cors import CORS

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Config, validate_required_config
from app.core.logger import setup_logger, get_logger
from app.core.extensions import limiter, scheduler

# 使用统一日志系统
logger = get_logger(__name__)

# 全局 app 引用
_current_app = None


def get_current_app():
    """获取当前 app 实例"""
    return _current_app


def create_app(config_class=None):
    """应用工厂函数"""
    global _current_app
    app = Flask(__name__)
    _current_app = app
    
    # 加载配置
    if config_class is None:
        config_class = Config
    app.config.from_object(config_class)
    
    # 设置 session 密钥
    app.secret_key = app.config.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1小时
    
    # 验证必要配置
    try:
        validate_required_config()
    except Exception as e:
        print(f"配置验证失败: {e}")
        sys.exit(1)
    
    # 初始化日志
    setup_logger(app)
    
    # 初始化扩展
    allowed_origins = app.config.get('ALLOWED_ORIGINS')
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)
    limiter.init_app(app)
    
    # HTTPS 强制跳转（生产环境）
    @app.before_request
    def force_https():
        if app.config.get('FORCE_HTTPS', False) and not request.is_secure:
            return redirect(request.url.replace('http://', 'https://', 1), code=301)

    # ========== 全局安全检查（IP黑名单拦截 + 攻击检测 + 安全事件记录） ==========
    from app.utils.security import security_before_request
    @app.before_request
    def global_security_check():
        return security_before_request()

    # ========== 全局错误处理器（隐藏敏感信息） ==========
    
    @app.errorhandler(400)
    def bad_request(error):
        """400 Bad Request - 返回通用错误信息，不暴露细节"""
        logger.warning(f"400 Bad Request: {error}")
        return jsonify({
            'status': 'error',
            'message': '请求参数错误，请检查输入'
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        """401 Unauthorized - 返回通用认证失败信息"""
        logger.warning(f"401 Unauthorized: {error}")
        return jsonify({
            'status': 'error',
            'message': '认证失败，请重新登录'
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        """403 Forbidden - 返回通用权限不足信息"""
        logger.warning(f"403 Forbidden: {error}")
        return jsonify({
            'status': 'error',
            'message': '权限不足，无法访问'
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        """404 Not Found - 返回通用资源未找到信息"""
        logger.warning(f"404 Not Found: {error}")
        return jsonify({
            'status': 'error',
            'message': '请求的资源不存在'
        }), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        """405 Method Not Allowed - 返回通用方法不允许信息"""
        logger.warning(f"405 Method Not Allowed: {error}")
        return jsonify({
            'status': 'error',
            'message': 'HTTP 方法不允许'
        }), 405
    
    @app.errorhandler(413)
    def request_too_large(error):
        """413 Request Too Large - 返回通用请求过大信息"""
        logger.warning(f"413 Request Too Large: {error}")
        return jsonify({
            'status': 'error',
            'message': '请求大小超过限制'
        }), 413
    
    @app.errorhandler(429)
    def too_many_requests(error):
        """429 Too Many Requests - 返回通用限流信息"""
        logger.warning(f"429 Too Many Requests: {error}")
        return jsonify({
            'status': 'error',
            'message': '请求过于频繁，请稍后再试'
        }), 429
    
    @app.errorhandler(500)
    def internal_server_error(error):
        """500 Internal Server Error - 返回通用服务器错误信息，隐藏详细错误"""
        logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': '服务器内部错误，请稍后重试'
        }), 500
    
    @app.errorhandler(Exception)
    def handle_uncaught_exception(error):
        """捕获所有未处理的异常 - 返回通用错误信息，隐藏详细错误"""
        logger.error(f"Uncaught Exception: {error}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': '服务器内部错误，请稍后重试'
        }), 500
    
    # ========== 安全响应头（增强浏览器安全） ==========
    
    @app.after_request
    def add_security_headers(response):
        """添加安全相关的 HTTP 响应头"""
        # X-Content-Type-Options: 禁止浏览器猜测 MIME 类型
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # X-Frame-Options: 禁止在 iframe 中加载，防止点击劫持
        response.headers['X-Frame-Options'] = 'DENY'
        # X-XSS-Protection: 启用浏览器内置的 XSS 防护
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Strict-Transport-Security: 强制 HTTPS（生产环境）
        if app.config.get('FORCE_HTTPS', False):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Content-Security-Policy: 限制资源加载来源
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "frame-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        # Referrer-Policy: 限制 Referrer 信息传递
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Permissions-Policy: 限制浏览器特性使用
        response.headers['Permissions-Policy'] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        # 禁止缓存 API 响应：避免浏览器/代理缓存 GET（如爬虫状态、爬取任务详情），
        # 否则轮询会一直拿到陈旧状态 —— 表现为「任务横幅卡在执行中」「任务管理卡片永不点亮」。
        if request.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    # 健康检查接口
    @app.route('/api/ping', methods=['GET'])
    def ping():
        return {'status': 'ok'}

    # 初始化数据库（创建表）
    # 先导入所有模型，确保 Base.metadata 包含所有表
    from app.model import (
        WeatherRecord, WeatherAlert, ElectricityRecord, ElectricityRemaining, ElectricityTotalCapacity,
        Course, CourseWeek, CustomPush, TaskProcess, TokenBlacklist, UserMFA, User,
        LoginLog, ModuleConfig, Webhook, PushTask,
    )
    from app.model.ip_blacklist import IPBlacklist, IPSecurityEvent
    from app.model.server_session import ServerSession
    from app.core.database import db_manager
    db_manager.init_database()
    logger.info('数据库初始化完成')

    # 补齐 server_sessions 撤销相关列（老库兼容，幂等）
    from app.services.session_service import ensure_session_columns, ensure_user_columns
    ensure_session_columns()
    ensure_user_columns()

    # 初始化 JWT 管理器（双 Token 认证机制）
    from app.utils.jwt_auth import JWTManager
    jwt_manager = JWTManager(
        secret_key=app.config['SECRET_KEY'],
        access_token_expire=app.config.get('JWT_ACCESS_TOKEN_EXPIRE', 3600),
        refresh_token_expire=app.config.get('JWT_REFRESH_TOKEN_EXPIRE', 604800),
        refresh_idle_expire=app.config.get('JWT_REFRESH_IDLE_EXPIRE', 259200),
        refresh_absolute_expire=app.config.get('JWT_REFRESH_ABSOLUTE_EXPIRE', 2592000),
    )
    # 将 JWT 管理器存入 app.extensions，供装饰器和路由使用
    app.extensions['jwt_manager'] = jwt_manager
    logger.info('JWT 认证管理器初始化完成')
    
    # 初始化 CSRF 防护
    from app.utils.csrf_protect import CSRFProtect
    csrf = CSRFProtect()
    csrf.init_app(app)
    logger.info('CSRF 防护已初始化')

    # 注册蓝图
    from app.api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # 注册电量监控蓝图
    from app.api.electricity_routes import electricity_bp
    app.register_blueprint(electricity_bp, url_prefix='/api/electricity')

    # 注册天气模块蓝图
    from app.api.weather_routes import weather_bp
    app.register_blueprint(weather_bp, url_prefix='/api/weather')

    # 注册 JWT 认证蓝图（登录、刷新、登出等）
    from app.api.auth_routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    # 注册管理后台蓝图（仪表盘、模块配置、任务管理等）
    from app.api.admin_routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    # 注册课程管理蓝图
    from app.api.course_routes import course_bp
    app.register_blueprint(course_bp, url_prefix='/api/course')
    
    # 注册自定义推送蓝图
    from app.api.push_routes import push_bp
    app.register_blueprint(push_bp, url_prefix='/api/admin/push')
    
    # 注册进程管理蓝图
    from app.api.process_routes import process_bp
    app.register_blueprint(process_bp, url_prefix='/api/admin/processes')
    
    # 注册模块配置蓝图
    from app.api.config_routes import config_bp
    app.register_blueprint(config_bp, url_prefix='/api/admin/config')
    
    # 注册 webhook 管理蓝图
    from app.api.webhook_routes import webhook_bp
    app.register_blueprint(webhook_bp, url_prefix='/api/admin/webhooks')
    
    # 注册用户管理蓝图
    from app.api.admin_user_routes import admin_user_bp
    app.register_blueprint(admin_user_bp, url_prefix='/api/admin/user')
    
    # 注册 IP 黑名单管理蓝图
    from app.api.ip_blacklist_routes import ip_blacklist_bp
    app.register_blueprint(ip_blacklist_bp, url_prefix='/api/admin/ip-blacklist')
    
    # 注册 Session 管理蓝图
    from app.api.session_routes import session_bp
    app.register_blueprint(session_bp, url_prefix='/api/auth')

    # 注册统一任务查询蓝图（按 ID 查任务状态的单一入口）
    from app.api.task_routes import task_bp
    app.register_blueprint(task_bp, url_prefix='/api/tasks')

    # 初始化服务
    from app.services import init_services
    init_services(app)
    
    # 清理僵尸进程（服务器重启后遗留的 running 状态进程）
    from app.core.database import get_db
    from app.model.task_process import TaskProcess
    from app.model.module_config import init_default_configs
    from app.model.user import User
    import bcrypt
    session = get_db()
    try:
        # 清理僵尸进程
        zombie_count = session.query(TaskProcess).filter(TaskProcess.status == 'running').update(
            {'status': 'cancelled', 'message': '服务器重启，进程已失效'},
            synchronize_session=False
        )
        session.commit()
        if zombie_count > 0:
            logger.info(f'[启动] 清理了 {zombie_count} 个僵尸进程')
        
        # 初始化默认配置
        init_default_configs(session)
        
        # 初始化默认管理员账号
        admin_user = session.query(User).filter_by(username='admin').first()
        if not admin_user:
            # 从 .env 读取初始密码
            initial_password = app.config.get('JWT_ADMIN_PASSWORD', '') or app.config.get('ADMIN_TOKEN', 'admin')
            password_hash = bcrypt.hashpw(initial_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            admin_user = User(
                username='admin',
                password_hash=password_hash,
                role='admin',
                is_active=True,
                is_primary=True,
            )
            session.add(admin_user)
            session.commit()
            logger.info('[启动] 已创建默认管理员账号 admin')
        else:
            logger.info(f'[启动] 管理员账号已存在: admin')
    finally:
        session.close()
    
    # 启动定时任务
    from app.tasks.scheduler import start_scheduler
    start_scheduler(app)
    
    logger.info(f"{app.config['APP_NAME']} v{app.config['APP_VERSION']} 启动完成")
    
    return app

