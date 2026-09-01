#!/usr/bin/env python3
"""
学生资料模型

与 User 表 1:1 关联（user_id 唯一），存放学生身份扩展信息
（学号、学院、专业、班级、年级、手机号）。

设计说明：
- 不把学号/班级等学生属性塞进 User 主表，避免影响现有管理员认证模型。
- 微信小程序学生用户首次登录时只创建骨架（仅 user_id），
  学号/姓名等由学生本人（PUT /api/miniapp/student/profile）或后续管理端补充。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class StudentProfile(Base):
    """
    学生资料表

    与 User 一对一：student_profiles.user_id 唯一指向 users.id。
    """

    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
        comment="关联用户ID（1:1）",
    )
    student_number = Column(String(30), nullable=True, index=True, comment="学号")
    real_name = Column(String(50), nullable=True, comment="真实姓名")
    nickname = Column(String(50), nullable=True, comment="昵称（展示名，优先于真实姓名）")
    college = Column(String(100), nullable=True, comment="学院")
    major = Column(String(100), nullable=True, comment="专业")
    class_name = Column(String(100), nullable=True, comment="班级")
    grade = Column(String(20), nullable=True, comment="年级")
    phone = Column(String(20), nullable=True, comment="手机号")
    profile_bg = Column(String(30), nullable=True, comment="我的页背景预设（default/sunset/ocean/forest/night）")

    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    user = relationship("User", backref="student_profile")

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "student_number": self.student_number,
            "real_name": self.real_name,
            "nickname": self.nickname,
            "college": self.college,
            "major": self.major,
            "class_name": self.class_name,
            "grade": self.grade,
            "phone": self.phone,
            "profile_bg": self.profile_bg or "default",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
