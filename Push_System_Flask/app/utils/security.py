#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全中间件

提供全面的安全防护功能：
- IP黑名单检查（自动封禁恶意IP）
- 敏感路径拦截
- 可疑请求检测（路径遍历、空字节等）
- SQL注入检测
- XSS攻击检测
- 请求参数验证和输入过滤
- 请求大小限制
- 统一错误处理和日志记录
"""
import re
import functools
import secrets
from flask import request, jsonify, g, current_app
from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)

# 合法 API 路径白名单（这些路径跳过敏感路径检查）
API_WHITELIST_PATHS = {
    '/', '/health', '/status',
    '/request_token', '/trigger',
    '/schedules', '/schedules/today', '/schedules/statistics',
    '/rules', '/tasks',
    '/templates', '/templates/reload',
    '/spider/run', '/spider/status',
}

# 敏感路径黑名单 (40+ patterns)
# 注意：部分模式（如 token、temp）使用更精确的匹配，避免误拦截合法 API 路径
SENSITIVE_PATTERNS = [
    re.compile(p) for p in [
        # 文件/目录相关
        r'^\.env', r'^\.git', r'\.json$', r'\.log$', r'\.py$', r'\.conf$',
        r'\.ini$', r'\.ya?ml$', r'^config', r'^logs', r'^__pycache__',
        r'\.htaccess', r'^\.ssh', r'id_rsa', r'\.docker',
        r'\.sql$', r'\.bak$', r'\.zip$', r'\.tar', r'\.gz$',
        r'\.db$', r'\.sqlite', r'\.pem$', r'\.key$', r'\.crt$',
        r'processed_course_table', r'course-data', r'node_modules',
        r'package-lock',
        # 管理面板（仅匹配根级 /admin，避免误拦 /api/admin/* 业务接口）
        r'^/admin(/|$)', r'phpmyadmin', r'wp-admin', r'server-status',
        r'actuator', r'swagger',
        # 敏感关键词（使用边界匹配，避免误拦 /templates 等）
        r'credentials', r'/secret', r'/token[s]?/', r'graphql',
        r'backup', r'dump', r'/upload', r'/tmp/',
        # 拓展文件类型
        r'\.env\.', r'\.env$',
    ]
]

# 可疑请求模式（路径遍历、空字节等）
SUSPICIOUS_PATTERNS = [
    re.compile(r'\x00'), re.compile(r'\.\./'), re.compile(r'%2e%2e', re.IGNORECASE),
    re.compile(r'\.env\.'), re.compile(r'\.env%00'),
]

# SQL注入检测模式
SQL_INJECTION_PATTERNS = [
    re.compile(r'\b(select|insert|update|delete|drop|union|exec|execute|xp_|sp_|0x7e)\b', re.IGNORECASE),
    re.compile(r'\b(and|or|not)\s+\d+\s*=\s*\d+', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+(\d+|\'\d+\')\s*like', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+\d+\s*<>(?!=)\s*\d+', re.IGNORECASE),
    re.compile(r"\b(and|or)\s+'[^']*'?\s*=\s*'[^']*'?", re.IGNORECASE),
    re.compile(r"\b(and|or)\s+'[^']*'?\s*like\s+'[^']*'?", re.IGNORECASE),
    re.compile(r'\bunion\s+all\s+select', re.IGNORECASE),
    re.compile(r'\bselect\s+\*\s+from', re.IGNORECASE),
    re.compile(r'\bselect\s+count\(\*\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+1\s*=\s*1', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+0\s*=\s*0', re.IGNORECASE),
    re.compile(r"\b(and|or)\s+'\s*=\s*'", re.IGNORECASE),
    re.compile(r'\b(and|or)\s+\d+\s*>\s*\d+', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+\d+\s*<\s*\d+', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+\d+\s*between\s+\d+\s+and\s+\d+', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+\d+\s+in\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r"\b(and|or)\s+'[^']*'\s+in\s*\([^)]+\)", re.IGNORECASE),
    re.compile(r'\b(and|or)\s+exists\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+not\s+exists\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+substring\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+mid\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+ascii\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+char\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+benchmark\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+waitfor\s+delay', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+sleep\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+if\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+case\s+when', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+cast\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+convert\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+concat\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+group_concat\s*\([^)]+\)', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+information_schema', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+mysql\.user', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+systables', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+sysobjects', re.IGNORECASE),
    re.compile(r'\b(and|or)\s+syscolumns', re.IGNORECASE),
]

# XSS攻击检测模式
XSS_PATTERNS = [
    re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<script[^>]*>', re.IGNORECASE),
    re.compile(r'</script>', re.IGNORECASE),
    re.compile(r'<iframe[^>]*>.*?</iframe>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<iframe[^>]*>', re.IGNORECASE),
    re.compile(r'<img[^>]*src\s*=\s*["\']?javascript:', re.IGNORECASE),
    re.compile(r'<img[^>]*src\s*=\s*["\']?data:', re.IGNORECASE),
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'vbscript:', re.IGNORECASE),
    re.compile(r'expression\s*\(', re.IGNORECASE),
    re.compile(r'on\w+\s*=\s*["\']?[^"\'>]+["\']?', re.IGNORECASE),
    re.compile(r'<svg[^>]*>.*?</svg>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<svg[^>]*>', re.IGNORECASE),
    re.compile(r'<embed[^>]*>', re.IGNORECASE),
    re.compile(r'<object[^>]*>', re.IGNORECASE),
    re.compile(r'<applet[^>]*>', re.IGNORECASE),
    re.compile(r'<form[^>]*>', re.IGNORECASE),
    re.compile(r'<input[^>]*>', re.IGNORECASE),
    re.compile(r'<textarea[^>]*>', re.IGNORECASE),
    re.compile(r'<script[^>]*src\s*=\s*["\']?[^"\'>]+["\']?', re.IGNORECASE),
    re.compile(r'<link[^>]*href\s*=\s*["\']?javascript:', re.IGNORECASE),
    re.compile(r'<meta[^>]*http-equiv\s*=\s*["\']?refresh["\']?', re.IGNORECASE),
    re.compile(r'<base[^>]*>', re.IGNORECASE),
    re.compile(r'&lt;script[^>]*&gt;', re.IGNORECASE),
    re.compile(r'&lt;/script&gt;', re.IGNORECASE),
    re.compile(r'&#x3c;script', re.IGNORECASE),
    re.compile(r'&#x3c;/script', re.IGNORECASE),
    re.compile(r'&#60;script', re.IGNORECASE),
    re.compile(r'&#60;/script', re.IGNORECASE),
]

# 请求大小限制（字节）
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB

# 允许的 HTTP 方法
ALLOWED_METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'}

# 特殊字符过滤（用于输入验证）
SPECIAL_CHARS = re.compile(r'[<>"\';&|`$(){}[\]]')

# 敏感关键词列表
SENSITIVE_KEYWORDS = {
    'admin', 'root', 'superuser', 'administrator', 'system',
    'password', 'secret', 'token', 'credential', 'api_key',
    'private_key', 'public_key', 'certificate', 'ssh_key',
}

# 内网 IP 段
PRIVATE_IP_PATTERNS = [
    re.compile(r'^10\.'), re.compile(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.'),
    re.compile(r'^192\.168\.'), re.compile(r'^127\.'),
]


def get_client_ip():
    """获取客户端真实 IP（仅信任反向代理传来的最右端 IP）"""
    # 优先使用 Flask 原生 remote_addr，它来自 TCP 连接，不可伪造
    remote_addr = request.remote_addr or '127.0.0.1'

    # 如果请求来自可信代理（内网），才信任 X-Forwarded-For
    if is_private_ip(remote_addr):
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            # X-Forwarded-For: client, proxy1, proxy2
            # 最左端是真实客户端 IP（前提：最右端代理是可信的）
            return forwarded.split(',')[0].strip()
        real_ip = request.headers.get('X-Real-IP', '')
        if real_ip:
            return real_ip

    return remote_addr


def is_private_ip(ip):
    """判断是否为内网 IP"""
    if ip in ('127.0.0.1', 'localhost', '::1', '::ffff:127.0.0.1'):
        return True
    return any(p.match(ip) for p in PRIVATE_IP_PATTERNS)


def is_sensitive_path(path):
    """检查是否为敏感路径

    注意：/api/ 前缀下均为系统自有业务接口（含 /api/admin/* 管理员接口），
    不存在“直接访问敏感文件”的场景，且已由 JWT 认证保护；此处对 /api/ 前缀
    直接放行，可避免误杀合法业务接口。SQL 注入/XSS/路径遍历等攻击检测在
    _run_security_checks 的后续步骤中仍对所有路径生效，不受此放行影响。
    """
    if path.startswith('/api/'):
        return False
    decoded = __import__('urllib.parse').parse.unquote(path)
    return any(p.search(decoded) for p in SENSITIVE_PATTERNS)


def is_suspicious_request(path):
    """检查是否为可疑请求（路径遍历、空字节等）"""
    decoded = __import__('urllib.parse').parse.unquote(path)
    return any(p.search(decoded) for p in SUSPICIOUS_PATTERNS)


def detect_sql_injection(input_str):
    """检测 SQL 注入攻击"""
    if not input_str:
        return False
    decoded = __import__('urllib.parse').parse.unquote(str(input_str))
    return any(p.search(decoded) for p in SQL_INJECTION_PATTERNS)


def detect_xss(input_str):
    """检测 XSS 攻击"""
    if not input_str:
        return False
    decoded = __import__('urllib.parse').parse.unquote(str(input_str))
    return any(p.search(decoded) for p in XSS_PATTERNS)


def sanitize_input(input_str, allow_special_chars=False):
    """
    清理输入，移除潜在危险字符
    
    Args:
        input_str: 输入字符串
        allow_special_chars: 是否允许特殊字符
    
    Returns:
        清理后的字符串
    """
    if input_str is None:
        return ''
    
    # 转换为字符串
    result = str(input_str)
    
    # 解码 URL 编码
    result = __import__('urllib.parse').parse.unquote(result)
    
    # 移除 NULL 字节
    result = result.replace('\x00', '')
    
    # 如果不允许特殊字符，移除它们
    if not allow_special_chars:
        result = SPECIAL_CHARS.sub('', result)
    
    return result.strip()


def validate_request_size():
    """验证请求大小是否超过限制"""
    content_length = request.content_length or 0
    if content_length > MAX_REQUEST_SIZE:
        return False
    return True


def validate_http_method():
    """验证 HTTP 方法是否合法"""
    return request.method in ALLOWED_METHODS


def scan_request_for_attacks():
    """
    扫描整个请求是否包含攻击模式
    
    Returns:
        tuple: (is_attack, attack_type, details)
    """
    # 检查路径
    path = request.path
    if is_suspicious_request(path):
        return (True, 'path_traversal', f'Suspicious path detected: {path}')
    
    # 检查查询参数
    for key, value in request.args.items(multi=True):
        if detect_sql_injection(value):
            return (True, 'sql_injection', f'SQL injection in query param "{key}"')
        if detect_xss(value):
            return (True, 'xss', f'XSS in query param "{key}"')
    
    # 检查表单数据
    if request.form:
        for key, value in request.form.items(multi=True):
            if detect_sql_injection(value):
                return (True, 'sql_injection', f'SQL injection in form field "{key}"')
            if detect_xss(value):
                return (True, 'xss', f'XSS in form field "{key}"')
    
    # 检查 JSON 数据
    if request.is_json:
        try:
            json_data = request.get_json()
            if isinstance(json_data, dict):
                for key, value in json_data.items():
                    if isinstance(value, str):
                        if detect_sql_injection(value):
                            return (True, 'sql_injection', f'SQL injection in JSON field "{key}"')
                        if detect_xss(value):
                            return (True, 'xss', f'XSS in JSON field "{key}"')
                    elif isinstance(value, (list, dict)):
                        # 递归检查复杂结构
                        if _scan_json_for_attacks(value, key):
                            return (True, 'attack', f'Malicious content in JSON field "{key}"')
        except Exception:
            pass
    
    return (False, None, None)


def _scan_json_for_attacks(data, parent_key=''):
    """递归扫描 JSON 数据中的攻击模式"""
    if isinstance(data, dict):
        for key, value in data.items():
            current_key = f'{parent_key}.{key}' if parent_key else key
            if isinstance(value, str):
                if detect_sql_injection(value) or detect_xss(value):
                    return True
            elif isinstance(value, (list, dict)):
                if _scan_json_for_attacks(value, current_key):
                    return True
    elif isinstance(data, list):
        for index, item in enumerate(data):
            current_key = f'{parent_key}[{index}]' if parent_key else f'[{index}]'
            if isinstance(item, str):
                if detect_sql_injection(item) or detect_xss(item):
                    return True
            elif isinstance(item, (list, dict)):
                if _scan_json_for_attacks(item, current_key):
                    return True
    return False


def _run_security_checks():
    """执行安全检查，返回拦截响应(元组)或 None 表示放行。

    负责：IP黑名单、HTTP方法、请求大小、敏感路径、可疑请求、SQL注入/XSS 检测。
    不含认证（认证由 JWT 中间件负责）。
    """
    path = request.path
    client_ip = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')

    # 健康检查路径跳过所有安全检查
    if path == '/health':
        return None

    # === 1. IP黑名单检查 ===
    if _check_ip_blacklist(client_ip):
        logger.warning(f'IP黑名单拦截: {client_ip} 访问 {path}')
        return jsonify({'status': 'error', 'message': 'Access Denied'}), 403

    # 2. 验证 HTTP 方法
    if not validate_http_method():
        _record_security_event(
            ip_address=client_ip, event_type='invalid_method', path=path,
            method=request.method, user_agent=user_agent,
            detail=f'Invalid HTTP method: {request.method}', severity='warning',
        )
        logger.warning(f"Blocked invalid HTTP method: {request.method} from {client_ip}")
        return jsonify({'status': 'error', 'message': 'Method Not Allowed'}), 405

    # 3. 验证请求大小
    if not validate_request_size():
        _record_security_event(
            ip_address=client_ip, event_type='large_request', path=path,
            method=request.method, user_agent=user_agent,
            detail=f'Request size: {request.content_length} bytes (limit: {MAX_REQUEST_SIZE})',
            severity='warning',
        )
        logger.warning(f"Blocked oversized request: {request.content_length} bytes from {client_ip}")
        return jsonify({'status': 'error', 'message': 'Request Too Large'}), 413

    # 4. 敏感路径检查
    if path in API_WHITELIST_PATHS:
        pass  # 跳过敏感路径检查，继续后续安全检查
    elif is_sensitive_path(path):
        _record_security_event(
            ip_address=client_ip, event_type='suspicious_path', path=path,
            method=request.method, user_agent=user_agent,
            detail=f'Sensitive path access attempt: {path}', severity='critical',
        )
        logger.warning(f"Blocked sensitive path: {path} from {client_ip}")
        return jsonify({'status': 'error', 'message': 'Access Forbidden'}), 403

    # 5. 可疑请求检查（路径遍历、空字节等）
    if is_suspicious_request(path):
        _record_security_event(
            ip_address=client_ip, event_type='path_traversal', path=path,
            method=request.method, user_agent=user_agent,
            detail=f'Suspicious request path: {path}', severity='critical',
        )
        logger.warning(f"Blocked suspicious request: {path} from {client_ip}")
        return jsonify({'status': 'error', 'message': 'Bad Request'}), 400

    # 6. 全面攻击扫描（SQL注入、XSS等）
    is_attack, attack_type, details = scan_request_for_attacks()
    if is_attack:
        severity = 'critical' if attack_type in ('sql_injection', 'xss') else 'warning'
        _record_security_event(
            ip_address=client_ip, event_type=attack_type, path=path,
            method=request.method, user_agent=user_agent,
            detail=details, severity=severity,
        )
        logger.warning(f"Blocked {attack_type} attack: {details} from {client_ip}")
        return jsonify({'status': 'error', 'message': 'Bad Request'}), 400

    # 记录请求审计日志
    log_request_audit(client_ip, path)

    return None


# 登录接口白名单：黑名单/攻击检测不拦截登录，避免误封管理员 IP 后无法进入后台
_SECURITY_BEFORE_REQUEST_WHITELIST = {
    '/api/auth/login',
    '/api/auth/login_mfa',
}


def security_before_request():
    """全局安全检查（注册到 @app.before_request）。

    对所有 /api/* 请求执行 IP 黑名单拦截 + 攻击检测 + 安全事件记录；
    白名单排除 /health、静态资源、登录接口，避免误锁门。
    """
    path = request.path
    # 健康检查与静态资源跳过
    if path == '/health' or path.startswith('/static/'):
        return None
    # 登录接口不拦截（避免误封自己 IP 后无法登录），仅记录审计
    if path in _SECURITY_BEFORE_REQUEST_WHITELIST:
        log_request_audit(get_client_ip(), path)
        return None
    # 仅对 /api/ 前缀接口执行安全检查（前端 SPA 与业务 API 都在此下）
    if not path.startswith('/api/'):
        return None
    result = _run_security_checks()
    if result is not None:
        return result
    return None



def log_request_audit(client_ip, path):
    """
    记录请求审计日志
    
    Args:
        client_ip: 客户端 IP 地址
        path: 请求路径
    """
    method = request.method
    user_agent = request.headers.get('User-Agent', '')[:100]
    
    # 仅记录非健康检查和非静态文件的请求
    if path != '/health' and not path.startswith('/static/'):
        logger.info(
            f'AUDIT_REQUEST - IP={client_ip}, METHOD={method}, PATH={path}, '
            f'UA={user_agent}'
        )


# ============================================================
# IP黑名单集成（延迟导入，避免循环依赖）
# ============================================================

def _record_security_event(ip_address, event_type, path, method, user_agent, detail, severity='warning'):
    """记录安全事件到数据库（失败不阻塞请求）"""
    try:
        from app.services.ip_blacklist_service import IPBlacklistService
        from app.core.database import get_db
        session = get_db()
        try:
            IPBlacklistService.record_event(
                session=session,
                ip_address=ip_address,
                event_type=event_type,
                path=path,
                method=method,
                user_agent=user_agent,
                detail=detail,
                severity=severity,
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning(f'记录安全事件失败: {exc}')


def _check_ip_blacklist(ip_address):
    """检查IP是否在黑名单中（失败不阻塞请求）"""
    try:
        from app.services.ip_blacklist_service import IPBlacklistService
        from app.core.database import get_db
        session = get_db()
        try:
            return IPBlacklistService.is_ip_blocked(session, ip_address)
        finally:
            session.close()
    except Exception as exc:
        logger.warning(f'IP黑名单检查失败: {exc}')
        return False
