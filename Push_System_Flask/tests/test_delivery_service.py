"""
推送执行服务（推送链核心）单元测试（v6.14.0）

覆盖 delivery_service.DeliveryService 的关键决策与纯逻辑：
1) _get_adapter_name_for_task：任务类型 -> adapter 路由（课表/天气/电量/系统/默认）
2) _prepare_data：模板数据准备（课程提醒 / 每日课表合并）
3) _merge_courses：同课程多节次合并为大课
4) _process_pending_tasks：
   - 假期激活且非 force_send -> 整批静音（status=skipped，不调 adapter）
   - force_send=True -> 豁免假期静音，照常推送
   - 正常消息任务 -> adapter.send 成功 -> status=success，并建/更执行历史
   - 无对应 adapter -> status=failed（不抛异常，fail-safe）

隔离方式：直接 monkeypatch delivery_service 模块级的 task_service /
holiday_service / adapter_service / template_service / uts 引用，
不依赖真实 DB、Redis、企业微信适配器。
"""

import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import delivery_service as ds_mod
from app.services.delivery_service import DeliveryService


# ----------------------------------------------------------------------
# 协作假对象（隔离真实 DB / 适配器 / 企业微信）
# ----------------------------------------------------------------------
class _FakePeriod:
    name = "2026年暑假"
    start_date = date(2026, 7, 1)
    end_date = date(2026, 8, 31)


class _FakeHoliday:
    def __init__(self, active=False, period=None):
        self._active = active
        self._period = period

    def is_active(self):
        return (self._active, self._period)


class _FakeTaskService:
    def __init__(self):
        self.pending = []
        self.updates = []

    def get_pending_tasks(self, limit=100):
        return self.pending

    def update_status(self, task_id, status, result=None):
        self.updates.append((task_id, status))


class _Adapter:
    """被 get_adapter 返回的 adapter 假对象，带 send / send_image。"""

    def __init__(self, success=True):
        self._success = success
        self.sent = []
        self.images = []

    def send(self, message):
        self.sent.append(message)
        return {"success": self._success}

    def send_image(self, path):
        self.images.append(path)
        return {"success": self._success}


class _AdapterService:
    def __init__(self, instance):
        self._instance = instance

    def get_adapter(self, name):
        return self._instance


class _FakeTemplate:
    def render(self, template_id, data):
        return f"rendered:{template_id}"


class _FakeUTS:
    def __init__(self):
        self.created = []
        self.completed = []

    def create_process(self, *a, **k):
        self.created.append((a, k))
        return 99

    def complete_process(self, *a, **k):
        self.completed.append((a, k))


def _install_fakes(monkeypatch, *, holiday_active=False, adapter_instance=...,
                   adapter_success=True):
    """把所有外部依赖替换为假对象，返回 (task, holiday, adapter_obj, template, uts)。

    adapter_instance 用哨兵区分：默认(...)建一个可用假 adapter；
    显式传 None 表示"无对应 adapter"（模拟 get_adapter 返回 None）。
    """
    task = _FakeTaskService()
    holiday = _FakeHoliday(active=holiday_active, period=_FakePeriod())
    adapter_obj = _Adapter(success=adapter_success) if adapter_instance is ... else adapter_instance
    adapter_svc = _AdapterService(adapter_obj)
    template = _FakeTemplate()
    uts = _FakeUTS()
    monkeypatch.setattr(ds_mod, "task_service", task)
    monkeypatch.setattr(ds_mod, "holiday_service", holiday)
    monkeypatch.setattr(ds_mod, "adapter_service", adapter_svc)
    monkeypatch.setattr(ds_mod, "template_service", template)
    monkeypatch.setattr(ds_mod, "uts", uts)
    return task, holiday, adapter_obj, template, uts


def _new_service():
    ds = DeliveryService()
    ds._running = True  # _process_pending_tasks 在 _running 时才真正工作
    return ds


# ----------------------------------------------------------------------
# 1) adapter 路由
# ----------------------------------------------------------------------
class TestAdapterRouting:
    def test_course_related_routes_to_course(self):
        ds = _new_service()
        for task_type, sub in [
            ("schedule", "daily"),
            ("course", "daily_no_class"),
            ("image", "weekly_image"),
            ("schedule", "course_reminder"),
            ("schedule", "before_end_class"),
            ("schedule", "after_class"),
        ]:
            task = {"task_type": task_type, "sub_type": sub}
            assert ds._get_adapter_name_for_task(task) == "course"

    def test_weather_electricity_system_routes(self):
        ds = _new_service()
        assert ds._get_adapter_name_for_task({"task_type": "weather"}) == "weather"
        assert ds._get_adapter_name_for_task({"task_type": "electricity"}) == "electricity"
        assert ds._get_adapter_name_for_task({"task_type": "system"}) == "system"
        assert ds._get_adapter_name_for_task({"task_type": "spider"}) == "system"

    def test_unknown_task_type_defaults_to_course(self):
        ds = _new_service()
        assert ds._get_adapter_name_for_task({"task_type": "anything"}) == "course"


# ----------------------------------------------------------------------
# 2) 模板数据准备
# ----------------------------------------------------------------------
class TestPrepareData:
    def test_course_reminder_builds_data(self):
        ds = _new_service()
        task = {
            "task_type": "course_reminder",
            "sub_type": "before_class",
            "course_info": {
                "course_name": "高等数学",
                "start_time": "08:10",
                "end_time": "08:55",
                "extra_info": {"teacher": "王教授", "building": "教一", "classroom": "A101"},
            },
            "trigger_condition": {"minutes_before": 10, "minutes_before_end": 5},
            "next_course_info": {
                "course_name": "线性代数",
                "start_time": "10:10",
                "end_time": "10:55",
                "extra_info": {"building": "教一", "classroom": "B202"},
            },
        }
        data = ds._prepare_data(task)
        assert data["course_name"] == "高等数学"
        assert data["teacher"] == "王教授"
        assert data["classroom"] == "教一A101"  # building + classroom 拼接
        assert data["minutes_before"] == 10
        assert data["minutes_before_end"] == 5
        assert "线性代数" in data["next_course_block"]

    def test_schedule_summary_merges_and_lists(self):
        ds = _new_service()
        task = {
            "task_type": "schedule_summary",
            "sub_type": "daily",
            "course_info": [
                {
                    "course_name": "高等数学",
                    "start_time": "08:10",
                    "end_time": "08:55",
                    "period_idx": 1,
                    "periods": [1],
                    "extra_info": {"teacher": "王", "building": "教一", "classroom": "A101"},
                },
                {
                    "course_name": "大学物理",
                    "start_time": "10:10",
                    "end_time": "10:55",
                    "period_idx": 3,
                    "periods": [3],
                    "extra_info": {"teacher": "李", "building": "教一", "classroom": "B202"},
                },
            ],
        }
        data = ds._prepare_data(task)
        assert "高等数学" in data["courses_list"]
        assert "大学物理" in data["courses_list"]


# ----------------------------------------------------------------------
# 3) 课程合并
# ----------------------------------------------------------------------
class TestMergeCourses:
    def test_same_course_merges_into_two_big_classes(self):
        """同名同师同教室、节次 [1,2] 与 [3,4] 两记录 -> 合并为 [1,2,3,4] -> 拆 2 条大课。"""
        ds = _new_service()
        courses = [
            {
                "course_name": "高等数学",
                "period_idx": 1,
                "periods": [1, 2],
                "period_name": "第一、二节",
                "extra_info": {"teacher": "王", "building": "教一", "classroom": "A101"},
            },
            {
                "course_name": "高等数学",
                "period_idx": 3,
                "periods": [3, 4],
                "period_name": "第三、四节",
                "extra_info": {"teacher": "王", "building": "教一", "classroom": "A101"},
            },
        ]
        merged = ds._merge_courses(courses)
        assert len(merged) == 2
        assert all(c["course_name"] == "高等数学" for c in merged)


# ----------------------------------------------------------------------
# 4) _process_pending_tasks 主流程
# ----------------------------------------------------------------------
class TestProcessPendingTasks:
    def test_holiday_mute_skips_without_sending(self, monkeypatch):
        """假期激活且非 force_send：任务被静音跳过，不调用任何 adapter。"""
        task, _, adapter_obj, _, uts = _install_fakes(monkeypatch, holiday_active=True)
        task.pending = [
            {
                "task_id": "t1",
                "task_type": "schedule",
                "sub_type": "daily",
                "course_info": [],
                "force_send": False,
            }
        ]
        ds = _new_service()
        ds._process_pending_tasks()

        assert ("t1", "skipped") in task.updates
        assert adapter_obj.sent == [], "假期静音不应调用 adapter.send"
        assert uts.created == [], "假期静音不应创建执行历史"

    def test_force_send_bypasses_holiday_mute(self, monkeypatch):
        """force_send=True 时即便假期激活也照常推送。"""
        task, _, adapter_obj, _, _ = _install_fakes(monkeypatch, holiday_active=True)
        task.pending = [
            {
                "task_id": "t2",
                "task_type": "weather",
                "sub_type": "daily",
                "course_info": {},
                "force_send": True,
            }
        ]
        ds = _new_service()
        ds._process_pending_tasks()

        assert ("t2", "success") in task.updates
        assert adapter_obj.sent, "force_send 豁免，正常发送"

    def test_normal_message_task_succeeds(self, monkeypatch):
        """正常消息任务：adapter.send 成功，标记 success 并写入执行历史。"""
        task, _, adapter_obj, _, uts = _install_fakes(monkeypatch, holiday_active=False)
        task.pending = [
            {"task_id": "t3", "task_type": "weather", "sub_type": "daily", "course_info": {}}
        ]
        ds = _new_service()
        ds._process_pending_tasks()

        assert ("t3", "success") in task.updates
        assert adapter_obj.sent == ["rendered:weather_daily"]
        assert uts.created, "应创建执行历史记录"

    def test_missing_adapter_marks_failed_not_throws(self, monkeypatch):
        """无对应 adapter：标记 failed，且不抛异常（fail-safe）。"""
        task, _, _, _, _ = _install_fakes(monkeypatch, holiday_active=False, adapter_instance=None)
        task.pending = [
            {"task_id": "t4", "task_type": "weather", "sub_type": "daily", "course_info": {}}
        ]
        ds = _new_service()
        ds._process_pending_tasks()  # 不应抛异常

        assert ("t4", "failed") in task.updates

    def test_empty_pending_is_noop(self, monkeypatch):
        task, _, adapter_obj, _, uts = _install_fakes(monkeypatch, holiday_active=False)
        task.pending = []
        ds = _new_service()
        ds._process_pending_tasks()
        assert task.updates == []
        assert adapter_obj.sent == []
        assert uts.created == []
