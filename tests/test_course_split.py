"""
课程大课拆分单元测试（v6.14.0）

覆盖 app.api.course_routes.split_course_to_big_classes：
- 单节 / 双节（≤1 组大课）：返回 1 条，不加 schedule_id 后缀
- 四节（跨 2 组大课）：拆成 2 条，schedule_id 加 #p1-2 / #p3-4 后缀，period_idx 取各组首节
- 无 periods 也无 period_idx：原样交给 apply_timetable_times（1 条）
- 仅有 period_idx（无 periods）：以 period_idx 当作节次（1 条）
- 时间按课表规定填充（building=教一, 第1节 -> 08:10~08:55）

不依赖 DB / Flask 上下文，直接调用纯函数。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.course_helpers import split_course_to_big_classes


def _course(**overrides):
    base = {
        "course_name": "高等数学",
        "extra_info": {"teacher": "王", "building": "教一", "classroom": "A101"},
    }
    base.update(overrides)
    return base


class TestSplitCourseToBigClasses:
    def test_single_period_one_result(self):
        c = _course(periods=[1])
        res = split_course_to_big_classes(c)
        assert len(res) == 1
        assert "schedule_id" not in res[0]  # 单组大课不加后缀

    def test_two_periods_one_chunk(self):
        c = _course(periods=[1, 2])
        res = split_course_to_big_classes(c)
        assert len(res) == 1
        assert res[0]["periods"] == [1, 2]

    def test_four_periods_split_into_two(self):
        c = _course(id="SCH-1", periods=[1, 2, 3, 4])
        res = split_course_to_big_classes(c)
        assert len(res) == 2
        # 第 1 组大课：1-2 节
        assert res[0]["period_idx"] == 1
        assert res[0]["periods"] == [1, 2]
        assert res[0]["schedule_id"] == "SCH-1#p1-2"
        # 第 2 组大课：3-4 节
        assert res[1]["period_idx"] == 3
        assert res[1]["periods"] == [3, 4]
        assert res[1]["schedule_id"] == "SCH-1#p3-4"

    def test_no_periods_no_pidx_returns_one(self):
        c = _course()
        res = split_course_to_big_classes(c)
        assert len(res) == 1

    def test_period_idx_only_used_as_section(self):
        c = _course(period_idx=3)  # 无 periods
        res = split_course_to_big_classes(c)
        assert len(res) == 1
        assert res[0]["period_idx"] == 3

    def test_times_filled_from_timetable(self):
        # building=教一 属于第一套时间表，第1节 -> 08:10~08:55
        c = _course(periods=[1])
        res = split_course_to_big_classes(c)
        assert res[0]["start_time"] == "08:10"
        assert res[0]["end_time"] == "08:55"

    def test_period_name_synced_to_chunks(self):
        c = _course(id="SCH-9", periods=[1, 2, 3, 4])
        res = split_course_to_big_classes(c)
        assert res[0]["period_name"] == "第一、二节"
        assert res[1]["period_name"] == "第三、四节"
