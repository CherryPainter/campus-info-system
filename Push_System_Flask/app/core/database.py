#!/usr/bin/env python3
"""
数据库核心配置模块

使用 SQLAlchemy ORM，仅支持 MySQL
所有数据库操作必须通过 ORM 完成，禁止裸 SQL
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Config

# SQLAlchemy 声明基类
Base = declarative_base()


class DatabaseManager:
    """
    数据库管理器

    职责：
    - 管理数据库连接引擎
    - 提供 Session 工厂
    - 处理数据库初始化
    """

    _instance: "DatabaseManager" = None
    _engine = None
    _session_factory = None

    def __new__(cls) -> "DatabaseManager":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化 MySQL 数据库连接"""
        if self._engine is not None:
            return

        # 数据库 URL：从 Config 获取
        database_url = Config.get_database_url()

        # 确保 MySQL 数据库存在，再创建引擎
        self._ensure_mysql_database(database_url)

        self._engine = create_engine(
            database_url,
            pool_pre_ping=True,  # 自动检测断开的连接
            pool_recycle=3600,  # 连接回收时间
            echo=False,  # 关闭 SQL 日志
        )

        # 创建 Session 工厂
        self._session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine,
        )

    def _ensure_mysql_database(self, database_url: str):
        """
        确保 MySQL 数据库存在，不存在则自动创建
        """
        from urllib.parse import urlparse

        from sqlalchemy import text

        from app.core.logger import get_logger

        logger = get_logger(__name__)

        try:
            # 使用 urllib 解析 URL
            parsed = urlparse(database_url)
            db_name = parsed.path.lstrip("/")

            if not db_name:
                logger.warning("无法从 URL 解析数据库名，跳过自动建库")
                return

            # 构造连接 MySQL 服务器的 URL（不带数据库名）
            server_url = f"{parsed.scheme}://{parsed.netloc}/"

            # 连接 MySQL 服务器
            server_engine = create_engine(server_url, echo=False)
            with server_engine.connect() as conn:
                # 检查数据库是否存在
                result = conn.execute(text("SHOW DATABASES LIKE :db_name"), {"db_name": db_name})
                exists = result.fetchone() is not None

                if not exists:
                    # 创建数据库
                    conn.execute(
                        text(
                            f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )
                    conn.commit()
                    logger.info(f"[数据库] 已自动创建数据库: {db_name}")
                else:
                    logger.info(f"[数据库] 数据库已存在: {db_name}")

            server_engine.dispose()
        except Exception as e:
            logger.warning(f"[数据库] 自动建库失败: {e}，请手动创建数据库")

    @property
    def engine(self):
        """获取数据库引擎"""
        return self._engine

    def create_session(self) -> Session:
        """创建新的数据库会话"""
        return self._session_factory()

    def init_database(self) -> None:
        """初始化数据库：创建所有表"""
        # 延迟导入模型，避免循环依赖
        # 导入 model 包会自动导入所有模型类

        Base.metadata.create_all(bind=self._engine)

    def drop_all(self) -> None:
        """删除所有表（仅用于测试）"""
        Base.metadata.drop_all(bind=self._engine)


# 全局数据库管理器实例
db_manager = DatabaseManager()


def get_db_session() -> Generator[Session, None, None]:
    """
    获取数据库会话的生成器

    用于 FastAPI/Flask 依赖注入，确保会话正确关闭

    Yields:
        Session: 数据库会话对象
    """
    session = db_manager.create_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Session:
    """
    获取数据库会话（用于非生成器场景）

    Returns:
        Session: 数据库会话对象
    """
    return db_manager.create_session()
