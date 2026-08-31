#!/usr/bin/env python3
"""
微信小程序账号模型

与 User 表多对一（一个用户可绑定多个登录渠道），存储微信身份信息
（openid / unionid / session_key）。

设计说明：
- openid 唯一，作为微信用户身份标识，由后端调用微信官方 code2Session 获得，
  绝不信任客户端直接提交的 openid。
- unionid 可空：同一微信开放平台主体下多个小程序/公众号互通时才存在。
- session_key 为微信会话密钥，仅用于解密微信用户数据，服务端保存、绝不外泄。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class WechatAccount(Base):
    """
    微信小程序账号绑定表
    """

    __tablename__ = "wechat_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="关联用户ID")
    openid = Column(String(64), nullable=False, unique=True, comment="微信用户唯一标识")
    unionid = Column(String(64), nullable=True, comment="微信开放平台唯一标识")
    session_key = Column(String(64), nullable=True, comment="微信会话密钥（服务端专用）")

    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    last_login_at = Column(DateTime, nullable=True, comment="最近登录时间")

    user = relationship("User", backref="wechat_accounts")

    def to_dict(self):
        # 注意：不返回 session_key，避免泄露微信会话密钥
        return {
            "id": self.id,
            "user_id": self.user_id,
            "openid": self.openid,
            "unionid": self.unionid,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
