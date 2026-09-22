#!/usr/bin/env python3
"""
课程数据仓库层

负责课程表的数据库操作，遵循 Repository 模式
"""

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.model.course import Course

# ----------------------------------------------------------------------
# 课程导入时的字段补全/规范化辅助函数
# 课程表爬虫无法稳定获取教务系统内部的学期ID与课程代码，因此这里提供
# 1) 根据当前日期推导当前学期信息
# 2) 在没有真实课程代码时生成稳定的兜底代码
# 3) 将各种格式的周次/节次字符串规范化为列表，确保 JSON 列存储正确
# ----------------------------------------------------------------------


def derive_current_semester() -> dict[str, Any]:
    """
    根据当前日期推导"当前学期"信息。

    中国高校校历（学年第一学期=秋季，第二学期=春季）：
      - 秋季学期（9月~次年1月）属于学年 {Y}-{Y+1}，term=1（第一学期）
      - 春季学期（2月~7月）属于学年 {Y-1}-{Y}，term=2（第二学期）

    semester_id 作为应用内部标识，由「起始年 + 学期」推导为稳定整数，
    例如 2025-2026 秋季 -> 20251，春季（第二学期）-> 20252。

    Returns:
        dict: {semester_id, semester_name, academic_year, term}
    """
    today = date.today()
    y, m = today.year, today.month
    if 9 <= m <= 12:
        # 秋季学期（第一学期），属学年 Y-(Y+1)
        start, term = y, 1
    elif 1 <= m <= 2:
        # 仍属上一学年秋季学期（第一学期）
        start, term = y - 1, 1
    elif m == 8:
        # 8 月为暑假，下一学期为秋季学期（第一学期），属学年 Y-(Y+1)。
        # 此前误把 3~8 月整体算作春季学期，导致 8 月「当前学期」错判为
        # 已结束的春季（开学日 3/2），课表表头显示 3 月日期。
        start, term = y, 1
    else:  # 3 ~ 7 月为春季学期（第二学期）
        start, term = y - 1, 2
    academic_year = f"{start}-{start + 1}"
    return {
        "semester_id": int(f"{start}{term}"),
        "semester_name": f"{academic_year}-{term}",
        "academic_year": academic_year,
        "term": term,
    }


def get_current_semester_id() -> int:
    """当前学期 DB id（单一真相源，与网页端 /course/timetable 口径一致）。

    优先读 cqie-course-timetable 爬虫产出的 course_meta.json 的
    current_semester_name（爬虫成功运行后写入，代表真实在用的学期）；
    缺省/异常/解析失败则回退到按当前日期推导的学期
    （derive_current_semester），避免拿到 None 而显示空白课表。

    注意：小程序 /api/miniapp/schedule/* 与网页端 /course/timetable 必须
    解析到同一个学期，否则两端课表数据对不上（小程序显示错误/假数据）。
    """
    import json as _json
    import os as _os

    meta_path = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "..",
        "cqie-course-timetable",
        "output",
        "course-data",
        "raw",
        "course_meta.json",
    )
    if _os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = _json.load(f)
            name = meta.get("current_semester_name")
            if name:
                parts = str(name).split("-")
                year = int(parts[0])
                term = int(parts[-1])
                return year * 10 + term
        except Exception:
            pass
    # 候选学期：course_meta.json 当前学期 或 按日期推导学期
    candidate = derive_current_semester()["semester_id"]
    # 兜底：若候选学期在库中没有任何课程（典型场景：处于寒暑假空档期，
    # 推导出的新学期尚未爬取），则回退到库里实际存有课表数据的学期，
    # 避免小程序/网页端显示空白或错误（假）数据。
    try:
        from app.core.database import get_db
        from sqlalchemy import text

        session = get_db()
        try:
            rows = session.execute(
                text(
                    "SELECT semester_id, COUNT(*) AS c FROM courses "
                    "WHERE is_deleted=0 GROUP BY semester_id ORDER BY c DESC"
                )
            ).fetchall()
            if rows:
                best_id, best_count = rows[0].semester_id, rows[0].c
                # 仅当候选学期确实无课、且库中存在有课的学期时才替换
                has_candidate = any(r.semester_id == candidate and r.c > 0 for r in rows)
                if not has_candidate and best_count > 0:
                    return int(best_id)
        finally:
            session.close()
    except Exception:
        pass
    return candidate


def semester_info_from_id(semester_id: int) -> dict[str, Any]:
    """
    根据 DB 格式学期 ID（如 20251）推导学期元信息。

    与 derive_current_semester 的区别：后者按「今天」推导当前学期，
    本函数按给定的 semester_id 推导任意学期，用于历史/指定学期入库时
    补全 semester_name / academic_year / term。

    Args:
        semester_id: DB 格式学期 ID，如 20251（2025-2026 学年第 1 学期）

    Returns:
        dict: {semester_id, semester_name, academic_year, term}
    """
    s = str(semester_id)
    term = int(s[-1])
    start = int(s[:-1])
    academic_year = f"{start}-{start + 1}"
    return {
        "semester_id": semester_id,
        "semester_name": f"{academic_year}-{term}",
        "academic_year": academic_year,
        "term": term,
    }


def candidate_semester_pairs(years_back: int = 3, years_forward: int = 0) -> list[tuple[str, int]]:
    """生成候选学期 (eams_id, db_semester_id) 列表，供学期下拉与全量爬取使用。

    不再依赖 course_meta.json 的快照（可能只含当前学期，导致下拉/全量爬取
    选项缺失）。基于当前日期推导的当前学年，向前 years_back 年、向后
    years_forward 年，覆盖每学期（term=1 秋 / term=2 春），按 db_id 降序
    （新→旧）返回。

    eams_id 按 DB id 末三位推算（与 crawl_task_service._resolve_eams_id 的
    兜底规则一致）：20252 -> '252'。教务系统学期下拉通常即为此编号。
    """
    cur = derive_current_semester()["semester_id"]
    start_year = cur // 10
    pairs: list[tuple[str, int]] = []
    for y in range(start_year - years_back, start_year + years_forward + 1):
        for term in (1, 2):
            db_id = y * 10 + term
            pairs.append((str(db_id)[-3:], db_id))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


def generate_course_code(data: dict[str, Any]) -> str:
    """
    在没有真实课程代码时，生成稳定的兜底课程代码。
    同一门课（课程名 + 星期 + 节次列表 + 教室）在不同爬取中应得到相同代码，
    以便去重逻辑稳定工作。

    关键：必须使用 hashlib（稳定哈希）。严禁使用内置 hash()——
    内置 hash() 受 PYTHONHASHSEED 影响，每次进程启动都会变化，
    会导致同一门课的兜底代码每次爬取都不同，去重失效、重复数据累积。

    v6.19.x：移除 week_number 输入，使 course_code 与周次无关（稳定）。
    真正承担“去重键”职责的是 compute_course_key，本函数仅作为展示用代码。

    Args:
        data: 课程数据字典（建议含 course_name / week_day / periods 或 period_idx / classroom）

    Returns:
        str: 形如 "CRAWL-01234" 的代码
    """
    name = data.get("course_name") or "UNKNOWN"
    wd = data.get("week_day", 0)
    # 优先用节次列表（更精准），回退到单个 period_idx
    periods = data.get("periods")
    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            periods = None
    if isinstance(periods, list) and periods:
        per = ",".join(str(p) for p in sorted(int(x) for x in periods if str(x).isdigit()))
    else:
        per = str(data.get("period_idx", 0))
    room = data.get("classroom") or ""
    raw = f"{name}|{wd}|{per}|{room}"
    h = int(hashlib.md5(raw.encode("utf-8")).hexdigest(), 16) % 100000
    return f"CRAWL-{h:05d}"


def compute_course_key(data: dict[str, Any]) -> str:
    """
    计算与周次无关的「稳定课程身份」哈希（v6.19.x 新增，根治重复行）。

    作为 (semester_id, course_key) 去重/对账键的一部分。同一门课不论在哪一周
    爬取、不论 weeks 取值如何，都得到同一个 key —— 这是根除去重键含 week_number
    导致“每次爬取新增重复行”的根本手段。

    输入（均不含 week_number / weeks）：
        - course_name  课程名
        - week_day     星期（1-7）
        - periods      节次列表（排序后，如 [5,6,7,8]）
        - classroom    教室
        - teacher      教师

    注：不引入真实 course_code 作前缀，因为爬虫兜底码 CRAWL-xxxxx 历史上由
    generate_course_code(含 week_number) 生成，前缀反而会把周次 instability 带进来。
    纯规范字段哈希保证跨爬取绝对稳定。

    Returns:
        str: 32 位 md5 十六进制串
    """
    name = (data.get("course_name") or "UNKNOWN").strip()
    wd = data.get("week_day", 0)
    periods = data.get("periods")
    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            periods = None
    if isinstance(periods, list) and periods:
        per = ",".join(str(p) for p in sorted(int(x) for x in periods if str(x).isdigit()))
    else:
        per = str(data.get("period_idx", 0))
    room = (data.get("classroom") or "").strip()
    teacher = (data.get("teacher") or "").strip()
    raw = f"{name}|{wd}|{per}|{room}|{teacher}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _find_existing_course(
    session: Session,
    sid: int,
    key: str,
    data: dict[str, Any],
    week_day: int,
    periods: list,
    classroom: str | None,
    teacher: str | None,
):
    """
    在 (semester_id, course_key) 维度查找未删除的既有课程行（v6.19.x 新增）。

    主匹配：直接用稳定 course_key。
    迁移兜底：老行 course_key 为 NULL（迁移期未跑回填脚本），按规范身份
    (课程名/星期/教室/教师 + 节次一致) 兜底匹配，命中后顺手补齐 course_key，
    防止漏跑回填脚本时又产生重复行。
    """
    existing = (
        session.query(Course)
        .filter(
            Course.semester_id == sid,
            Course.course_key == key,
            Course.is_deleted.is_(False),
        )
        .first()
    )
    if existing:
        return existing
    cand = (
        session.query(Course)
        .filter(
            Course.semester_id == sid,
            Course.course_key.is_(None),
            Course.is_deleted.is_(False),
            Course.course_name == (data.get("course_name") or ""),
            Course.week_day == week_day,
            Course.classroom == (classroom or ""),
            Course.teacher == (teacher or ""),
        )
        .all()
    )
    for c in cand:
        if normalize_periods(c.periods) == periods:
            c.course_key = key
            return c
    return None


def normalize_weeks(weeks) -> list[int]:
    """
    将各种格式的周次描述规范化为升序去重的周次整数列表。

    支持：
      - list: [2, 3, 4] / [ "[2,3]" ]（嵌套字符串也会解析）
      - int: 14 -> [14]
      - str: "2-5 7 9 11-18" / "1,3,5" / "[1,2]" / ""（空 -> []）
      - 单双周标记：含"单"/"双"的区间会按奇偶筛选

    Args:
        weeks: 周次原始值

    Returns:
        List[int]: 周次数字列表（可能为空）
    """
    if weeks is None:
        return []
    if isinstance(weeks, bool):
        return []
    if isinstance(weeks, int):
        return [weeks]
    if isinstance(weeks, list):
        out = []
        for x in weeks:
            if isinstance(x, int):
                out.append(x)
            elif isinstance(x, str):
                out.extend(normalize_weeks(x))
            else:
                try:
                    out.append(int(x))
                except (ValueError, TypeError):
                    pass
        return sorted(set(out))
    if isinstance(weeks, str):
        s = weeks.strip()
        if not s:
            return []
        # 先尝试 JSON 数组
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return normalize_weeks(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
        # 再按 空格/逗号 切分，逐段解析范围
        out = set()
        for part in re.split(r"[\s,，]+", s):
            part = part.strip()
            if not part:
                continue
            is_odd = "单" in part
            is_even = "双" in part
            clean = part.replace("单", "").replace("双", "").replace("周", "")
            if "-" in clean:
                try:
                    a, b = clean.split("-")
                    a, b = int(a.strip()), int(b.strip())
                    for w in range(a, b + 1):
                        if is_odd and w % 2 == 0:
                            continue
                        if is_even and w % 2 == 1:
                            continue
                        out.add(w)
                except (ValueError, IndexError):
                    pass
            else:
                try:
                    out.add(int(clean))
                except ValueError:
                    pass
        return sorted(out)
    return []


def normalize_periods(periods) -> list[int]:
    """将节次字段规范化为整数列表（与 normalize_weeks 同理，但无单双周）。"""
    return normalize_weeks(periods)


def weeks_to_bitmap(weeks: list[int], total: int = 25) -> str | None:
    """
    将周次列表转换为位图字符串（长度 total，'1' 表示有课）。

    Args:
        weeks: 周次列表
        total: 位图长度（默认 25 周）

    Returns:
        str | None: 位图字符串或 None（无周次时）
    """
    if not weeks:
        return None
    bits = ["0"] * total
    for w in weeks:
        if 1 <= w <= total:
            bits[w - 1] = "1"
    return "".join(bits)


class CourseRepository:
    """
    课程数据仓库

    职责：
    - 封装所有课程相关的数据库操作
    - 提供查询、创建、更新、删除方法
    - 不包含业务逻辑
    """

    @staticmethod
    def get_all(
        session: Session, week_number: int | None = None, semester_id: int | None = None
    ) -> list[Course]:
        """
        获取所有未删除的课程

        Args:
            session: 数据库会话
            week_number: 可选，按周次筛选
            semester_id: 可选，按学期筛选（默认 None = 不过滤，兼容旧调用方）

        Returns:
            List[Course]: 课程列表
        """
        query = session.query(Course).filter(Course.is_deleted.is_(False))
        if week_number is not None:
            query = query.filter(Course.week_number == week_number)
        if semester_id is not None:
            query = query.filter(Course.semester_id == semester_id)
        return query.order_by(Course.week_day, Course.period_idx).all()

    @staticmethod
    def get_by_id(session: Session, course_id: int) -> Course | None:
        """
        根据ID获取课程

        Args:
            session: 数据库会话
            course_id: 课程ID

        Returns:
            Optional[Course]: 课程对象或None
        """
        return session.query(Course).filter(Course.id == course_id).first()

    @staticmethod
    def get_by_week_day(
        session: Session, week_day: int, week_number: int | None = None
    ) -> list[Course]:
        """
        获取指定星期的课程

        Args:
            session: 数据库会话
            week_day: 星期几 (1-7)
            week_number: 可选，周次

        Returns:
            List[Course]: 课程列表
        """
        query = session.query(Course).filter(Course.week_day == week_day)
        if week_number is not None:
            query = query.filter(Course.week_number == week_number)
        return query.order_by(Course.period_idx).all()

    @staticmethod
    def get_today_courses(session: Session, week_number: int | None = None) -> list[Course]:
        """
        获取今天的课程

        Args:
            session: 数据库会话
            week_number: 可选，周次

        Returns:
            List[Course]: 今日课程列表
        """
        # 获取今天是星期几 (0=周一, 6=周日)
        today_week_day = date.today().weekday() + 1  # 转换为 1-7

        return CourseRepository.get_by_week_day(session, today_week_day, week_number)

    @staticmethod
    def create(
        session: Session,
        course_name: str,
        week_day: int,
        period_idx: int,
        teacher: str | None = None,
        classroom: str | None = None,
        building: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        weeks: str | None = None,
        week_number: int | None = None,
    ) -> Course:
        """
        创建课程

        Args:
            session: 数据库会话
            course_name: 课程名称
            week_day: 星期几 (1-7)
            period_idx: 节次索引 (1-12)
            teacher: 教师姓名
            classroom: 教室
            building: 教学楼
            start_time: 开始时间
            end_time: 结束时间
            weeks: 上课周次
            week_number: 当前周次

        Returns:
            Course: 创建的课程对象
        """
        sem = derive_current_semester()
        course = Course(
            course_code=generate_course_code(
                {
                    "course_name": course_name,
                    "week_day": week_day,
                    "period_idx": period_idx,
                    "classroom": classroom or "",
                }
            ),
            course_name=course_name,
            semester_id=sem["semester_id"],
            semester_name=sem["semester_name"],
            academic_year=sem["academic_year"],
            term=sem["term"],
            week_day=week_day,
            period_idx=period_idx,
            teacher=teacher,
            classroom=classroom,
            building=building,
            start_time=start_time or "",
            end_time=end_time or "",
            weeks=normalize_weeks(weeks),
            weeks_bitmap=weeks_to_bitmap(normalize_weeks(weeks)),
            week_number=week_number,
        )
        session.add(course)
        session.flush()
        return course

    @staticmethod
    def create_batch(
        session: Session,
        courses_data: list[dict[str, Any]],
        data_source: str = "full",
        reconcile: bool = False,
        logger: Any = None,
    ) -> tuple[int, int]:
        """
        批量创建课程（按 (semester_id, course_key) 稳定身份去重，智能合并）

        v6.19.x 去重策略改写（根治重复行）：
        去重键 = (semester_id, course_key)，其中
        course_key = md5(课程名|星期|排序节次|教室|教师)，**与周次无关**。
        旧策略 course_code + week_day + period_idx + week_number 因 week_number(=爬取周)
        随每次爬取漂移，导致每爬一周都新增重复行——已废弃。

        - 已存在 → 更新有变化的字段，刷新来源/校验时间
        - 不存在 → 创建新记录，补全所有 NOT NULL 字段

        手动课保护：爬虫来源（full/daily）下，course_key 命中 data_source='admin'
        行则整条跳过，不覆盖、不插入第二条挤占人工课。

        对账软删（reconcile=True 且 full 来源）：全量重爬后，本学期内
        data_source='full' 且本次未被命中的行视为已消失课程，软删
        （deleted_reason='stale_reconcile'）。reimport_with_teacher / 后台 admin 路由
        不传 reconcile，避免按"部分批次"误删整学期其他课程。

        Args:
            session: 数据库会话
            courses_data: 课程数据列表
            data_source: 数据来源标记（'full'=全量/指定学期爬虫, 'daily'=每日爬虫, 'admin'=手动）
            reconcile: 是否启用对账软删（仅全量爬虫应置 True）
            logger: 可选日志器，用于输出对账软删条数

        Returns:
            Tuple[int, int]: (实际新建数量, 已更新数量)
                注意：不要把返回值当作"库内课程总数"，重爬时新建可能为 0 而更新 > 0。
        """
        created_count = 0
        updated_count = 0
        sem = derive_current_semester()

        # 批次起始时间：对账软删(stale_reconcile)以"本次批次之前未被命中的 full 行"为脏数据。
        _batch_start = datetime.utcnow()
        _touched_ids: set = set()
        _affected_semesters: set = set()

        # v6.19.x：手动课保护改为基于稳定 course_key，而非 (week_day, period_idx, week_number)
        # 槽位。week_number 是爬取周、随每次爬取漂移，用其做槽位判据会使保护失效；
        # 改为预载受影响学期内 data_source='admin' 行的 course_key 集合，爬虫行 key 命中即跳过。
        _crawler_source = data_source in ("full", "daily")
        _admin_keys = set()
        if _crawler_source:
            _sems = {
                (d.get("semester_id") or sem["semester_id"])
                for d in courses_data
            }
            if _sems:
                _admins = (
                    session.query(Course)
                    .filter(
                        Course.data_source == "admin",
                        Course.is_deleted.is_(False),
                        Course.semester_id.in_(_sems),
                    )
                    .all()
                )
                for _a in _admins:
                    _admin_keys.add(
                        compute_course_key(
                            {
                                "course_name": _a.course_name,
                                "week_day": _a.week_day,
                                "periods": normalize_periods(_a.periods),
                                "classroom": _a.classroom,
                                "teacher": _a.teacher,
                            }
                        )
                    )

        for data in courses_data:
            # 规范化学期、周次、节次
            weeks = normalize_weeks(data.get("weeks"))
            weeks_bitmap = weeks_to_bitmap(weeks)
            periods = normalize_periods(data.get("periods", ""))
            # 规范化 period_idx 为首节（periods[0]），避免源数据 period_idx 不一致
            # （如 [1,2] 课被标成 pidx=2）导致去重键错位、重复数据
            period_idx = periods[0] if periods else data.get("period_idx", 1)
            # 传入 periods 让兜底码基于节次列表生成，更精准且稳定
            course_code = data.get("course_code") or generate_course_code(
                {
                    "course_name": data.get("course_name"),
                    "week_day": data.get("week_day"),
                    "periods": periods,
                    "classroom": data.get("classroom"),
                }
            )
            # v6.19.x：稳定课程身份 key（与周次无关），作为去重/对账主键
            sid = data.get("semester_id") or sem["semester_id"]
            course_key = compute_course_key(
                {
                    "course_name": data.get("course_name"),
                    "week_day": data.get("week_day"),
                    "periods": periods,
                    "classroom": data.get("classroom"),
                    "teacher": data.get("teacher"),
                }
            )

            # v6.19.x：手动课保护——爬虫来源且 key 命中 admin 行则整条跳过，保留人工修正
            if _crawler_source and course_key in _admin_keys:
                continue

            # 按 (semester_id, course_key) 去重（course_key 与周次无关，根治重复行）
            existing = _find_existing_course(
                session, sid, course_key, data, data.get("week_day", 1), periods,
                data.get("classroom"), data.get("teacher"),
            )

            if existing:
                # 计入"已更新"：命中既有记录即刷新来源/校验时间（无论字段是否变化）
                updated_count += 1
                # 已存在：比对更新（只更新有变化的字段）
                if data.get("course_name") and data["course_name"] != existing.course_name:
                    existing.course_name = data["course_name"]
                if data.get("teacher") and data["teacher"] != existing.teacher:
                    existing.teacher = data["teacher"]
                if data.get("classroom") and data["classroom"] != existing.classroom:
                    existing.classroom = data["classroom"]
                if data.get("building") and data["building"] != existing.building:
                    existing.building = data["building"]
                if data.get("start_time") and data["start_time"] != existing.start_time:
                    existing.start_time = data["start_time"]
                if data.get("end_time") and data["end_time"] != existing.end_time:
                    existing.end_time = data["end_time"]
                if data.get("periods") is not None and periods and periods != existing.periods:
                    existing.periods = periods
                if weeks and weeks != existing.weeks:
                    existing.weeks = weeks
                    existing.weeks_bitmap = weeks_bitmap
                # 学期信息以最新爬取为准，保持整批一致
                existing.semester_id = data.get("semester_id") or sem["semester_id"]
                existing.semester_name = data.get("semester_name") or sem["semester_name"]
                existing.academic_year = data.get("academic_year") or sem["academic_year"]
                existing.term = data.get("term") or sem["term"]
                # 补齐/刷新稳定身份 key（迁移期老行可能为 NULL）
                existing.course_key = course_key
                # 记录被本次批次命中的行，用于对账软删（stale_reconcile）
                _touched_ids.add(existing.id)
                _affected_semesters.add(sid)
                # 刷新来源与校验时间（v6.11.1）
                existing.data_source = data_source
                existing.last_verified_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
            else:
                # 不存在：创建新记录（补全所有 NOT NULL 字段）
                course = Course(
                    course_code=course_code,
                    course_key=course_key,
                    course_name=data.get("course_name", ""),
                    semester_id=data.get("semester_id") or sem["semester_id"],
                    semester_name=data.get("semester_name") or sem["semester_name"],
                    academic_year=data.get("academic_year") or sem["academic_year"],
                    term=data.get("term") or sem["term"],
                    week_day=data.get("week_day", 1),
                    period_idx=period_idx,
                    periods=periods,
                    teacher=data.get("teacher", ""),
                    classroom=data.get("classroom", ""),
                    building=data.get("building", ""),
                    start_time=data.get("start_time", ""),
                    end_time=data.get("end_time", ""),
                    weeks=weeks,
                    weeks_bitmap=weeks_bitmap,
                    week_number=data.get("week_number"),
                    course_type=data.get("course_type"),
                    credit=data.get("credit"),
                    # 来源与校验时间（v6.11.1）
                    data_source=data_source,
                    last_verified_at=datetime.utcnow(),
                )
                session.add(course)
                created_count += 1
                _touched_ids.add(course.id)
                _affected_semesters.add(sid)

        # v6.19.x：对账软删（仅 reconcile=True 且 full 来源，由爬虫全量重爬触发）。
        # 全量重爬后，库中属于本批次学期、data_source='full' 且本次未被命中的行，
        # 视为"本学期已消失的课程"软删（deleted_reason='stale_reconcile'），
        # 既清理旧爬取遗留的脏重复行，也保证课表随培养方案更新而收敛。
        # 手动课(admin)与每日课(daily)均不被本逻辑触碰。
        # 注意：reimport_with_teacher / 后台 admin 路由不传 reconcile，避免按"部分批次"
        # 误删整学期其他课程。
        _stale_count = 0
        if reconcile and data_source == "full" and _touched_ids:
            for _sid in _affected_semesters:
                _stale = (
                    session.query(Course)
                    .filter(
                        Course.semester_id == _sid,
                        Course.data_source == "full",
                        Course.is_deleted.is_(False),
                        Course.id.notin_(_touched_ids),
                        (Course.last_verified_at < _batch_start)
                        | (Course.last_verified_at.is_(None)),
                    )
                    .all()
                )
                for _c in _stale:
                    _c.is_deleted = True
                    _c.deleted_at = datetime.utcnow()
                    _c.deleted_reason = "stale_reconcile"
                    _stale_count += 1
            if _stale_count and logger is not None:
                logger.info(
                    f"[课程对账] 软删本学期已消失课程 {_stale_count} 条 (stale_reconcile)"
                )

        session.flush()
        return created_count, updated_count

    @staticmethod
    def update(session: Session, course_id: int, **kwargs) -> Course | None:
        """
        更新课程

        Args:
            session: 数据库会话
            course_id: 课程ID
            **kwargs: 要更新的字段

        Returns:
            Optional[Course]: 更新后的课程或None
        """
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return None

        for key, value in kwargs.items():
            if hasattr(course, key) and key not in ("id", "created_at"):
                setattr(course, key, value)

        course.updated_at = datetime.utcnow()
        session.flush()
        return course

    @staticmethod
    def delete(session: Session, course_id: int) -> bool:
        """
        硬删除课程（从数据库中完全删除）

        Args:
            session: 数据库会话
            course_id: 课程ID

        Returns:
            bool: 是否删除成功
        """
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return False

        session.delete(course)
        session.flush()
        return True

    @staticmethod
    def restore(session: Session, course_id: int) -> bool:
        """
        恢复已删除的课程

        Args:
            session: 数据库会话
            course_id: 课程ID

        Returns:
            bool: 是否恢复成功
        """
        course = session.query(Course).filter(Course.id == course_id).first()
        if not course:
            return False

        course.is_deleted = False
        course.deleted_at = None
        course.deleted_reason = None
        session.flush()
        return True

    @staticmethod
    def delete_all(session: Session) -> int:
        """
        删除所有课程

        Args:
            session: 数据库会话

        Returns:
            int: 删除的数量
        """
        count = session.query(Course).count()
        session.query(Course).delete()
        session.flush()
        return count

    @staticmethod
    def count(session: Session, week_number: int | None = None) -> int:
        """
        统计课程数量

        Args:
            session: 数据库会话
            week_number: 可选，按周次筛选

        Returns:
            int: 课程数量
        """
        query = session.query(Course)
        if week_number is not None:
            query = query.filter(Course.week_number == week_number)
        return query.count()
