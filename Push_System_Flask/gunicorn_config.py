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


def when_ready(server):
    """服务就绪回調。"""
    server.log.info(
        f"[Gunicorn] 服务就绪 — bind={server.cfg.bind}, "
        f"workers={server.cfg.workers}, preload_app={server.cfg.preload_app}"
    )
