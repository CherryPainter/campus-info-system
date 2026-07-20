"""
课程推送规则与假期/教学周联动单元测试（v6.14.0）

验证 `app/tasks/scheduler.check_push_rules`（每日课表推送规则引擎）与假期模式、
教学周判断的联动：是假期 / 不在教学周 → 跳过课程推送规则检查（不创建推送任务）。
与课程爬虫 `run_spider` 同源规则，确保假期里既不爬也不推。

设计要点：
- check_push_rules 先判假期模式（holiday_service.is_active），再判 _is_in_teaching_week()；
  任一处命中即提前返回，不调用 rule_service.check_conditions / task_service.create_tasks。
- _is_in_teaching_week() 基于 course_weeks 真实日期范围；异常 fail-open 回退「继续检查」，
  不会因数据缺失静默漏推。
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import holiday_service as hs_mod
from app.tasks import executors as scheduler_mod


class _Rec:
    def __init__(self):
        self.checks = 0
        self.creates = 0

    def check_conditions(self, *a, **k):
        self.checks += 1
        # 返回一个不触发「与爬虫 cron 重合延迟」分支的伪任务，确保 create_tasks 被调用
        return [{"rule_id": "daily_schedule", "trigger_condition": {}}]

    def create_tasks(self, *a, **k):
        self.creates += 1
        return []


@pytest.fixture
def push_rec(monkeypatch):
    rec = _Rec()
    # 隔离真实规则引擎与任务创建，仅记录是否被调用
    monkeypatch.setattr(scheduler_mod.schedule_service, "get_schedules", lambda: [])
    # is_data_ready 是只读 property，需在类级别替换描述符
    monkeypatch.setattr(type(scheduler_mod.schedule_service), "is_data_ready", True)
    monkeypatch.setattr(scheduler_mod.rule_service, "check_conditions", rec.check_conditions)
    monkeypatch.setattr(scheduler_mod.task_service, "create_tasks", rec.create_tasks)
    return rec


class TestCheckPushRulesHolidayLinkage:
    def test_skip_when_not_in_teaching_week(self, monkeypatch, push_rec):
        """不在教学周（暑假/寒假/假期）：check_push_rules 应跳过，不调用规则引擎。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: False)

        scheduler_mod.check_push_rules()

        assert push_rec.checks == 0
        assert push_rec.creates == 0

    def test_skip_when_holiday_active(self, monkeypatch, push_rec):
        """假期模式开启：check_push_rules 应跳过（与假期模式联动）。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (True, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: True)

        scheduler_mod.check_push_rules()

        assert push_rec.checks == 0
        assert push_rec.creates == 0

    def test_proceeds_when_in_teaching_week_and_no_holiday(self, monkeypatch, push_rec):
        """在教学周内且未开假期模式：check_push_rules 应正常调用规则引擎。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: True)

        scheduler_mod.check_push_rules()

        assert push_rec.checks == 1
        assert push_rec.creates == 1
