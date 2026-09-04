#!/usr/bin/env python3
"""
组织单元服务（学校→学院→专业→班级 层级树）

- 四层固定：school（parent 为空）→ college → major → class。
- create 校验层级合法性 + 同父下名称唯一；
- rename 后级联刷新其子树内名单的冗余路径名（school/college/major/class_name）；
- delete 保护：有子节点或已被名单引用（class）时拒绝删除；
- get_path 向上回溯返回 {school,college,major,class} 全路径名称。
"""

from app.core.database import get_db
from app.core.logger import get_logger
from app.model.org_unit import OrgUnit

logger = get_logger(__name__)

# 层级顺序：值越大越深
NODE_ORDER = {"school": 0, "college": 1, "major": 2, "class": 3}

# 各类型的中文标签（错误提示用）
TYPE_LABEL = {"school": "学校", "college": "学院", "major": "专业", "class": "班级"}

# 类型 → 允许的父类型（school 无父）
PARENT_OF = {"college": "school", "major": "college", "class": "major"}


def _norm(value):
    return (value or "").strip()


class OrgUnitService:
    """组织树服务"""

    # ---------- 查询 ----------

    @staticmethod
    def get(unit_id):
        """按 id 取节点。返回 OrgUnit|None。"""
        if not unit_id:
            return None
        session = get_db()
        try:
            return session.query(OrgUnit).filter_by(id=unit_id).first()
        finally:
            session.close()

    @staticmethod
    def list_schools():
        """学校列表（管理端与小程序绑定页的待选项数据源）。"""
        session = get_db()
        try:
            rows = (
                session.query(OrgUnit)
                .filter(OrgUnit.node_type == "school")
                .order_by(OrgUnit.id.asc())
                .all()
            )
            return [r.to_dict() for r in rows]
        finally:
            session.close()

    @staticmethod
    def tree():
        """返回嵌套树（含 children，顶层为学校）。供管理端组织树与级联选择。"""
        session = get_db()
        try:
            rows = session.query(OrgUnit).order_by(OrgUnit.id.asc()).all()
            nodes = [r.to_dict() for r in rows]
            children_map = {}
            roots = []
            for n in nodes:
                n["children"] = []
                children_map[n["id"]] = n
            for n in nodes:
                pid = n["parent_id"]
                if pid is not None and pid in children_map:
                    children_map[pid]["children"].append(n)
                else:
                    roots.append(n)
            return roots
        finally:
            session.close()

    @staticmethod
    def get_path(unit_id):
        """向上回溯全路径名称：{school,college,major,class}（供名单冗余列带出）。"""
        if not unit_id:
            return {"school": None, "college": None, "major": None, "class": None}
        session = get_db()
        try:
            unit = session.query(OrgUnit).filter_by(id=unit_id).first()
            if not unit:
                return {"school": None, "college": None, "major": None, "class": None}
            path = OrgUnitService._path_of(session, unit)
            return path
        finally:
            session.close()

    @staticmethod
    def _path_of(session, unit):
        """在给定 session 内自下而上回溯节点链，返回名称 dict（不额外开 session）。"""
        names = {"school": None, "college": None, "major": None, "class": None}
        cur = unit
        while cur is not None:
            if cur.node_type in names:
                names[cur.node_type] = cur.name
            if cur.parent_id is None:
                break
            cur = session.query(OrgUnit).filter_by(id=cur.parent_id).first()
        return names

    # ---------- 写操作 ----------

    @staticmethod
    def create(node_type, name, parent_id=None):
        """新建节点。返回 (OrgUnit|None, error|None)。"""
        node_type = _norm(node_type)
        name = _norm(name)
        if node_type not in NODE_ORDER:
            return None, f"不支持的节点类型：{node_type}"
        if not name:
            return None, "名称不能为空"
        parent_id = parent_id or None
        session = get_db()
        try:
            parent = None
            if node_type == "school":
                if parent_id is not None:
                    return None, "学校为顶层节点，不能挂在其他节点下"
            else:
                if parent_id is None:
                    return None, f"{TYPE_LABEL[node_type]}必须挂在上级节点下"
                parent = session.query(OrgUnit).filter_by(id=parent_id).first()
                if not parent:
                    return None, "上级节点不存在"
                if parent.node_type != PARENT_OF[node_type]:
                    return None, f"{TYPE_LABEL[node_type]}只能挂在{TYPE_LABEL[PARENT_OF[node_type]]}下"
            # 同父同类型下名称唯一
            dup = (
                session.query(OrgUnit)
                .filter(
                    OrgUnit.parent_id == parent_id,
                    OrgUnit.node_type == node_type,
                    OrgUnit.name == name,
                )
                .first()
            )
            if dup:
                return None, f"同级下已存在同名{TYPE_LABEL[node_type]}：{name}"
            row = OrgUnit(parent_id=parent_id, node_type=node_type, name=name)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[OrgUnit] 新建节点失败: {exc}")
            return None, "保存失败，请稍后重试"
        finally:
            session.close()

    @staticmethod
    def rename(unit_id, name):
        """重命名节点，并级联刷新其子树下所有名单的冗余路径名（同一事务）。
        返回 (OrgUnit|None, error|None)。"""
        from app.model.student_roster import StudentRoster

        name = _norm(name)
        if not name:
            return None, "名称不能为空"
        session = get_db()
        try:
            row = session.query(OrgUnit).filter_by(id=unit_id).first()
            if not row:
                return None, "节点不存在"
            dup = (
                session.query(OrgUnit)
                .filter(
                    OrgUnit.parent_id == row.parent_id,
                    OrgUnit.node_type == row.node_type,
                    OrgUnit.name == name,
                    OrgUnit.id != unit_id,
                )
                .first()
            )
            if dup:
                return None, f"同级下已存在同名{TYPE_LABEL[row.node_type]}：{name}"
            row.name = name
            # 级联刷新子树内名单的冗余列（与改名同事务，保证一致性）
            for class_id in OrgUnitService._collect_class_ids(session, unit_id):
                cls = session.query(OrgUnit).filter_by(id=class_id).first()
                if not cls:
                    continue
                names = OrgUnitService._path_of(session, cls)
                session.query(StudentRoster).filter(StudentRoster.class_id == class_id).update(
                    {
                        "school": names["school"],
                        "college": names["college"],
                        "major": names["major"],
                        "class_name": names["class"],
                    }
                )
            session.commit()
            session.refresh(row)
            return row, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[OrgUnit] 重命名失败: {exc}")
            return None, "保存失败，请稍后重试"
        finally:
            session.close()

    @staticmethod
    def refresh_roster_paths(unit_id):
        """把以 unit 为根的子树上所有班级名单的冗余列（school/college/major/class_name）
        按最新树路径整体刷新（重命名节点后调用；独立事务）。"""
        from app.model.student_roster import StudentRoster

        session = get_db()
        try:
            class_ids = OrgUnitService._collect_class_ids(session, unit_id)
            if not class_ids:
                return
            # 一个班级一个班级刷：班级内学号路径一致
            for class_id in class_ids:
                cls = session.query(OrgUnit).filter_by(id=class_id).first()
                if not cls:
                    continue
                names = OrgUnitService._path_of(session, cls)
                session.query(StudentRoster).filter(StudentRoster.class_id == class_id).update(
                    {
                        "school": names["school"],
                        "college": names["college"],
                        "major": names["major"],
                        "class_name": names["class"],
                    }
                )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error(f"[OrgUnit] 刷新名单冗余路径失败: {exc}")
        finally:
            session.close()

    @staticmethod
    def _collect_class_ids(session, unit_id):
        """收集以 unit 为根的子树上所有 class 节点 id（含自身若是 class）。"""
        rows = session.query(OrgUnit).all()
        children_map = {}
        for r in rows:
            children_map.setdefault(r.parent_id, []).append(r)
        found = []
        stack = [unit_id]
        while stack:
            cur = stack.pop()
            for child in children_map.get(cur, []):
                if child.node_type == "class":
                    found.append(child.id)
                stack.append(child.id)
        return found

    @staticmethod
    def delete(unit_id):
        """删除节点。有子节点或班级被名单引用时拒绝。返回 (bool, error|None)。"""
        from app.model.student_roster import StudentRoster

        session = get_db()
        try:
            row = session.query(OrgUnit).filter_by(id=unit_id).first()
            if not row:
                return False, "节点不存在"
            has_child = session.query(OrgUnit).filter_by(parent_id=unit_id).first()
            if has_child:
                return False, "请先删除其下的子节点"
            if row.node_type == "class":
                used = (
                    session.query(StudentRoster)
                    .filter(StudentRoster.class_id == unit_id)
                    .first()
                )
                if used:
                    return False, "该班级下仍有学生名单，请先移除学生"
            session.delete(row)
            session.commit()
            return True, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[OrgUnit] 删除节点失败: {exc}")
            return False, "删除失败，请稍后重试"
        finally:
            session.close()

    @staticmethod
    def find_class_by_path(school, college=None, major=None, class_name=None):
        """按名称路径定位班级节点（批量导入 / 归属校验用）。
        学校必填；college/major/class 提供时逐级下钻，缺级则返回当前层（须是 class 才有效）。"""
        school = _norm(school)
        college = _norm(college)
        major = _norm(major)
        class_name = _norm(class_name)
        if not school:
            return None
        session = get_db()
        try:
            cur = (
                session.query(OrgUnit)
                .filter(
                    OrgUnit.parent_id.is_(None),
                    OrgUnit.node_type == "school",
                    OrgUnit.name == school,
                )
                .first()
            )
            if not cur:
                return None
            for ntype, nname in (("college", college), ("major", major), ("class", class_name)):
                if not nname:
                    break
                child = (
                    session.query(OrgUnit)
                    .filter(
                        OrgUnit.parent_id == cur.id,
                        OrgUnit.node_type == ntype,
                        OrgUnit.name == nname,
                    )
                    .first()
                )
                if not child:
                    return None
                cur = child
            return cur if cur.node_type == "class" else None
        finally:
            session.close()
