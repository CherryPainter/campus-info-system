"""
微信小程序第二阶段接口测试（课表 / 天气 / 电量，v6.16.0）

覆盖：
- 鉴权：无 token 401、admin token 403（student_required 生效）
- 课表：today（按 full_date 过滤）、week（按 weeks 字段过滤 + 默认当前周 + 非法周 400）、current
- 天气：current / hourly / alerts（复用 weather_service，路由薄封装）
- 电量：current / history（按用电日聚合，一天一条）/ daily/<date>（用电日详情）

设计：路由层所有业务查询走现有 Service 单例，测试直接 mock Service 方法
或注入 schedule_service 内存缓存，不依赖真实 MySQL。

运行：
    cd Push_System_Flask && python -m pytest tests/test_miniapp_phase2.py -v
"""

import os
import sys
import time
import uuid
from datetime import date
from unittest import mock

import jwt as _jwt
import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.schedule_service import schedule_service
from app.services.weather_service import weather_service
from app.utils.jwt_auth import JWTManager

SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


class _FakeQuery:
    """查询桩：StudentProfile 返回已绑定身份，其余（黑名单等）返回 None"""

    def __init__(self, model):
        self._model = model

    def filter_by(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def offset(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def count(self):
        # 无真实数据时查询返回空结果集
        return 0

    def all(self):
        return []

    def first(self):
        from app.model.student_profile import StudentProfile
        from app.model.user import User

        if self._model is StudentProfile:
            # 模拟已通过预录名单完成身份绑定（student_bound_required 要求 student_number 非空）
            from types import SimpleNamespace

            return SimpleNamespace(student_number="20260001", electricity_cookie="")
        if self._model is User:
            # 模拟当前用户存在且启用（student_required 的 USER_GONE 存在性校验）
            from types import SimpleNamespace

            return SimpleNamespace(id=1)
        return None


class _FakeSession:
    """会话桩：任何查询返回 _FakeQuery（token 未撤销 / 身份已绑定）"""

    def query(self, model, *a, **k):
        return _FakeQuery(model)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _no_db():
    """jwt 黑名单校验与身份绑定校验均不连真实 MySQL"""
    with mock.patch("app.utils.jwt_auth.get_db", return_value=_FakeSession()), mock.patch(
        "app.core.database.get_db", return_value=_FakeSession()
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_schedule():
    """每个用例清空课表内存缓存，避免跨用例污染"""
    schedule_service._schedules = []
    yield
    schedule_service._schedules = []


@pytest.fixture(scope="module")
def app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        JWT_ACCESS_TOKEN_EXPIRE=3600,
        JWT_REFRESH_TOKEN_EXPIRE=604800,
        JWT_REFRESH_IDLE_EXPIRE=259200,
        JWT_REFRESH_ABSOLUTE_EXPIRE=2592000,
    )
    flask_app.extensions["jwt_manager"] = JWTManager(
        secret_key=flask_app.config["SECRET_KEY"],
        access_token_expire=flask_app.config["JWT_ACCESS_TOKEN_EXPIRE"],
        refresh_token_expire=flask_app.config["JWT_REFRESH_TOKEN_EXPIRE"],
        refresh_idle_expire=flask_app.config["JWT_REFRESH_IDLE_EXPIRE"],
        refresh_absolute_expire=flask_app.config["JWT_REFRESH_ABSOLUTE_EXPIRE"],
    )
    from app.api.miniapp_routes import miniapp_bp

    flask_app.register_blueprint(miniapp_bp, url_prefix="/api/miniapp")
    # 接入公开接口匿名会话令牌签发 + 访问日志（与生产 create_app 一致）
    from app.utils import anon_session

    anon_session.attach_anon_session(flask_app)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _make_token(app, user_id, username, role):
    now = int(time.time())
    payload = {
        "user_id": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return _jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


@pytest.fixture
def student_token(app):
    return _make_token(app, 1, "wx_student", "student")


@pytest.fixture
def admin_token(app):
    return _make_token(app, 999, "admin", "admin")


def _course(**over):
    """构造一条 schedule_service 内存课表数据"""
    base = {
        "schedule_id": "1",
        "day_of_week": 1,
        "start_time": "08:10",
        "end_time": "08:55",
        "course_name": "高等数学",
        "course_code": "",
        "period_idx": 1,
        "periods": [1],
        "extra_info": {
            "teacher": "张老师",
            "building": "启智楼",
            "classroom": "A101",
            "weeks": [1, 2, 3],
            "credits": "",
            "full_date": date.today().strftime("%Y-%m-%d"),
        },
        "_timeInfo": {"start_ts": 1000.0, "end_ts": 3600.0},
    }
    base.update(over)
    return base


# ==================== 鉴权 ====================


def test_no_token_401(client):
    # 需登录的接口：无 token 仍返回 401
    for path in (
        "/api/miniapp/electricity/current",
        "/api/miniapp/student/profile",
    ):
        assert client.get(path).status_code == 401, path


def test_public_endpoints_anonymous_ok(client):
    # 天气 / 公告为校园公开信息，游客（无 token）可直接浏览，满足「先体验后授权」审核规范
    # 7 个天气端点全部公开（含 2026-09-09 新增的 alerts/daily/indices/air/minutely）；
    # cache/fetcher 用 mock 兜底，避免测试依赖真实 Redis / 外网回源
    fake_cache = mock.MagicMock(get=mock.MagicMock(return_value=None))
    fake_fetcher = mock.MagicMock(
        fetch_daily=mock.MagicMock(return_value=[]),
        fetch_indices=mock.MagicMock(return_value=[]),
        fetch_airquality=mock.MagicMock(return_value=None),
        fetch_minutely=mock.MagicMock(return_value=None),
    )
    for path in (
        "/api/miniapp/weather/current",
        "/api/miniapp/weather/hourly",
        "/api/miniapp/weather/alerts",
        "/api/miniapp/weather/daily",
        "/api/miniapp/weather/indices",
        "/api/miniapp/weather/air",
        "/api/miniapp/weather/minutely",
        "/api/miniapp/announcements",
        "/api/miniapp/announcements/unread-count",
    ):
        with mock.patch.object(
            weather_service, "get_active_alerts", return_value=[]
        ), mock.patch(
            "app.modules.weather.tasks._make_cache", return_value=fake_cache
        ), mock.patch(
            "app.modules.weather.tasks._make_fetcher", return_value=fake_fetcher
        ):
            resp = client.get(path)
        assert resp.status_code == 200, path


def test_public_endpoint_issues_anon_token(client):
    # 公开接口应下发 X-Anon-Token（匿名会话令牌），供客户端回传以按会话溯源 + 限流
    resp = client.get("/api/miniapp/weather/current")
    assert resp.status_code == 200
    assert "X-Anon-Token" in resp.headers
    token = resp.headers["X-Anon-Token"]
    # 回传同一令牌后，响应应原样回显（会话稳定，不旋转）
    resp2 = client.get("/api/miniapp/announcements", headers={"X-Anon-Token": token})
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Anon-Token") == token


def test_admin_token_403(client, admin_token):
    # 仍受 student_required 保护的接口：admin token 返回 403
    for path in (
        "/api/miniapp/electricity/history",
        "/api/miniapp/electricity/current",
    ):
        resp = client.get(path, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 403, path


class _GoneUserQuery:
    """查询桩：恒查不到（模拟用户已被删除/禁用）"""

    def filter_by(self, *a, **k):
        return self

    def first(self):
        return None


class _GoneUserSession:
    """会话桩：任何查询返回空，模拟 users 表无该用户"""

    def query(self, model, *a, **k):
        return _GoneUserQuery()

    def close(self):
        pass


def test_deleted_user_returns_401_user_gone(client, student_token):
    """回归（2026-09-06）：清库/删号后旧 token 仍签名有效，
    student_required 必须查库拦截为 401 USER_GONE，
    而不是一路放行到 bind 落库才报外键 500。
    （用仍受 student_bound_required 保护的电量接口验证该路径；天气/公告已放开为公开）"""
    with mock.patch("app.core.database.get_db", return_value=_GoneUserSession()):
        resp = client.get(
            "/api/miniapp/electricity/current",
            headers={"Authorization": f"Bearer {student_token}"},
        )
    assert resp.status_code == 401
    assert resp.get_json().get("code") == "USER_GONE"


# ==================== 课表 ====================


def test_schedule_today_filters_by_date(client, student_token):
    """今日课程口径（v6.19.0）：day_of_week == 今天星期几 且 当前教学周 ∈ weeks。

    不再依赖 extra_info.full_date（旧口径）：full_date 由随每次爬取漂移的 week_number
    推导，跨周后会整体偏移，导致「今日课程」恒为空。原测试固定 day_of_week=1（周一），
    对星期几敏感——这里改为按今天真实星期构造，保证任何一天都稳定通过。
    """
    today_str = date.today().strftime("%Y-%m-%d")
    today_wd = date.today().isoweekday()  # 1..7
    other_wd = 1 if today_wd != 1 else 2

    schedule_service._schedules = [
        # 星期匹配 + 当前教学周(2) ∈ weeks([1,2,3]) → 命中，full_date 被修正为今天
        _course(schedule_id="1", course_name="今天有课", day_of_week=today_wd),
        # 星期不匹配 → 不返回；其 full_date 刻意设成非今天，证明不再依赖该字段
        _course(
            schedule_id="2",
            course_name="不是今天",
            day_of_week=other_wd,
            extra_info={
                "teacher": "李老师",
                "building": "启智楼",
                "classroom": "B202",
                "weeks": [1, 2, 3],
                "credits": "",
                "full_date": "2099-01-01",
            },
        ),
    ]
    with mock.patch("app.utils.course_helpers.get_current_week_number", return_value=2):
        resp = client.get(
            "/api/miniapp/schedule/today", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    courses = resp.get_json()["data"]["courses"]
    assert [c["course_name"] for c in courses] == ["今天有课"]
    assert courses[0]["extra_info"]["full_date"] == today_str


def test_schedule_week_filters_by_week(client, student_token):
    schedule_service._schedules = [
        _course(schedule_id="1", course_name="第2周有课", extra_info={
            "teacher": "张老师", "building": "启智楼", "classroom": "A101",
            "weeks": [1, 2, 3], "credits": "", "full_date": "2026-09-01",
        }),
        _course(schedule_id="2", course_name="只在第5周", extra_info={
            "teacher": "王老师", "building": "艺教楼", "classroom": "C303",
            "weeks": [5], "credits": "", "full_date": "2026-09-01",
        }),
    ]
    with mock.patch(
        "app.services.teaching_week_service.build_available_weeks",
        return_value=[{"week_number": 1, "start_date": "2026-09-01", "end_date": "2026-09-07"}],
    ):
        resp = client.get(
            "/api/miniapp/schedule/week?week_number=2",
            headers={"Authorization": f"Bearer {student_token}"},
        )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert [c["course_name"] for c in body["courses"]] == ["第2周有课"]
    assert body["week_number"] == 2
    assert body["available_weeks"]


def test_schedule_week_default_current_week(client, student_token):
    schedule_service._schedules = [
        _course(schedule_id="1", course_name="本周课", extra_info={
            "teacher": "张老师", "building": "启智楼", "classroom": "A101",
            "weeks": [3], "credits": "", "full_date": "2026-09-01",
        })
    ]
    with mock.patch("app.utils.course_helpers.get_current_week_number", return_value=3), mock.patch(
        "app.services.teaching_week_service.build_available_weeks", return_value=[]
    ):
        resp = client.get(
            "/api/miniapp/schedule/week", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["week_number"] == 3
    assert [c["course_name"] for c in body["courses"]] == ["本周课"]


def test_schedule_week_invalid_week_400(client, student_token):
    resp = client.get(
        "/api/miniapp/schedule/week?week_number=0",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 400


def test_schedule_current_returns_week_info(client, student_token):
    with mock.patch("app.utils.course_helpers.get_current_week_number", return_value=3):
        resp = client.get(
            "/api/miniapp/schedule/current", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["week_number"] == 3
    assert data["is_teaching_week"] is True
    assert data["date"] == date.today().strftime("%Y-%m-%d")
    assert 1 <= data["week_day"] <= 7


# ==================== 天气 ====================


def test_weather_current(client, student_token):
    with mock.patch.object(
        weather_service,
        "get_now_weather",
        return_value={"temp": 28, "text": "多云", "update_time": "2026-08-27 20:00"},
    ):
        resp = client.get(
            "/api/miniapp/weather/current", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["weather"]["temp"] == 28
    assert data["weather"]["text"] == "多云"


def test_weather_current_no_data(client, student_token):
    with mock.patch.object(weather_service, "get_now_weather", return_value=None):
        resp = client.get(
            "/api/miniapp/weather/current", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["weather"] is None


def test_weather_hourly(client, student_token):
    with mock.patch.object(
        weather_service,
        "get_hourly_forecast",
        return_value=[{"fxTime": "2026-08-27T20:00", "temp": "28"}],
    ):
        resp = client.get(
            "/api/miniapp/weather/hourly", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["hourly"][0]["fxTime"]


def test_weather_alerts(client, student_token):
    with mock.patch.object(
        weather_service,
        "get_active_alerts",
        return_value=[{"headline": "高温橙色预警", "severity": "橙色"}],
    ):
        resp = client.get(
            "/api/miniapp/weather/alerts", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["warnings"][0]["headline"] == "高温橙色预警"


# ==================== 电量 ====================


def test_electricity_current(client, student_token):
    with mock.patch("app.services.electricity_service.get_electricity_service") as _get_svc:
        _get_svc.return_value.get_remaining_power.return_value = {
            "remaining": 36.5,
            "total_capacity": 100.0,
            "percentage": 36.5,
            "is_low_power": False,
            "recorded_at": "2026-08-27 00:30",
        }
        resp = client.get(
            "/api/miniapp/electricity/current", headers={"Authorization": f"Bearer {student_token}"}
        )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["electricity"]["remaining"] == 36.5
    assert data["electricity"]["is_low_power"] is False


def test_electricity_history_returns_daily_aggregates(client, student_token):
    """
    用电记录按用电日聚合（一天一条），limit / offset 的单位是「天」

    为什么改：原始明细里一个宿舍一天有两条（两块分表，record_time 完全相同），
    列表直接展示就是「一天两条」，且 record_time 是结算时刻（用电日 + 1 天），
    整体错后一天。现由 Service 按天聚合后返回，路由只做透传。
    """
    captured = {}

    def _fake_daily(limit=30, offset=0):
        captured["limit"] = limit
        captured["offset"] = offset
        return {
            "days": [
                {
                    "date": "2026-09-17",
                    "total_usage": 2.46,
                    "settle_time": "2026-09-18 00:09:51",
                }
            ],
            "total": 1,
            "offset": offset,
            "limit": limit,
        }

    with mock.patch("app.services.electricity_service.get_electricity_service") as _get_svc:
        _get_svc.return_value.get_daily_records.side_effect = _fake_daily
        resp = client.get(
            "/api/miniapp/electricity/history?limit=5",
            headers={"Authorization": f"Bearer {student_token}"},
        )
    assert resp.status_code == 200
    assert captured["limit"] == 5  # limit 透传，单位是天
    assert captured["offset"] == 0

    data = resp.get_json()["data"]
    assert data["total"] == 1
    assert data["days"][0]["date"] == "2026-09-17"
    assert data["days"][0]["total_usage"] == 2.46
    assert data["fetch_triggered"] is False  # 有记录，不触发懒采集


def test_electricity_daily_detail_rejects_bad_date(client, student_token):
    """用电日格式非法 → 400，且不把脏串带进查询"""
    with mock.patch("app.services.electricity_service.get_electricity_service") as _get_svc:
        resp = client.get(
            "/api/miniapp/electricity/daily/not-a-date",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 400
        _get_svc.return_value.get_daily_detail.assert_not_called()


def test_electricity_daily_detail_404_when_no_record(client, student_token):
    """该用电日无记录 → 404"""
    with mock.patch("app.services.electricity_service.get_electricity_service") as _get_svc:
        _get_svc.return_value.get_daily_detail.return_value = None
        resp = client.get(
            "/api/miniapp/electricity/daily/2026-09-17",
            headers={"Authorization": f"Bearer {student_token}"},
        )
    assert resp.status_code == 404


def test_electricity_daily_detail_ok(client, student_token):
    """详情正常返回：总用量 + 各分表占比 + 对比 + 结算后剩余电量"""
    detail = {
        "date": "2026-09-17",
        "settle_time": "2026-09-18 00:09:51",
        "total_usage": 2.46,
        "meter_count": 2,
        "meters": [
            {"meter": "310512", "usage": 1.71, "percent": 69.51},
            {"meter": "31栋512", "usage": 0.75, "percent": 30.49},
        ],
        "prev": {"date": "2026-09-16", "total_usage": 2.35},
        "diff_prev": 0.11,
        "avg_recent": 2.66,
        "avg_recent_days": 7,
        "diff_avg": -0.20,
        "remaining": 101.81,
        "remaining_at": "2026-09-18 00:10:00",
    }
    with mock.patch("app.services.electricity_service.get_electricity_service") as _get_svc:
        _get_svc.return_value.get_daily_detail.return_value = detail
        resp = client.get(
            "/api/miniapp/electricity/daily/2026-09-17",
            headers={"Authorization": f"Bearer {student_token}"},
        )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total_usage"] == 2.46
    assert data["meter_count"] == 2
    # 各分表占比合计应为 100%
    assert round(sum(m["percent"] for m in data["meters"]), 2) == 100.00
