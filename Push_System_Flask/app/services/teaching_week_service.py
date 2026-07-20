#!/usr/bin/env python3
"""
教学周唯一真相源服务。

职责：回答「当前是第几教学周 / 今天是否在教学周内」这一个唯一问题。
所有需要周次判定的地方（课表展示过滤、推送拦截）都必须走这里，
杜绝过去「硬编码日历 get_current_week_number」与「查 course_weeks 表
_is_in_teaching_week」两套口径相互矛盾、各算各的乱象。

权威判定顺序：
  1. 假期模式激活（holiday_service，管理员显式配置） -> 非教学周（None）
  2. 基于开学日推算当前周次：
       开学日 = 配置 system.semester_start_date（管理员可填）
                或按 term 默认推算（秋=9/1，春=次年3/2）
        weeks_passed = (today - 开学日).days // 7 + 1
        1 <= weeks_passed <= weeks_max(默认20, 可配) -> 该周次
  3. 否则 -> 非教学周（None）

注意：开学日不再依赖任何数据库表（旧 course_weeks 表已彻底移除于本次重构），
爬虫与系统均无法污染开学基准，从根上杜绝「暑假被算成第2周」类脏数据。
"""

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


# 每学期教学周数上限（超出视为已放假：暑假/寒假）。
# 中国高校教学周一般 16~20 周，含小学期/延长可达 21~22 周；
# 取 22 作为内置下限保护，可在 module_configs 的 system.teaching_weeks_max
# 覆盖（如贵校确为 18 周则配 18）。注意：最终上限不低于 22，避免把
# "第21周"（开学日 3/2 推算，7 月下旬已满 21 周）误判为非教学周；
# 真暑假（8 月及以后，推算 ≥23 周）仍远超此上限，正确归为非教学周。
_DEFAULT_TEACHING_WEEKS_MAX = 22


def _get_weeks_max() -> int:
    """读取教学周数上限。

    权威来源优先级：
      1. 配置 system.teaching_weeks_max（管理员可覆盖，如贵校确为 18 周则配 18）
      2. 教务系统真实界限：爬虫抓到的 course_meta.json 的 weeks 最大值
         （从教务系统「教学周」下拉框抓取，随日常爬取自愈）
      3. 兜底 _DEFAULT_TEACHING_WEEKS_MAX（22，覆盖含小学期的长学期）

    下限保护：无论配置/爬虫快照如何，最终上限不低于 22。
    原因见模块常量注释——防止 7 月下旬的第 21 周被错误截断为暑假。
    """
    candidates = [_DEFAULT_TEACHING_WEEKS_MAX]  # 内置下限保护
    # 1. 配置覆盖
    try:
        from app.services.config_service import get_config_service

        _cfg = get_config_service().get("system", "teaching_weeks_max", None)
        if _cfg:
            candidates.append(int(_cfg))
    except Exception:
        pass
    # 2. 教务系统真实界限（爬虫产物，随爬取自愈）
    try:
        import json
        import os

        _meta_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cqie-course-timetable",
            "output",
            "course-data",
            "raw",
            "course_meta.json",
        )
        if os.path.exists(_meta_path):
            with open(_meta_path, encoding="utf-8") as _f:
                _meta = json.load(_f)
            _weeks = _meta.get("weeks") or []
            if _weeks:
                candidates.append(max(int(w) for w in _weeks))
    except Exception:
        pass
    return max(candidates)


def get_semester_start_date(semester_id: int | None = None) -> date | None:
    """返回指定学期的开学日（第1周基准日）。

    优先级：
      1. 配置 system.semester_start_date（管理员在后台填写的当前学期开学日，ISO 日期）。
         仅当未指定 semester_id（即当前学期）时生效。
      2. 按 term 默认推算：
            term==1（秋季）：year-09-01
            term==2（春季）：(year+1)-03-02
         其中 year = semester_id // 10（如 20251 -> 2025，20252 -> 2025）。
         与前端 src/utils/semester.ts 的 getSemesterStartDate 保持一致。

    Args:
        semester_id: DB 格式学期 id（如 20251）；None 表示当前学期。

    Returns:
        date | None: 开学日；无法推算时 None。
    """
    # 1. 配置覆盖（仅当前学期）
    if semester_id is None:
        try:
            from app.services.config_service import get_config_service

            _cfg = get_config_service().get("system", "semester_start_date", "")
            if _cfg:
                try:
                    return datetime.strptime(str(_cfg).strip(), "%Y-%m-%d").date()
                except Exception:
                    logger.warning(f"[教学周] semester_start_date 配置非法: {_cfg}")
        except Exception:
            pass
        # 回退到当前学期 id 再做 term 推算
        try:
            from app.repository.course_repository import derive_current_semester

            semester_id = derive_current_semester()["semester_id"]
        except Exception:
            return None

    if not semester_id:
        return None

    # 2. 按 term 默认推算（与前端 semester.ts 对齐）
    year = semester_id // 10
    term = semester_id % 10
    if term == 1:
        return date(year, 9, 1)
    # term == 2（春）：次年 3 月 2 日
    return date(year + 1, 3, 2)


def get_current_teaching_week() -> int | None:
    """返回当前教学周周次；非教学周/假期/未配置/异常均返回 None。

    判定基准：开学日（配置 system.semester_start_date 或按 term 推算）。
    用 ``(today - 开学日).days // 7 + 1`` 推算当前周次，并做教学周上限校验。

    为什么不再依赖数据库表：
        旧 course_weeks 表的锚点由爬虫写入，暑假爬取会把开学锚点(week1)
        写成暑假日期（如 7/13），导致 7/20 被算成「第2周」、暑假仍显示
        「上课中」。改为「开学日推算 + 上限校验」后，开学日来自配置/固定
        规则，爬虫无法污染，从根上杜绝脏数据。
    """
    # 1. 假期模式优先：管理员显式静默期，一律视为非教学周
    try:
        from app.services.holiday_service import holiday_service

        if holiday_service.is_active()[0]:
            return None
    except Exception as e:
        logger.warning(f"[教学周] 假期模式判断异常，继续走开学日推算: {e}")

    # 2. 基于开学日推算当前周次
    try:
        start = get_semester_start_date(None)
        if not start:
            return None

        today = date.today()
        weeks_max = _get_weeks_max()
        weeks_passed = (today - start).days // 7 + 1
        if today >= start and 1 <= weeks_passed <= weeks_max:
            return weeks_passed
        return None
    except Exception as e:
        logger.warning(f"[教学周] 开学日推算异常，视为非教学周: {e}")
        return None


def build_available_weeks(
    semester_id: int | None = None, weeks_max: int | None = None
) -> list[dict]:
    """基于开学日推算周次列表（替代旧 course_weeks 表查询）。

    返回 ``[{"week_number", "start_date", "end_date"}, ...]``，字段名保持
    week_number/start_date/end_date，前端无需改动即可消费。

    Args:
        semester_id: 学期 id；None 表示当前学期
        weeks_max: 周数上限；None 取配置/默认
    """
    start = get_semester_start_date(semester_id)
    if not start:
        return []
    if weeks_max is None:
        weeks_max = _get_weeks_max()
    weeks: list[dict] = []
    for i in range(1, weeks_max + 1):
        ws = start + timedelta(days=(i - 1) * 7)
        we = ws + timedelta(days=6)
        weeks.append(
            {
                "week_number": i,
                "start_date": ws.strftime("%Y-%m-%d"),
                "end_date": we.strftime("%Y-%m-%d"),
            }
        )
    return weeks
