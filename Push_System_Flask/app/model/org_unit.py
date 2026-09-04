#!/usr/bin/env python3
"""
组织单元模型（学校→学院→专业→班级 层级树）

替代此前 student_rosters 上逐行重复填写 school/college/major/class_name 的扁平方式：
- 学校 / 学院 / 专业 / 班级 各建一次，学生名单只挂到班级（class_id），
  全路径（学校→学院→专业→班级）由树继承，录入与维护只改一处。
- node_type 限定四层：school / college / major / class（根节点 school 的 parent_id 为空）。
- 同父节点下 name 唯一（同学院下专业名不重复等），由 service 层校验。

迁移说明：新表由启动指纹迁移自动创建（模型须注册进 app/model/__init__.py）。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class OrgUnit(Base):
    """组织单元表（自引用树）"""

    __tablename__ = "org_units"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(
        Integer,
        ForeignKey("org_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="父节点ID（学校节点为空）",
    )
    node_type = Column(
        String(20), nullable=False, index=True, comment="节点类型：school/college/major/class"
    )
    name = Column(String(100), nullable=False, comment="节点名称（同父下唯一）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "node_type": self.node_type,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
