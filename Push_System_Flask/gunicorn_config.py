#!/usr/bin/env python3
"""Gunicorn 生产环境配置

核心修复：preload_app = True
  让 Flask app 在 master 进程中加载一次，BackgroundScheduler 只启动一次。
  否则每个 worker 都会启动自己的调度器，天气 API 等定时任务被执行 N 倍，
  导致 API 请求次数爆炸、触发限流。

启动方式：
  gunicorn -c gunicorn_config.py run:app
"""

import os

# ============================================================
# 关键：预加载应用
# 调度器只在 master 进程启动一次，workers 不执行 create_app()
# ============================================================
preload_app = True

# ============================================================
# Worker 数量
# 默认 4 个，通过环境变量 GUNICORN_WORKERS 覆盖
# 4 个足够处理 Web API 请求，定时任务在 master 中运行不占 worker
# ============================================================
workers = int(os.environ.get("GUNICORN_WORKERS", 4))

# ============================================================
# 绑定地址
# 默认 127.0.0.1:29528，与 Flask Config.PORT 一致
# 通过环境变量 GUNICORN_BIND 覆盖
# 生产环境 Nginx 反向代理到本机此端口
# ============================================================
bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:29528")

# ============================================================
# 超时设置（秒）
# 爬虫等长时间操作可能持续几分钟
# ============================================================
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 180))

# ============================================================
# Worker 类型：sync（同步）
# 对于 I/O 密集型的小型服务，sync worker 最简单可靠
# ============================================================
worker_class = "sync"

# ============================================================
# 内存管理
# max_requests: 每个 worker 处理一定请求后重启，防止内存泄漏
# max_requests_jitter: 随机偏移，避免所有 worker 同时重启
# ============================================================
max_requests = 1000
max_requests_jitter = 100

# ============================================================
# 优雅关闭
# ============================================================
graceful_timeout = 30

# ============================================================
# 日志
# ============================================================
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")

# ============================================================
# 进程命名（便于排查问题）
# ============================================================
proc_name = "push_system"


def post_fork(server, worker):
    """Worker 进程创建后立即回调：标记当前为 worker 进程。

    配合 scheduler.py 中的环境变量检查，
    确保即使 preload_app 失效，worker 也不会启动调度器。
    """
    os.environ["GUNICORN_WORKER"] = "1"

    # 关键修复：preload_app=True 下 create_app 在 master 进程里就创建了 SQLAlchemy
    # 引擎并打开了数据库连接（init_services → schedule_service.init_app → load_schedules）。
    # fork 会把 master 的连接池（含已打开连接的 socket FD）原样复制到每个 worker，
    # 导致多个 worker 进程共用同一个 MySQL 连接 → 协议错位，偶发
    # 「Packet sequence number wrong」「(2013) Lost connection during query」
    # 「(2014) Command Out of Sync」。这正是生产日志里课表缓存加载批量报错的根因。
    # 这里在 fork 后立刻 dispose 引擎，丢弃继承来的共享连接；各 worker 下次取连接时
    # 自建独立连接池（FD 不再跨进程共享），彻底消除跨进程共用连接。
    # 注意：dispose 只关掉当前 worker 继承的连接副本，master 的连接不受影响（fork 后
    # FD 引用独立计数，关闭子进程副本不会破坏父进程连接）。
    try:
        from app.core.database import db_manager

        if db_manager.engine is not None:
            db_manager.engine.dispose()
    except Exception:
        pass

    # 修复：preload 模式下 fork 会丢掉 master 的课表缓存刷新线程，worker 内
    # schedule_service 缓存是 fork 时刻的冻结快照、定时刷新失效，导致课程增删改
    # 后部分 worker 仍返回旧数据（小程序「今日课程」一会一节一会两节）。
    # 这里为每个 worker 重新加载并启动属于自己的刷新定时器（幂等）。
    try:
        from app.services.schedule_service import schedule_service

        schedule_service.ensure_worker_refresh()
    except Exception:
        # 缓存刷新失败不应阻塞 worker 启动，等待 60s 定时器兜底
        pass


def when_ready(server):
    """服务就绪回調。"""
    server.log.info(
        f"[Gunicorn] 服务就绪 — bind={server.cfg.bind}, "
        f"workers={server.cfg.workers}, preload_app={server.cfg.preload_app}"
    )
