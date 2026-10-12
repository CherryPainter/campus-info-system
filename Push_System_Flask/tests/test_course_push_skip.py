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
- is_data_ready=False（启动加载失败 / 刚部署无数据）时不再静默早退：check_push_rules
  会即时调用 get_schedules(force_reload=True) 尝试按需重载，重载成功则继续推送、
  失败才跳过，避免等 60s 定时器自愈期间漏推。见 TestCheckPushRulesDataReadyReload。
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


class TestCheckPushRulesDataReadyReload:
    """反向验证：is_data_ready=False 时 check_push_rules 必须按需即时重载，
    而非静默早退；移除 executors.py 的 force_reload 分支会使本测试变红。

    机制：初始 is_data_ready=False，模拟 get_schedules(force_reload=True) 触发一次
    重载，重载后是否就绪由 ready_after_reload 控制。验证两条路径：
    - 重载成功 → 继续调用规则引擎（不再漏推）；
    - 重载失败 → 仍跳过（安全，不误触发）。
    """

    def _setup(self, monkeypatch, ready_after_reload: bool):
        state = {"ready": False, "reload_called": False}

        # 把只读 property 替换为受 state 控制的动态描述符
        monkeypatch.setattr(
            type(scheduler_mod.schedule_service),
            "is_data_ready",
            property(lambda self: state["ready"]),
        )

        def fake_get_schedules(force_reload: bool = False):
            if force_reload:
                state["reload_called"] = True
                # 模拟一次重载并落地结果
                state["ready"] = ready_after_reload
                return [{"rule_id": "x"}] if ready_after_reload else []
            # 非强制：返回当前（初始为空）缓存
            return []

        monkeypatch.setattr(
            scheduler_mod.schedule_service, "get_schedules", fake_get_schedules
        )

        rec = _Rec()
        monkeypatch.setattr(scheduler_mod.rule_service, "check_conditions", rec.check_conditions)
        monkeypatch.setattr(scheduler_mod.task_service, "create_tasks", rec.create_tasks)
        return state, rec

    def test_reloads_and_proceeds_when_data_becomes_ready(self, monkeypatch):
        """is_data_ready 初始 False，但重载成功 → 应调用规则引擎（不再静默漏推）。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: True)

        state, rec = self._setup(monkeypatch, ready_after_reload=True)
        scheduler_mod.check_push_rules()

        assert state["reload_called"] is True, "is_data_ready=False 时应触发按需重载"
        assert rec.checks == 1, "重载成功后应继续调用规则引擎"
        assert rec.creates == 1

    def test_still_skips_when_reload_fails(self, monkeypatch):
        """is_data_ready 初始 False 且重载仍失败 → 仍跳过，不调用规则引擎（安全）。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: True)

        state, rec = self._setup(monkeypatch, ready_after_reload=False)
        scheduler_mod.check_push_rules()

        assert state["reload_called"] is True, "即使重载失败也应先尝试重载"
        assert rec.checks == 0, "重载仍失败时应跳过，不调用规则引擎"
        assert rec.creates == 0
