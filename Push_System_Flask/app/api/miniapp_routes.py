#!/usr/bin/env python3
"""
微信小程序业务路由（/api/miniapp/*）

仅提供学生端只读查询与个人资料接口，与 /api/admin 管理端能力完全隔离。
数据权限基于 JWT 中的 user_id（g.current_user），不接受客户端传入他人 ID（防 IDOR 越权）。

接口清单：
- GET  /api/miniapp/user/me                    当前学生用户信息（v6.16.0）
- GET  /api/miniapp/student/bind-status        身份绑定状态（是否通过预录名单绑定）
- GET  /api/miniapp/student/schools            身份绑定可选学校列表（从组织树动态读取）
- POST /api/miniapp/student/bind               身份绑定（学校+学号+一次性绑定码 命中预录名单）
- GET  /api/miniapp/student/profile            本人学生资料
- PUT  /api/miniapp/student/profile            更新本人学生资料
- GET  /api/miniapp/schedule/today             今日课表（v6.16.0 第二阶段）
- GET  /api/miniapp/schedule/week              指定周课表（默认当前周）
- GET  /api/miniapp/schedule/current           当前教学周信息
- GET  /api/miniapp/weather/current            实时天气
- GET  /api/miniapp/weather/hourly             24 小时预报
- GET  /api/miniapp/weather/alerts             生效中预警
- GET  /api/miniapp/weather/daily              未来 7 天逐天预报
- GET  /api/miniapp/weather/indices            生活指数
- GET  /api/miniapp/weather/air                实时空气质量 AQI
- GET  /api/miniapp/weather/minutely           分钟级降水
- GET  /api/miniapp/electricity/current        剩余电量（按用户隔离）
- GET  /api/miniapp/electricity/refresh        轻量刷新剩余电量（未配置 Cookie 时引导）
- GET  /api/miniapp/electricity/history        用电记录（按用电日聚合，一天一条；该学生无任何记录时自动懒采集一次全量爬取，响应含 fetch_triggered）
- GET  /api/miniapp/electricity/daily/<date>   某个用电日的用电详情（总用量 + 各分表明细 + 对比 + 结算后剩余电量）
- GET  /api/miniapp/electricity/trend          用电趋势
- GET  /api/miniapp/electricity/cookie         电表 Cookie 配置状态（脱敏）
- PUT  /api/miniapp/electricity/cookie         保存本人电表 Cookie
- POST /api/miniapp/electricity/cookie/test    测试 Cookie 有效性
- GET  /api/miniapp/notifications/messages     个人站内通知列表（含未读公告提醒）
- GET  /api/miniapp/notifications/messages/<id> 单条通知详情（列表只放摘要，点进看全文并自动记已读）
- POST /api/miniapp/notifications/messages/read 标记已读（指定或全部，全部联动清公告）
- GET  /api/miniapp/notifications/unread-count 消息未读统计（站内通知+公告，角标用）
- GET  /api/miniapp/notifications/upcoming     近期提醒（学校日历事件）
- GET  /api/miniapp/notifications/all          全部未过期提醒
- GET  /api/miniapp/announcements              校园通知列表（纯拉取，支持 category/department/channel/keyword 筛选）
- GET  /api/miniapp/announcements/channels      频道清单（列表页顶部频道标签）
- GET  /api/miniapp/announcements/unread-count 未读通知数（首页红点）
- GET  /api/miniapp/announcements/<id>         通知详情（自动记已读）
- POST /api/miniapp/announcements/<id>/favorite 收藏/取消收藏
- POST /api/miniapp/announcements/<id>/read     标记已读
- GET  /api/miniapp/announcements/attachment/<id> 下载附件

设计原则：底层一律复用现有 Service（schedule_service / weather_service /
electricity_service）与 Repository，路由层只做鉴权与编排，不复制业务逻辑。
课表说明：Course 表是全校/单账号爬取的唯一课表数据，无学生身份维度（详见
《微信小程序扩展开发指南》§35），小程序端查询的即该份课表，接口按周过滤返回。
"""

from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, g, request

from app.core.api_response import api_error, api_success
from app.core.extensions import RATE_LIMITS, limiter
from app.core.logger import get_logger
from app.utils.student_auth import (
    miniapp_optional,
    student_bound_required,
    student_required,
)

# 使用统一日志系统
logger = get_logger(__name__)

# 小程序业务蓝图，挂载前缀 /api/miniapp
miniapp_bp = Blueprint("miniapp", __name__)


@miniapp_bp.route("/user/me", methods=["GET"])
@student_required
def me():
    """
    获取当前学生用户基本信息

    user_id 取自 JWT（g.current_user），不接受客户端传参，防止越权访问他人信息。
    """
    from app.core.database import get_db
    from app.model.user import User

    user_id = int(g.current_user["user_id"])
    db = get_db()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)
        return api_success(user=user.to_dict())
    finally:
        db.close()


@miniapp_bp.route("/student/bind-status", methods=["GET"])
@student_required
def bind_status():
    """
    身份绑定状态查询

    返回是否已通过预录名单完成身份绑定（student_number 非空即视为已绑定），
    以及已绑定的学校/学号/班级快照。小程序端据此决定是否跳转绑定页。
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    user_id = int(g.current_user["user_id"])
    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            return api_success(bound=False)
        bound = bool(profile.student_number)
        return api_success(
            bound=bound,
            school=profile.school,
            student_number=profile.student_number,
            class_name=profile.class_name,
        )
    finally:
        db.close()


@miniapp_bp.route("/student/schools", methods=["GET"])
@student_required
def student_schools():
    """
    身份绑定可选学校列表（从管理端已建组织树动态读取）
    """
    from app.services.org_unit_service import OrgUnitService

    units = OrgUnitService.list_schools()
    return api_success(schools=[u["name"] for u in units])


@miniapp_bp.route("/student/bind", methods=["POST"])
@student_required
def bind_student():
    """
    身份绑定：校验「学校 + 学号 + 一次性绑定码」命中预录名单（启用中）后写入本人资料

    - 学校/学号/码 命中且名单条目 is_active=1 才绑定成功；
    - 学院/专业/班级 由名单所在组织树继承写入 profile（学生无需填写、不可自填）；
    - 绑定码一次性：绑定成功即核销（防重放/转借/先到先得冒绑）；
    - 已绑定学生不可重复调用本接口（防覆盖为他人学号，ALREADY_BOUND 403）；
      如需解绑/换绑请联系管理员走管理端。
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile
    from app.model.student_roster import StudentRoster
    from app.services.student_roster_service import StudentRosterService

    payload = request.get_json(silent=True) or {}
    school = (payload.get("school") or "").strip()
    student_number = (payload.get("student_number") or "").strip()
    bind_code = (payload.get("bind_code") or "").strip()
    if not school or not student_number or not bind_code:
        return api_error(message="学校、学号、绑定码均不能为空", http_status=400)

    user_id = int(g.current_user["user_id"])

    # 防重复绑定：已绑定身份的学生不可再次调用本接口（防止覆盖为他人学号）
    db = get_db()
    try:
        existing = (
            db.query(StudentProfile)
            .filter_by(user_id=user_id)
            .first()
        )
        if existing and existing.student_number:
            logger.warning(
                f"身份已绑定拒绝重复bind: user_id={user_id}, "
                f"current_school={existing.school}, "
                f"current_student_number={existing.student_number}"
            )
            return api_error(
                message="已绑定身份，不可重复绑定。如需换绑请联系管理员",
                http_status=403,
                code="ALREADY_BOUND",
            )
    finally:
        db.close()

    ok, _matched = StudentRosterService.verify(school, student_number, bind_code)
    if not ok:
        logger.warning(
            f"身份绑定校验未通过: user_id={g.current_user.get('user_id')}, "
            f"school={school}, student_number={student_number}"
        )
        return api_error(
            message="身份校验未通过：请确认学校/学号与绑定码无误，或联系管理员", http_status=403
        )

    db = get_db()
    try:
        # 重新在同一事务取名单行（verify 的会话已关闭，避免跨 session 操作 detached 对象）
        roster = (
            db.query(StudentRoster)
            .filter(
                StudentRoster.school == school,
                StudentRoster.student_number == student_number,
                StudentRoster.is_active.is_(True),
            )
            .first()
        )
        if not roster:
            return api_error(message="名单不存在或已停用", http_status=403)
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = StudentProfile(user_id=user_id)
            db.add(profile)
        # 身份字段全部以名单（组织树冗余列）为准写入，学生不可自填/篡改
        profile.school = roster.school
        profile.student_number = roster.student_number
        profile.class_name = roster.class_name
        profile.college = roster.college
        profile.major = roster.major
        profile.dorm = roster.dorm
        # 核销一次性绑定码（同一事务，绑定成功即作废）
        roster.bind_code_hash = None
        db.commit()
        db.refresh(profile)
        logger.info(
            f"身份绑定成功: user_id={user_id}, school={school}, "
            f"student_number={student_number}, class_name={roster.class_name}"
        )
        return api_success(bound=True, profile=profile.to_dict(), message="绑定成功")
    except Exception as exc:
        db.rollback()
        logger.error(f"身份绑定落库失败: user_id={user_id}: {exc}")
        return api_error(message="绑定失败，请稍后重试", http_status=500)
    finally:
        db.close()


@miniapp_bp.route("/student/profile", methods=["GET"])
@student_bound_required
def get_profile():
    """
    获取当前学生资料（student_profiles 表，按 JWT user_id 查询本人资料）
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    user_id = int(g.current_user["user_id"])
    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            return api_error(message="学生资料不存在", http_status=404)
        return api_success(profile=profile.to_dict())
    finally:
        db.close()


@miniapp_bp.route("/student/profile", methods=["PUT"])
@student_bound_required
def update_profile():
    """
    更新当前学生资料（只允许更新本人资料，user_id 取自 JWT 而非客户端）

    请求体（全部可选，只更新传入字段）：
        {
            "campus_card_number": "校园卡号（一卡通号）",
            "nickname": "昵称",
            "phone": "手机号"
        }

    注意（名单派生的身份字段一律不可自改，防止绕过权威来源冒用身份）：
    - school / student_number / class_name：由「身份绑定」接口（POST /student/bind）写入；
    - college / major / grade / real_name：绑定或名单同步时以**预录名单**为准写入
      （student_roster_service 按名单回填）。此前它们在本白名单内，学生可直接调 API
      改成任意学院/年级/姓名，与「身份以名单为准」冲突 → 2026-10-01 移出。
      小程序端「编辑信息」页本身只允许改昵称，学院/专业等为只读展示，故移出不影响前端。
    传了这些字段不会报错，但会被忽略（与其它未在白名单内的字段一致）。
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}

    allowed_fields = {
        "campus_card_number",
        "nickname",
        "phone",
    }
    updates = {}
    for k, v in data.items():
        if k not in allowed_fields or not (v is None or isinstance(v, (str, int))):
            continue
        # 显式传 null 或空串均视为清空该字段（存 NULL）
        updates[k] = None if v is None else (str(v).strip() or None)
    if not updates:
        return api_error(message="没有可更新的字段", http_status=400)

    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            # 首次完善资料：自动补建骨架（正常登录流程已建，此处兜底）
            profile = StudentProfile(user_id=user_id)
            db.add(profile)
        for key, value in updates.items():
            setattr(profile, key, value)
        db.commit()
        db.refresh(profile)
        logger.info(f"学生资料已更新: user_id={user_id}, fields={list(updates.keys())}")
        return api_success(profile=profile.to_dict())
    finally:
        db.close()


@miniapp_bp.route("/user/avatar", methods=["PUT"])
@student_bound_required
def update_avatar():
    """
    更新当前学生用户头像（data URI 形式，复用管理端头像校验，无修改次数配额）

    请求体：
        {"avatar": "data:image/jpeg;base64,..."}

    防护：validate_avatar_data_uri 校验 MIME 白名单（显式拒绝 SVG）、
    文件头 Magic Bytes 防伪造、解码后体积上限 2MB。
    """
    from app.core.database import get_db
    from app.model.user import User
    from app.utils.file_upload_security import FileUploadError, validate_avatar_data_uri

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}
    avatar_raw = data.get("avatar")
    try:
        validated = validate_avatar_data_uri(avatar_raw)
    except FileUploadError as e:
        return api_error(message=str(e), http_status=400)

    db = get_db()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return api_error(message="用户不存在", http_status=404)
        user.avatar = validated
        db.commit()
        db.refresh(user)
        logger.info(f"学生头像已更新: user_id={user_id}")
        return api_success(user=user.to_dict())
    finally:
        db.close()


# ==================== 课表（复用 schedule_service，路由薄封装） ====================


@miniapp_bp.route("/schedule/today", methods=["GET"])
@student_bound_required
def schedule_today():
    """
    指定日期课表（默认今天）

    复用 schedule_service.get_today_schedules()（内存缓存，60 秒自动从 DB 刷新）。
    返回课程字段：course_name/start_time/end_time/periods/period_idx/day_of_week/
    extra_info{teacher,building,classroom,weeks,full_date}/_timeInfo{start_ts,end_ts,is_today}。

    查询参数：
        date (str, 可选): 目标日期 YYYY-MM-DD，缺省今天
    """
    from app.services.schedule_service import schedule_service

    target_date = request.args.get("date") or None
    courses = schedule_service.get_today_schedules(target_date=target_date)
    return api_success(data={"courses": courses})


@miniapp_bp.route("/schedule/week", methods=["GET"])
@student_bound_required
def schedule_week():
    """
    指定周课表（可指定学期，默认当前教学周）

    查询参数：
        week_number (int, 可选): 目标周次，缺省取当前教学周（非教学周回退第 1 周）
        semester_id (int, 可选): 目标学期 DB id；缺省取当前学期

    返回：
        courses: 该周有课的课程列表（按 weeks 字段过滤，形状为 ScheduleCourse）
        week_number: 实际查询的周次
        available_weeks: 可选周次列表（基于该学期开学日推算）
    """
    from app.services.schedule_service import schedule_service
    from app.services.teaching_week_service import build_available_weeks
    from app.utils.course_helpers import get_current_week_number, is_course_in_week
    from app.repository.course_repository import get_current_semester_id

    semester_id = request.args.get("semester_id", type=int)
    if semester_id is None:
        semester_id = get_current_semester_id()

    week_number = request.args.get("week_number", type=int)
    if week_number is None:
        if semester_id == get_current_semester_id():
            week_number = get_current_week_number() or 1
        else:
            # 历史学期：定位第一个有课的周，找不到回退第 1 周
            from app.core.database import get_db
            from app.model.course import Course
            from app.utils.course_helpers import is_course_in_week as _icw

            _db = get_db()
            try:
                _all = (
                    _db.query(Course)
                    .filter(Course.is_deleted.is_(False), Course.semester_id == semester_id)
                    .all()
                )
                week_number = next(
                    (w for w in range(1, 26) if any(_icw(c.weeks or "", w) for c in _all)),
                    1,
                )
            finally:
                _db.close()
    if week_number <= 0:
        return api_error(message="周次无效", http_status=400)

    # 可选周次：与网页端 /course/timetable 口径一致（基于所选学期开学日推算）
    try:
        available_weeks = build_available_weeks(semester_id)
    except Exception as e:
        logger.warning(f"获取可选周次失败（接口降级返回空列表）: {e}")
        available_weeks = []

    all_courses = schedule_service.get_schedules_for_semester(semester_id)
    courses = [
        c for c in all_courses if is_course_in_week(c["extra_info"]["weeks"], week_number)
    ]

    # ===== 端到端诊断日志（临时，定位"切周无数据"）=====
    logger.warning(
        f"[DIAG-week] sem={semester_id} week={week_number} "
        f"raw_count={len(all_courses)} filtered={len(courses)}"
    )
    for _c in all_courses:
        logger.warning(
            f"[DIAG-week]   id={_c.get('id')} name={_c.get('course_name')} "
            f"weeks={_c['extra_info'].get('weeks')!r} "
            f"week_number_field={_c.get('week_number')} source={_c.get('data_source')} "
            f"in_week={is_course_in_week(_c['extra_info'].get('weeks'), week_number)}"
        )
    # ===================================================

    return api_success(
        data={
            "courses": courses,
            "week_number": week_number,
            "available_weeks": available_weeks,
            "semester_id": semester_id,
        }
    )


@miniapp_bp.route("/schedule/current", methods=["GET"])
@student_bound_required
def schedule_current():
    """
    当前教学周信息 + 学期周次面板数据 + 可选学期列表

    返回：
        week_number: 当前周次（0 表示非教学周/假期）
        is_teaching_week: 是否处于教学周
        date: 今天日期（YYYY-MM-DD）
        week_day: 今天星期几（1=周一，7=周日）
        semester_id: 当前学期 ID（如 20261）
        semester_name: 当前学期名称（如 "2026-2027 秋季"）
        available_weeks: 可选周次列表 [{week_number, start_date, end_date, is_teaching}]
        semesters: 可选学期列表（与网页端 /course/semesters 同口径，基于当前学年
                   向前候选生成，供周次选择器左列"学年"滚轮使用）：
                   [{id, name, academic_year, term, is_current}, ...]
    """
    from datetime import date

    from app.utils.course_helpers import get_current_week_number
    from app.repository.course_repository import (
        get_current_semester_id,
        semester_info_from_id,
        candidate_semester_pairs,
    )
    from app.services.teaching_week_service import build_available_weeks

    week_number = get_current_week_number()
    today = date.today()
    sem_id = get_current_semester_id()
    sem_info = semester_info_from_id(sem_id)

    # 可选学期列表（与网页端一致：当前学年往前 3 学年 × 每学年 2 学期，新→旧）
    semesters = []
    try:
        for _eams_id, _db in candidate_semester_pairs(years_back=3, years_forward=0):
            _si = semester_info_from_id(_db)
            semesters.append(
                {
                    "id": _db,
                    "name": _si["semester_name"],
                    "academic_year": _si["academic_year"],
                    "term": _si["term"],
                    "is_current": _db == sem_id,
                }
            )
    except Exception:
        semesters = []

    try:
        available_weeks = build_available_weeks(sem_id)
    except Exception:
        available_weeks = []
    return api_success(
        data={
            "week_number": week_number,
            "is_teaching_week": week_number > 0,
            "date": today.strftime("%Y-%m-%d"),
            "week_day": today.isoweekday(),
            "semester_id": sem_id,
            "semester_name": sem_info.get("semester_name", ""),
            "available_weeks": available_weeks,
            "semesters": semesters,
        }
    )


# ==================== 天气（复用 weather_service，路由薄封装） ====================


@miniapp_bp.route("/weather/current", methods=["GET"])
def weather_current():
    """
    实时天气（30 分钟 TTL，过期返回旧数据并后台刷新）
    """
    from app.services.weather_service import weather_service

    weather = weather_service.get_now_weather()
    if weather is None:
        return api_success(data={"weather": None}, message="暂无天气数据")
    return api_success(data={"weather": weather})


@miniapp_bp.route("/weather/hourly", methods=["GET"])
def weather_hourly():
    """
    24 小时逐小时预报（60 分钟 TTL，过期返回旧数据并后台刷新）
    """
    from app.services.weather_service import weather_service

    hourly = weather_service.get_hourly_forecast()
    return api_success(data={"hourly": hourly})


@miniapp_bp.route("/weather/alerts", methods=["GET"])
def weather_alerts():
    """
    生效中的天气预警（公开浏览：与 weather/current 一致，无用户身份依赖）
    """
    from app.services.weather_service import weather_service

    alerts = weather_service.get_active_alerts()
    return api_success(data={"warnings": alerts})


@miniapp_bp.route("/weather/daily", methods=["GET"])
def weather_daily():
    """
    未来 7 天逐天预报（缓存 3 小时，未命中按需回源；公开浏览，无用户身份依赖）
    """
    from app.modules.weather.cache import DAILY_TTL
    from app.modules.weather.tasks import _make_cache, _make_fetcher

    cache = _make_cache()
    data = cache.get("daily")
    if data is None:
        data = _make_fetcher().fetch_daily()
        if data:
            cache.set("daily", data, DAILY_TTL)
    return api_success(data={"daily": data or []})


@miniapp_bp.route("/weather/indices", methods=["GET"])
def weather_indices():
    """
    生活指数（缓存 6 小时，未命中按需回源；公开浏览，无用户身份依赖）
    """
    from app.modules.weather.cache import INDICES_TTL
    from app.modules.weather.tasks import _make_cache, _make_fetcher

    cache = _make_cache()
    data = cache.get("indices")
    if data is None:
        data = _make_fetcher().fetch_indices()
        if data:
            cache.set("indices", data, INDICES_TTL)
    return api_success(data={"indices": data or []})


@miniapp_bp.route("/weather/air", methods=["GET"])
def weather_air():
    """
    实时空气质量 AQI（缓存 30 分钟，未命中按需回源；公开浏览，无用户身份依赖）
    """
    from app.modules.weather.cache import AIR_TTL
    from app.modules.weather.tasks import _make_cache, _make_fetcher

    cache = _make_cache()
    data = cache.get("air")
    if data is None:
        data = _make_fetcher().fetch_airquality()
        if data:
            cache.set("air", data, AIR_TTL)
    return api_success(data={"air": data})


@miniapp_bp.route("/weather/minutely", methods=["GET"])
def weather_minutely():
    """
    分钟级降水（缓存 30 分钟，未命中按需回源；公开浏览，无用户身份依赖）
    """
    from app.modules.weather.cache import MINUTELY_TTL
    from app.modules.weather.tasks import _make_cache, _make_fetcher

    cache = _make_cache()
    data = cache.get("minutely")
    if data is None:
        data = _make_fetcher().fetch_minutely()
        if data:
            cache.set("minutely", data, MINUTELY_TTL)
    return api_success(data={"minutely": data})


# ==================== 电量（按 JWT 用户隔离，路由薄封装） ====================


def _get_student_cookie(user_id: int) -> str:
    """读取当前学生自配的电表爬虫 Cookie（未配置返回空串）"""
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        return (profile.electricity_cookie or "").strip() if profile else ""
    finally:
        db.close()


@miniapp_bp.route("/electricity/current", methods=["GET"])
@student_bound_required
def electricity_current():
    """
    剩余电量（含百分比/总量/低电量标记，按 JWT 用户隔离，recorded_at 为数据采集时间）
    """
    from app.services.electricity_service import get_electricity_service

    user_id = int(g.current_user["user_id"])
    cookie = _get_student_cookie(user_id)
    svc = get_electricity_service(user_id=user_id, cookie=cookie)
    electricity = svc.get_remaining_power()
    if electricity is None:
        return api_success(
            data={"electricity": None, "cookie_configured": bool(cookie)},
            message="暂无电量数据",
        )
    return api_success(data={"electricity": electricity, "cookie_configured": bool(cookie)})


@miniapp_bp.route("/electricity/refresh", methods=["GET"])
@student_bound_required
def electricity_refresh():
    """
    轻量刷新剩余电量：触发一次实时爬取（1 个请求）并返回最新值。
    后端带 60s 冷却，冷却期内重复调用直接返回缓存，避免被学校接口反爬。
    用于小程序打开电量详情页 / 我的页（展示电量）时主动更新数据。

    未配置电表 Cookie 时不发起爬取，返回 cookie_configured=false 引导去设置。
    """
    from app.services.electricity_service import get_electricity_service

    user_id = int(g.current_user["user_id"])
    cookie = _get_student_cookie(user_id)
    if not cookie:
        return api_success(
            data={"electricity": None, "cookie_configured": False},
            message="未配置电表接入信息，请前往设置中配置",
        )
    svc = get_electricity_service(user_id=user_id, cookie=cookie)
    electricity = svc.refresh_remaining_power()
    if electricity is None:
        return api_success(
            data={"electricity": None, "cookie_configured": True},
            message="暂无电量数据",
        )
    return api_success(data={"electricity": electricity, "cookie_configured": True})


@miniapp_bp.route("/electricity/history", methods=["GET"])
@student_bound_required
def electricity_history():
    """
    用电记录（**按用电日聚合，一天一条**，按 JWT 用户隔离）

    查询参数：
        limit  (int, 可选): 每页**天数**（不是原始记录条数），默认 30，上限 1000
        offset (int, 可选): 跳过天数，默认 0

    返回：
        {
          "days": [
            {"date": "2026-09-17",                  # 用电日
             "total_usage": 2.46,                   # 该日各分表合计
             "settle_time": "2026-09-18 00:09:51"},  # 结算时刻
            ...
          ],
          "total": <有记录的天数>,
          "offset": <本次偏移>,
          "limit": <本次每页天数>,
          "fetch_triggered": <bool, 该学生此前无任何记录且已配置 Cookie 时自动触发首次全量采集>
        }

    为什么改成按天聚合（2026-09-22）：
        一个宿舍通常有【两块分表】（如 "31栋512" 与 "310512"），同一次爬取会写入
        两条 record_time 完全相同的记录。此前直接返回原始明细，列表就成「一天两条」，
        每条只有一半的量，用户看不出当天真实用量。而项目里**其它所有用电展示本就是
        按天合计**（趋势图 get_usage_trend、日报/周报/月报、本月已用 get_monthly_usage），
        只有这一个列表口径不一致 —— 本次统一。

    为什么日期是「用电日」而非 record_time 的日期：
        record_time 是**结算时刻**（用电日次日 00:0x）。此前直接把它当用电日展示，
        比日报的「统计日期」整体错后一天（列表写 09-18，日报写 09-17，其实是同一天的电）。
        此处统一换算为用电日返回，前端不需要再做偏移。

    说明：学生第一次进入电量详情页且其用电记录为空时，后端自动为其触发一次全量爬取
    （异步执行，本次仍返回空列表，前端应提示"正在首次采集，请稍后刷新"）。
    """
    from app.services.electricity_service import get_electricity_service

    user_id = int(g.current_user["user_id"])
    svc = get_electricity_service(user_id=user_id)

    limit = request.args.get("limit", type=int) or 30
    limit = max(1, min(limit, 1000))
    offset = request.args.get("offset", type=int) or 0
    offset = max(0, offset)

    payload = svc.get_daily_records(limit=limit, offset=offset)
    total = payload["total"]

    # 懒采集：该学生从未有过任何用电记录（管理员未手动触发、定时任务尚未覆盖）时，
    # 自动为其触发一次全量爬取补全记录。异步执行不阻塞本次响应，
    # 前端据 fetch_triggered 提示"正在首次采集，请稍后刷新"。
    fetch_triggered = False
    if total == 0:
        from app.modules.electricity.tasks import lazy_fetch_for_user

        fetch_triggered = lazy_fetch_for_user(user_id)

    return api_success(data={**payload, "fetch_triggered": fetch_triggered})


@miniapp_bp.route("/electricity/daily/<date>", methods=["GET"])
@student_bound_required
def electricity_daily_detail(date: str):
    """
    某个用电日的用电详情（结构化，按 JWT 用户隔离）

    路径参数：
        date: 用电日 'YYYY-MM-DD'

    返回：
        {
          "date": "2026-09-17",
          "settle_time": "2026-09-18 00:09:51",
          "total_usage": 2.46,
          "meter_count": 2,
          "meters": [{"meter": "310512", "usage": 1.71, "percent": 69.51}, ...],
          "prev": {"date": "2026-09-16", "total_usage": 2.35} | null,
          "diff_prev": 0.11 | null,
          "avg_recent": 2.66 | null,      # 该日之前有记录的最近 7 天日均
          "avg_recent_days": 7,
          "diff_avg": -0.20 | null,
          "remaining": 101.81 | null,     # 该日结算时点之后最近一次采集的剩余电量
          "remaining_at": "2026-09-18 00:10:00" | null
        }

    口径见 ElectricityService.get_daily_detail 的文档；该日无记录时返回 404。
    """
    from app.services.electricity_service import get_electricity_service

    # 先校验日期格式，避免把非法串带进查询（strptime 会在 service 内抛 ValueError）
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return api_error(message="日期格式应为 YYYY-MM-DD", http_status=400)

    user_id = int(g.current_user["user_id"])
    svc = get_electricity_service(user_id=user_id)
    detail = svc.get_daily_detail(date)
    if detail is None:
        return api_error(message="该日期暂无用电记录", http_status=404)
    return api_success(data=detail)


@miniapp_bp.route("/electricity/trend", methods=["GET"])
@student_bound_required
def electricity_trend():
    """
    用电趋势（按日聚合，仅返回少量点，按 JWT 用户隔离）

    查询参数：
        range (str, 可选): "day"(近7天) | "week"(近7天) | "month"(近30天)，默认 "week"

    返回：
        { "points": [ {"date": "YYYY-MM-DD", "usage": float}, ... ] }  （旧->新，含零值日）
    """
    from app.services.electricity_service import get_electricity_service

    user_id = int(g.current_user["user_id"])
    svc = get_electricity_service(user_id=user_id)

    range_param = (request.args.get("range") or "week").lower()
    days = 30 if range_param == "month" else 7
    points = svc.get_usage_trend(days=days)
    return api_success(data={"points": points})


@miniapp_bp.route("/electricity/monthly", methods=["GET"])
@student_bound_required
def electricity_monthly():
    """
    本月累计用电量（后端按自然月聚合，按 JWT 用户隔离）

    修复说明：此前「本月已用」由前端各自拉取用电记录在本地累加——我的页拉 1000 条、
    详情页只拉首屏 20 条，同一月份在两处显示成 162.93 / 74.04 两个不同数字。
    改为后端统一按 user_id + 自然月 SUM，两个页面共用同一口径。

    返回：
        { "month_used": 本月累计(度), "month_start": "YYYY-MM-DD", "days": 已统计天数 }
    """
    from app.services.electricity_service import get_electricity_service

    user_id = int(g.current_user["user_id"])
    svc = get_electricity_service(user_id=user_id)
    return api_success(data=svc.get_monthly_usage())


@miniapp_bp.route("/electricity/cookie", methods=["GET"])
@student_bound_required
def electricity_cookie_get():
    """
    获取当前学生电表 Cookie 配置状态（脱敏，不返回完整 Cookie）

    返回：
        {
          "configured": bool,          # 是否已配置
          "cookie_preview": "****..."  # 脱敏预览（前4后2，未配置为空串）
        }
    """
    user_id = int(g.current_user["user_id"])
    cookie = _get_student_cookie(user_id)
    preview = ""
    if cookie:
        preview = cookie[:4] + "****" + (cookie[-2:] if len(cookie) > 6 else "")
    return api_success(data={"configured": bool(cookie), "cookie_preview": preview})


@miniapp_bp.route("/electricity/cookie", methods=["PUT"])
@student_bound_required
def electricity_cookie_put():
    """
    保存当前学生电表爬虫 Cookie（仅本人可写，存在 student_profiles.electricity_cookie）

    请求体：
        { "cookie": "..." }
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}
    cookie = str(data.get("cookie") or "").strip()
    if not cookie:
        return api_error(message="接入信息不能为空", http_status=400)
    if len(cookie) > 4096:
        return api_error(message="接入信息过长（上限 4096 字符）", http_status=400)

    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = StudentProfile(user_id=user_id)
            db.add(profile)
        profile.electricity_cookie = cookie
        db.commit()
        logger.info(f"[miniapp] 用户 {user_id} 已更新电表 Cookie")
        return api_success(message="电表接入信息已保存")
    except Exception as exc:
        db.rollback()
        logger.error(f"[miniapp] 保存电表 Cookie 失败 user_id={user_id}: {exc}")
        return api_error(message="保存失败，请稍后重试", http_status=500)
    finally:
        db.close()


@miniapp_bp.route("/electricity/cookie/test", methods=["POST"])
@student_bound_required
def electricity_cookie_test():
    """
    测试电表 Cookie 是否有效（不落库，仅检测）

    请求体：
        { "cookie": "..." }

    返回：
        { "valid": bool, "reason": "..." }
    """
    from app.modules.electricity.crawler import ElectricityCrawler

    data = request.get_json(silent=True) or {}
    cookie = str(data.get("cookie") or "").strip()
    if not cookie:
        return api_error(message="接入信息不能为空", http_status=400)

    crawler = ElectricityCrawler(cookie=cookie)
    is_valid, reason = crawler.check_cookie_valid()
    return api_success(data={"valid": is_valid, "reason": reason})


# ==================== 个人站内通知（user_notifications） ====================


@miniapp_bp.route("/notifications/messages", methods=["GET"])
@student_bound_required
def user_notifications_list():
    """
    个人站内通知列表（电量日报/周报/月报、低电量提醒、Cookie 失效提醒等）
    + 未读公告提醒（announcements 表中用户未读的已发布公告）

    查询参数：
        limit       (int, 可选): 每页条数，默认 20，上限 100
        offset      (int, 可选): 跳过条数，默认 0
        unread_only (int, 可选): 1 时仅返回未读

    返回：
        {
          "notifications": [...],        # 个人站内通知（分页）
          "announcements": [...],        # 未读公告（置顶优先，最多 5 条）
          "unread_count": <站内通知未读数>,
          "announcement_unread": <公告未读数>,
          "total_unread": <两者之和（角标用）>,
          "offset": ...,
          "limit": ...
        }
    """
    from app.services.user_notification_service import user_notification_service
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    limit = request.args.get("limit", type=int) or 20
    limit = max(1, min(limit, 100))
    offset = request.args.get("offset", type=int) or 0
    offset = max(0, offset)
    unread_only = request.args.get("unread_only", type=int) == 1

    notifications = user_notification_service.list_notifications(
        user_id, limit=limit, offset=offset, unread_only=unread_only
    )
    unread_count = user_notification_service.unread_count(user_id)
    # 未读公告提醒：仅当拉取第一页时附带（分页翻页无需重复携带）
    announcements, announcement_unread = [], 0
    if offset == 0:
        announcement_unread = announcement_service.unread_count(user_id)
        if announcement_unread > 0:
            announcements, _ = announcement_service.list_for_user(
                user_id, page=1, page_size=5, only_unread=True
            )
    return api_success(
        data={
            "notifications": notifications,
            "announcements": announcements,
            "unread_count": unread_count,
            "announcement_unread": announcement_unread,
            "total_unread": unread_count + announcement_unread,
            "offset": offset,
            "limit": limit,
        }
    )


@miniapp_bp.route("/notifications/messages/<int:notification_id>", methods=["GET"])
@student_bound_required
def user_notification_detail(notification_id: int):
    """
    个人站内通知详情（供消息详情页展示完整内容）

    消息列表只展示摘要（电量日报等正文较长，全部铺开会让列表很臃肿），
    点进详情页再看完整内容，并在此处标记已读。

    安全：以 JWT 中的 user_id 过滤，客户端无法读取他人消息。

    返回：
        { "notification": {...} }
    """
    from app.services.user_notification_service import user_notification_service

    user_id = int(g.current_user["user_id"])
    detail = user_notification_service.get_notification(user_id, notification_id)
    if not detail:
        return api_error(message="消息不存在", http_status=404)

    # 进入详情即视为已读、已看（两层已读：is_read 清外部气泡，is_viewed 清卡片红点）
    if not detail.get("is_read") or not detail.get("is_viewed"):
        user_notification_service.mark_viewed(user_id, notification_id)
        detail["is_read"] = True
        detail["is_viewed"] = True

    return api_success(data={"notification": detail})


@miniapp_bp.route("/notifications/messages/read", methods=["POST"])
@student_bound_required
def user_notifications_read():
    """
    标记个人站内通知已读

    请求体：
        { "id": int }   标记单条；不传 id 则全部标记已读（联动清空未读公告）

    返回：
        { "affected": <受影响条数>, "unread_count": <剩余站内通知未读数>,
          "announcement_unread": <剩余公告未读数>, "total_unread": <总未读数> }
    """
    from app.services.user_notification_service import user_notification_service
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}
    notification_id = data.get("id")
    if notification_id is not None:
        try:
            notification_id = int(notification_id)
        except (TypeError, ValueError):
            return api_error(message="通知 ID 无效", http_status=400)

    affected = user_notification_service.mark_read(user_id, notification_id)
    # 全部已读时联动清空未读公告（消息页「全部已读」语义 = 清空整个收件箱）
    if notification_id is None:
        announcement_service.mark_all_read(user_id)
    unread_count = user_notification_service.unread_count(user_id)
    announcement_unread = announcement_service.unread_count(user_id)
    return api_success(
        data={
            "affected": affected,
            "unread_count": unread_count,
            "announcement_unread": announcement_unread,
            "total_unread": unread_count + announcement_unread,
        },
        message="已标记已读",
    )


@miniapp_bp.route("/notifications/messages/viewed", methods=["POST"])
@student_bound_required
def user_notifications_viewed():
    """
    标记单条个人站内通知已看过（点进详情/关联业务详情）

    用于「卡片右上角红点」语义：进入列表已把全部标记 is_read（清外部气泡），
    但「已读≠看过」，点进详情才清卡片红点（is_viewed）。
    普通通知的 is_viewed 由详情 GET 自动标记；公告类通知（ref_type=announcement）
    点击后跳转的是公告详情页而非消息详情，故由本接口显式标记。

    请求体：
        { "id": int }   必填，要标记已看的通知 ID

    返回：
        { "affected": <受影响条数> }
    """
    from app.services.user_notification_service import user_notification_service

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}
    notification_id = data.get("id")
    if notification_id is None:
        return api_error(message="缺少通知 ID", http_status=400)
    try:
        notification_id = int(notification_id)
    except (TypeError, ValueError):
        return api_error(message="通知 ID 无效", http_status=400)

    affected = user_notification_service.mark_viewed(user_id, notification_id)
    return api_success(data={"affected": affected}, message="已标记已看")


@miniapp_bp.route("/notifications/unread-count", methods=["GET"])
@student_bound_required
def user_notifications_unread_count():
    """
    消息未读统计（「我的」页消息图标角标用）

    返回：
        {
          "unread": <站内通知未读数>,
          "announcement_unread": <公告未读数>,
          "total": <两者之和>
        }
    """
    from app.services.user_notification_service import user_notification_service
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    unread = user_notification_service.unread_count(user_id)
    announcement_unread = announcement_service.unread_count(user_id)
    return api_success(
        data={
            "unread": unread,
            "announcement_unread": announcement_unread,
            "total": unread + announcement_unread,
        }
    )


# ============================================================================
# 近期提醒（v6.16.0 第三阶段）
# 数据源：notifications 表（学校日历类事件：考试报名/节假日/讲座等）
# ============================================================================


@miniapp_bp.route("/notifications/upcoming", methods=["GET"])
@student_bound_required
def notifications_upcoming():
    """
    即将到来的活跃提醒（首页/时间轴"近期提醒"卡片用）

    查询参数：
        limit (int, 可选): 返回条数上限，默认 5，上限 50

    返回：
        events: 按日期升序的事件列表（每条带 days_left/event_date_label 等派生字段）
        count: 实际返回条数
    """
    from app.core.database import get_db
    from app.model.notification import Notification

    limit = request.args.get("limit", type=int) or 5
    limit = max(1, min(limit, 50))

    db = get_db()
    try:
        events = Notification.get_upcoming(db, limit=limit)
        items = [e.to_dict() for e in events]
        return api_success(data={"events": items, "count": len(items)})
    finally:
        db.close()


@miniapp_bp.route("/notifications/all", methods=["GET"])
@student_bound_required
def notifications_all():
    """
    所有未过期活跃提醒（"更多"列表页用，不限 remind_days 窗口）

    返回：
        events: 按日期升序的全部事件
        count: 总条数
    """
    from app.core.database import get_db
    from app.model.notification import Notification

    db = get_db()
    try:
        events = Notification.get_all_active(db)
        items = [e.to_dict() for e in events]
        return api_success(data={"events": items, "count": len(items)})
    finally:
        db.close()


# ============================================================================
# 校园通知（公告）
# 数据源：announcements 表（有标题/正文/附件的公告通知），与近期提醒是两套业务。
# 送达方式：纯拉取（进页面 / 下拉刷新时请求），不使用微信订阅消息推送。
# ============================================================================


@miniapp_bp.route("/announcements", methods=["GET"])
@miniapp_optional
def announcements_list():
    """校园通知列表（仅已发布、未过期，置顶优先）

    查询参数：
        category (str, 可选): notice/activity/urgent/system，缺省或 all 表示全部
        department (str, 可选): 发布部门精确筛选，缺省或 all 表示全部
        page (int, 可选): 页码，默认 1
        page_size (int, 可选): 每页条数，默认 20，上限 50
        only_unread (str, 可选): "1"/"true" 时仅返回未读

    返回：
        items: 通知列表（含 is_top/is_read/is_favorite/attachment_count/summary；
               display_cover 为卡片展示图，已按「配置封面 → 正文首图」回退）
        total: 满足条件的总条数
    """
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"]) if g.current_user else None
    category = request.args.get("category") or None
    department = request.args.get("department") or None
    channel = request.args.get("channel") or None
    keyword = request.args.get("keyword") or None
    page = request.args.get("page", type=int) or 1
    page_size = request.args.get("page_size", type=int) or 20
    only_unread = (request.args.get("only_unread") or "").lower() in ("1", "true", "yes")
    only_favorite = (request.args.get("only_favorite") or "").lower() in ("1", "true", "yes")

    items, total = announcement_service.list_for_user(
        user_id,
        category=category,
        department=department,
        channel=channel,
        keyword=keyword,
        page=page,
        page_size=page_size,
        only_unread=only_unread,
        only_favorite=only_favorite,
    )
    return api_success(
        data={"items": items, "total": total, "page": page, "page_size": page_size}
    )


@miniapp_bp.route("/announcements/channels", methods=["GET"])
@miniapp_optional
def announcements_channels():
    """频道清单（小程序列表页顶部频道标签数据源）

    只统计当前对学生可见（已发布、未过期、未软删）且填写了频道的公告，
    items 为 [{"key": "学校要闻", "name": "学校要闻", "count": 3}, ...]，按公告数量倒序；
    total 为可见公告总数（含未填频道的），供标签上的条数定位。
    该清单不随筛选变化（始终是全量口径），便于标签上的条数保持稳定。
    """
    from app.services.announcement_service import announcement_service

    return api_success(
        data={
            "items": announcement_service.list_channels(),
            "total": announcement_service.count_visible(),
        }
    )


@miniapp_bp.route("/announcements/unread-count", methods=["GET"])
@miniapp_optional
def announcements_unread_count():
    """未读通知数（首页角标/红点用）；游客返回 0"""
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"]) if g.current_user else None
    return api_success(data={"unread": announcement_service.unread_count(user_id)})


@miniapp_bp.route("/announcements/<int:announcement_id>", methods=["GET"])
@miniapp_optional
def announcement_detail(announcement_id):
    """通知详情（含正文、附件、同分类相关推荐；登录用户首次访问自动记已读并累加阅读数，游客只读不记）"""
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"]) if g.current_user else None
    data = announcement_service.detail_for_user(user_id, announcement_id, mark_read=bool(g.current_user))
    if not data:
        return api_error(message="通知不存在或已撤回", http_status=404)
    return api_success(data={"announcement": data})


@miniapp_bp.route("/announcements/<int:announcement_id>/favorite", methods=["POST"])
@student_bound_required
def announcement_favorite(announcement_id):
    """收藏 / 取消收藏（toggle），返回操作后的收藏状态"""
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    result = announcement_service.toggle_favorite(user_id, announcement_id)
    if result is None:
        return api_error(message="通知不存在或已撤回", http_status=404)
    return api_success(data={"is_favorite": result})


@miniapp_bp.route("/announcements/<int:announcement_id>/read", methods=["POST"])
@student_bound_required
def announcement_mark_read(announcement_id):
    """显式标记已读（详情页底部按钮，正常浏览已自动记已读）"""
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    announcement_service.mark_read(user_id, announcement_id)
    return api_success(data={"is_read": True})


@miniapp_bp.route("/announcements/attachment/<int:attachment_id>", methods=["GET"])
@student_bound_required
def announcement_attachment(attachment_id):
    """下载公告附件（仅限所属公告对学生可见时可下）"""
    import os

    from flask import send_file

    from app.core.config import Config
    from app.services.announcement_service import announcement_service

    att = announcement_service.get_attachment(attachment_id, require_visible=True)
    if not att:
        return api_error(message="附件不存在", http_status=404)

    root = os.path.abspath(os.path.join(Config.OUTPUT_DIR, "announcements"))
    abs_path = os.path.abspath(os.path.join(Config.OUTPUT_DIR, att["file_url"] or ""))
    if not abs_path.startswith(root) or not os.path.exists(abs_path):
        return api_error(message="附件文件已丢失", http_status=404)
    return send_file(abs_path, as_attachment=True, download_name=att["file_name"])


# ==================== 学生自建「第三方消息通知」webhook ====================
# 学生可在小程序设置里自助添加 webhook（企业微信机器人），仅限个人相关模块
# （course / electricity / weather）。服务端强制 scope=student + scope_target=[本人 user_id]，
# 客户端无法指定接收范围或归属，杜绝越权与范围篡改；免审核即生效。

# 学生可配置的个人相关模块白名单
_STUDENT_WEBHOOK_MODULES = {"course", "electricity", "weather"}

# 单个学生可创建的 webhook 数量上限。
# 每条 webhook 都会收到课表/天气的广播副本（app/services/webhook_push_service.py 的
# fanout_broadcast_webhooks 会遍历所有非全局 webhook 逐条发送），不设上限则可被滥建：
# 出站请求数与库行数被无限放大，也会把学生自己/他人的机器人打到微信限流。
_MAX_WEBHOOKS_PER_STUDENT = 10

# 仅允许企业微信机器人域名（学生自建 webhook 的合法目标）。
# 这一条白名单已严格覆盖「IP 字面量指向内网」的情形（IP 字面量不可能等于该域名），
# 故原先附在后面的「IP 字面量查内网段」分支是**不可达死代码**，已于 B 级加固项 B14 删除。
_STUDENT_WEBHOOK_HOST = "qyapi.weixin.qq.com"


def _validate_webhook_url(url: str):
    """校验学生自建 webhook 的 URL：https + 仅企业微信机器人域名。

    返回 (ok, error_message)；ok 为 False 时 error_message 直接作为接口报错文案。
    仅作用于学生自建路由，不影响管理端系统级 webhook（管理端目标可多元化，
    通用出站校验见 `app/utils/url_guard.py`：协议/凭据/内网域名/内网 IP/DNS 解析）。
    """
    if not url:
        return False, "URL 不能为空"
    if not url.startswith("https://"):
        return False, "URL 必须以 https:// 开头"
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL 格式非法"
    if not parsed.hostname:
        return False, "URL 缺少主机名"
    host = parsed.hostname.lower()
    # 仅允许企业微信机器人域名，杜绝外部中继 / 任意站点。
    # 该白名单同时覆盖了 SSRF 场景：任何 IP 字面量（含 127.0.0.1、10.x.x.x）都不可能
    # 等于这个域名，故无需再单独拦内网网段（B14 删掉的正是那段死代码）。
    if host != _STUDENT_WEBHOOK_HOST:
        return False, "仅支持企业微信机器人域名 qyapi.weixin.qq.com"
    return True, None


def _student_webhook_owned(webhook, user_id):
    """校验 webhook 归属当前学生（owner_user_id 命中）；否则按 404 语义处理。"""
    return webhook is not None and webhook.owner_user_id == user_id


@miniapp_bp.route("/webhooks", methods=["GET"])
@student_required
def list_my_webhooks():
    """列出本人创建的「第三方消息通知」webhook（按 owner_user_id 过滤）。"""
    from app.core.database import get_db
    from app.model.webhook import Webhook

    user_id = int(g.current_user["user_id"])
    session = get_db()
    try:
        rows = (
            session.query(Webhook)
            .filter(Webhook.owner_user_id == user_id)
            .order_by(Webhook.created_at.desc())
            .all()
        )
        return api_success(data=[w.to_dict() for w in rows])
    finally:
        session.close()


@miniapp_bp.route("/webhooks", methods=["POST"])
@student_required
def create_my_webhook():
    """创建本人 webhook（服务端强制 scope=student + scope_target=[本人]）。"""
    from app.core.database import get_db
    from app.model.webhook import Webhook

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    if not name:
        return api_error(message="名称不能为空", http_status=400)
    ok, err = _validate_webhook_url(url)
    if not ok:
        return api_error(message=err, http_status=400)

    # 模块白名单：仅 course / electricity / weather；客户端传其它模块一律裁剪
    raw_modules = data.get("modules") or "course"
    if isinstance(raw_modules, list):
        raw_modules = ",".join(raw_modules)
    module_list = [m.strip() for m in raw_modules.split(",") if m.strip()]
    allowed = [m for m in module_list if m in _STUDENT_WEBHOOK_MODULES]
    modules = ",".join(allowed) if allowed else "course"

    session = get_db()
    try:
        # 围栏：限制单人所建数量，避免被滥建导致广播出站放大
        owned = session.query(Webhook).filter(Webhook.owner_user_id == user_id).count()
        if owned >= _MAX_WEBHOOKS_PER_STUDENT:
            return api_error(
                message=f"最多只能创建 {_MAX_WEBHOOKS_PER_STUDENT} 个通知，请先删除不再使用的",
                http_status=400,
            )

        webhook = Webhook.create(
            session=session,
            name=name,
            url=url,
            modules=modules,
            scope="student",                # 服务端强制：个人定向
            scope_target=[user_id],         # 服务端强制：仅本人
            description=(data.get("description") or "").strip() or None,
            owner_user_id=user_id,          # 归属本人
        )
        return api_success(message="创建成功", data=webhook.to_dict(), http_status=201)
    finally:
        session.close()


@miniapp_bp.route("/webhooks/<int:webhook_id>", methods=["PUT"])
@student_required
def update_my_webhook(webhook_id):
    """更新本人 webhook（归属与接收范围服务端强制，客户端不可改）。"""
    from app.core.database import get_db
    from app.model.webhook import Webhook

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}

    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not _student_webhook_owned(webhook, user_id):
            return api_error(message="Webhook 不存在", http_status=404)

        fields = {}
        if "name" in data:
            name = (data["name"] or "").strip()
            if not name:
                return api_error(message="名称不能为空", http_status=400)
            fields["name"] = name
        if "url" in data:
            url = (data["url"] or "").strip()
            ok, err = _validate_webhook_url(url)
            if not ok:
                return api_error(message=err, http_status=400)
            fields["url"] = url
        if "modules" in data:
            raw = data["modules"]
            if isinstance(raw, list):
                raw = ",".join(raw)
            ml = [m.strip() for m in raw.split(",") if m.strip()]
            allowed = [m for m in ml if m in _STUDENT_WEBHOOK_MODULES]
            fields["modules"] = ",".join(allowed) if allowed else "course"
        if "description" in data:
            fields["description"] = (data["description"] or "").strip() or None
        if "is_enabled" in data:
            fields["is_enabled"] = bool(data["is_enabled"])

        # 服务端强制：归属与接收范围不可被客户端篡改
        fields["owner_user_id"] = user_id
        fields["scope"] = "student"
        fields["scope_target"] = [user_id]

        Webhook.update(session, webhook_id, **fields)
        webhook = Webhook.get_by_id(session, webhook_id)
        return api_success(message="已保存", data=webhook.to_dict())
    finally:
        session.close()


@miniapp_bp.route("/webhooks/<int:webhook_id>", methods=["DELETE"])
@student_required
def delete_my_webhook(webhook_id):
    """删除本人 webhook。"""
    from app.core.database import get_db
    from app.model.webhook import Webhook

    user_id = int(g.current_user["user_id"])
    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not _student_webhook_owned(webhook, user_id):
            return api_error(message="Webhook 不存在", http_status=404)
        Webhook.delete(session, webhook_id)
        return api_success(message="已删除")
    finally:
        session.close()


@miniapp_bp.route("/webhooks/<int:webhook_id>/test", methods=["POST"])
@student_required
@limiter.limit(RATE_LIMITS["strict"])
def test_my_webhook(webhook_id):
    """测试本人 webhook（发送一条示例消息）。

    限流：该端点会向外部地址真实发起请求，单独设「strict」档（10 次/分钟），
    避免被反复调用刷出站流量或把自己的机器人打到微信侧限流。
    """
    import requests

    from app.core.database import get_db
    from app.model.webhook import Webhook

    user_id = int(g.current_user["user_id"])
    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not _student_webhook_owned(webhook, user_id):
            return api_error(message="Webhook 不存在", http_status=404)

        test_message = {
            "msgtype": "markdown",
            "markdown": {
                "content": "**测试消息**\n\n来自「第三方消息通知」自检\n时间：刚刚\n\n> 若收到说明配置正确"
            },
        }
        try:
            resp = requests.post(webhook.url, json=test_message, timeout=10)
            try:
                rdata = resp.json()
            except ValueError:
                rdata = {"raw": resp.text[:200]}
            if resp.status_code != 200:
                return api_error(message=f"测试失败：HTTP {resp.status_code}", data=rdata, http_status=400)
            errcode = rdata.get("errcode")
            if errcode is not None and errcode != 0:
                return api_error(message=f"测试失败：{rdata.get('errmsg', '未知错误')}", data=rdata, http_status=400)
            return api_success(message="测试消息发送成功", data={"webhook_response": rdata})
        except Exception as e:
            return api_error(message=f"测试异常：{str(e)}", http_status=500)
    finally:
        session.close()
