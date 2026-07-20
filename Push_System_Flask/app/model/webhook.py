#!/usr/bin/env python3
"""
Webhook 管理模型

用于存储和管理企业微信 webhook 地址，支持：
- 多个 webhook 地址
- 按类型分类（推送/状态/全部）
- 启用/禁用状态
- 动态增删改查
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class Webhook(Base):
    """
    Webhook 配置表

    存储企业微信机器人 webhook 地址，支持动态管理。
    """

    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment='Webhook 名称，如"班级群"、"测试群"')
    url = Column(String(500), nullable=False, comment="Webhook 完整 URL")
    modules = Column(
        String(100),
        default="course",
        comment="所属模块: course,weather,electricity,system 的逗号分隔列表",
    )
    is_enabled = Column(Boolean, default=True, comment="是否启用")
    description = Column(String(500), nullable=True, comment="描述说明")
    last_test_status = Column(
        String(20), nullable=True, comment="上次测试结果: success/failed/pending"
    )
    last_test_time = Column(DateTime, nullable=True, comment="上次测试时间")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "modules": self.modules,
            "module_list": self.get_module_list(),
            "is_enabled": self.is_enabled,
            "description": self.description,
            "last_test_status": self.last_test_status,
            "last_test_time": self.last_test_time.isoformat() if self.last_test_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_module_list(self):
        """获取模块列表"""
        if not self.modules:
            return []
        return [m.strip() for m in self.modules.split(",") if m.strip()]

    @staticmethod
    def get_enabled_webhooks(session, module=None):
        """
        获取启用的 webhook 列表

        Args:
            session: 数据库会话
            module: 按模块过滤，None 则返回所有启用的

        Returns:
            list: Webhook 对象列表
        """
        query = session.query(Webhook).filter(Webhook.is_enabled.is_(True))

        if module:
            # 匹配包含指定模块的 webhook
            from sqlalchemy import or_

            query = query.filter(
                or_(
                    Webhook.modules.like(f"%{module}%"),
                )
            )

        return query.order_by(Webhook.created_at).all()

    @staticmethod
    def get_webhooks_by_module(session, module):
        """
        获取指定模块的所有启用 webhook

        Args:
            session: 数据库会话
            module: 模块名称 (course/weather/electricity/system/all)

        Returns:
            list: Webhook 对象列表
        """
        all_enabled = Webhook.get_enabled_webhooks(session)
        result = []
        for w in all_enabled:
            module_list = w.get_module_list()
            # 如果 webhook 标记为 'all'，或者包含指定模块
            if "all" in module_list or module in module_list:
                result.append(w)
        return result

    @staticmethod
    def get_all_webhooks(session):
        """
        获取所有 webhook（包括禁用的）

        Args:
            session: 数据库会话

        Returns:
            list: Webhook 对象列表
        """
        return session.query(Webhook).order_by(Webhook.created_at.desc()).all()

    @staticmethod
    def get_by_id(session, webhook_id):
        """
        根据 ID 获取 webhook

        Args:
            session: 数据库会话
            webhook_id: Webhook ID

        Returns:
            Webhook 对象或 None
        """
        return session.query(Webhook).filter(Webhook.id == webhook_id).first()

    @staticmethod
    def create(session, name, url, modules="course", description=None):
        """
        创建新 webhook

        Args:
            session: 数据库会话
            name: 名称
            url: URL
            modules: 所属模块列表（逗号分隔）
            description: 描述

        Returns:
            创建的 Webhook 对象
        """
        webhook = Webhook(
            name=name,
            url=url,
            modules=modules,
            description=description,
            is_enabled=True,
        )
        session.add(webhook)
        session.commit()
        return webhook

    @staticmethod
    def update(session, webhook_id, **kwargs):
        """
        更新 webhook

        Args:
            session: 数据库会话
            webhook_id: Webhook ID
            **kwargs: 要更新的字段

        Returns:
            是否更新成功
        """
        webhook = Webhook.get_by_id(session, webhook_id)
        if not webhook:
            return False

        allowed_fields = ["name", "url", "modules", "is_enabled", "description"]
        for field in allowed_fields:
            if field in kwargs:
                setattr(webhook, field, kwargs[field])

        webhook.updated_at = datetime.now()
        session.commit()
        return True

    @staticmethod
    def delete(session, webhook_id):
        """
        删除 webhook

        Args:
            session: 数据库会话
            webhook_id: Webhook ID

        Returns:
            是否删除成功
        """
        webhook = Webhook.get_by_id(session, webhook_id)
        if not webhook:
            return False

        session.delete(webhook)
        session.commit()
        return True

    def update_test_status(self, session, status):
        """
        更新测试状态

        Args:
            session: 数据库会话
            status: 状态字符串
        """
        self.last_test_status = status
        self.last_test_time = datetime.now()
        session.commit()
