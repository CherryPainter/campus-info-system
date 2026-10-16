"""
schedule_service.ensure_worker_refresh 幂等性与激活测试

背景（2026-10-10 生产事故）：
Gunicorn preload_app=True 下 app 只在 master 创建一次，fork 出的 worker 不会继承
master 的 60s 刷新定时器线程，导致 worker 内课表缓存是 fork 时的冻结快照、定时刷新
失效。课程增删改后只有处理写请求的那个 worker 拿到新数据，其余 worker 持续返回旧数据，
小程序「今日课程」刷新一会一节一会两节。

覆盖：
- ensure_worker_refresh 在定时器未启动时，会启动本进程的定时器，且立即重载缓存。
- 幂等：定时器已存活时再调用不重复启动（避免线程泄漏）。
- 反向：去掉 ensure_worker_refresh 对 timer.is_alive() 的判活，fork 后的死定时器
  会被误认为已运行而永不重启 —— 本用例通过断言“调用后 timer 必须 alive”保证修复有效。

运行：
    cd Push_System_Flask && python -m pytest tests/test_schedule_worker_refresh.py -v
"""

import threading

import pytest

from app.services import schedule_service as svc_mod
from app.services.schedule_service import ScheduleService


def _make_service():
    s = ScheduleService()
    s._refresh_interval = 5
    # 用一个永真的 get_db 占位，避免真实连接数据库
    s.load_schedules = lambda: True
    return s


def test_ensure_worker_refresh_starts_timer_when_dead():
    s = _make_service()
    # 模拟 fork 后继承到一个“从未在本进程启动”的死定时器
    s._refresh_timer = threading.Timer(5, lambda: None)

    s.ensure_worker_refresh()

    assert s._refresh_timer is not None
    assert s._refresh_timer.is_alive(), "ensure_worker_refresh 必须启动本进程的刷新定时器"


def test_ensure_worker_refresh_idempotent_when_alive():
    s = _make_service()
    s._start_auto_refresh()  # 已启动一个活定时器
    assert s._refresh_timer.is_alive()
    first = s._refresh_timer

    s.ensure_worker_refresh()

    # 不应再新建定时器（避免泄漏），仍复用同一个活定时器
    assert s._refresh_timer is first
    assert s._refresh_timer.is_alive()


def test_ensure_worker_refresh_reloads_cache(monkeypatch):
    s = _make_service()
    called = {"n": 0}

    def fake_load():
        called["n"] += 1
        return True

    monkeypatch.setattr(s, "load_schedules", fake_load)
    s._refresh_timer = threading.Timer(5, lambda: None)  # 死定时器

    s.ensure_worker_refresh()

    assert called["n"] == 1, "ensure_worker_refresh 应立即重载一次缓存"


def test_reload_schedule_cache_module_function_exists():
    # 仅确认导出符号存在，避免回归误删
    assert hasattr(svc_mod, "schedule_service")
    assert hasattr(svc_mod.schedule_service, "ensure_worker_refresh")
