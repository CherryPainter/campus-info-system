#!/usr/bin/env python3
"""
课程时间 / 周次相关的纯函数与常量（无副作用）

原位于 app.api.course_routes 顶部，作为路由处理函数与多个 service 共同依赖的
纯计算逻辑。将其下沉到 utils 层，可以：

1. 消除「service 反向 import api 层」的分层倒置
   （delivery_service / rule_service / schedule_service 原先从 course_routes 取纯函数）；
2. 让路由层保持「薄」——只负责请求解析、鉴权、编排，不承载领域计算；
3. 该模块为依赖图叶子节点（仅依赖标准库），任何层都可安全 import。

约定：本模块所有函数均为纯函数，不碰数据库、不读配置、不发请求。
"""

import json
from datetime import datetime

# 爬虫有两套时间表，根据楼栋选择
# 第一套（first）：启智楼、雏鹰楼、语慧楼、思源楼、讯达楼、盛德楼
# 第二套（second）：艺教楼、图书馆、理工楼、鸿志楼、明远楼

# 第一套时间表
FIRST_SCHEDULE = {
    1: ("08:10", "08:55"),  # 第一节
    2: ("09:05", "09:50"),  # 第二节
    3: ("10:10", "10:55"),  # 第三节
    4: ("11:05", "11:50"),  # 第四节
    5: ("14:10", "14:55"),  # 第五节
    6: ("15:05", "15:50"),  # 第六节
    7: ("16:10", "16:55"),  # 第七节
    8: ("17:05", "17:50"),  # 第八节
    9: ("18:50", "19:35"),  # 第九节
    10: ("19:35", "20:20"),  # 第十节
    11: ("20:30", "21:15"),  # 第十一节
    12: ("21:15", "22:00"),  # 第十二节
}

# 第二套时间表
SECOND_SCHEDULE = {
    1: ("08:10", "08:55"),  # 第一节
    2: ("09:05", "09:50"),  # 第二节
    3: ("10:30", "11:15"),  # 第三节
    4: ("11:25", "12:10"),  # 第四节
    5: ("14:10", "14:55"),  # 第五节
    6: ("15:05", "15:50"),  # 第六节
    7: ("16:30", "17:15"),  # 第七节
    8: ("17:25", "18:10"),  # 第八节
    9: ("18:50", "19:35"),  # 第九节
    10: ("19:35", "20:20"),  # 第十节
    11: ("20:30", "21:15"),  # 第十一节
    12: ("21:15", "22:00"),  # 第十二节
}

# 第一套教学楼
FIRST_SCHEDULE_BUILDINGS = [
    "启智楼",
    "雏鹰楼",
    "语慧楼",
    "思源楼",
    "讯达楼",
    "盛德楼",
    "S01",
    "S02",
    "J01",
    "J04",
    "J14",
    "J15",
]

_CN_NUM = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
    11: "十一",
    12: "十二",
}

# 默认使用第二套（兼容旧数据）
PERIOD_TIME_MAP = SECOND_SCHEDULE


def get_schedule_by_building(building: str) -> dict:
    """根据楼栋获取对应的时间表"""
    if building in FIRST_SCHEDULE_BUILDINGS:
        return FIRST_SCHEDULE
    return SECOND_SCHEDULE


def _normalize_periods(periods):
    """把 periods 字段统一成 int 列表；支持 list / JSON 字符串 / None"""
    if periods is None:
        return []
    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            return []
    if not isinstance(periods, list | tuple):
        return []
    out = []
    for p in periods:
        try:
            out.append(int(p))
        except (TypeError, ValueError):
            continue
    return out


def apply_timetable_times(course: dict) -> dict:
    """
    用课表规定的时间覆盖课程的 start_time / end_time（去除任何“减10分钟”之类的调整）。

    - 依据课程自身的 periods 列表 + 楼栋，从 FIRST/SECOND_SCHEDULE 取权威时间。
    - 同时修正 _timeInfo 的时间戳（基于 extra_info.full_date），使提醒触发时间也准确。
    - 缺少 periods / building 信息时原样返回，不破坏既有数据。
    """
    if not isinstance(course, dict):
        return course

    periods = _normalize_periods(course.get("periods"))
    if not periods:
        pidx = course.get("period_idx")
        if pidx:
            periods = [int(pidx)]
    if not periods:
        return course

    building = (course.get("extra_info") or {}).get("building", "") or ""
    sch = get_schedule_by_building(building)
    nums = [n for n in periods if n in sch]
    if not nums:
        return course

    lo, hi = min(nums), max(nums)
    start_time = sch[lo][0]
    end_time = sch[hi][1]

    course = dict(course)
    course["start_time"] = start_time
    course["end_time"] = end_time

    # 同步修正 period_name 为中文“第X、Y节”形式（更准确反映实际节次）
    if lo in _CN_NUM and hi in _CN_NUM:
        if lo == hi:
            course["period_name"] = f"第{_CN_NUM[lo]}节"
        else:
            course["period_name"] = f"第{_CN_NUM[lo]}、{_CN_NUM[hi]}节"

    ti = course.get("_timeInfo")
    full_date = (course.get("extra_info") or {}).get("full_date")
    if ti and full_date:
        try:
            y, m, d = map(int, str(full_date).split("-"))
            sh, sm = map(int, start_time.split(":"))
            eh, em = map(int, end_time.split(":"))
            course["_timeInfo"] = {
                "start_ts": datetime(y, m, d, sh, sm).timestamp(),
                "end_ts": datetime(y, m, d, eh, em).timestamp(),
                **{k: v for k, v in ti.items() if k not in ("start_ts", "end_ts")},
            }
        except Exception:
            pass
    return course


def split_course_to_big_classes(course: dict) -> list:
    """
    将跨多组大课的课程（如 1-4节）按“每2节=1门大课”拆成多条。

    返回 list[dict]，每条为一组大课（periods 为相邻2节），时间已按课表规定填充。
    """
    periods = _normalize_periods(course.get("periods"))
    if not periods:
        pidx = course.get("period_idx")
        if pidx:
            periods = [int(pidx)]
    if not periods:
        return [apply_timetable_times(course)]

    periods = sorted(set(periods))
    chunks = [periods[i : i + 2] for i in range(0, len(periods), 2)]
    if len(chunks) <= 1:
        return [apply_timetable_times(course)]

    results = []
    for _idx, chunk in enumerate(chunks):
        c = dict(course)
        c["period_idx"] = chunk[0]
        c["periods"] = chunk
        c = apply_timetable_times(c)
        orig_id = str(course.get("schedule_id") or course.get("id") or "")
        c["schedule_id"] = f"{orig_id}#p{chunk[0]}-{chunk[-1]}"
        results.append(c)
    return results


def parse_weeks(weeks_str: str) -> set:
    """
    解析上课周次字符串，返回周次集合

    支持格式：
      - 单个数字: "14" -> {14}
      - 范围: "1-16" -> {1,2,3,...,16}
      - 逗号分隔: "1,3,5" -> {1,3,5}
      - 混合: "1-4,8,12-16" -> {1,2,3,4,8,12,13,14,15,16}
      - 空字符串: "" -> set() (表示所有周都有课)

    Args:
        weeks_str: 上课周次字符串

    Returns:
        set: 周次集合
    """
    if not weeks_str or not weeks_str.strip():
        return set()  # 空表示所有周

    result = set()
    parts = weeks_str.replace("，", ",").split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            # 范围: "1-16"
            try:
                start, end = part.split("-")
                start_num = int(start.strip())
                end_num = int(end.strip())
                result.update(range(start_num, end_num + 1))
            except (ValueError, IndexError):
                pass
        else:
            # 单个数字: "14"
            try:
                result.add(int(part))
            except ValueError:
                pass

    return result


def is_course_in_week(course_weeks, target_week: int) -> bool:
    """
    判断课程在指定周次是否有课

    支持两种格式：
      - JSON列表格式: [1, 2, 3, 14, 15, 16]
      - 旧字符串格式: "1-16" 或 "1,3,5"

    Args:
        course_weeks: 课程的上课周次（字符串或列表）
        target_week: 目标周次

    Returns:
        bool: 是否有课
    """
    # 非教学周 / 周次未确定（0 或 None）：不显示任何课程，
    # 避免假期或未知周次下把全部课程（含空 weeks 默认 True）都匹配出来。
    if not isinstance(target_week, int) or target_week <= 0:
        return False

    if not course_weeks:
        return True  # 没有填写周次，默认所有周都有课

    # 如果是列表（JSON格式）
    if isinstance(course_weeks, list):
        if not course_weeks:
            return True  # 空列表表示所有周
        return target_week in course_weeks

    # 如果是字符串（旧格式 或 JSON 数组字符串）
    if isinstance(course_weeks, str):
        s = course_weeks.strip()
        if not s:
            return True  # 空字符串表示所有周

        # 去除可能被二次转义的外层引号（数据库 TEXT 列存储 list 时常见，
        # 例如存成 "[18]" 或 '"[18]"'，首字符是引号而非 [）
        if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
            s = s[1:-1].strip()

        # 优先尝试 JSON 数组格式，如 "[19]" 或 "[2, 3, 4, ..., 18]"
        # （数据库以字符串存储 list 时会出现这种形式，parse_weeks 无法识别）
        if s.startswith("["):
            try:
                import json as _json

                parsed = _json.loads(s)
                # 防御二次编码：json.loads 后仍可能是字符串
                if isinstance(parsed, str):
                    parsed = _json.loads(parsed)
                if isinstance(parsed, list):
                    if not parsed:
                        return True  # 空列表表示所有周
                    return target_week in parsed
            except (ValueError, TypeError):
                pass

        weeks = parse_weeks(s)
        if not weeks:
            return True  # 解析为空，默认所有周都有课

        return target_week in weeks

    return True


def get_current_week_number() -> int:
    """当前周次（int 语义兼容历史调用方）。

    委托 teaching_week_service.get_current_teaching_week() 唯一真相源：
    教学周内返回真实周次；非教学周/假期/异常返回 0（调用方据此跳过展示与推送）。

    注意：本函数已不再是纯函数（见文件头约定变更），它通过 service 层查询
    course_weeks 表与假期配置，是「周次口径统一」后的唯一出口，不再依赖
    任何硬编码学期日历。
    """
    from app.services.teaching_week_service import get_current_teaching_week

    wk = get_current_teaching_week()
    return wk if wk else 0


def get_current_period_and_status(building: str = "") -> dict:
    """
    获取当前节次和上课状态

    注意：
    - is_ongoing 仅表示当前时间落在某个节次的时间范围内
    - 是否真的"正在上课"需要结合课表数据判断（is_current_course）

    Args:
        building: 楼栋名称，用于选择对应的时间表

    Returns:
        dict: {
            'current_period': int,  # 当前节次（1-12），0表示还没开始，13表示已结束
            'is_ongoing': bool,     # 当前时间是否在某个节次的时间范围内
            'is_class_time': bool,  # 当前是否是上课时间段
            'current_week_day': int, # 今天星期几（1-7）
        }
    """
    from datetime import datetime

    now = datetime.now()
    current_time = now.hour * 60 + now.minute

    current_week_day = now.isoweekday()  # 1=周一, 7=周日

    # 根据楼栋选择时间表
    schedule = get_schedule_by_building(building)

    # 检查当前在哪一节
    for period in range(1, 13):
        start_str, end_str = schedule.get(period, ("", ""))
        if not start_str or not end_str:
            continue

        # 解析时间
        try:
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m

            # 如果当前时间在该节次范围内
            if start_minutes <= current_time <= end_minutes:
                return {
                    "current_period": period,
                    "is_ongoing": True,
                    "is_class_time": True,
                    "current_week_day": current_week_day,
                }
        except (ValueError, IndexError):
            continue

    # 检查当前时间在哪个节次之间（用于确定应该显示哪个节次）
    for period in range(1, 13):
        start_str, end_str = schedule.get(period, ("", ""))
        if not start_str:
            continue

        try:
            start_h, start_m = map(int, start_str.split(":"))
            start_minutes = start_h * 60 + start_m

            # 如果当前时间在第一节之前
            if period == 1 and current_time < start_minutes:
                return {
                    "current_period": 0,
                    "is_ongoing": False,
                    "is_class_time": False,
                    "current_week_day": current_week_day,
                }

            # 如果当前时间在某个节次之前
            if current_time < start_minutes:
                # 返回上一节作为当前节次（表示处于两节之间或之前）
                return {
                    "current_period": period - 1,
                    "is_ongoing": False,
                    "is_class_time": False,
                    "current_week_day": current_week_day,
                }
        except (ValueError, IndexError):
            continue

    # 所有节次都结束了
    return {
        "current_period": 13,
        "is_ongoing": False,
        "is_class_time": False,
        "current_week_day": current_week_day,
    }
