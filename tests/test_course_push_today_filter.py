"""
课程推送「今日课程」口径 + 合并健壮性回归测试（2026-10-13）

背景（生产现象「自建能推、爬虫不推」+ 每日课表推送 failed）：
- 定时推送规则层 ``check_conditions`` 旧用 ``full_date == today`` 字符串匹配过滤今日课程，
  而 full_date 由 ``schedule_service._calculate_date`` 按课程静态 ``week_number`` 锚定算得：
  爬虫课 ``week_number = weeks_list[0]``（课程第一周，如第2周）→ full_date 落在其第一周、
  永远 ≠ 今天 → 定时推送（每日课表 / 课前 / 下课提醒）漏掉全部爬虫课；自建课
  ``week_number=None`` 锚定本周 → 能推。显示端 ``get_today_schedules`` 早已改用
  「星期几 + is_course_in_week」，推送端没跟着改 → 显示对、推送漏。
- 修复：``check_conditions`` 改委托 ``schedule_service.get_today_schedules()``；并给
  ``rule_service._merge_courses_for_push`` 与 ``delivery_service._merge_courses`` 加
  单课程组 try/except，避免一门脏课（period_idx 非数字致 int() 抛错）崩掉整批推送。

反向验证：撤掉修复（恢复 full_date 过滤 / 去掉 try/except）下列用例应变红。
"""

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.rule_service import RuleService
from app.services.delivery_service import DeliveryService
from app.services.schedule_service import schedule_service


def _course(name, **over):
    base = {
        "schedule_id": name,
        "course_name": name,
        "day_of_week": 2,
        "start_time": "08:00",
        "end_time": "09:40",
        "period_idx": 1,
        "periods": [1, 2],
        "extra_info": {
            "teacher": "",
            "building": "",
            "classroom": "101",
            "weeks": [1, 2, 3],
        },
        "_timeInfo": {"start_ts": 0.0, "end_ts": 0.0, "is_today": True},
    }
    base.update(over)
    return base


class TestTodayFilterSource:
    def test_today_schedules_come_from_get_today_schedules(self, monkeypatch):
        """定时推送「今日课程」必须来自 get_today_schedules，而非 full_date==today 过滤。

        传入 full_date 非今天的全量 schedules：若仍用旧 full_date 口径，今日课表会被过滤空；
        修复后应直接采用 get_today_schedules() 的结果（星期+教学周口径，含爬虫课）。
        """
        rs = RuleService()
        rs._init_rules()
        # 只留 daily_schedule 规则，隔离其它规则对 today_schedules 的加工
        rs._rules = [r for r in rs._rules if r["id"] == "daily_schedule"]

        # 一门爬虫课：full_date 在过去（旧 full_date==today 口径会漏掉它），
        # 但 get_today_schedules（星期+教学周）会把它算作今日课。
        spider = _course("爬虫课A")
        spider["extra_info"]["full_date"] = "2026-09-01"
        sentinel = [spider]
        captured = {}

        monkeypatch.setattr(
            schedule_service, "get_today_schedules", lambda *a, **k: sentinel
        )

        def _cap(now, today_schedules, all_schedules, rule):
            captured["today"] = today_schedules
            captured["all"] = all_schedules
            return None

        monkeypatch.setattr(rs, "_check_daily_schedule", _cap)

        passed = [{"extra_info": {"full_date": "2099-01-01"}}]
        rs.check_conditions(datetime(2026, 10, 13, 7, 0, 0), passed)

        assert captured["today"] is sentinel, (
            "今日课程必须取自 get_today_schedules（星期+教学周口径）"
        )
        assert captured["all"] == passed, "all_schedules 仍是传入的全量课表"


class TestMergeRobustness:
    def test_rule_merge_skips_malformed_course(self):
        """rule._merge_courses_for_push：单门课 period_idx 非数字→跳过该课，不崩、不影响其余课。"""
        rs = RuleService()
        good = _course("正常课", periods=[1, 2], period_idx=1)
        # period_idx="1-2"：合并循环里 int("1-2") 会抛 ValueError（无兜底时整批崩）
        bad = _course("脏数据课", periods=None, period_idx="1-2")

        merged = rs._merge_courses_for_push([good, bad])

        names = [c["course_name"] for c in merged]
        assert "正常课" in names
        assert "脏数据课" not in names, "脏数据课应被跳过，而非让整批合并崩溃"

    def test_delivery_merge_skips_malformed_course(self):
        """delivery._merge_courses：同样单课程组兜底，一门脏课不崩掉整批推送。"""
        ds = DeliveryService()
        good = _course("正常课", periods=[1, 2], period_idx=1)
        bad = _course("脏数据课", periods=None, period_idx="1-2")

        merged = ds._merge_courses([good, bad])

        names = [c["course_name"] for c in merged]
        assert "正常课" in names
        assert "脏数据课" not in names
