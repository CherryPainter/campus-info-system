"""
天气降雨提醒「分时段」逻辑单元测试。

验证用户诉求：
1. 排除夜间（06:00 之前 / 22:00 及之后不播报）；
2. 白天等分为 4 段（上午 06-10 / 中午 10-14 / 下午 14-18 / 傍晚 18-22）；
3. 每次只播报「当前所处时段」内的高概率（>=70%）时段，不把全天/次日一次性罗列；
4. 同一时段当天有且只有一次（持久化去重）。

同时验证每日晨报 get_daily_summary 的降雨概率也只统计「当天白天」，
避免次日 / 夜间高概率误报「今日有雨」。
"""

import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from unittest.mock import patch

from app.modules.weather.analyzer import WeatherAnalyzer


class _FixedDateTime(datetime):
    """把 datetime.now() 固定到指定时刻，便于确定性测试。

    仅替换 now()，fromisoformat 等静态解析仍走标准库实现。
    """

    _fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


def _hourly(iso_prefix, hour, pop, text="雨"):
    """构造一条逐小时预报项（time 为当天/指定日期的某整点 ISO 串）。"""
    return {"time": f"{iso_prefix}T{hour:02d}:00+08:00", "pop": pop, "text": text, "temp": "20"}


def _make_hourly(now_dt):
    """围绕当前时刻构造一组覆盖各场景的逐小时数据。

    分时段采用半开区间：上午[6,10) 中午[10,14) 下午[14,18) 傍晚[18,22)。
    因此 hour=10 属「中午」段而非「上午」段——测试用例的断言必须与此一致。
    """
    day = now_dt.strftime("%Y-%m-%d")
    from datetime import timedelta

    tomorrow = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    items = [
        # ── 当前时段（上午 06-10 且晚于 now），两条 >=70 高概率，应被播报 ──
        _hourly(day, 8, 78),
        _hourly(day, 9, 75),
        # ── 其它白天时段（应排除：只播当前段）──
        _hourly(day, 10, 72),  # 中午段起点（半开区间归属下一段）
        _hourly(day, 11, 90),  # 中午段
        _hourly(day, 14, 95),  # 下午段
        _hourly(day, 19, 88),  # 傍晚段
        # ── 夜间（应排除）──
        _hourly(day, 23, 99),
        _hourly(day, 3, 99),  # 凌晨，属夜间
        # ── 次日（应排除，这是「到第二天」的历史 bug 来源）──
        _hourly(tomorrow, 9, 99),
        _hourly(tomorrow, 14, 99),
    ]
    return items


class TestRainSegmentAnalysis:
    def setup_method(self):
        self._state_dir = tempfile.mkdtemp(prefix="weather_test_")

    def teardown_method(self):
        for f in os.listdir(self._state_dir):
            os.remove(os.path.join(self._state_dir, f))
        os.rmdir(self._state_dir)

    def test_only_current_segment_reported(self):
        """当前处于上午段(07:30)，只应播报上午段（晚于 now）的高概率小时，
        次日/夜间/其它段一律排除。"""
        now_dt = datetime(2026, 9, 18, 7, 30)
        analyzer = WeatherAnalyzer(state_dir=self._state_dir)
        hourly = _make_hourly(now_dt)

        with patch("app.modules.weather.analyzer.datetime", _FixedDateTime):
            _FixedDateTime._fixed = now_dt
            events = analyzer.analyze(None, hourly, [])

        rain_events = [e for e in events if e.get("type") == "rain"]
        # 全天有多个高概率小时分布在 4 个白天段 + 夜间 + 次日，
        # 但只应产出 1 条「上午」降雨事件，且只包含上午段晚于 07:30 的小时。
        assert len(rain_events) == 1, f"期望 1 条降雨事件，实际 {len(rain_events)}: {rain_events}"
        ev = rain_events[0]
        assert ev["segment_label"] == "上午"
        assert ev["segment_range"] == "06:00-10:00"
        assert ev["has_heavy_rain"] is False  # 78/75 均 <80，非大雨
        # 仅 08、09 两个整点被纳入（均为上午段且晚于 07:30）
        reported_hours = sorted(
            datetime.fromisoformat(rh["time"]).strftime("%H:%M") for rh in ev["rain_hours"]
        )
        assert reported_hours == ["08:00", "09:00"], f"播报时段异常: {reported_hours}"
        # 次日 / 夜间 / 其它段（含紧邻的 10:00 中午段起点）绝不应出现
        all_times = " ".join(rh["time"] for rh in ev["rain_hours"])
        assert "T10:00" not in all_times
        assert "T11:00" not in all_times
        assert "T14:00" not in all_times
        assert "T19:00" not in all_times
        assert "T23:00" not in all_times

    def test_segment_once_per_day(self):
        """同一时段当天第二次调用不再播报（有且只有一次）。"""
        now_dt = datetime(2026, 9, 18, 7, 30)
        analyzer = WeatherAnalyzer(state_dir=self._state_dir)
        hourly = _make_hourly(now_dt)

        with patch("app.modules.weather.analyzer.datetime", _FixedDateTime):
            _FixedDateTime._fixed = now_dt
            first = analyzer.analyze(None, hourly, [])
            second = analyzer.analyze(None, hourly, [])

        first_rain = [e for e in first if e.get("type") == "rain"]
        second_rain = [e for e in second if e.get("type") == "rain"]
        assert len(first_rain) == 1
        assert len(second_rain) == 0, "同一上午段当天第二次调用不应再播报"

    def test_night_excluded_entirely(self):
        """当前处于夜间(23:30)，不应产出任何降雨事件。"""
        now_dt = datetime(2026, 9, 18, 23, 30)
        analyzer = WeatherAnalyzer(state_dir=self._state_dir)
        hourly = _make_hourly(now_dt)

        with patch("app.modules.weather.analyzer.datetime", _FixedDateTime):
            _FixedDateTime._fixed = now_dt
            events = analyzer.analyze(None, hourly, [])

        rain_events = [e for e in events if e.get("type") == "rain"]
        assert len(rain_events) == 0, f"夜间不应播报降雨，实际: {rain_events}"

    def test_no_rain_when_below_threshold(self):
        """当前时段所有小时概率都低于阈值，不应播报。"""
        now_dt = datetime(2026, 9, 18, 7, 30)
        analyzer = WeatherAnalyzer(state_dir=self._state_dir)
        day = now_dt.strftime("%Y-%m-%d")
        hourly = [
            _hourly(day, 8, 50),
            _hourly(day, 9, 60),
            _hourly(day, 10, 65),
        ]

        with patch("app.modules.weather.analyzer.datetime", _FixedDateTime):
            _FixedDateTime._fixed = now_dt
            events = analyzer.analyze(None, hourly, [])

        rain_events = [e for e in events if e.get("type") == "rain"]
        assert len(rain_events) == 0


class TestDailySummaryDaytimeOnly:
    def setup_method(self):
        self._state_dir = tempfile.mkdtemp(prefix="weather_test_")

    def teardown_method(self):
        for f in os.listdir(self._state_dir):
            os.remove(os.path.join(self._state_dir, f))
        os.rmdir(self._state_dir)

    def test_rain_probability_excludes_night_and_next_day(self):
        """每日晨报的降雨概率只取当天白天最大值，排除夜间与次日。"""
        now_dt = datetime(2026, 9, 18, 7, 0)
        analyzer = WeatherAnalyzer(state_dir=self._state_dir)
        day = now_dt.strftime("%Y-%m-%d")
        from datetime import timedelta

        tomorrow = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        hourly = [
            _hourly(day, 9, 40),  # 白天
            _hourly(day, 14, 55),  # 白天（最高，应被采纳）
            _hourly(day, 23, 99),  # 夜间，应排除
            _hourly(tomorrow, 10, 99),  # 次日，应排除
        ]

        with patch("app.modules.weather.analyzer.datetime", _FixedDateTime):
            _FixedDateTime._fixed = now_dt
            summary = analyzer.get_daily_summary(None, hourly)

        assert summary["rain_probability"] == 55, (
            f"晨报降雨概率应仅取当天白天最大 55，实际 {summary['rain_probability']}"
        )
