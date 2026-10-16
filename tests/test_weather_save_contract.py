"""
天气写入契约与并发防御单元测试（v6.21.x）

背景（2026-10-13 生产故障）：
- 实时天气更新固定失败于 `DELETE FROM weather_records`（OperationalError），
  但 `fetch_and_save_now` 把异常吞掉只返回 None，调用方照常标记 completed，
  ERROR 日志后紧跟「已更新」的 completed，极具误导性（DB 其实没写进去）。
- 根因诱因：weather_records 的写者有多个（定时任务 master 进程 + 读路径补写
  worker/后台线程），并发 DELETE + INSERT 同一张表互锁。

本测试锁定修复后的契约：
1. 写路径：上游无数据返回 None/[]；DB 失败（含重试耗尽）抛异常，不再用返回值
   同时表示「合法值」和「错误」。
2. 读路径（get_now_weather / get_hourly_forecast）：刷新失败时降级返回
   None / 空列表 / 旧数据，不向 API 抛异常。
3. _run_db_op 对 MySQL 瞬时错误（1213 死锁 / 1205 锁等待 / 2006 / 2013 / 2014）
   退避重试；非瞬时错误（如 1045 拒绝访问）立即抛出、不浪费重试。
"""

import os
import sys
import threading
import types

import pytest
from sqlalchemy.exc import OperationalError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import weather_service as ws
from app.services.weather_service import WeatherService


def _operational_error(code: int, msg: str = "boom") -> OperationalError:
    """构造带 pymysql 错误码的 SQLAlchemy OperationalError。"""
    return OperationalError("DELETE FROM weather_records", {}, Exception(code, msg))


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _FakeRecord:
    id = 1

    def to_dict(self) -> dict:
        return {"id": 1, "record_type": "now", "temp": 20}


_UNSET = object()


class _FakeFetcher:
    def __init__(self, now_data=_UNSET, hourly_data=_UNSET) -> None:
        self._now = {"temp": "20", "city_name": "永川区"} if now_data is _UNSET else now_data
        self._hourly = hourly_data

    def fetch_now(self):
        return self._now

    def fetch_hourly(self):
        return self._hourly


@pytest.fixture
def fake_time(monkeypatch):
    """把 weather_service 模块的 time.sleep 打成空操作，让重试测试不等真实退避。"""
    monkeypatch.setattr(ws, "time", types.SimpleNamespace(sleep=lambda _s: None))


class _CountingDelete:
    """可控的 delete 桩：前 fail_times 次抛指定异常，之后正常。"""

    def __init__(self, fail_times: int, exc: Exception) -> None:
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    def __call__(self, session=None, city_name="重庆"):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return 0


class TestNowSaveContract:
    """fetch_and_save_now 写入契约。"""

    def test_db_failure_raises_after_retries(self, monkeypatch, fake_time):
        """DB 持续瞬时失败：重试耗尽后抛异常，不再吞掉返回 None。"""
        session_holder = []

        def fake_get_db():
            s = _FakeSession()
            session_holder.append(s)
            return s

        monkeypatch.setattr(ws, "get_db", fake_get_db)
        delete_stub = _CountingDelete(fail_times=99, exc=_operational_error(1213, "Deadlock"))
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_now_records", lambda **kw: delete_stub(**kw)
        )

        svc = WeatherService(fetcher=_FakeFetcher())
        with pytest.raises(OperationalError):
            svc.fetch_and_save_now()

        assert delete_stub.calls == ws._DB_MAX_ATTEMPTS  # 重试次数符合预期
        assert all(s.rolled_back and s.closed for s in session_holder)  # 每次重试都干净收尾

    def test_no_upstream_data_returns_none(self, monkeypatch):
        """上游 API 无数据：返回 None（这是合法值，与 DB 失败区分）。"""
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        svc = WeatherService(fetcher=_FakeFetcher(now_data=None))
        assert svc.fetch_and_save_now() is None

    def test_success_returns_dict(self, monkeypatch):
        """正常路径：返回 dict，session 已提交并关闭。"""
        session = _FakeSession()
        monkeypatch.setattr(ws, "get_db", lambda: session)
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_now_records", lambda **kw: 1
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "create_weather_record", lambda **kw: _FakeRecord()
        )

        svc = WeatherService(fetcher=_FakeFetcher())
        result = svc.fetch_and_save_now()

        assert result == {"id": 1, "record_type": "now", "temp": 20}
        assert session.committed and session.closed


class TestRetryBehavior:
    """_run_db_op 重试策略。"""

    def test_retry_succeeds_after_deadlock(self, monkeypatch, fake_time):
        """1213 死锁后重试成功：返回结果，DELETE 只多调一次。"""
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        delete_stub = _CountingDelete(
            fail_times=1, exc=_operational_error(1213, "Deadlock found")
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_now_records", lambda **kw: delete_stub(**kw)
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "create_weather_record", lambda **kw: _FakeRecord()
        )

        svc = WeatherService(fetcher=_FakeFetcher())
        result = svc.fetch_and_save_now()

        assert result["id"] == 1
        assert delete_stub.calls == 2  # 第一次失败 + 第二次成功

    def test_non_retryable_error_raises_immediately(self, monkeypatch, fake_time):
        """非瞬时错误（1045 拒绝访问）：不重试，直接抛。"""
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        delete_stub = _CountingDelete(
            fail_times=99, exc=_operational_error(1045, "Access denied")
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_now_records", lambda **kw: delete_stub(**kw)
        )

        svc = WeatherService(fetcher=_FakeFetcher())
        with pytest.raises(OperationalError):
            svc.fetch_and_save_now()

        assert delete_stub.calls == 1  # 没有浪费重试


class TestHourlySaveContract:
    """fetch_and_save_hourly 写入契约。"""

    def test_db_failure_raises_after_retries(self, monkeypatch, fake_time):
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        delete_stub = _CountingDelete(fail_times=99, exc=_operational_error(1213, "Deadlock"))
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_hourly_records", lambda **kw: delete_stub(**kw)
        )

        svc = WeatherService(fetcher=_FakeFetcher(hourly_data=[{"time": "2026-10-13T10:00+08:00"}]))
        with pytest.raises(OperationalError):
            svc.fetch_and_save_hourly()

        assert delete_stub.calls == ws._DB_MAX_ATTEMPTS

    def test_no_upstream_data_returns_empty(self, monkeypatch):
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        svc = WeatherService(fetcher=_FakeFetcher(hourly_data=None))
        assert svc.fetch_and_save_hourly() == []


class TestReadPathDegradation:
    """读路径降级：刷新失败不能让 API 500。"""
    def test_get_now_weather_refresh_failure_returns_none(self, monkeypatch, fake_time):
        """DB 无记录且刷新失败：返回 None，不抛异常。"""
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        monkeypatch.setattr(
            ws.WeatherRepository, "get_latest_now_record", lambda session, city_name="重庆": None
        )
        delete_stub = _CountingDelete(
            fail_times=99, exc=_operational_error(1045, "Access denied")
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_now_records", lambda **kw: delete_stub(**kw)
        )

        svc = WeatherService(fetcher=_FakeFetcher())
        assert svc.get_now_weather() is None

    def test_get_hourly_forecast_refresh_failure_returns_empty(self, monkeypatch, fake_time):
        """DB 无记录且刷新失败：返回空列表，不抛异常。"""
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        monkeypatch.setattr(
            ws.WeatherRepository, "get_hourly_records",
            lambda session, city_name="重庆", limit=24: [],
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "get_latest_now_record", lambda session, city_name="重庆": None
        )
        delete_stub = _CountingDelete(
            fail_times=99, exc=_operational_error(1045, "Access denied")
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_now_records", lambda **kw: delete_stub(**kw)
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "delete_all_hourly_records", lambda **kw: delete_stub(**kw)
        )

        svc = WeatherService(fetcher=_FakeFetcher(hourly_data=[{"time": "2026-10-13T10:00+08:00"}]))
        assert svc.get_hourly_forecast() == []


class _FakeWeatherRecord:
    def __init__(self, created_at):
        self.created_at = created_at

    def to_dict(self):
        return {"temp": 20, "created_at": self.created_at.isoformat()}


class _FakeThreadRecorder:
    """记录 Thread 构造与 start，不真跑后台任务。"""

    def __init__(self):
        self.started = 0

    def __call__(self, target=None, args=(), daemon=False):
        self.target = target
        self.started += 1
        return self

    def start(self):
        pass


class TestStalenessClock:
    """过期判定必须与 created_at 的写入口径（本地时间 datetime.now）一致。

    2026-10-13 修复：早期误用 datetime.utcnow() 与本地时间写入的 created_at 比较，
    相差约 8 小时导致记录「永不过期」，定时任务写库失败时读路径不会补写。
    """

    def test_now_stale_record_triggers_background_refresh(self, monkeypatch):
        from datetime import datetime, timedelta

        stale = _FakeWeatherRecord(datetime.now() - timedelta(minutes=35))
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        monkeypatch.setattr(
            ws.WeatherRepository, "get_latest_now_record", lambda session, city_name="重庆": stale
        )
        monkeypatch.setattr(
            ws.WeatherService, "fetch_and_save_now", lambda self, city_name="重庆": {}
        )
        recorder = _FakeThreadRecorder()
        monkeypatch.setattr(threading, "Thread", recorder)

        svc = WeatherService(fetcher=_FakeFetcher())
        result = svc.get_now_weather()

        assert result == {"temp": 20, "created_at": stale.created_at.isoformat()}
        assert recorder.started == 1, "过期记录应触发后台刷新线程"

    def test_now_fresh_record_no_refresh(self, monkeypatch):
        from datetime import datetime, timedelta

        fresh = _FakeWeatherRecord(datetime.now() - timedelta(minutes=10))
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        monkeypatch.setattr(
            ws.WeatherRepository, "get_latest_now_record", lambda session, city_name="重庆": fresh
        )
        calls = []
        monkeypatch.setattr(
            ws.WeatherService, "fetch_and_save_now",
            lambda self, city_name="重庆": calls.append(1) or {},
        )
        recorder = _FakeThreadRecorder()
        monkeypatch.setattr(threading, "Thread", recorder)

        svc = WeatherService(fetcher=_FakeFetcher())
        svc.get_now_weather()

        assert recorder.started == 0, "未过期记录不应触发刷新"
        assert calls == [], "未过期记录不应调用 fetch_and_save_now"

    def test_hourly_stale_record_triggers_sync_refresh(self, monkeypatch, fake_time):
        from datetime import datetime, timedelta

        stale = _FakeWeatherRecord(datetime.now() - timedelta(minutes=90))
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        monkeypatch.setattr(
            ws.WeatherRepository, "get_hourly_records",
            lambda session, city_name="重庆", limit=24: [stale],
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "get_latest_now_record", lambda session, city_name="重庆": None
        )
        calls = []
        monkeypatch.setattr(
            ws.WeatherService, "fetch_and_save_hourly",
            lambda self, city_name="重庆": calls.append(1) or [{"time": "2026-10-13T11:00+08:00"}],
        )
        monkeypatch.setattr(
            ws.WeatherService, "fetch_and_save_now", lambda self, city_name="重庆": {}
        )

        svc = WeatherService(fetcher=_FakeFetcher(hourly_data=[{"time": "2026-10-13T11:00+08:00"}]))
        svc.get_hourly_forecast()

        assert calls == [1], "过期预报应触发同步刷新"

    def test_hourly_fresh_record_no_refresh(self, monkeypatch, fake_time):
        from datetime import datetime, timedelta

        fresh = _FakeWeatherRecord(datetime.now() - timedelta(minutes=10))
        monkeypatch.setattr(ws, "get_db", _FakeSession)
        monkeypatch.setattr(
            ws.WeatherRepository, "get_hourly_records",
            lambda session, city_name="重庆", limit=24: [fresh],
        )
        monkeypatch.setattr(
            ws.WeatherRepository, "get_latest_now_record", lambda session, city_name="重庆": None
        )
        calls = []
        monkeypatch.setattr(
            ws.WeatherService, "fetch_and_save_hourly",
            lambda self, city_name="重庆": calls.append(1) or [],
        )
        monkeypatch.setattr(
            ws.WeatherService, "fetch_and_save_now", lambda self, city_name="重庆": {}
        )

        svc = WeatherService(fetcher=_FakeFetcher(hourly_data=[]))
        svc.get_hourly_forecast()

        assert calls == [], "未过期预报不应触发刷新"
