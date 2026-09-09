#!/usr/bin/env python3
"""
学生名单服务（预录白名单）

- 管理端：新建 / 批量导入 / 编辑 / 停用启用 / 删除 名单条目 + 生成一次性绑定密钥
- 小程序端：verify() 校验「学校 + 学号 + 绑定码」命中启用名单（身份绑定门禁）

组织维度（v6.17）：
- 学校/学院/专业/班级 由 OrgUnit 树维护，名单通过 class_id 挂班级节点；
  school/college/major/class_name 为冗余列，由本服务从树路径带出写入（展示免 join）。
- 绑定门禁升级为「持有凭证」：管理员为学生生成一次性密钥（8 位随机码，
  存 sha256），学生凭「学校+学号+码」绑定；绑定成功即核销，杜绝"先到先得冒绑"。
"""

import hashlib
import secrets
import string

from sqlalchemy import or_

from app.core.database import get_db
from app.core.logger import get_logger
from app.model.org_unit import OrgUnit
from app.model.student_profile import StudentProfile
from app.model.student_roster import StudentRoster
from app.model.user import User
from app.services.org_unit_service import OrgUnitService

logger = get_logger(__name__)

# 绑定码字符集：去易混淆 0O1I，剩余 32 字符，8 位 → 32^8 ≈ 1.1 万亿空间
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def _norm(value):
    """去首尾空白，None 转空串"""
    return (value or "").strip()


def _hash_code(code):
    """绑定码 sha256（码统一大写后哈希，输入大小写不敏感）。"""
    return hashlib.sha256(_norm(code).upper().encode("utf-8")).hexdigest()


def generate_code():
    """生成 8 位随机绑定码（大写字母+数字，无 0O1I）。"""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


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

    # ---------- 组织归属辅助 ----------

    @staticmethod
    def _resolve_class(class_id):
        """校验 class_id 指向班级节点，返回其名称路径 dict；非法返回 None。"""
        if not class_id:
            return None
        session = get_db()
        try:
            node = session.query(OrgUnit).filter_by(id=class_id).first()
            if not node or node.node_type != "class":
                return None
            names = OrgUnitService._path_of(session, node)
            return names
        finally:
            session.close()

    # ---------- 新建 / 批量 ----------

    @staticmethod
    def create(class_id, student_number, real_name=None, remark=None, is_active=True):
        """按班级节点新建名单条目（学校/学院/专业/班级名由树继承带出）。

        Returns:
            (row|None, error|None)
        """
        class_id = class_id or None
        student_number = _norm(student_number)
        if not class_id or not student_number:
            return None, "班级与学号均不能为空"
        names = StudentRosterService._resolve_class(class_id)
        if not names:
            return None, "所选班级不存在或类型不正确"
        if not names.get("school") or not names.get("class"):
            return None, "班级节点缺少完整归属路径"
        session = get_db()
        try:
            exists = (
                session.query(StudentRoster)
                .filter_by(school=names["school"], student_number=student_number)
                .first()
            )
            if exists:
                return None, f"该学校下学号 {student_number} 已存在"
            row = StudentRoster(
                class_id=class_id,
                school=names["school"],
                college=names["college"],
                major=names["major"],
                class_name=names["class"],
                student_number=student_number,
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

        每行按名称路径定位班级节点（学校/学院/专业/班级须已先建好），
        学号只写一次，冗余路径名由树带出——批量导入模板无需逐行重复填组织名。

        Args:
            rows (list[dict]): 每项含 school / college / major / class_name /
                               student_number / real_name / remark
                               （real_name、remark 可缺省）。

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
                if not school or not student_number:
                    failures.append({"row": idx, "reason": "学校/学号为必填"})
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
                # 按名称路径定位班级（缺列则不参与定位；最终须落在 class 节点）
                cls = OrgUnitService.find_class_by_path(
                    school,
                    college=item.get("college"),
                    major=item.get("major"),
                    class_name=item.get("class_name"),
                )
                if not cls:
                    failures.append(
                        {
                            "row": idx,
                            "reason": "未找到匹配的班级节点（请先在组织管理中创建 学校→学院→专业→班级）",
                        }
                    )
                    continue
                names = OrgUnitService._path_of(session, cls)
                session.add(
                    StudentRoster(
                        class_id=cls.id,
                        school=names["school"],
                        college=names["college"],
                        major=names["major"],
                        class_name=names["class"],
                        student_number=student_number,
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

    # ---------- 绑定密钥 ----------

    @staticmethod
    def generate_bind_code(roster_id):
        """为学生生成一次性绑定码（覆盖旧码即旧码作废）。返回 (code|None, error|None)。

        明文仅在本次返回（调用方负责展示/导出）；库内只存 sha256。
        """
        session = get_db()
        try:
            row = session.query(StudentRoster).filter_by(id=roster_id).first()
            if not row:
                return None, "名单条目不存在"
            code = generate_code()
            row.bind_code_hash = _hash_code(code)
            session.commit()
            return code, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 生成绑定码失败: {exc}")
            return None, "生成失败，请稍后重试"
        finally:
            session.close()

    @staticmethod
    def generate_bind_codes(roster_ids):
        """批量生成绑定码（事务内逐条），供导出 CSV 一次性发放。

        Returns:
            list[{"roster_id", "student_number", "real_name", "code"}]（仅含成功条目）
        """
        session = get_db()
        results = []
        try:
            for rid in roster_ids:
                row = session.query(StudentRoster).filter_by(id=rid).first()
                if not row:
                    continue
                code = generate_code()
                row.bind_code_hash = _hash_code(code)
                results.append(
                    {
                        "roster_id": row.id,
                        "student_number": row.student_number,
                        "real_name": row.real_name,
                        "code": code,
                    }
                )
            session.commit()
            logger.info(f"[StudentRoster] 批量生成绑定码 {len(results)} 条")
            return results
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 批量生成绑定码失败: {exc}")
            return []
        finally:
            session.close()

    @staticmethod
    def revoke_bind_code(roster_id):
        """作废绑定码（不换新），使该生暂时不可绑定。返回是否成功。"""
        session = get_db()
        try:
            row = session.query(StudentRoster).filter_by(id=roster_id).first()
            if not row:
                return False
            row.bind_code_hash = None
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 作废绑定码失败: {exc}")
            return False
        finally:
            session.close()

    @staticmethod
    def _consume_bind_code(session, row):
        """绑定成功后核销码（同一事务内调用，不自行 commit/close）。"""
        row.bind_code_hash = None

    # ---------- 绑定门禁 ----------

    @staticmethod
    def verify(school, student_number, bind_code):
        """
        身份绑定门禁校验：学校 + 学号 + 一次性绑定码 命中启用名单才通过。

        学号/班级属半公开信息，码为管理员私下发放的持有凭证——防止
        "知道别人学号就抢先绑定"（先到先得冒绑）。码绑定成功即核销。

        Returns:
            (bool, StudentRoster|None): 是否通过；通过时附带命中的名单条目
        """
        school = _norm(school)
        student_number = _norm(student_number)
        bind_code = _norm(bind_code)
        if not school or not student_number or not bind_code:
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
            # 未发放码 / 已核销 → 不可绑定
            if not row.bind_code_hash:
                return False, row
            if row.bind_code_hash != _hash_code(bind_code):
                return False, row
            return True, row
        finally:
            session.close()

    @staticmethod
    def list(school=None, class_id=None, keyword=None, page=1, page_size=20):
        """分页查询名单（可选：学校 / 班级节点 / 关键字）。"""
        session = get_db()
        try:
            query = session.query(StudentRoster)
            if school:
                query = query.filter(StudentRoster.school == school)
            if class_id:
                query = query.filter(StudentRoster.class_id == class_id)
            if keyword:
                kw = f"%{keyword}%"
                query = query.filter(
                    or_(
                        StudentRoster.student_number.like(kw),
                        StudentRoster.class_name.like(kw),
                        StudentRoster.college.like(kw),
                        StudentRoster.major.like(kw),
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
    def export(school=None, class_id=None, keyword=None):
        """不分页查询名单（导出 CSV 用），复用与 list 相同的筛选与绑定聚合逻辑。"""
        session = get_db()
        try:
            query = session.query(StudentRoster)
            if school:
                query = query.filter(StudentRoster.school == school)
            if class_id:
                query = query.filter(StudentRoster.class_id == class_id)
            if keyword:
                kw = f"%{keyword}%"
                query = query.filter(
                    or_(
                        StudentRoster.student_number.like(kw),
                        StudentRoster.class_name.like(kw),
                        StudentRoster.college.like(kw),
                        StudentRoster.major.like(kw),
                        StudentRoster.real_name.like(kw),
                    )
                )
            rows = query.order_by(StudentRoster.id.desc()).all()
            items = [row.to_dict() for row in rows]
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
            return items
        finally:
            session.close()

    @staticmethod
    def update(roster_id, class_id=None, real_name=None, remark=None, is_active=None):
        """
        编辑名单条目（学校/学号只读，防止破坏绑定语义）。
        class_id 换班时自动带出新的冗余路径名。

        Returns:
            (row|None, error|None)
        """
        session = get_db()
        try:
            row = session.query(StudentRoster).filter_by(id=roster_id).first()
            if not row:
                return None, "名单条目不存在"
            if class_id is not None:
                class_id = class_id or None
                names = StudentRosterService._resolve_class(class_id)
                if not names:
                    return None, "所选班级不存在或类型不正确"
                row.class_id = class_id
                row.school = names["school"]
                row.college = names["college"]
                row.major = names["major"]
                row.class_name = names["class"]
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

    @staticmethod
    def unbind(roster_id):
        """
        管理端「解绑/收回身份」：清空已绑定该名单条目的用户身份快照，保留名单条目本身
        并重发一次性绑定码，使其可立即重新绑定（对应小程序「重新绑定身份」诉求）。

        - 按 (school, student_number) 定位绑定用户（与 _merge_binding / 绑定门禁同键）；
        - 清空 student_profiles 身份字段（学号/学校/学院/专业/班级/年级/姓名/校园卡号），
          用户随即落到「未绑定」，被 student_bound_required 拦截并走绑定流程；
        - 吊销该用户全部活跃会话（强制重新登录，确保小程序端立即反映未绑定状态）；
        - 名单条目保留，bind_code_hash 重置为新码（明文随本次返回，供管理员私下发放）；
        - 若名单未被绑定（无匹配 profile）返回 (None, "该名单未被任何用户绑定")，不报错。
        """
        session = get_db()
        try:
            row = session.query(StudentRoster).filter_by(id=roster_id).first()
            if not row:
                return None, "名单条目不存在"
            profile = (
                session.query(StudentProfile)
                .filter_by(school=row.school, student_number=row.student_number)
                .first()
            )
            if not profile or profile.user_id is None:
                return None, "该名单未被任何用户绑定"
            # 清空身份字段（保留昵称/手机号/电表cookie等个人数据，避免误删配置）
            profile.student_number = None
            profile.school = None
            profile.campus_card_number = None
            profile.real_name = None
            profile.college = None
            profile.major = None
            profile.class_name = None
            profile.grade = None
            # 吊销该用户全部会话，强制重新登录以走绑定流程
            try:
                from app.services.session_service import session_service

                session_service.delete_all_user_sessions(
                    profile.user_id, reason="admin_unbind"
                )
            except Exception as exc:
                logger.warning(f"[StudentRoster] 解绑吊销会话失败（忽略）: {exc}")
            # 保留名单，重发一次性绑定码
            code = generate_code()
            row.bind_code_hash = _hash_code(code)
            session.commit()
            return code, None
        except Exception as exc:
            session.rollback()
            logger.error(f"[StudentRoster] 解绑身份失败: {exc}")
            return None, "解绑失败，请稍后重试"
        finally:
            session.close()
