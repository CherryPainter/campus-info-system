#!/usr/bin/env python3
"""
课表管理服务

职责：
- 从数据库加载课表数据
- 提供课表查询接口
- 管理课表缓存

遵循分层架构：
- Service 层负责业务逻辑
- Repository 层负责数据库操作
"""

import json
import threading
from datetime import date, datetime, timedelta
from typing import Any

from app.core.database import get_db
from app.core.logger import get_logger
from app.repository.course_repository import CourseRepository, derive_current_semester, get_current_semester_id

# 使用统一日志系统
logger = get_logger(__name__)


class ScheduleService:
    """
    课表数据管理服务

    职责：
    - 从数据库加载课表数据
    - 提供课表查询接口
    - 管理内存缓存
    """

    def __init__(self):
        self._schedules: list[dict[str, Any]] = []
        self._last_updated: datetime | None = None
        self._lock = threading.Lock()
        self._refresh_timer: threading.Timer | None = None
        self._data_ready: bool = False
        self._app = None
        self._refresh_interval: int = 60  # 60秒刷新

    def init_app(self, app) -> None:
        """
        初始化服务

        Args:
            app: Flask 应用实例
        """
        self._app = app
        self.load_schedules()
        self._start_auto_refresh()
        logger.info("课表服务初始化完成（数据源：数据库）")

    def _start_auto_refresh(self) -> None:
        """启动自动刷新定时器"""
        self._refresh_timer = threading.Timer(self._refresh_interval, self._auto_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _auto_refresh(self) -> None:
        """自动刷新循环"""
        self.load_schedules()
        self._refresh_timer = threading.Timer(self._refresh_interval, self._auto_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def load_schedules(self) -> bool:
        """
        从数据库加载课表数据

        Returns:
            bool: 是否加载成功
        """
        try:
            session = get_db()
            try:
                # 从数据库获取当前学期的课程
                # 隐患修复：get_all 原本不过滤学期，会把所有学期课程一并加载并按
                # week_number 排到本周日期推送，导致新旧学期同周次课程重复推送。
                # 这里只加载"当前学期"，与网页端 /course/timetable 口径一致：
                # 优先读 course_meta.json 的真实在用学期，回退按日期推导。
                courses = CourseRepository.get_all(
                    session, semester_id=get_current_semester_id()
                )

                # 转换为推送服务需要的格式
                transformed = self._transform(courses)

                with self._lock:
                    # 隐患修复：原条件 `if len(transformed) != len(self._schedules)`
                    # 只比条数，条数不变但内容变化（如 UPDATE 某条记录的 periods/period_idx）
                    # 会导致缓存永远不刷新、API 持续返回旧数据。
                    # 定时器反正每 60 秒重读 DB，取消条数门控直接覆盖更稳妥。
                    prev_count = len(self._schedules)
                    self._schedules = transformed
                    self._last_updated = datetime.now()
                    if prev_count != len(transformed):
                        logger.info(
                            f"从数据库加载了 {len(self._schedules)} 条课表数据"
                        )
                    self._data_ready = True

                return True
            finally:
                session.close()
        except Exception as e:
            logger.error(f"从数据库加载课表数据失败: {e}")
            return False

    def _transform(
        self, courses: list, week1_monday: date | None = None
    ) -> list[dict[str, Any]]:
        """
        将数据库模型转换为推送服务需要的格式

        Args:
            courses: Course 模型列表
            week1_monday: 可选。历史学期查看时传入该学期第 1 周的周一基准日，
                使 full_date/时间戳锚定到该学期真实日历；缺省为 None = 按当前周。

        Returns:
            List[Dict]: 转换后的课表数据
        """
        result = []

        for course in courses:
            # 计算日期（week1_monday 传入时锚定该基准，否则基于当前周次和星期几）
            course_date = self._calculate_date(
                course.week_day, course.week_number, week1_monday=week1_monday
            )
            if course_date is None:
                continue

            start_time = course.start_time or "00:00"
            end_time = course.end_time or "00:00"
            periods = course.periods or ""
            building = course.building or ""

            # 用课表规定的时间覆盖（去除任何“减10分钟”之类的调整，保证通知时间严格按课表）
            try:
                from app.utils.course_helpers import apply_timetable_times

                fixed = apply_timetable_times(
                    {
                        "periods": periods,
                        "period_idx": course.period_idx,
                        "start_time": start_time,
                        "end_time": end_time,
                        "extra_info": {
                            "building": building,
                            "full_date": course_date.strftime("%Y-%m-%d"),
                        },
                    }
                )
                start_time = fixed.get("start_time", start_time)
                end_time = fixed.get("end_time", end_time)
            except Exception:
                pass  # 失败则退回数据库原值

            # 构建推送服务需要的格式
            result.append(
                {
                    "schedule_id": str(course.id),
                    "day_of_week": course.week_day,
                    "start_time": start_time,
                    "end_time": end_time,
                    "course_name": course.course_name,
                    "course_code": "",
                    "period_idx": course.period_idx,  # 添加节次索引
                    "periods": periods,  # 添加节次列表
                    "extra_info": {
                        "teacher": course.teacher or "",
                        "building": building,
                        "classroom": course.classroom or "",
                        "weeks": course.weeks or "",
                        "credits": "",
                        "full_date": course_date.strftime("%Y-%m-%d"),
                    },
                    "_timeInfo": {
                        "start_ts": self._get_timestamp(course_date, start_time),
                        "end_ts": self._get_timestamp(course_date, end_time),
                    },
                }
            )

        # 合并同天、同课名、同教室的多条记录为一条
        # 爬虫可能把一门 5-8 节的课拆成 4 条单节记录分别存储，这里统一合并，
        # 让前端拿到正确的 periods 数组（如 [5,6,7,8]），而非分散的 [5]/[6]/[7]/[8]。
        return self._merge_split_courses(result)

    @staticmethod
    def _merge_split_courses(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        合并同一天、同一课程名、同一教室的多条记录。

        爬虫按单节写入时会产生多条记录（如 5-8 节写成 periods=[5]、[6]、[7]、[8] 各一条），
        本方法将它们合并为 periods=[5,6,7,8] 的单条记录，schedule_id 取组内第一条。

        Args:
            courses: _transform 产出的原始记录列表

        Returns:
            合并后的记录列表（与 /course/list 接口合并口径一致）
        """
        if not courses:
            return courses

        def _normalize_periods(p) -> list[int]:
            """把 periods 的各种格式统一为 list[int]"""
            if isinstance(p, list):
                return [int(x) for x in p if isinstance(x, (int, str)) and str(x).strip().isdigit()]
            if isinstance(p, str):
                try:
                    a = json.loads(p)
                    if isinstance(a, list):
                        return [int(x) for x in a if isinstance(x, (int, str)) and str(x).strip().isdigit()]
                except (json.JSONDecodeError, ValueError):
                    pass
                if p.strip():
                    return [int(x.strip()) for x in p.split(",") if x.strip().isdigit()]
            return []

        merged: dict[tuple, dict[str, Any]] = {}
        for c in courses:
            extra = c.get("extra_info") or {}
            key = (
                c.get("day_of_week"),
                c.get("course_name"),
                extra.get("classroom") or "",
                extra.get("full_date") or "",
            )

            if key in merged:
                existing = merged[key]
                # 合并 periods
                all_p = sorted(set(_normalize_periods(existing.get("periods")) + _normalize_periods(c.get("periods"))))
                existing["periods"] = all_p
                existing["period_idx"] = min(all_p) if all_p else existing.get("period_idx")

                # 更新时间：取 periods 最小时对应的 start_time、最大时对应的 end_time
                if all_p:
                    # 简单策略：直接取 start_time 最早、end_time 最晚的
                    if c.get("start_time", "") and c["start_time"] < existing.get("start_time", "99:99"):
                        existing["start_time"] = c["start_time"]
                        existing["_timeInfo"]["start_ts"] = c.get("_timeInfo", {}).get("start_ts", existing["_timeInfo"]["start_ts"])
                    if c.get("end_time", "") and c["end_time"] > existing.get("end_time", "00:00"):
                        existing["end_time"] = c["end_time"]
                        existing["_timeInfo"]["end_ts"] = c.get("_timeInfo", {}).get("end_ts", existing["_timeInfo"]["end_ts"])
            else:
                merged[key] = dict(c)

        # 合并后 periods 可能已改变（从 [5]/[6]/[7]/[8] → [5,6,7,8]），
        # 再用课表权威时间覆盖 start_time / end_time，保证时间与 periods 严格对齐。
        result = list(merged.values())
        try:
            from app.utils.course_helpers import apply_timetable_times

            for c in result:
                fixed = apply_timetable_times(c)
                c["start_time"] = fixed.get("start_time", c.get("start_time", ""))
                c["end_time"] = fixed.get("end_time", c.get("end_time", ""))
        except Exception:
            pass

        return result

    def _calculate_date(
        self, week_day: int, week_number: int | None, week1_monday: date | None = None
    ) -> date | None:
        """
        根据星期几和周次计算日期

        锚定规则（与前端周历口径一致）：
        - week1_monday 传入（历史学期/任意学期）：以该学期第 1 周的周一为基准，
          直接 ``week1_monday + (week_number-1)*7 + (week_day-1)`` 得到真实日历日期。
        - week1_monday 为 None（当前学期默认）：以「当前真实日历周一」为基准，
          按 (week_number − 当前教学周) 做相对偏移。这样切换周只是"围绕当前时间
          查看那个周的课程"，不会把日期跳到教学周真实日历（如第2周跳到 03-09），
          且 getWeek 返回的 full_date 与前端周历显示日期天然对齐。

        Args:
            week_day: 星期几 (1-7)
            week_number: 周次
            week1_monday: 可选，基准周一；缺省走当前周相对锚定

        Returns:
            Optional[date]: 计算出的日期
        """
        if week1_monday is not None:
            if week_number is None:
                week_number = 1
            return week1_monday + timedelta(
                weeks=week_number - 1, days=week_day - 1
            )

        today = date.today()
        if week_number is None:
            days_ahead = week_day - today.isoweekday()
            return today + timedelta(days=days_ahead)

        current_weekday = today.isoweekday()  # 1=周一, 7=周日
        days_since_monday = current_weekday - 1
        this_monday = today - timedelta(days=days_since_monday)

        current_week_number = self._get_current_week_number()
        if current_week_number is None:
            current_week_number = 1

        weeks_diff = week_number - current_week_number
        target_monday = this_monday + timedelta(weeks=weeks_diff)
        target_date = target_monday + timedelta(days=week_day - 1)
        return target_date

    def _get_current_week_number(self) -> int | None:
        """
        获取当前周次

        Returns:
            Optional[int]: 当前周次
        """
        try:
            from app.utils.course_helpers import get_current_week_number

            wk = get_current_week_number()
            # 0 表示非教学周，按要求转为 None（调用方据此回退第 1 周）
            return wk if wk else None
        except Exception:
            return None

    def _get_timestamp(self, course_date: date, time_str: str) -> float:
        """
        获取时间戳

        Args:
            course_date: 日期
            time_str: 时间字符串 (HH:MM)

        Returns:
            float: 时间戳
        """
        try:
            parts = time_str.split(":")
            h = int(parts[0]) if len(parts) > 0 else 0
            m = int(parts[1]) if len(parts) > 1 else 0
            dt = datetime(course_date.year, course_date.month, course_date.day, h, m)
            return dt.timestamp()
        except Exception:
            return 0.0

    def _enrich_is_today(self, schedules: list[dict]) -> list[dict]:
        """
        为课表列表动态计算 is_today 字段

        Args:
            schedules: 课表列表

        Returns:
            List[Dict]: 添加了 is_today 字段的课表列表
        """
        today_str = date.today().strftime("%Y-%m-%d")
        result = []
        for s in schedules:
            enriched = dict(s)
            enriched["_timeInfo"] = dict(s["_timeInfo"])
            enriched["_timeInfo"]["is_today"] = s["extra_info"]["full_date"] == today_str
            result.append(enriched)
        return result

    @property
    def is_data_ready(self) -> bool:
        """是否曾成功加载过课表数据"""
        return self._data_ready

    def get_schedules(self, force_reload: bool = False) -> list[dict[str, Any]]:
        """
        获取所有课表

        Args:
            force_reload: 是否强制重新加载

        Returns:
            List[Dict]: 课表列表
        """
        if force_reload:
            self.load_schedules()
        with self._lock:
            schedules = list(self._schedules)
        return self._enrich_is_today(schedules)

    def get_schedules_for_semester(self, semester_id: int) -> list[dict[str, Any]]:
        """
        获取指定学期的整学期课表（ScheduleCourse 形状，供小程序/网页历史学期查看）。

        当前学期直接复用内存缓存（self._schedules）；非当前学期临时查库并按其
        开学日锚定真实日期（full_date/_timeInfo），避免历史学期被"围绕今天相对偏移"
        而算错日期。

        Args:
            semester_id: 目标学期 DB id（如 20252）

        Returns:
            List[Dict]: 该学期课表 dict 列表
        """
        try:
            from app.repository.course_repository import get_current_semester_id

            if semester_id == get_current_semester_id():
                return self.get_schedules()
        except Exception:
            pass

        # 非当前学期：直接查库（按学期过滤），并解析该学期开学日锚定第 1 周周一
        session = get_db()
        try:
            courses = CourseRepository.get_all(session, semester_id=semester_id)
        finally:
            session.close()

        week1_monday = None
        try:
            from app.services.teaching_week_service import get_semester_start_date

            start = get_semester_start_date(semester_id)
            if start:
                week1_monday = start - timedelta(days=start.isoweekday() - 1)
        except Exception:
            pass

        return self._transform(courses, week1_monday=week1_monday)

    def get_today_schedules(
        self, force_reload: bool = False, target_date: str | None = None
    ) -> list[dict[str, Any]]:
        """
        获取指定日期课表（默认今天）

        Args:
            force_reload: 是否强制重新加载
            target_date: 目标日期（YYYY-MM-DD），缺省今天

        Returns:
            List[Dict]: 该日期课表列表

        判定口径（v6.18.x 修复）：
            不再依赖 extra_info.full_date 的精确日期匹配。原因：full_date 由
            _calculate_date 基于课程静态字段 week_number（爬虫写入当周、不会随真实
            教学周推进）相对当前周偏移得到；一旦真实教学周超过爬虫写入的 week_number，
            full_date 被整体偏移到过去/未来周，导致「今日课程」在跨周后恒为空
            （用户反馈"过了一个周就一直显示今日无课"）。

            改为与 /schedule/week 接口、前端周视图一致的口径：
                「星期几 == 目标日星期」且「当前教学周 ∈ 课程 weeks 数组」
            命中后把 full_date 与 _timeInfo 时间戳修正为目标日，保证 CourseCard
            的"进行中/已结束"状态计算正确（start_ts/end_ts 必须落在目标日）。
        """
        from app.utils.course_helpers import is_course_in_week

        today = (
            datetime.strptime(target_date, "%Y-%m-%d").date()
            if target_date
            else date.today()
        )
        target_str = today.strftime("%Y-%m-%d")
        target_wd = today.isoweekday()

        # 当前教学周（int；非教学周/假期为 None）。转成 0 交给 is_course_in_week，
        # 后者对 <=0 直接返回 False（假期不显示课程，符合预期）。
        current_week = self._get_current_week_number()
        current_week = current_week if current_week else 0

        result = []
        for s in self.get_schedules(force_reload):
            if s.get("day_of_week") != target_wd:
                continue
            weeks = (s.get("extra_info") or {}).get("weeks")
            if not is_course_in_week(weeks, current_week):
                continue
            item = dict(s)
            item["extra_info"] = dict(s.get("extra_info") or {})
            item["extra_info"]["full_date"] = target_str
            item["_timeInfo"] = dict(s.get("_timeInfo") or {})
            item["_timeInfo"]["is_today"] = True
            item["_timeInfo"]["start_ts"] = self._get_timestamp(
                today, s.get("start_time") or "00:00"
            )
            item["_timeInfo"]["end_ts"] = self._get_timestamp(
                today, s.get("end_time") or "00:00"
            )
            result.append(item)
        return result

    def get_upcoming_courses(
        self, minutes: int = 30, force_reload: bool = False
    ) -> list[dict[str, Any]]:
        """
        获取即将开始的课程

        Args:
            minutes: 提前多少分钟
            force_reload: 是否强制重新加载

        Returns:
            List[Dict]: 即将开始的课程列表
        """
        now = datetime.now().timestamp()
        future = now + minutes * 60
        return sorted(
            [
                s
                for s in self.get_schedules(force_reload)
                if s["_timeInfo"]["start_ts"] > now
                and s["_timeInfo"]["start_ts"] <= future
                and s["_timeInfo"].get("is_today", False)
            ],
            key=lambda x: x["_timeInfo"]["start_ts"],
        )

    def get_statistics(self) -> dict[str, Any]:
        """
        获取统计信息

        Returns:
            Dict: 统计数据
        """
        schedules = self.get_schedules()
        return {
            "total": len(schedules),
            "today": sum(1 for s in schedules if s["_timeInfo"].get("is_today", False)),
            "unique_courses": len(
                {s["course_name"] for s in schedules if s["course_name"] != "未命名课程"}
            ),
            "unique_teachers": len(
                {s["extra_info"]["teacher"] for s in schedules if s["extra_info"].get("teacher")}
            ),
            "data_ready": self._data_ready,
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
        }


# 全局单例
schedule_service = ScheduleService()
