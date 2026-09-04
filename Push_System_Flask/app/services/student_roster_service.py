#!/usr/bin/env python3
"""
学生名单服务（预录白名单）

- 管理端：新建 / 批量导入 / 编辑 / 停用启用 / 删除 名单条目
- 小程序端：verify() 校验「学校 + 学号 + 班级」是否命中启用名单（身份绑定门禁）
"""

from sqlalchemy import or_

from app.core.database import get_db
from app.core.logger import get_logger
from app.model.student_profile import StudentProfile
from app.model.student_roster import StudentRoster
from app.model.user import User

logger = get_logger(__name__)


def _norm(value):
    """去首尾空白，None 转空串"""
    return (value or "").strip()


def _merge_binding(items, profiles, users):
    """纯函数：把已绑定身份（profiles）与用户（users）关联到名单条目 items。

    按 (school, student_number) 匹配——与小程序身份绑定的门禁键一致。
    items / profiles / users 均为 to_dict 后的 dict 列表；本函数就地给每个 item
    写入 bound_user_id / bound_username / bound_at（未匹配则置 None）。
    抽成纯函数便于单测，不依赖数据库会话。
    """
    prof_map = {}
    for p in profiles:
        sn = p.get("student_number")
        if sn:
            prof_map[(p.get("school"), sn)] = p
    user_map = {u.get("id"): u for u in users}
    for it in items:
        p = prof_map.get((it.get("school"), it.get("student_number")))
        if p and p.get("user_id") is not None:
            u = user_map.get(p.get("user_id"))
            it["bound_user_id"] = p.get("user_id")
            it["bound_username"] = u.get("username") if u else None
            it["bound_at"] = p.get("updated_at")
        else:
            it["bound_user_id"] = None
            it["bound_username"] = None
            it["bound_at"] = None


class StudentRosterService:
    """学生名单（预录白名单）服务"""

    @staticmethod
    def create(school, student_number, class_name, real_name=None, remark=None, is_active=True):
        """新建单个名单条目。返回 (row|None, error|None)。"""
        school = _norm(school)
        student_number = _norm(student_number)
        class_name = _norm(class_name)
        if not school or not student_number or not class_name:
            return None, "学校、学号、班级均不能为空"
        session = get_db()
        try:
            exists = (
                session.query(StudentRoster)
                .filter_by(school=school, student_number=student_number)
                .first()
            )
            if exists:
                return None, f"该学校下学号 {student_number} 已存在"
            row = StudentRoster(
                school=school,
                student_number=student_number,
                class_name=class_name,
                real_name=_norm(real_name) or None,
                remark=_norm(remark) or None,
                is_active=bool(is_active),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 新建名单失败: {exc}")
            return None, "保存失败，请稍后重试"
        finally:
            session.close()

    @staticmethod
    def create_batch(rows):
        """
        批量导入名单条目（同一事务内逐条校验）。

        Args:
            rows (list[dict]): 每项含 school / student_number / class_name /
                               real_name / remark（real_name、remark 可缺省）。

        Returns:
            dict: {"created": int, "failures": [{"row": int, "reason": str}]}
                  row 为源文件行号（表头占第 1 行，数据从第 2 行起）。
        """
        session = get_db()
        seen = set()
        created = 0
        failures = []
        try:
            for idx, item in enumerate(rows, start=2):
                school = _norm(item.get("school"))
                student_number = _norm(item.get("student_number"))
                class_name = _norm(item.get("class_name"))
                if not school or not student_number or not class_name:
                    failures.append({"row": idx, "reason": "学校/学号/班级为空"})
                    continue
                key = (school, student_number)
                if key in seen:
                    failures.append({"row": idx, "reason": f"文件内重复：{school} {student_number}"})
                    continue
                seen.add(key)
                exists = (
                    session.query(StudentRoster)
                    .filter_by(school=school, student_number=student_number)
                    .first()
                )
                if exists:
                    failures.append({"row": idx, "reason": f"名单已存在：{school} {student_number}"})
                    continue
                session.add(
                    StudentRoster(
                        school=school,
                        student_number=student_number,
                        class_name=class_name,
                        real_name=_norm(item.get("real_name")) or None,
                        remark=_norm(item.get("remark")) or None,
                        is_active=True,
                    )
                )
                created += 1
            session.commit()
            logger.info(f"[StudentRoster] 批量导入完成：新增 {created} 条，失败 {len(failures)} 条")
            return {"created": created, "failures": failures}
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 批量导入失败: {exc}")
            return {"created": 0, "failures": [{"row": 0, "reason": f"导入过程异常：{exc}"}]}
        finally:
            session.close()

    @staticmethod
    def verify(school, student_number, class_name):
        """
        身份绑定门禁校验：学校 + 学号 + 班级 三项均命中启用名单才通过。

        Returns:
            (bool, StudentRoster|None): 是否通过；通过时附带命中的名单条目
        """
        school = _norm(school)
        student_number = _norm(student_number)
        class_name = _norm(class_name)
        if not school or not student_number or not class_name:
            return False, None
        session = get_db()
        try:
            row = (
                session.query(StudentRoster)
                .filter(
                    StudentRoster.school == school,
                    StudentRoster.student_number == student_number,
                    StudentRoster.is_active.is_(True),
                )
                .first()
            )
            if not row:
                return False, None
            if row.class_name != class_name:
                return False, row
            return True, row
        finally:
            session.close()

    @staticmethod
    def list(school=None, keyword=None, page=1, page_size=20):
        """分页查询名单（关键字匹配 学号/班级/姓名）。"""
        session = get_db()
        try:
            query = session.query(StudentRoster)
            if school:
                query = query.filter(StudentRoster.school == school)
            if keyword:
                kw = f"%{keyword}%"
                query = query.filter(
                    or_(
                        StudentRoster.student_number.like(kw),
                        StudentRoster.class_name.like(kw),
                        StudentRoster.real_name.like(kw),
                    )
                )
            total = query.count()
            rows = (
                query.order_by(StudentRoster.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            items = [row.to_dict() for row in rows]
            # 聚合绑定状态：按 (school, student_number) 关联已绑定身份 + 用户，
            # 让管理端「学生身份」视图能直接看到每条名单被哪个用户认领 / 是否已绑定。
            numbers = {it["student_number"] for it in items if it.get("student_number")}
            profiles = []
            users = []
            if numbers:
                prof_rows = (
                    session.query(StudentProfile)
                    .filter(StudentProfile.student_number.in_(numbers))
                    .all()
                )
                profiles = [p.to_dict() for p in prof_rows]
                uids = [p.user_id for p in prof_rows if p.user_id]
                if uids:
                    user_rows = session.query(User).filter(User.id.in_(uids)).all()
                    users = [u.to_dict() for u in user_rows]
            _merge_binding(items, profiles, users)
            return {
                "total": total,
                "items": items,
                "page": page,
                "page_size": page_size,
            }
        finally:
            session.close()

    @staticmethod
    def update(roster_id, class_name=None, real_name=None, remark=None, is_active=None):
        """
        编辑名单条目（学校/学号只读，防止破坏绑定语义）。

        Returns:
            (row|None, error|None)
        """
        session = get_db()
        try:
            row = session.query(StudentRoster).filter_by(id=roster_id).first()
            if not row:
                return None, "名单条目不存在"
            if class_name is not None:
                class_name = _norm(class_name)
                if not class_name:
                    return None, "班级不能为空"
                row.class_name = class_name
            if real_name is not None:
                row.real_name = _norm(real_name) or None
            if remark is not None:
                row.remark = _norm(remark) or None
            if is_active is not None:
                row.is_active = bool(is_active)
            session.commit()
            session.refresh(row)
            return row, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 更新名单失败: {exc}")
            return None, "保存失败，请稍后重试"
        finally:
            session.close()

    @staticmethod
    def delete(roster_id):
        """删除名单条目。返回是否删除成功。"""
        session = get_db()
        try:
            row = session.query(StudentRoster).filter_by(id=roster_id).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 删除名单失败: {exc}")
            return False
        finally:
            session.close()
