#!/usr/bin/env python3
"""
学生名单（预录白名单）模型

管理员提前录入的合法学生名单，用于小程序登录后的身份绑定校验：
- 小程序用户提交「学校 + 学号 + 班级」，三项均命中本表且 is_active=1 才允许绑定；
- 只有绑定成功的学生才能查看课表/电量/消息等对应信息（筛除无关人员）。

设计说明：
- 与 StudentProfile 解耦：本表是"门禁名单"，StudentProfile 是绑定后的身份快照。
- school + student_number 联合唯一（不同学校学号可能重复）。
- 名单停用/删除只影响"新绑定"，已绑定用户不受影响（绑定是一次性入场）。
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint

from app.core.database import Base


class StudentRoster(Base):
    """学生预录名单表"""

    __tablename__ = "student_rosters"
    __table_args__ = (
        UniqueConstraint("school", "student_number", name="uq_roster_school_student"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    school = Column(String(50), nullable=False, comment="学校名称")
    student_number = Column(String(30), nullable=False, index=True, comment="学号")
    class_name = Column(String(100), nullable=False, comment="班级")
    real_name = Column(String(50), nullable=True, comment="姓名")
    remark = Column(String(200), nullable=True, comment="备注")
    is_active = Column(
        Boolean, default=True, nullable=False, comment="是否启用（停用后不可绑定）"
    )
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "school": self.school,
            "student_number": self.student_number,
            "class_name": self.class_name,
            "real_name": self.real_name,
            "remark": self.remark,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
