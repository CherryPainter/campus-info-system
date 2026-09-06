"""
课程爬虫纯解析函数单元测试（P2-2 抽取自 main.py）。

验证 app/cqie-course-timetable/parser_utils.py 的纯函数与抽取前
CourseTableTool 上的同名方法行为完全一致（仅从实例方法变为模块级函数，
不依赖 self / 浏览器状态）。

这些函数只依赖标准库 re，可在 Flask venv 直接运行，无需爬虫依赖环境。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPIDER_DIR = os.path.join(ROOT, "app", "cqie-course-timetable")
if SPIDER_DIR not in sys.path:
    sys.path.insert(0, SPIDER_DIR)

import parser_utils as pu


class TestUnquote:
    def test_strips_matching_double_quotes(self):
        assert pu._unquote('"hello"') == "hello"

    def test_strips_matching_single_quotes(self):
        assert pu._unquote("'world'") == "world"

    def test_leaves_unmatched_alone(self):
        assert pu._unquote("noquote") == "noquote"

    def test_leaves_inner_quotes(self):
        # 仅去掉两端成对引号，内部引号保留
        assert pu._unquote('"a\\"b"') == 'a\\"b'


class TestSplitJsArgs:
    def test_basic_split(self):
        assert pu._split_js_args("a,b,c") == ["a", "b", "c"]

    def test_respects_string_commas(self):
        assert pu._split_js_args('"a,b","c"') == ['"a,b"', '"c"']

    def test_respects_nested_parens(self):
        assert pu._split_js_args('foo(1,2),bar') == ["foo(1,2)", "bar"]

    def test_respects_brackets_inside_string(self):
        # 字符串内的括号与逗号不触发切分
        assert pu._split_js_args('"x(y,z)",k') == ['"x(y,z)"', "k"]


class TestWeeksBitmapRoundTrip:
    def test_contiguous_range(self):
        # 下标 0 不用；下标 1-16 为 1 -> "1-16"
        bitmap = "0" + "1" * 16 + "0" * 3
        assert pu._weeks_bitmap_to_str(bitmap) == "1-16"

    def test_gaps_and_single(self):
        # 第 2、5、7-9 周有课
        weeks = {2, 5, 7, 8, 9}
        bitmap = "".join("1" if i in weeks else "0" for i in range(20))
        assert pu._weeks_bitmap_to_str(bitmap) == "2 5 7-9"

    def test_empty(self):
        assert pu._weeks_bitmap_to_str("0" * 20) == ""

    def test_expand_inverts_bitmap(self):
        weeks = {1, 2, 3, 5, 7, 8, 9}
        bitmap = "".join("1" if i in weeks else "0" for i in range(20))
        s = pu._weeks_bitmap_to_str(bitmap)
        assert pu._expand_weeks_str(s) == weeks


class TestCountDistinctWeeks:
    def test_counts_union_of_weeks(self):
        activities = [
            {"weeks_str": "1-3"},
            {"weeks_str": "5 7-8"},
        ]
        assert pu._count_distinct_weeks(activities) == 6

    def test_empty_activities(self):
        assert pu._count_distinct_weeks([]) == 0


class TestParsePeriodNameRange:
    """回归测试：import 环节用 period_name 重推 periods 时，必须支持 '第X至Y节' 范围格式。

    历史 bug：综合实训（毕业设计）'第五至八节' 被旧解析器只截到 '第五'，
    落库 periods=[5] 而非 [5,6,7,8]，导致课表只显示 1 格。
    """

    def setup_method(self):
        from pipeline import parse_period_name

        self.parse = parse_period_name

    def test_range_to_format(self):
        assert self.parse("第五至八节", 1) == [5, 6, 7, 8]

    def test_range_first_to_fourth(self):
        assert self.parse("第一至四节", 1) == [1, 2, 3, 4]

    def test_range_eleven_to_twelve(self):
        assert self.parse("第十一至十二节", 1) == [11, 12]

    def test_range_ten_to_twelve(self):
        assert self.parse("第十至十二节", 1) == [10, 11, 12]

    def test_enum_still_works(self):
        assert self.parse("第一、二节", 1) == [1, 2]

    def test_single_still_works(self):
        assert self.parse("第五节", 5) == [5]

    def test_empty_falls_back_to_default(self):
        assert self.parse("", 3) == [3]
