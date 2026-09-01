#!/usr/bin/env python3
"""
微信小程序业务路由（/api/miniapp/*）

仅提供学生端只读查询与个人资料接口，与 /api/admin 管理端能力完全隔离。
数据权限基于 JWT 中的 user_id（g.current_user），不接受客户端传入他人 ID（防 IDOR 越权）。

接口清单：
- GET  /api/miniapp/user/me                    当前学生用户信息（v6.16.0）
- GET  /api/miniapp/student/bind-status        身份绑定状态（是否通过预录名单绑定）
- GET  /api/miniapp/student/schools            身份绑定可选学校列表（含模糊干扰项）
- POST /api/miniapp/student/bind               身份绑定（学校+学号+班级 命中预录名单）
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
- GET  /api/miniapp/electricity/history        用电记录（该学生无任何记录时自动懒采集一次全量爬取，响应含 fetch_triggered）
- GET  /api/miniapp/electricity/trend          用电趋势
- GET  /api/miniapp/electricity/cookie         电表 Cookie 配置状态（脱敏）
- PUT  /api/miniapp/electricity/cookie         保存本人电表 Cookie
- POST /api/miniapp/electricity/cookie/test    测试 Cookie 有效性
- GET  /api/miniapp/notifications/messages     个人站内通知列表（含未读公告提醒）
- POST /api/miniapp/notifications/messages/read 标记已读（指定或全部，全部联动清公告）
- GET  /api/miniapp/notifications/unread-count 消息未读统计（站内通知+公告，角标用）
- GET  /api/miniapp/notifications/upcoming     近期提醒（学校日历事件）
- GET  /api/miniapp/notifications/all          全部未过期提醒
- GET  /api/miniapp/announcements              校园通知列表（纯拉取）
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

from flask import Blueprint, g, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.utils.student_auth import student_bound_required, student_required

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
    身份绑定可选学校列表（含模糊干扰项；重庆科创职业学院必须保留）
    """
    from app.api.admin_roster_routes import SCHOOL_OPTIONS

    return api_success(schools=SCHOOL_OPTIONS)


@miniapp_bp.route("/student/bind", methods=["POST"])
@student_required
def bind_student():
    """
    身份绑定：校验「学校 + 学号 + 班级」命中预录名单（启用中）后写入本人资料

    - 三项均匹配且名单条目 is_active=1 才绑定成功；
    - 绑定成功后 school/student_number/class_name 由本接口管理，
      不再接受 PUT /student/profile 修改（防止绕过名单直接填学号）。
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile
    from app.services.student_roster_service import StudentRosterService

    payload = request.get_json(silent=True) or {}
    school = (payload.get("school") or "").strip()
    student_number = (payload.get("student_number") or "").strip()
    class_name = (payload.get("class_name") or "").strip()
    if not school or not student_number or not class_name:
        return api_error(message="学校、学号、班级均不能为空", http_status=400)

    ok, _row = StudentRosterService.verify(school, student_number, class_name)
    if not ok:
        logger.warning(
            f"身份绑定校验未通过: user_id={g.current_user.get('user_id')}, "
            f"school={school}, student_number={student_number}"
        )
        return api_error(
            message="身份校验未通过，请联系管理员确认名单", http_status=403
        )

    user_id = int(g.current_user["user_id"])
    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = StudentProfile(user_id=user_id)
            db.add(profile)
        profile.school = school
        profile.student_number = student_number
        profile.class_name = class_name
        db.commit()
        db.refresh(profile)
        logger.info(
            f"身份绑定成功: user_id={user_id}, school={school}, "
            f"student_number={student_number}, class_name={class_name}"
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
            "real_name": "姓名",
            "nickname": "昵称",
            "college": "学院",
            "major": "专业",
            "grade": "年级",
            "phone": "手机号"
        }

    注意：school / student_number / class_name 由「身份绑定」接口（POST /student/bind）
    管理，不在此白名单内——防止绕过预录名单直接填写学号。
    """
    from app.core.database import get_db
    from app.model.student_profile import StudentProfile

    user_id = int(g.current_user["user_id"])
    data = request.get_json(silent=True) or {}

    allowed_fields = {
        "campus_card_number",
        "real_name",
        "nickname",
        "college",
        "major",
        "grade",
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
    指定周课表（默认当前教学周）

    查询参数：
        week_number (int, 可选): 目标周次，缺省取当前教学周（非教学周回退第 1 周）

    返回：
        courses: 该周有课的课程列表（按 weeks 字段过滤）
        week_number: 实际查询的周次
        available_weeks: 可选周次列表（基于开学日推算）
    """
    from app.services.schedule_service import schedule_service
    from app.services.teaching_week_service import build_available_weeks
    from app.utils.course_helpers import get_current_week_number, is_course_in_week
    from app.repository.course_repository import get_current_semester_id

    week_number = request.args.get("week_number", type=int)
    if week_number is None:
        week_number = get_current_week_number() or 1
    if week_number <= 0:
        return api_error(message="周次无效", http_status=400)

    # 可选周次：与网页端 /course/timetable 口径一致（基于真实当前学期推算）
    try:
        sem_id = get_current_semester_id()
        available_weeks = build_available_weeks(sem_id)
    except Exception as e:
        logger.warning(f"获取可选周次失败（接口降级返回空列表）: {e}")
        available_weeks = []

    all_courses = schedule_service.get_schedules()
    courses = [
        c for c in all_courses if is_course_in_week(c["extra_info"]["weeks"], week_number)
    ]
    return api_success(
        data={
            "courses": courses,
            "week_number": week_number,
            "available_weeks": available_weeks,
        }
    )


@miniapp_bp.route("/schedule/current", methods=["GET"])
@student_bound_required
def schedule_current():
    """
    当前教学周信息 + 学期周次面板数据

    返回：
        week_number: 当前周次（0 表示非教学周/假期）
        is_teaching_week: 是否处于教学周
        date: 今天日期（YYYY-MM-DD）
        week_day: 今天星期几（1=周一，7=周日）
        semester_id: 当前学期 ID（如 20261）
        semester_name: 当前学期名称（如 "2026-2027 秋季"）
        available_weeks: 可选周次列表 [{week_number, start_date, end_date, is_teaching}]
    """
    from datetime import date

    from app.utils.course_helpers import get_current_week_number
    from app.repository.course_repository import get_current_semester_id, semester_info_from_id
    from app.services.teaching_week_service import build_available_weeks

    week_number = get_current_week_number()
    today = date.today()
    sem_id = get_current_semester_id()
    sem_info = semester_info_from_id(sem_id)
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
        }
    )


# ==================== 天气（复用 weather_service，路由薄封装） ====================


@miniapp_bp.route("/weather/current", methods=["GET"])
@student_bound_required
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
@student_bound_required
def weather_hourly():
    """
    24 小时逐小时预报（60 分钟 TTL，过期返回旧数据并后台刷新）
    """
    from app.services.weather_service import weather_service

    hourly = weather_service.get_hourly_forecast()
    return api_success(data={"hourly": hourly})


@miniapp_bp.route("/weather/alerts", methods=["GET"])
@student_bound_required
def weather_alerts():
    """
    生效中的天气预警
    """
    from app.services.weather_service import weather_service

    alerts = weather_service.get_active_alerts()
    return api_success(data={"warnings": alerts})


@miniapp_bp.route("/weather/daily", methods=["GET"])
@student_bound_required
def weather_daily():
    """
    未来 7 天逐天预报（缓存 3 小时，未命中按需回源）
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
@student_bound_required
def weather_indices():
    """
    生活指数（缓存 6 小时，未命中按需回源）
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
@student_bound_required
def weather_air():
    """
    实时空气质量 AQI（缓存 30 分钟，未命中按需回源）
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
@student_bound_required
def weather_minutely():
    """
    分钟级降水（缓存 30 分钟，未命中按需回源）
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
            message="未配置电表 Cookie，请前往设置中配置",
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
    用电记录（按需分页，前端用多少请求多少，按 JWT 用户隔离）

    查询参数：
        limit  (int, 可选): 每页条数，默认 30，上限 1000
        offset (int, 可选): 跳过条数，默认 0
        days   (int, 可选): 仅统计/返回最近 N 天；缺省为全部

    返回：
        {
          "records": [...],
          "total": <满足条件的记录总数>,
          "offset": <本次偏移>,
          "limit": <本次每页>,
          "fetch_triggered": <bool, 该学生此前无任何记录且已配置 Cookie 时自动触发首次全量采集>
        }

    说明：学生第一次进入电量详情页（管理员尚未手动触发、定时任务未覆盖）时，
    若其用电记录为空，后端自动为其触发一次全量爬取补全记录（异步执行，
    本次仍返回空列表，前端应提示"正在首次采集，请稍后刷新"）。
    """
    from app.services.electricity_service import get_electricity_service

    user_id = int(g.current_user["user_id"])
    svc = get_electricity_service(user_id=user_id)

    limit = request.args.get("limit", type=int) or 30
    limit = max(1, min(limit, 1000))
    offset = request.args.get("offset", type=int) or 0
    offset = max(0, offset)
    days = request.args.get("days", type=int)

    records = svc.get_usage_records(days=days, limit=limit, offset=offset)
    total = svc.count_usage_records(days=days)

    # 懒采集：该学生从未有过任何用电记录（管理员未手动触发、定时任务尚未覆盖）时，
    # 自动为其触发一次全量爬取补全记录。异步执行不阻塞本次响应，
    # 前端据 fetch_triggered 提示"正在首次采集，请稍后刷新"。
    fetch_triggered = False
    if total == 0:
        from app.modules.electricity.tasks import lazy_fetch_for_user

        fetch_triggered = lazy_fetch_for_user(user_id)

    return api_success(
        data={
            "records": records,
            "total": total,
            "offset": offset,
            "limit": limit,
            "fetch_triggered": fetch_triggered,
        }
    )


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
        return api_error(message="Cookie 不能为空", http_status=400)
    if len(cookie) > 4096:
        return api_error(message="Cookie 过长（上限 4096 字符）", http_status=400)

    db = get_db()
    try:
        profile = db.query(StudentProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = StudentProfile(user_id=user_id)
            db.add(profile)
        profile.electricity_cookie = cookie
        db.commit()
        logger.info(f"[miniapp] 用户 {user_id} 已更新电表 Cookie")
        return api_success(message="电表 Cookie 已保存")
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
        return api_error(message="Cookie 不能为空", http_status=400)

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
@student_bound_required
def announcements_list():
    """校园通知列表（仅已发布、未过期，置顶优先）

    查询参数：
        category (str, 可选): notice/activity/urgent/system，缺省或 all 表示全部
        page (int, 可选): 页码，默认 1
        page_size (int, 可选): 每页条数，默认 20，上限 50
        only_unread (str, 可选): "1"/"true" 时仅返回未读

    返回：
        items: 通知列表（含 is_top/is_read/is_favorite/attachment_count/summary）
        total: 满足条件的总条数
    """
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    category = request.args.get("category") or None
    page = request.args.get("page", type=int) or 1
    page_size = request.args.get("page_size", type=int) or 20
    only_unread = (request.args.get("only_unread") or "").lower() in ("1", "true", "yes")
    only_favorite = (request.args.get("only_favorite") or "").lower() in ("1", "true", "yes")

    items, total = announcement_service.list_for_user(
        user_id,
        category=category,
        page=page,
        page_size=page_size,
        only_unread=only_unread,
        only_favorite=only_favorite,
    )
    return api_success(
        data={"items": items, "total": total, "page": page, "page_size": page_size}
    )


@miniapp_bp.route("/announcements/unread-count", methods=["GET"])
@student_bound_required
def announcements_unread_count():
    """未读通知数（首页角标/红点用）"""
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    return api_success(data={"unread": announcement_service.unread_count(user_id)})


@miniapp_bp.route("/announcements/<int:announcement_id>", methods=["GET"])
@student_bound_required
def announcement_detail(announcement_id):
    """通知详情（含正文、附件、同分类相关推荐；首次访问自动记已读并累加阅读数）"""
    from app.services.announcement_service import announcement_service

    user_id = int(g.current_user["user_id"])
    data = announcement_service.detail_for_user(user_id, announcement_id)
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
