#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证 API 路由蓝图
提供管理员登录、Token 刷新、登出、用户信息查询等接口

端点列表：
- POST /api/auth/login    — 管理员登录，验证密码，返回 JWT 双 token
- POST /api/auth/refresh  — 使用 refresh_token 刷新 access_token
- POST /api/auth/logout   — 撤销当前 token（登出）
- GET  /api/auth/me       — 获取当前登录用户信息

密码存储方案：
- 使用 bcrypt 哈希存储密码
- 哈希文件保存在 data/auth/password.hash
- 首次使用时自动使用 Config.ADMIN_TOKEN（或 JWT_ADMIN_PASSWORD）生成哈希
"""

import os
import bcrypt
import jwt
from collections import defaultdict
import time
from threading import Lock
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, g
from app.core.api_response import api_success, api_error, api_paginate

from app.utils.auth_middleware import jwt_required
from app.utils.security import get_client_ip
from app.core.logger import get_logger
from app.core.extensions import limiter, RATE_LIMITS

# 使用统一日志系统
logger = get_logger(__name__)

# 认证蓝图，挂载前缀 /api/auth
auth_bp = Blueprint('auth', __name__)

# 登录限流：每个 IP 最多 5 次/分钟
_login_attempts = defaultdict(list)
_login_lock = Lock()
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW = 60  # 秒


def _record_login_log(user_id, username, ip_address, user_agent, status='success', failure_reason=None):
    """
    记录登录日志
    
    Args:
        user_id: 用户ID
        username: 用户名
        ip_address: IP地址
        user_agent: 浏览器/设备信息
        status: 登录状态 ('success' 或 'failed')
        failure_reason: 失败原因（可选）
    
    Returns:
        登录日志ID
    """
    from app.core.database import get_db
    from app.model.login_log import LoginLog
    
    session = get_db()
    log_id = None
    try:
        log = LoginLog(
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            failure_reason=failure_reason
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        log_id = log.id
    except Exception as e:
        logger.error(f'记录登录日志失败: {e}')
    finally:
        session.close()
    
    return log_id


def _ip_is_blocked(ip_address):
    """检查 IP 是否已被封禁（检查失败视为未封禁，不阻塞登录）"""
    try:
        from app.services.ip_blacklist_service import IPBlacklistService
        from app.core.database import get_db
        s = get_db()
        try:
            return IPBlacklistService.is_ip_blocked(s, ip_address)
        finally:
            s.close()
    except Exception as exc:
        logger.warning(f'IP 黑名单检查失败: {exc}')
        return False


def _verify_password(user, password):
    """校验密码（bcrypt），异常视为失败"""
    try:
        if not user:
            return False
        return bcrypt.checkpw(
            password.encode('utf-8'),
            user.password_hash.encode('utf-8'),
        )
    except Exception as exc:
        logger.error(f'密码验证异常: {exc}')
        return False


def _record_logout(log_id):
    """
    记录退出时间
    
    Args:
        log_id: 登录日志ID
    """
    if not log_id:
        return
        
    from app.core.database import get_db
    from app.model.login_log import LoginLog
    
    session = get_db()
    try:
        log = session.query(LoginLog).filter_by(id=log_id).first()
        if log:
            log.logout_time = datetime.now()
            session.commit()
        logger.info(f'记录退出时间成功: log_id={log_id}')
    except Exception as e:
        logger.error(f'记录退出时间失败: {e}')
    finally:
        session.close()


def _check_login_rate_limit():
    """检查登录频率限制，超过限制返回错误响应或 None"""
    client_ip = get_client_ip()
    now = time.time()
    
    with _login_lock:
        # 清理过期记录
        _login_attempts[client_ip] = [
            t for t in _login_attempts[client_ip] if now - t < LOGIN_RATE_WINDOW
        ]
        
        if len(_login_attempts[client_ip]) >= LOGIN_RATE_LIMIT:
            return api_error(message=f'登录尝试过于频繁，请在 {LOGIN_RATE_WINDOW} 秒后重试', http_status=429)
        
        _login_attempts[client_ip].append(now)
    
    return None

# 密码哈希文件路径常量
_PASSWORD_HASH_FILE = 'password.hash'


def _get_password_hash_path():
    """
    获取密码哈希文件的完整路径

    Returns:
        str: 密码哈希文件的绝对路径
    """
    auth_dir = current_app.config.get('JWT_AUTH_DATA_DIR', 'data/auth')
    return os.path.join(auth_dir, _PASSWORD_HASH_FILE)


def _ensure_password_hash_exists():
    """
    确保密码哈希文件存在

    如果文件不存在，使用初始密码生成 bcrypt 哈希并写入文件。
    初始密码优先级：JWT_ADMIN_PASSWORD > ADMIN_TOKEN

    Returns:
        str: 密码哈希字符串（bcrypt 格式）
    """
    hash_path = _get_password_hash_path()

    # 如果哈希文件已存在，直接读取
    if os.path.exists(hash_path):
        try:
            with open(hash_path, 'r', encoding='utf-8') as f:
                stored_hash = f.read().strip()
            if stored_hash:
                return stored_hash
        except Exception as e:
            logger.error(f'读取密码哈希文件失败: {e}')

    # 文件不存在或为空，生成初始密码哈希
    # 优先使用 JWT_ADMIN_PASSWORD，为空则使用 ADMIN_TOKEN
    initial_password = current_app.config.get('JWT_ADMIN_PASSWORD', '')
    if not initial_password:
        initial_password = current_app.config.get('ADMIN_TOKEN', '')

    if not initial_password:
        logger.error('无法生成初始密码哈希: JWT_ADMIN_PASSWORD 和 ADMIN_TOKEN 均未设置')
        return None

    # 生成 bcrypt 哈希
    password_bytes = initial_password.encode('utf-8')
    hash_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    stored_hash = hash_bytes.decode('utf-8')

    # 确保目录存在
    auth_dir = os.path.dirname(hash_path)
    os.makedirs(auth_dir, exist_ok=True)

    # 写入文件
    try:
        with open(hash_path, 'w', encoding='utf-8') as f:
            f.write(stored_hash)
        logger.info('初始密码哈希已生成并保存到 data/auth/password.hash')
    except Exception as e:
        logger.error(f'写入密码哈希文件失败: {e}')

    return stored_hash


def _get_jwt_manager():
    """
    获取 JWT 管理器实例

    Returns:
        JWTManager: JWT 管理器实例
    """
    return current_app.extensions.get('jwt_manager')


@auth_bp.route('/login', methods=['POST'])
@limiter.limit(RATE_LIMITS['strict'])
def _login_failure_response(client_ip, username, kind, user_id, user_agent):
    """评估登录失败信号并返回对应响应；返回 None 表示按普通'密码错误'处理。

    kind: 'password'（密码错/账号存在）| 'notfound'（用户名不存在）| 'empty'（空参数）
    信号感知：账号级(按IP+账号)失败→限流该IP(429)；IP跨账号/枚举/总量→限流(429)或临时封禁(403)；
    账号遭多IP围攻→提升账号风险等级(不封IP，避免NAT/校园网误伤)，由 login() 在密码正确时强制 MFA 挑战。
    账号本身永不锁，避免攻击源自锁 admin。
    """
    from app.services.ip_blacklist_service import (
        evaluate_login_failure, IPBlacklistService,
    )
    try:
        dec = evaluate_login_failure(client_ip, username, kind)
    except Exception as exc:
        logger.warning(f'[登录防护] 信号评估异常，按原流程继续: {exc}')
        return None
    if not dec:
        return None

    action = dec['action']
    label = dec['label']
    severity = dec['severity']
    lock_sec = dec.get('lock_seconds') or 300

    from app.core.database import get_db as _gdb
    _bs = _gdb()
    try:
        IPBlacklistService.record_event(
            session=_bs, ip_address=client_ip,
            event_type='login_security', path='/api/auth/login',
            method='POST', user_agent=(user_agent or '')[:200],
            detail=f'{label}({kind}): 第{dec["level"]}级(累计{dec.get("current_count", "?")})',
            severity=severity,
        )

        if action == 'rate_limit':
            IPBlacklistService.send_login_security_alert(client_ip, dec, blocked=False)
            _bs.commit()
            _record_login_log(user_id or 0, username, client_ip, user_agent,
                              'rate_limited', label)
            return api_error(
                message=f'登录尝试过于频繁，请 {max(lock_sec // 60, 1)} 分钟后再试',
                http_status=429,
                headers={'Retry-After': str(lock_sec)},
            )

        if action == 'temp_block':
            source = dec.get('source') or 'login_brute_tier2'
            dur_h = dec.get('duration_hours')
            if dec.get('scope') == 'account_target':
                reason = f'{label}(账号 {username} 遭 {dec.get("current_count")} 个不同IP围攻)'
            else:
                reason = f'{label}(5分钟内{dec.get("current_count")}个不同账号失败)'
            target_ips = dec.get('target_ips') or [client_ip]
            for tip in target_ips:
                if not tip:
                    continue
                IPBlacklistService.block_ip(
                    session=_bs, ip_address=tip, reason=reason,
                    source=source, created_by='auto-detect',
                    duration_hours=dur_h, note='登录信号感知自动封禁',
                )
            IPBlacklistService._send_block_alert(client_ip, reason, source, tier_info=dec)
            _bs.commit()
            _record_login_log(user_id or 0, username, client_ip, user_agent, 'blocked', label)
            return api_error(message='拒绝访问', http_status=403)

        if action == 'account_risk':
            # 账号风险升级（不封 IP）：仅告警，不阻断登录；密码正确后将强制 MFA 挑战
            IPBlacklistService.send_login_security_alert(client_ip, dec, blocked=False)
            _bs.commit()
            return None
    finally:
        _bs.close()
    return None


def login():
    """
    管理员登录接口

    请求格式：
        POST /api/auth/login
        Content-Type: application/json
        {
            "username": "admin",
            "password": "your_password"
        }

    成功响应 (200):
        {
            "status": "success",
            "user": {
                "id": "admin",
                "username": "admin",
                "role": "admin"
            }
        }
        
    MFA 要求响应 (200):
        {
            "status": "mfa_required",
            "message": "请输入MFA验证码",
            "mfa_token": "临时令牌"
        }
    """
    # 获取客户端信息
    client_ip = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')

    # 限流检查
    rate_limit_error = _check_login_rate_limit()
    if rate_limit_error:
        return rate_limit_error

    # 解析请求体
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    # IP 黑名单拦截：被封禁 IP 直接拒绝，不再产生“密码错误”登录日志，避免暴力破解与日志污染
    # 仅保留“持有正确凭据的管理员”自助解封通道（避免误封自己 IP 后无法登录）
    if _ip_is_blocked(client_ip):
        if not (username and password):
            _record_login_log(0, username or '(空)', client_ip, user_agent, 'blocked', 'IP 已被封禁')
            return api_error(message='拒绝访问', http_status=403)
        # 查用户并校验密码，决定是否放行（自助解封通道）
        from app.model.user import User
        from app.core.database import get_db
        _s = get_db()
        try:
            _u = _s.query(User).filter_by(username=username, is_active=True).first()
            _ok = _verify_password(_u, password)
        finally:
            _s.close()
        if not _ok:
            logger.warning(f'登录被拦截: 封禁 IP {client_ip} 凭据无效')
            _record_login_log(_u.id if _u else 0, username, client_ip, user_agent, 'blocked', 'IP 已被封禁')
            return api_error(message='拒绝访问', http_status=403)
        # 被封禁 IP 凭正确凭据登录（管理员自助解封通道）
        logger.warning(f'被封禁 IP {client_ip} 凭正确凭据登录，进入自助解封通道')

    # 参数校验
    if not username or not password:
        _r = _login_failure_response(client_ip, username, 'empty', 0, user_agent)
        if _r:
            return _r
        logger.warning('登录失败: 用户名或密码为空')
        # 记录失败日志
        _record_login_log(0, username, client_ip, user_agent, 'failed', '用户名或密码为空')
        return api_error(message='用户名或密码错误', http_status=401)

    # 从数据库查找用户
    from app.core.database import get_db
    from app.model.user import User
    from app.model.user_mfa import UserMFA

    session = get_db()
    try:
        user = session.query(User).filter_by(username=username, is_active=True).first()
    finally:
        session.close()

    if not user:
        _r = _login_failure_response(client_ip, username, 'notfound', 0, user_agent)
        if _r:
            return _r
        logger.warning(f'登录失败: 用户不存在或已禁用 (input={username})')
        _record_login_log(0, username, client_ip, user_agent, 'failed', '用户不存在或已禁用')
        return api_error(message='用户名或密码错误', http_status=401)

    # 使用 bcrypt 验证密码
    try:
        password_bytes = password.encode('utf-8')
        hash_bytes = user.password_hash.encode('utf-8')
        if not bcrypt.checkpw(password_bytes, hash_bytes):
            # ===== 密码错误 → 信号感知处置 =====
            _r = _login_failure_response(client_ip, username, 'password', user.id, user_agent)
            if _r:
                return _r

            # 未触发任何信号 → 原有"密码错误"返回
            logger.warning(f'登录失败: 密码验证失败 (user={username})')
            _record_login_log(user.id, username, client_ip, user_agent, 'failed', '密码错误')
            return api_error(message='用户名或密码错误', http_status=401)

        # ===== 密码正确 → 重置登录计数 =====
        try:
            from app.services.ip_blacklist_service import reset_login_counters
            reset_login_counters(client_ip, username)
        except Exception:
            pass  # 重置失败不阻塞正常登录
    except Exception as e:
        logger.error(f'密码验证异常: {e}')
        _record_login_log(user.id, username, client_ip, user_agent, 'failed', f'验证异常: {e}')
        return api_error(message='服务器内部错误', http_status=500)

    # 检查是否启用了 MFA
    session = get_db()
    try:
        user_mfa = session.query(UserMFA).filter_by(user_id=str(user.id)).first()
        mfa_enabled = user_mfa and user_mfa.enabled
    finally:
        session.close()

    # 强制管理员 MFA（v6.11.0）：管理员必须启用 MFA 才能完整登录；
    # 首次引导——系统内尚无任何已启用 MFA 的用户时放行，但要求先完成 MFA 设置，避免永久锁死。
    _require_mfa_setup = False
    if user.role == 'admin' and not mfa_enabled and current_app.config.get('FORCE_ADMIN_MFA', True):
        from app.core.database import get_db as _gdb2
        from app.model.user_mfa import UserMFA as _UMFA
        _s2 = _gdb2()
        try:
            _any_mfa_enabled = _s2.query(_UMFA).filter_by(enabled=True).first() is not None
        finally:
            _s2.close()
        if _any_mfa_enabled:
            logger.warning(f'管理员 {username} 未启用 MFA，已拒绝登录（强制 MFA 策略）')
            _record_login_log(user.id, username, client_ip, user_agent, 'failed', '管理员未启用 MFA')
            return api_error(
                message='管理员账户已强制启用多因素认证(MFA)。请先在个人中心完成 MFA 设置后再登录；若无法自助设置，请联系已有 MFA 权限的管理员协助。',
                http_status=423,
            )
        # 首次引导：系统内尚无任何已启用 MFA 的用户 → 放行但要求完成 MFA 设置
        _require_mfa_setup = True

    if mfa_enabled:
        # 生成临时 MFA token（10分钟有效期）
        jwt_manager = _get_jwt_manager()
        if not jwt_manager:
            logger.error('登录失败: JWT 管理器未初始化')
            return api_error(message='服务器配置错误', http_status=500)
        
        # 使用 JWT 编码 mfa_token，避免依赖 session（支持跨域请求）
        mfa_payload = {
            'user_id': str(user.id),
            'username': user.username,
            'role': user.role,
            'ip': client_ip,
            'agent': user_agent,
            'remember_me': bool(data.get('remember_me', False)),
            'exp': int(time.time()) + 600,  # 10分钟过期
            'type': 'mfa'
        }
        mfa_token = jwt.encode(mfa_payload, current_app.config['SECRET_KEY'], algorithm='HS256')
        
        logger.info(f'用户 {username} 密码验证通过，需要 MFA 验证')
        return api_success(status='mfa_required', message='请输入MFA验证码', mfa_token=mfa_token)

    # 更新当前登录信息（需在同一 session 内重新查询，避免 detached instance 问题）
    from app.model.login_log import LoginLog
    session = get_db()
    try:
        db_user = session.query(User).filter_by(id=user.id).first()
        if db_user:
            db_user.last_login = datetime.now()
            db_user.last_login_ip = client_ip
            session.commit()
        # 自动关闭该用户上一个未结束的登录会话
        prev_log = session.query(LoginLog).filter(
            LoginLog.user_id == user.id,
            LoginLog.logout_time.is_(None),
            LoginLog.status == 'success'
        ).order_by(LoginLog.login_time.desc()).first()
        if prev_log:
            prev_log.logout_time = datetime.now()
            session.commit()
    finally:
        session.close()
    
    # 记录成功登录日志并获取ID
    login_log_id = _record_login_log(user.id, username, client_ip, user_agent, 'success')

    # 密码验证通过且无需 MFA，直接生成 JWT token
    jwt_manager = _get_jwt_manager()
    if not jwt_manager:
        logger.error('登录失败: JWT 管理器未初始化')
        return api_error(message='服务器配置错误', http_status=500)

    # 记住我：默认不勾选 = 短会话（服务端 24h / JWT 闲置 2h / 绝对 1d）；
    # 勾选 = 长会话（服务端 30d / JWT 闲置 7d / 绝对 30d）。
    remember_me = bool(data.get('remember_me', False))
    idle_expire, absolute_expire = (
        (7 * 24 * 3600, 30 * 24 * 3600) if remember_me else (2 * 3600, 1 * 24 * 3600)
    )

    tokens = jwt_manager.generate_tokens(
        user_id=str(user.id),
        username=user.username,
        role=user.role,
        login_log_id=login_log_id,
        idle_expire=idle_expire,
        absolute_expire=absolute_expire,
    )

    # 创建服务端 Session（可撤销会话登记；过期随 remember_me：勾选 30 天，否则 24 小时）
    from app.services.session_service import session_service
    session_obj = session_service.create_session(
        user_id=user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        remember_me=remember_me,
    )
    session_id = session_obj.session_id if session_obj else None

    # 单会话策略：登录成功即踢掉该用户的其他所有活跃会话（保留当前），
    # 实现“同一用户同一时刻只能一处在线”，新登录挤掉旧登录。
    # 记录撤销原因与“踢人设备IP”，供被踢的旧设备弹框显示。
    try:
        if session_id:
            session_service.delete_all_user_sessions(
                user.id, except_session_id=session_id, reason='new_login', by_ip=client_ip
            )
    except Exception as e:
        logger.warning(f'清理旧会话失败（不影响登录）: {e}')

    # 根据用户角色生成日志消息
    role_display = '管理员' if user.role == 'admin' else '用户'
    logger.info(f'{role_display}登录成功: user={username}')

    # 创建响应
    resp_kwargs = {}
    if _require_mfa_setup:
        resp_kwargs['mfa_setup_required'] = True
    response, _ = api_success(user=user.to_dict(), **resp_kwargs)

    # 设置 httpOnly cookie（防止 XSS）
    from datetime import timedelta
    
    # 根据环境决定是否启用 secure（HTTP 环境下不启用）
    is_https = current_app.config.get('FORCE_HTTPS', False)
    # 本地开发使用宽松设置，服务器使用严格设置
    cookie_secure = is_https
    cookie_samesite = 'Lax' if is_https else None
    
    # access_token cookie - 1小时
    response.set_cookie(
        'access_token',
        tokens['access_token'],
        httponly=True,  # 防止 JavaScript 访问
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=tokens['expires_in'],
        path='/'
    )
    
    # refresh_token cookie - 7天
    response.set_cookie(
        'refresh_token',
        tokens['refresh_token'],
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=7 * 24 * 3600,
        path='/'  # 本地开发允许所有路径
    )

    # session_id cookie - 与 Session 过期对齐（remember_me 时 30 天）
    if session_id:
        response.set_cookie(
            'session_id',
            session_id,
            httponly=True,
            secure=cookie_secure,
            samesite=cookie_samesite,
            max_age=(30 if remember_me else 1) * 24 * 3600,
            path='/'
        )

    return response


@auth_bp.route('/refresh', methods=['POST'])
@limiter.limit(RATE_LIMITS['moderate'])
def refresh():
    """
    刷新 access_token 接口

    从 httpOnly cookie 中读取 refresh_token

    成功响应 (200):
        {
            "status": "success",
            "message": "令牌已刷新"
        }

    失败响应 (401):
        {
            "status": "error",
            "message": "刷新令牌无效或已过期"
        }
    """
    # 从 cookie 读取 refresh_token
    refresh_token = request.cookies.get('refresh_token', '').strip()

    if not refresh_token:
        logger.warning('Token 刷新失败: refresh_token cookie 为空')
        return api_error(message='请提供 refresh_token', http_status=401)

    jwt_manager = _get_jwt_manager()
    if not jwt_manager:
        return api_error(message='服务器配置错误', http_status=500)

    # 服务端 Session 联动校验：若携带 session_id 且对应会话已失效（被踢/过期），
    # 刷新也返回 401，强制前端重新登录。返回结构化撤销原因（含踢人设备IP）。
    # 破解“旧会话被踢后无限刷新”的死循环：jwt_required 因 session 失效返回 401
    # → 前端自动调 /refresh → 若 refresh 不校验 session 则永远成功 → 死循环。
    # Bearer token 调用（无 session_id cookie）跳过，保持向后兼容。
    sid = request.cookies.get('session_id')
    if sid:
        try:
            from app.services.session_service import session_service
            detail = session_service.get_session_detail(sid)
            if detail['status'] != 'active':
                reason = detail.get('reason')
                ip = detail.get('ip')
                if reason == 'new_login':
                    msg = (f'登录会话已在其他设备（IP：{ip}）登录，当前会话已失效，请重新登录'
                           if ip else '登录会话已在其他设备登录，当前会话已失效，请重新登录')
                elif reason == 'expired':
                    msg = '登录会话已过期，请重新登录'
                elif reason == 'admin_revoke':
                    msg = '会话已被管理员强制下线，请重新登录'
                else:
                    msg = '登录会话已失效，请重新登录'
                logger.warning(f'Token 刷新失败: 关联 Session 已失效 (session_id={sid}, reason={reason})')
                return api_error(message=msg, http_status=401, revoke_reason=reason, revoke_ip=ip)
        except Exception as e:
            # DB 异常时不阻断，避免基础设施抖动导致全站无法刷新
            logger.error(f'刷新时 Session 校验异常（已跳过）: {e}')

    try:
        new_tokens = jwt_manager.refresh_access_token(refresh_token)
    except jwt.ExpiredSignatureError:
        logger.warning('Token 刷新失败: refresh_token 已过期')
        return api_error(message='刷新令牌已过期，请重新登录', http_status=401)
    except (jwt.InvalidTokenError, ValueError) as e:
        msg = str(e)
        if 'idle timeout' in msg:
            message = '登录会话已闲置过久，请重新登录'
        elif 'absolute expiry' in msg:
            message = '登录会话已过期，请重新登录'
        else:
            message = '刷新令牌无效'
        logger.warning(f'Token 刷新失败: {e}')
        return api_error(message=message, http_status=401)

    new_access_token = new_tokens['access_token']
    new_refresh_token = new_tokens['refresh_token']

    logger.info('access_token 刷新成功')

    # 设置新的 access_token cookie
    response, _ = api_success(message='令牌已刷新')

    is_https = current_app.config.get('FORCE_HTTPS', False)
    cookie_secure = is_https
    cookie_samesite = 'Lax' if is_https else None

    response.set_cookie(
        'access_token',
        new_access_token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=jwt_manager.access_token_expire,
        path='/'
    )

    # 轮换 refresh_token：写入新令牌，旧的已在 refresh_access_token 内撤销
    response.set_cookie(
        'refresh_token',
        new_refresh_token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=jwt_manager.refresh_token_expire,
        path='/'
    )

    return response


@auth_bp.route('/session/status', methods=['GET'])
def session_status():
    """
    会话健康心跳：返回当前 session 是否有效及撤销原因（含踢人设备IP）。

    设计：
    - 不挂 @jwt_required，仅读取请求自带的 session_id cookie，避免“旧会话失效
      → 401 → 自动刷新 → 又 401”的死循环；且只反映调用者自己的会话，无安全风险。
    - 始终返回 200（success），valid=false 时由前端弹框并跳登录；这样响应拦截器
      不会把它当错误，空闲时也能被前端心跳及时探知被踢。
    """
    sid = request.cookies.get('session_id')
    if not sid:
        return api_success(data={'valid': False, 'reason': 'no_session'})
    from app.services.session_service import session_service
    detail = session_service.get_session_detail(sid)
    if detail['status'] == 'active':
        return api_success(data={'valid': True})
    return api_success(data={
        'valid': False,
        'reason': detail.get('reason'),
        'ip': detail.get('ip'),
        'time': detail.get('time'),
    })


@auth_bp.route('/logout', methods=['POST'])
@jwt_required
def logout():
    """
    登出接口（撤销当前 token 并清除 cookie）

    成功响应 (200):
        {
            "status": "success",
            "message": "已成功登出"
        }
    """
    jwt_manager = _get_jwt_manager()

    # 从 cookie 中提取 token 并撤销
    token = request.cookies.get('access_token', '')

    # 记录退出时间
    login_log_id = g.current_user.get('login_log_id')
    if login_log_id:
        _record_logout(login_log_id)

    if token and jwt_manager:
        jwt_manager.revoke_token(token)

    # 同时撤销 refresh_token，避免仅清 cookie 而 refresh 仍在黑名单外、可长期续期
    refresh_token = request.cookies.get('refresh_token', '')
    if refresh_token and jwt_manager:
        jwt_manager.revoke_token(refresh_token, reason='logout_refresh')

    # 撤销服务端 Session（让"查看/撤销活跃会话"实时生效）
    sid = request.cookies.get('session_id', '')
    if sid:
        from app.services.session_service import session_service
        session_service.delete_session(sid)

    username = g.current_user.get('username', 'unknown')
    role = g.current_user.get('role', 'user')
    role_display = '管理员' if role == 'admin' else '用户'
    logger.info(f'{role_display}登出: user={username}')

    # 清除 cookies（path 需与登录时设置保持一致，否则清不掉）
    response, _ = api_success(message='已成功登出')

    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/')
    response.delete_cookie('session_id', path='/')

    return response


@auth_bp.route('/me')
@jwt_required
def me():
    """
    获取当前用户信息接口

    请求格式：
        GET /api/auth/me
        Authorization: Bearer <access_token>

    成功响应 (200):
        {
            "status": "success",
            "user": {
                "id": "admin",
                "username": "admin",
                "nickname": "昵称",
                "email": "邮箱",
                "avatar": "头像",
                "role": "admin"
            }
        }
    """
    user_id = g.current_user.get('user_id')
    
    # 从数据库获取最新的用户信息
    from app.core.database import get_db
    from app.model.user import User
    
    session = get_db()
    try:
        user = session.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return api_error(message='用户不存在', http_status=404)
        
        return api_success(user=user.to_dict())
    finally:
        session.close()


@auth_bp.route('/login/mfa', methods=['POST'])
@limiter.limit(RATE_LIMITS['strict'])
def login_mfa():
    """
    MFA 验证登录接口

    请求格式：
        POST /api/auth/login/mfa
        Content-Type: application/json
        {
            "mfa_token": "临时令牌",
            "code": "6位验证码"
        }

    成功响应 (200):
        {
            "status": "success",
            "user": {
                "id": "admin",
                "username": "admin",
                "role": "admin"
            }
        }
    """
    data = request.get_json(silent=True) or {}
    mfa_token = data.get('mfa_token', '').strip()
    code = data.get('code', '').strip()

    if not mfa_token or not code:
        return api_error(message='请提供MFA令牌和验证码', http_status=400)

    # 验证临时 MFA token（JWT 编码，不依赖 session，支持跨域）
    try:
        pending_data = jwt.decode(mfa_token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return api_error(message='MFA令牌已过期，请重新登录', http_status=400)
    except jwt.InvalidTokenError:
        return api_error(message='MFA令牌无效，请重新登录', http_status=400)
    
    if pending_data.get('type') != 'mfa':
        return api_error(message='MFA令牌类型错误', http_status=400)
    
    # 获取客户端信息（优先使用 MFA 下发时记录的 IP，其次取真实客户端 IP）
    client_ip = pending_data.get('ip') or get_client_ip()
    user_agent = pending_data.get('agent', request.headers.get('User-Agent', ''))
    
    # 验证 MFA 代码
    from app.utils.mfa import mfa_manager
    from app.core.database import get_db
    from app.model.user_mfa import UserMFA
    from app.model.user import User
    
    user_id = pending_data.get('user_id')
    username = pending_data.get('username')
    session = get_db()
    try:
        user_mfa = session.query(UserMFA).filter_by(user_id=user_id).first()
        user = session.query(User).filter_by(id=int(user_id)).first()
    finally:
        session.close()
    
    if not user_mfa or not user_mfa.secret:
        return api_error(message='MFA未配置', http_status=400)
    
    if not mfa_manager.verify_mfa(user_mfa.secret, code):
        logger.warning(f'MFA验证失败: user_id={user_id}')
        # 记录失败日志
        _record_login_log(int(user_id), username, client_ip, user_agent, 'failed', 'MFA验证码错误')
        return api_error(message='验证码错误，请重试', http_status=401)
    
    # MFA 验证通过（JWT token 一次性使用，无需清理）
    
    # 更新当前登录信息（需在同一 session 内重新查询，避免 detached instance 问题）
    from app.model.login_log import LoginLog
    session = get_db()
    try:
        db_user = session.query(User).filter_by(id=int(user_id)).first()
        if db_user:
            db_user.last_login = datetime.now()
            db_user.last_login_ip = client_ip
            session.commit()
        # 自动关闭该用户上一个未结束的登录会话
        prev_log = session.query(LoginLog).filter(
            LoginLog.user_id == int(user_id),
            LoginLog.logout_time.is_(None),
            LoginLog.status == 'success'
        ).order_by(LoginLog.login_time.desc()).first()
        if prev_log:
            prev_log.logout_time = datetime.now()
            session.commit()
    finally:
        session.close()
    
    # 记录成功登录日志并获取ID
    login_log_id = _record_login_log(int(user_id), username, client_ip, user_agent, 'success')
    
    # 生成 JWT token（MFA 路径同样按 remember_me 决定长短会话）
    jwt_manager = _get_jwt_manager()
    remember_me = bool(pending_data.get('remember_me', False))
    idle_expire, absolute_expire = (
        (7 * 24 * 3600, 30 * 24 * 3600) if remember_me else (2 * 3600, 1 * 24 * 3600)
    )
    tokens = jwt_manager.generate_tokens(
        user_id=user_id,
        username=pending_data.get('username'),
        role=pending_data.get('role'),
        login_log_id=login_log_id,
        idle_expire=idle_expire,
        absolute_expire=absolute_expire,
    )

    # 创建服务端 Session（MFA 登录路径同样登记；过期随 remember_me：勾选 30 天，否则 24 小时）
    from app.services.session_service import session_service
    session_obj = session_service.create_session(
        user_id=int(user_id),
        ip_address=client_ip,
        user_agent=user_agent,
        remember_me=remember_me,
    )
    session_id = session_obj.session_id if session_obj else None

    # 单会话策略：登录成功即踢掉该用户的其他所有活跃会话（保留当前），
    # 实现“同一用户同一时刻只能一处在线”，新登录挤掉旧登录。
    # 记录撤销原因与“踢人设备IP”，供被踢的旧设备弹框显示。
    try:
        if session_id:
            session_service.delete_all_user_sessions(
                user.id, except_session_id=session_id, reason='new_login', by_ip=client_ip
            )
    except Exception as e:
        logger.warning(f'清理旧会话失败（不影响登录）: {e}')

    # 根据用户角色生成日志消息
    role_display = '管理员' if user.role == 'admin' else '用户'
    logger.info(f'{role_display}登录成功（MFA验证通过）: user={username}')
    
    # 创建响应
    response, _ = api_success(user=user.to_dict())

    # 设置 httpOnly cookie
    from datetime import timedelta
    is_https = current_app.config.get('FORCE_HTTPS', False)
    cookie_secure = is_https
    cookie_samesite = 'Lax' if is_https else None

    logger.info(f'[DEBUG] 设置 Cookie: secure={cookie_secure}, samesite={cookie_samesite}, expires_in={tokens["expires_in"]}')

    response.set_cookie(
        'access_token',
        tokens['access_token'],
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=tokens['expires_in'],
        path='/'
    )

    response.set_cookie(
        'refresh_token',
        tokens['refresh_token'],
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=7 * 24 * 3600,
        path='/'
    )

    # session_id cookie - 30 天（与 JWT 绝对上限对齐）
    if session_id:
        response.set_cookie(
            'session_id',
            session_id,
            httponly=True,
            secure=cookie_secure,
            samesite=cookie_samesite,
            max_age=30 * 24 * 3600,
            path='/'
        )

    logger.info('[DEBUG] Cookie 设置完成')

    return response


# ========== MFA 多因素认证接口 ==========

@auth_bp.route('/mfa/setup', methods=['POST'])
@jwt_required
def mfa_setup():
    """
    设置 MFA
    
    生成 MFA 密钥和二维码 URI
    
    成功响应 (200):
        {
            "status": "success",
            "data": {
                "secret": "JBSWY3DPEHPK3PXP",
                "provisioning_uri": "otpauth://totp/...",
                "qr_code_base64": "data:image/png;base64,..."
            }
        }
    """
    from app.utils.mfa import mfa_manager
    from app.core.database import get_db
    from app.model.user_mfa import UserMFA
    import qrcode
    import io
    import base64
    
    user_id = g.current_user.get('user_id')
    username = g.current_user.get('username') or str(user_id)
    
    # 生成 MFA 配置
    mfa_config = mfa_manager.setup_mfa(username)
    
    # 保存到数据库（未启用状态）
    session = get_db()
    try:
        user_mfa = session.query(UserMFA).filter_by(user_id=user_id).first()
        if not user_mfa:
            user_mfa = UserMFA(user_id=user_id)
            session.add(user_mfa)
        
        user_mfa.secret = mfa_config['secret']
        user_mfa.enabled = False  # 需要验证后才启用
        session.commit()
    finally:
        session.close()
    
    # 本地生成二维码（替代外部 API，避免网络问题）
    qr = qrcode.QRCode(
        version=3,  # 固定小版本
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # 使用低错误校正
        box_size=12,  # 增大方块尺寸
        border=6,  # 增大边框
    )
    qr.add_data(mfa_config['provisioning_uri'])
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # 转换为 Base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    qr_code_data_url = f"data:image/png;base64,{qr_code_base64}"
    
    return api_success(message='请使用 Google Authenticator 或类似应用扫描二维码', data={'secret': mfa_config['secret'], 'provisioning_uri': mfa_config['provisioning_uri'], 'qr_code_base64': qr_code_data_url})


@auth_bp.route('/mfa/verify', methods=['POST'])
@jwt_required
def mfa_verify():
    """
    验证 MFA 代码并启用 MFA
    
    请求体：
        {
            "code": "123456"
        }
    
    成功响应 (200):
        {
            "status": "success",
            "message": "MFA 已启用"
        }
    """
    from app.utils.mfa import mfa_manager
    from app.core.database import get_db
    from app.model.user_mfa import UserMFA
    
    user_id = g.current_user.get('user_id')
    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    
    if not code:
        return api_error(message='请提供 MFA 代码', http_status=400)
    
    # 获取用户 MFA 配置
    session = get_db()
    try:
        user_mfa = session.query(UserMFA).filter_by(user_id=user_id).first()
        
        if not user_mfa or not user_mfa.secret:
            return api_error(message='请先设置 MFA', http_status=400)
        
        # 验证代码
        if not mfa_manager.verify_mfa(user_mfa.secret, code):
            return api_error(message='MFA 代码无效', http_status=401)
        
        # 启用 MFA
        user_mfa.enabled = True
        session.commit()
        
        logger.info(f'用户 {user_id} 已启用 MFA')
        
        return api_success(message='MFA 已启用')
    finally:
        session.close()


@auth_bp.route('/mfa/disable', methods=['POST'])
@jwt_required
def mfa_disable():
    """
    禁用 MFA
    
    请求体：
        {
            "code": "123456"
        }
    
    成功响应 (200):
        {
            "status": "success",
            "message": "MFA 已禁用"
        }
    """
    from app.utils.mfa import mfa_manager
    from app.core.database import get_db
    from app.model.user_mfa import UserMFA
    
    user_id = g.current_user.get('user_id')
    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    
    if not code:
        return api_error(message='请提供 MFA 代码', http_status=400)
    
    # 获取用户 MFA 配置
    session = get_db()
    try:
        user_mfa = session.query(UserMFA).filter_by(user_id=user_id).first()
        
        if not user_mfa or not user_mfa.enabled:
            return api_error(message='MFA 未启用', http_status=400)
        
        # 验证代码
        if not mfa_manager.verify_mfa(user_mfa.secret, code):
            return api_error(message='MFA 代码无效', http_status=401)
        
        # 禁用 MFA
        user_mfa.enabled = False
        user_mfa.secret = None
        session.commit()
        
        logger.info(f'用户 {user_id} 已禁用 MFA')
        
        return api_success(message='MFA 已禁用')
    finally:
        session.close()


@auth_bp.route('/mfa/status', methods=['GET'])
@jwt_required
def mfa_status():
    """
    获取 MFA 状态
    
    成功响应 (200):
        {
            "status": "success",
            "data": {
                "enabled": true
            }
        }
    """
    from app.core.database import get_db
    from app.model.user_mfa import UserMFA
    
    user_id = g.current_user.get('user_id')
    
    session = get_db()
    try:
        user_mfa = session.query(UserMFA).filter_by(user_id=user_id).first()
        
        return api_success(data={'enabled': user_mfa.enabled if user_mfa else False})
    finally:
        session.close()


# ========== 密码管理接口 ==========

@auth_bp.route('/change-password', methods=['POST'])
@jwt_required
def change_password():
    """
    修改密码
    
    请求体：
        {
            "old_password": "旧密码",
            "new_password": "新密码"
        }
    
    成功响应 (200):
        {
            "status": "success",
            "message": "密码已修改"
        }
    """
    from app.core.database import get_db
    from app.model.user import User
    
    user_id = g.current_user.get('user_id')
    data = request.get_json(silent=True) or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    
    if not old_password or not new_password:
        return api_error(message='请提供旧密码和新密码', http_status=400)
    
    if len(new_password) < 6:
        return api_error(message='新密码长度不能少于6位', http_status=400)
    
    session = get_db()
    try:
        user = session.query(User).filter_by(id=int(user_id)).first()
        if not user:
            return api_error(message='用户不存在', http_status=404)
        
        # 验证旧密码
        if not bcrypt.checkpw(old_password.encode('utf-8'), user.password_hash.encode('utf-8')):
            return api_error(message='旧密码错误', http_status=401)
        
        # 更新密码
        user.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        session.commit()
        
        logger.info(f'用户 {user.username} 修改了密码')
        
        return api_success(message='密码已修改，请重新登录')
    finally:
        session.close()
