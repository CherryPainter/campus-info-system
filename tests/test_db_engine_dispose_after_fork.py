"""
post_fork 丢弃 fork 继承的共享 MySQL 连接后，worker 仍能自建连接池（回归测试）

根因（2026-10-11 生产日志）：
    preload_app=True 下 create_app 在 master 进程创建 SQLAlchemy 引擎并打开数据库连接
    （init_services → schedule_service.init_app → load_schedules）。fork 把 master 的连接池
    （含已打开连接的 socket FD）原样复制到每个 worker，导致多个 worker 进程共用同一个
    MySQL 连接 → 协议错位，偶发「Packet sequence number wrong - got 188 expected 1」
    「(2013) Lost connection during query」「(2014) Command Out of Sync」。

修复：gunicorn_config.post_fork 里 `db_manager.engine.dispose()` 丢弃继承连接，
    各 worker 下次取连接时自建独立连接池（FD 不再跨进程共享）。

覆盖：
- dispose 丢弃继承连接后，worker 仍能新建连接并查询（自建独立池）。
- post_fork 调用不抛异常，且 dispose 后引擎仍可用。

运行：
    cd Push_System_Flask && python -m pytest tests/test_db_engine_dispose_after_fork.py -v
"""

import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import db_manager


@pytest.fixture
def sqlite_engine():
    """用 sqlite in-memory 替换 db_manager 的引擎/工厂，测试后还原，避免污染其它用例。"""
    eng = create_engine("sqlite:///:memory:")
    saved_engine = db_manager._engine
    saved_factory = db_manager._session_factory
    db_manager._engine = eng
    db_manager._session_factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    try:
        yield eng
    finally:
        db_manager._engine = saved_engine
        db_manager._session_factory = saved_factory


def test_dispose_drops_inherited_connection_and_reconnects(sqlite_engine):
    # master 在 fork 前持有并归还一个连接（留在池里，被 fork 复制）
    with db_manager.create_session() as s:
        assert s.execute(text("SELECT 1")).scalar() == 1

    # post_fork：dispose 丢弃继承连接
    db_manager.engine.dispose()

    # dispose 后 worker 仍能新建连接并查询（自建独立池，不再共用 master 的连接）
    with db_manager.create_session() as s:
        assert s.execute(text("SELECT 1")).scalar() == 1


def test_post_fork_disposes_engine_without_breaking_app(monkeypatch, sqlite_engine):
    import gunicorn_config

    # 隔离 schedule_service 的 DB 预载逻辑，只验证 post_fork 的 dispose 部分
    monkeypatch.setattr(
        "app.services.schedule_service.schedule_service.ensure_worker_refresh",
        lambda: None,
    )

    # 不应抛异常；dispose 后引擎仍可用（worker 自建连接池）
    gunicorn_config.post_fork(None, None)
    with db_manager.create_session() as s:
        assert s.execute(text("SELECT 1")).scalar() == 1
