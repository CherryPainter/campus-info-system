"""
课程爬虫与假期/教学周联动单元测试（v6.14.0）

验证 `app/tasks/executors.run_spider`（每日课表爬虫，7:00/13:00 各一次）与假期模式、
教学周判断的联动：是假期 / 不在教学周 → 跳过爬取（不浪费学校教务系统请求、不跑 Playwright）。

设计要点：
- run_spider 先判假期模式（holiday_service.is_active），再判 _is_in_teaching_week()；
  任一处命中即提前返回 False，不调用 run_spider_process（不真正爬取）。
- _is_in_teaching_week() 基于 course_weeks 真实日期范围；异常 fail-open 回退「继续爬」，
  不会因数据缺失静默漏爬。
- generate_weekly_course 的 teaching-week 判断已提前到 run_spider 调用之前，
  避免「假期里爬到空数据后被误判为爬虫失败发告警」。
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import holiday_service as hs_mod
from app.services import process_service as process_routes_mod
from app.tasks import executors as scheduler_mod
from app.tasks import scheduler_state


class _FakeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


@pytest.fixture
def reset_state():
    # run_spider 依赖模块级并发锁全局变量，测试前后复位
    scheduler_state._spider_running = False
    yield
    scheduler_state._spider_running = False


@pytest.fixture
def no_real_process(monkeypatch):
    # 拦截真实进程记录与真实爬虫子进程，避免触库/触网
    monkeypatch.setattr(process_routes_mod, "create_task_process", lambda *a, **k: 1)
    monkeypatch.setattr(process_routes_mod, "complete_task_process", lambda *a, **k: None)
    # 注意：scheduler 在模块顶层 `from app.services.spider_runner import run_spider_process`
    # 绑定了名字，必须 patch scheduler_mod.run_spider_process 才生效
    monkeypatch.setattr(scheduler_mod, "run_spider_process", lambda *a, **k: _raise_if_called())
    # 让脚本存在性检查通过（避免提前 return 干扰闸口断言）
    monkeypatch.setattr(scheduler_mod.os.path, "exists", lambda *a, **k: True)


def _raise_if_called():
    raise AssertionError("run_spider_process 不应被调用（闸口应已跳过）")


class TestRunSpiderHolidayLinkage:
    def test_skip_when_not_in_teaching_week(self, monkeypatch, reset_state, no_real_process):
        """不在教学周（暑假/寒假/假期）：run_spider 应跳过，不调用爬虫子进程。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: False)

        result = scheduler_mod.run_spider("cron")

        assert result is False

    def test_skip_when_holiday_active(self, monkeypatch, reset_state, no_real_process):
        """假期模式开启：run_spider 应跳过（与假期模式联动），不调用爬虫子进程。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (True, None))
        # 即便在教学周内，假期模式优先级更高
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: True)

        result = scheduler_mod.run_spider("cron")

        assert result is False

    def test_proceeds_when_in_teaching_week_and_no_holiday(
        self, monkeypatch, reset_state, no_real_process
    ):
        """在教学周内且未开假期模式：run_spider 应真正调用爬虫子进程。"""
        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: True)
        called = []
        monkeypatch.setattr(
            scheduler_mod,
            "run_spider_process",
            lambda *a, **k: (called.append(1) or _FakeResult(0, "ok")),
        )

        result = scheduler_mod.run_spider("cron")

        assert result is True
        assert called == [1], "在教学周内应真正执行爬取"

    def test_teaching_week_check_before_crawl_avoids_false_failure(self, monkeypatch, reset_state):
        """generate_weekly_course：不在教学周时不应调用 run_spider（避免爬空 + 误报失败）。"""
        import threading

        monkeypatch.setattr(hs_mod.holiday_service, "is_active", lambda: (False, None))
        monkeypatch.setattr(scheduler_mod, "_is_in_teaching_week", lambda: False)
        spider_called = []
        monkeypatch.setattr(
            scheduler_mod, "run_spider", lambda *a, **k: spider_called.append(1) or True
        )

        # 让周课表路径内的线程同步执行，便于断言
        class _SyncThread:
            def __init__(self, target=None, daemon=None, *a, **k):
                self._target = target

            def start(self):
                if self._target:
                    self._target()

            def join(self, *a, **k):
                pass

        monkeypatch.setattr(threading, "Thread", _SyncThread)

        scheduler_mod.generate_weekly_course()

        assert spider_called == [], "不在教学周时不应爬取，也不应误触发爬虫失败告警"
