#!/usr/bin/env python3
"""应用启动期引导（建库 / 建默认管理员 / 指纹自动迁移）

把 create_app 中「启动期副作用」收敛到本模块，职责单一、可独立测试：
- run_bootstrap(app)：建表、补列、清僵尸进程、写默认配置与管理员、指纹自动迁移/清理
- flask bootstrap：显式 CLI 命令，等价于「手动跑一次 run_bootstrap」
- create_app 默认仍调用 run_bootstrap（受 AUTO_MIGRATE_ON_START 开关控制），
  以便灰度/排障时可关闭自动引导，改为人工执行 flask bootstrap。
"""

import os
import uuid

import click
import redis as _redis_mod
from flask import current_app
from flask.cli import with_appcontext

from app.core.config import Config
from app.core.logger import get_logger

logger = get_logger(__name__)


# ── 启动期数据库指纹自动迁移/清理的 Redis 分布式锁 ──────────────────
# 启动期指纹检查位于 create_app 内、每个 gunicorn worker 都会执行一遍；
# 若无并发控制，多 worker 同时 ALTER 同一表会触发元数据锁(MDL)竞争甚至
# 启动卡死。用 Redis 单飞锁保证仅一个进程执行自动迁移/清理。
_BOOTSTRAP_FP_LOCK_KEY = "push_system:bootstrap:fingerprint_migrate"
_BOOTSTRAP_FP_LOCK_TTL = 600  # 秒；足够一次迁移/清理完成，超时自动释放防死锁


def _try_acquire_fingerprint_lock():
    """尝试获取启动期指纹自动迁移分布式锁。

    返回:
        token(str)  —— 获取成功，调用方执行后须释放
        '__other__'  —— 锁已被其他进程持有，本进程应跳过
        None         —— Redis 不可用（无 REDIS_URL 或连接异常），降级为本地直接执行
    """
    url = getattr(Config, "REDIS_URL", None) or os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        client = _redis_mod.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        token = uuid.uuid4().hex
        if client.set(_BOOTSTRAP_FP_LOCK_KEY, token, nx=True, ex=_BOOTSTRAP_FP_LOCK_TTL):
            return token
        return "__other__"
    except Exception:
        return None


def _release_fingerprint_lock(token):
    """释放锁（仅删除自己持有的那把）。token 为 None/'__other__' 时 no-op。"""
    if not token or token == "__other__":
        return
    url = getattr(Config, "REDIS_URL", None) or os.getenv("REDIS_URL")
    if not url:
        return
    try:
        client = _redis_mod.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        # 仅当锁值仍为自己时删除，避免误删他人锁
        client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
            "else return 0 end",
            1,
            _BOOTSTRAP_FP_LOCK_KEY,
            token,
        )
    except Exception:
        pass


def _run_fingerprint_auto_fix(session):
    """启动期数据库指纹漂移检测与自动迁移/清理（仅在持锁时调用）。"""
    try:
        from app.core.db_fingerprint import check_db_fingerprint, summarize_diff

        fp = check_db_fingerprint(session)
        if not fp["match"]:
            # 不一致：先跑自动迁移修复 schema 漂移（补表/补列/补索引）
            logger.info(f"[数据库指纹] 实例与定义不一致，正在自动迁移… " f"({summarize_diff(fp)})")
            try:
                from init_db import cmd_migrate

                cmd_migrate(quiet=True)
            except Exception as me:
                logger.error(f"[数据库指纹] 自动迁移执行异常: {me}")
            # 迁移后重检（expire 避免 ORM 缓存干扰 INFORMATION_SCHEMA 读取）
            session.expire_all()
            fp2 = check_db_fingerprint(session)
            if fp2["match"]:
                logger.info(f'[数据库指纹] 自动迁移后一致 (码={fp2["definition_hash"][:12]}…)')
            else:
                # migrate 只补不删：尝试自动 cleanup 清除多余表/列/配置键/类型差异
                logger.warning(
                    f"[数据库指纹] 自动迁移后仍有差异，正在自动清理… " f"({summarize_diff(fp2)})"
                )
                try:
                    from init_db import cmd_cleanup

                    cmd_cleanup(auto=True, quiet=True)
                except Exception as ce:
                    logger.error(f"[数据库指纹] 自动清理执行异常: {ce}")
                session.expire_all()
                fp3 = check_db_fingerprint(session)
                if fp3["match"]:
                    logger.info(f'[数据库指纹] 自动清理后一致 (码={fp3["definition_hash"][:12]}…)')
                else:
                    logger.warning(
                        f"[数据库指纹] 自动清理后仍有差异 ({summarize_diff(fp3)})，"
                        f"请手动检查后执行 python init_db.py cleanup"
                    )
        else:
            logger.info(f'[数据库指纹] 实例与定义一致，跳过迁移 (码={fp["definition_hash"][:12]}…)')
    except Exception as e:
        logger.warning(f"[数据库指纹] 比对失败（不影响启动）: {e}")
    finally:
        session.close()


def _run_fingerprint_auto_fix_with_lock(session):
    """带分布式锁地执行启动期指纹自动迁移/清理。"""
    token = _try_acquire_fingerprint_lock()
    if token is None:
        # Redis 不可用：降级本地直接执行（无并发保护，但保证可用）
        logger.warning("[数据库指纹] Redis 不可用，降级为本地直接执行自动迁移/清理（无并发保护）")
        _run_fingerprint_auto_fix(session)
    elif token == "__other__":
        logger.info(
            "[数据库指纹] 其他进程正在执行自动迁移/清理，本进程跳过（避免并发元数据锁竞争）"
        )
    else:
        try:
            _run_fingerprint_auto_fix(session)
        finally:
            _release_fingerprint_lock(token)


def run_bootstrap(app):
    """执行启动期引导：建表、补列、清僵尸进程、写默认配置与管理员、指纹自动迁移。

    等价于旧版 create_app 中「初始化数据库 → 建默认管理员 → 指纹比对」整段。
    抽离后 create_app 可只负责蓝图注册与中间件，引导逻辑可单独测试，
    也可通过 flask bootstrap 命令手动触发。
    """
    # 初始化数据库（创建表）
    # 先导入所有模型，确保 Base.metadata 包含所有表
    from app.core.database import db_manager
    from app.model import (
        TaskProcess,
        User,
    )

    db_manager.init_database()
    logger.info("数据库初始化完成")

    # 补齐 server_sessions 撤销相关列（老库兼容，幂等；与上面迁移互补，保留无害）
    from app.services.session_service import ensure_session_columns, ensure_user_columns

    ensure_session_columns()
    ensure_user_columns()

    # 清理僵尸进程（服务器重启后遗留的 running 状态进程）
    import bcrypt

    from app.core.database import get_db
    from app.model.module_config import init_default_configs

    session = get_db()
    try:
        # 清理僵尸进程
        zombie_count = (
            session.query(TaskProcess)
            .filter(TaskProcess.status == "running")
            .update(
                {"status": "cancelled", "message": "服务器重启，进程已失效"},
                synchronize_session=False,
            )
        )
        session.commit()
        if zombie_count > 0:
            logger.info(f"[启动] 清理了 {zombie_count} 个僵尸进程")

        # 初始化默认配置
        init_default_configs(session)

        # 初始化默认管理员账号（用户名与 JWT_ADMIN_USERNAME / 指纹比对一致）
        from app.core.db_fingerprint import default_admin_username

        admin_username = app.config.get("JWT_ADMIN_USERNAME") or default_admin_username()
        admin_user = session.query(User).filter_by(username=admin_username).first()
        if not admin_user:
            # 从 .env 读取初始密码
            initial_password = app.config.get("JWT_ADMIN_PASSWORD", "") or app.config.get(
                "ADMIN_TOKEN", "admin"
            )
            password_hash = bcrypt.hashpw(
                initial_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            admin_user = User(
                username=admin_username,
                password_hash=password_hash,
                role="admin",
                is_active=True,
                is_primary=True,
            )
            session.add(admin_user)
            session.commit()
            logger.info(f"[启动] 已创建默认管理员账号 {admin_username}")
        else:
            logger.info(f"[启动] 管理员账号已存在: {admin_username}")

        # 数据库指纹比对（种子数据已写入后，检测实例是否与代码初始化定义一致）
        # 经 Redis 分布式锁保证仅单进程执行自动迁移/清理，避免多 gunicorn worker
        # 并发 ALTER 同一表造成元数据锁(MDL)竞争与启动卡死。
        _run_fingerprint_auto_fix_with_lock(session)
    finally:
        session.close()


@click.command("bootstrap")
@with_appcontext
def bootstrap_command():
    """执行启动期引导：建表 + 默认配置/管理员 + 指纹自动迁移。

    等价于 create_app 默认执行的引导逻辑，可手动运行：
        flask bootstrap
    """
    run_bootstrap(current_app._get_current_object())
    logger.info("flask bootstrap 执行完成")
