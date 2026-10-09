#!/usr/bin/env python3
"""学生身份键（student_key）通用工具 —— 所有个人数据归属维度的唯一收口点。

个人数据（电量 / 反馈 / 站内通知 / 公告已读收藏 / 头像昵称）的「归属维度」统一为
student_key = "学校|学号"，与微信号（user_id）解耦：换微信号（换 appid、重绑）不丢数据。

本模块是 student_key 的单一事实来源，避免各业务模块各写一套导致口径漂移：
- make_student_key        : (学校, 学号) -> student_key
- student_key_of_user     : user_id -> 其当前绑定身份的 student_key
- scope_filter            : 归属过滤表达式（读路径按 student_key 归属 + user_id 兜底）

注意：电量重构早期把 make_student_key / student_key_of_user 放在了 electricity_repository，
为消除耦合、统一收口，已迁移到本模块；electricity_repository 改为从本模块导入并继续
对外（admin_routes / electricity_routes / capacity_manager / electricity_service 等）
以原路径导出，调用方无需改动。
"""

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.model.student_profile import StudentProfile


def make_student_key(school: str | None, student_number: str | None) -> str | None:
    """
    由 (学校, 学号) 构造学生身份键。

    NULL 规则：学校或学号任一为空都返回 None（未绑定身份），
    此时数据不归属任何具体身份（仅全局视图可见）。
    """
    if not school or not student_number:
        return None
    return f"{school}|{student_number}"


def student_key_of_user(session: Session, user_id: int) -> str | None:
    """
    由 user_id 反查其当前绑定身份的学生身份键（student_key）。

    用于采集/读取入口拿到 JWT 的 user_id 时，反解为数据归属维度。
    无资料 / 未绑定身份时返回 None。

    优先取 student_profiles.student_key（绑定/回填时写入的权威值），
    缺省时回退到 (school, student_number) 现场拼装，二者语义一致。
    """
    row = (
        session.query(
            StudentProfile.student_key,
            StudentProfile.school,
            StudentProfile.student_number,
        )
        .filter(StudentProfile.user_id == user_id)
        .first()
    )
    if not row:
        return None
    if row.student_key:
        return row.student_key
    return make_student_key(row.school, row.student_number)


def scope_filter(model_cls, user_id: int, student_key: str | None):
    """
    个人数据「归属过滤」单一收口（读路径统一走这里）。

    规则：
    - 已绑定身份（student_key 非空）：归属该 student_key（换微信号共享同一学生数据）；
      同时兜底 student_key 为空但 user_id 命中（历史/未绑定身份时写入的孤立行）。
    - 未绑定身份（student_key 为空）：退化为按 user_id 审计列（仅本人可见）。

    用法：
        q = session.query(Model).filter(scope_filter(Model, user_id, sk))
    """
    if student_key:
        return or_(
            model_cls.student_key == student_key,
            and_(model_cls.student_key.is_(None), model_cls.user_id == user_id),
        )
    return model_cls.user_id == user_id
