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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.core.database import Base


class StudentRoster(Base):
    """学生预录名单表

    v6.17 组织树化后：学校/学院/专业/班级 由 org_units 树维护，
    本表通过 class_id 挂到「班级」节点，school/college/major/class_name
    冗余列仍保留并由服务端从树带出写入（兼容旧查询与展示，避免每行 join）。
    bind_code_hash 存一次性绑定密钥的 sha256（明文仅在生成/批量导出时返回一次）。
    """

    __tablename__ = "student_rosters"
    __table_args__ = (
        UniqueConstraint("school", "student_number", name="uq_roster_school_student"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(
        Integer,
        ForeignKey("org_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="所属班级节点ID（org_units，node_type=class）",
    )
    school = Column(String(50), nullable=False, comment="学校名称（从组织树冗余带出）")
    student_number = Column(String(30), nullable=False, index=True, comment="学号")
    class_name = Column(String(100), nullable=False, comment="班级（从组织树冗余带出）")
    college = Column(String(100), nullable=True, comment="学院（从组织树冗余带出）")
    major = Column(String(100), nullable=True, comment="专业（从组织树冗余带出）")
    real_name = Column(String(50), nullable=True, comment="姓名")
    dorm = Column(String(100), nullable=True, comment="宿舍（如 A栋305）；同宿舍的学生构成一个组，用于电量 webhook 按宿舍聚合推送")
    remark = Column(String(200), nullable=True, comment="备注")
    bind_code_hash = Column(String(64), nullable=True, comment="一次性绑定密钥 sha256（绑定成功即清空）")
    is_active = Column(
        Boolean, default=True, nullable=False, comment="是否启用（停用后不可绑定）"
    )
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "class_id": self.class_id,
            "school": self.school,
            "student_number": self.student_number,
            "class_name": self.class_name,
            "college": self.college,
            "major": self.major,
            "real_name": self.real_name,
            "dorm": self.dorm,
            "remark": self.remark,
            "has_bind_code": bool(self.bind_code_hash),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
