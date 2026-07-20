import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 导入配置和日志模块
from config import CONFIG
from logger import get_logger

# ---------------------------------------------------------------------------
# 教师映射解析（从源 HTML 实时解析，非写死）
# ---------------------------------------------------------------------------


def _unquote(s):
    """去掉字符串两端的引号"""
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _split_js_args(s):
    """按顶层逗号切分 JS 函数实参（忽略字符串内与括号嵌套的逗号）"""
    args = []
    depth = 0
    cur = ""
    in_str = False
    quote = ""
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            cur += c
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in ('"', "'"):
            in_str = True
            quote = c
            cur += c
        elif c == "(":
            depth += 1
            cur += c
        elif c == ")":
            depth -= 1
            cur += c
        elif c == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        args.append(cur.strip())
    return args


def extract_teacher_map_from_html(html):
    """
    从课表页 HTML 的 JavaScript 中解析「课程代码 → 授课教师」映射。

    数据来源：每个 ``new TaskActivity(...)`` 调用前最近的
    ``var actTeachers=[{name:"..."}]``。这是从教务系统页面**实时解析**的，
    并非代码里写死的常量。

    返回：
        dict: ``{course_code: teacher_str}``，例如 ``{'220110460.02': '罗强'}``
    """
    teacher_map = {}
    ta_iter = list(re.finditer(r"new\s+TaskActivity\((.*?)\)\s*;", html, re.DOTALL))
    for i, m in enumerate(ta_iter):
        args = _split_js_args(m.group(1))
        if len(args) < 7:
            continue
        # 课程代码：从 "188443(230111470.01)" 中取括号内内容
        code_raw = _unquote(args[2])
        code_m = re.search(r"\(([^)]+)\)", code_raw)
        code = code_m.group(1) if code_m else code_raw

        # 授课教师：取本次调用之前最近的 actTeachers 定义
        block_start = ta_iter[i - 1].end() if i > 0 else 0
        block = html[block_start : m.start()]
        act_blocks = re.findall(r"var\s+actTeachers\s*=\s*\[(.*?)\]\s*;", block, re.DOTALL)
        teacher = ""
        if act_blocks:
            names = re.findall(r'name\s*:\s*"([^"]*)"', act_blocks[-1])
            teacher = ",".join(names)

        if code and teacher:
            teacher_map[code] = teacher
    return teacher_map


class CourseProcessor:
    def __init__(self, course_data=None, teacher_map=None):
        # 初始化日志记录器
        self.logger = get_logger("processing")

        # 教师映射：{course_code: teacher}，由调用方从源 HTML 实时解析传入
        # （extract_teacher_map_from_html）。为 None 时不补全教师。
        self.teacher_map = teacher_map or {}

        # 获取配置
        processing_config = CONFIG["processing"]

        # 读取数据文件
        raw_data_dir = processing_config["raw_data_dir"]
        # 对于时间安排文件，使用相对于脚本所在目录的路径
        first_schedule_path = "first.json"
        second_schedule_path = "second.json"

        # 如果传入了 course_data 就用传入的，否则从文件读取
        if course_data is not None:
            self.course_data = course_data
        else:
            self.course_data = self._read_json(
                os.path.join("..", raw_data_dir, "course_table.json")
            )

        self.first_schedule = self._read_json(first_schedule_path)
        self.second_schedule = self._read_json(second_schedule_path)

        # 构建节次时间映射
        self.period_time_map = self._build_period_time_map()

        # 构建楼栋中文映射
        self.building_name_map = self._build_building_name_map()

        # 处理后的课程列表
        self.processed_courses = []

        # 最终输出结果
        self.final_courses = []

        self.logger.info("CourseProcessor初始化完成")

    def _read_json(self, file_path):
        """
        读取JSON文件
        """
        # 确保路径是相对于脚本所在目录的绝对路径
        abs_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), file_path))
        with open(abs_file_path, encoding="utf-8") as f:
            return json.load(f)

    def _build_period_time_map(self):
        """
        构建节次时间映射，key为节次名称（如"第一节"），value为对应的时间安排
        """
        period_time_map = {}

        # 添加第一套时间安排
        for slot in self.first_schedule["time_slots"]:
            period_time_map[slot["name"]] = {
                "start": slot["start"],
                "end": slot["end"],
                "schedule_type": "first",
                "period": slot["period"],
            }

        # 添加第二套时间安排
        for slot in self.second_schedule["time_slots"]:
            period_time_map[slot["name"]] = {
                "start": slot["start"],
                "end": slot["end"],
                "schedule_type": "second",
                "period": slot["period"],
            }

        return period_time_map

    # 中文数字 -> 阿拉伯数字（用于节次名「第一节」「第一、二节」等）
    CN_NUM = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
    }

    def _period_name_to_idx_periods(self, period_name):
        """
        从节次名反算起始节次序号与节次列表。

        例：
            第一节       -> (1, [1])
            第一、二节    -> (1, [1, 2])
            第一至四节    -> (1, [1, 2, 3, 4])

        这是渲染表格与周次过滤的唯一权威节次来源，
        不再依赖行号（行号会因表头行偏移而 +1 出错）。
        """
        if not period_name:
            return 1, [1]

        m = re.match(r"第(.+?)[、至](.+?)节", period_name)
        if m:
            a = self.CN_NUM.get(m.group(1), 0)
            b = self.CN_NUM.get(m.group(2), 0)
            if a and b and a <= b:
                return a, list(range(a, b + 1))

        m2 = re.match(r"第(.+?)节", period_name)
        if m2:
            a = self.CN_NUM.get(m2.group(1), 0)
            if a:
                return a, [a]

        return 1, [1]

    def _split_cell_courses(self, cell_text):
        """
        智能拆分一个单元格内堆叠的多门课程。

        eams 渲染表中同一节次不同周次可能上不同的课（如实训周上A、
        其他周上B）。bs4 get_text(strip=True) 会将多门课文本直接拼接，
        中间可能无任何分隔符。
        本方法通过定位每个「课程名(代码)」的位置逐门切分。
        """
        if not cell_text:
            return []

        # 快速路径：只有一个课程代码 → 无需拆分
        codes = re.findall(r"\([0-9]+\.[0-9]+\)", cell_text)
        if len(codes) <= 1:
            return [cell_text]

        # 多门课：找每个「(代码)」的匹配位置
        # 注意：课程名可能以数字结尾（如"劳动 4"），不能用 (?<![0-9.]) 排除
        code_positions = [m.start() for m in re.finditer(r"\([0-9]+\.[0-9]+\)", cell_text)]
        if len(code_positions) <= 1:
            return [cell_text]

        # 从每个 (代码) 位置往前回溯，找到课程名起始
        course_starts = []
        for pos in code_positions:
            start = pos
            # 往前跳过可能的空格/分号，然后继续往前找到上一个课程的结束边界
            while start > 0 and cell_text[start - 1] in (" ", "\t"):
                start -= 1
            # 再往前回溯课程名：跨过空格继续找真正的分隔符
            # （停止字符只保留分号和上一门课的右括号；空格不作为分隔符，
            #   否则 "体育 4(代码)" 会被在空格处截断成 "4(代码)"）
            while start > 0 and cell_text[start - 1] not in (";", "；", ")"):
                start -= 1
            course_starts.append(start)

        course_starts = sorted(set(course_starts))
        if len(course_starts) <= 1:
            return [cell_text]

        # 按位置切片
        courses = []
        for i, s in enumerate(course_starts):
            e = course_starts[i + 1] if i + 1 < len(course_starts) else len(cell_text)
            chunk = cell_text[s:e].strip()
            if chunk:
                courses.append(chunk)
        return courses if courses else [cell_text]

    def _extract_course_info(self, course_text):
        """
        从课程文本中提取课程信息
        格式示例：Vue.js前端框架应用(220110550.01) (罗强,罗明阳)\n([18]周,J060402机器学习技术实训室(校本部))
        格式示例：形势与政策 4(A01008008.98) (李亚腾)\n([12]周,J110301(校本部))
        格式示例：课程名(代码)\n([1-16]周,教室)  # 多周
        格式示例：课程名(代码)\n([2-5] [7-11单] [12-18]周,教室)  # 复杂周次
        """
        if not course_text:
            return None

        # 定义匹配模式 - 支持复杂周次格式
        # 周次部分：使用贪婪匹配 +(.+) 捕获到【最后一个】]周,
        # 因为周次串中可能包含多个 ]周 片段（如 [2-5] [7-11周] [12-18]周）
        pattern = (
            r"^(.*?)\(([A-Za-z0-9]+\.[0-9]+)\)(?:\s*\(([^)]*)\))?\s*\(\[(.+)\]周,(.*?)\(校本部\)\)"
        )
        match = re.match(pattern, course_text, re.DOTALL)

        if not match:
            # 尝试不带"校本部"的格式（同样使用贪婪匹配）
            pattern2 = r"^(.*?)\(([A-Za-z0-9]+\.[0-9]+)\)(?:\s*\(([^)]*)\))?\s*\(\[(.+)\]周,(.*?)\)"
            match = re.match(pattern2, course_text, re.DOTALL)

        if not match:
            return None

        course_name = match.group(1).strip()
        course_code = match.group(2).strip()  # 教务系统课程代码，如 "220110460.02"
        teacher = match.group(3).strip() if match.group(3) else ""
        weeks_str = match.group(4).strip()  # 可能是 "18" 或 "2-5 7-11单 12-18"
        classroom = match.group(5).strip()

        # 解析周次范围
        weeks_list = self._parse_weeks_string(weeks_str)

        return {
            "course_code": course_code,
            "course_name": course_name,
            "teacher": teacher,
            "weeks": weeks_str,  # 原始周次字符串
            "weeks_list": weeks_list,  # 解析后的周次列表
            "classroom": classroom,
            "week_number": weeks_list[0] if weeks_list else 1,  # 提取第一个周数作为默认
        }

    def _parse_weeks_string(self, weeks_str):
        """
        解析周次字符串，返回周次列表

        支持格式：
        - 单个周次: "18" -> [18]
        - 周次范围: "1-16" -> [1, 2, 3, ..., 16]
        - 多个范围: "2-5 7-11 12-18" -> [2, 3, 4, 5, 7, 8, 9, 10, 11, 12, ..., 18]
        - 单双周: "7-11单" -> [7, 9, 11], "2-4双" -> [2, 4]

        Args:
            weeks_str: 周次字符串

        Returns:
            list: 周次列表
        """
        if not weeks_str:
            return []

        weeks_list = []

        # 按空格分割多个周次范围
        week_ranges = weeks_str.split()

        for week_range in week_ranges:
            # 检查是否包含"单"或"双"
            is_odd = "单" in week_range
            is_even = "双" in week_range

            # 移除"单"、"双"、"周"、方括号等字符
            week_range = (
                week_range.replace("单", "").replace("双", "").replace("周", "").strip("[]")
            )

            if "-" in week_range:
                # 周次范围: "1-16"
                try:
                    start, end = week_range.split("-")
                    start_week = int(start.strip())
                    end_week = int(end.strip())

                    # 根据单双周过滤
                    for week in range(start_week, end_week + 1):
                        if is_odd and week % 2 == 0:
                            continue  # 跳过双周
                        if is_even and week % 2 == 1:
                            continue  # 跳过单周
                        weeks_list.append(week)
                except (ValueError, IndexError):
                    # 解析失败，跳过
                    continue
            else:
                # 单个周次: "18"
                try:
                    weeks_list.append(int(week_range))
                except ValueError:
                    # 解析失败，跳过
                    continue

        return sorted(set(weeks_list))  # 去重并排序

    def _build_building_name_map(self):
        """
        构建楼栋中文映射
        从first.json和second.json中提取楼栋映射关系
        """
        building_map = {}
        name_to_code_map = {}

        # 处理第一套时间安排的楼栋
        for location in self.first_schedule.get("locations", []):
            if isinstance(location, dict):
                name = location.get("name", "")
                code = location.get("code", "")
                if name and code:
                    building_map[code] = name
                    name_to_code_map[name] = code

        # 处理第二套时间安排的楼栋
        for location in self.second_schedule.get("locations", []):
            if isinstance(location, dict):
                name = location.get("name", "")
                code = location.get("code", "")
                if name and code:
                    building_map[code] = name
                    name_to_code_map[name] = code

        # 保存名称到代码的映射，供后续使用
        self.name_to_code_map = name_to_code_map

        return building_map

    def _parse_classroom(self, classroom):
        """
        解析教室信息，提取楼栋和教室名称
        示例：J060402机器学习技术实训室 -> 楼栋: J06, 教室: 402机器学习技术实训室
        示例：讯达楼905计算机网络基础实训室 -> 楼栋: J14, 教室: 905计算机网络基础实训室
        """
        if not classroom:
            return "", ""

        # 使用正则表达式提取楼栋代码
        import re

        # 模式1：匹配英文代码开头的楼栋（如J06、S01等）
        code_pattern = re.match(r"^([A-Z]\d{2})", classroom)
        if code_pattern:
            building_code = code_pattern.group(1)
            classroom_name = classroom[3:]
            # 去掉教室名称开头的0
            if classroom_name and classroom_name.startswith("0"):
                classroom_name = classroom_name[1:]
            return building_code, classroom_name

        # 模式2：匹配中文楼栋名称（如讯达楼、理工楼等）
        chinese_pattern = re.match(r"^([\u4e00-\u9fa5]+楼)", classroom)
        if chinese_pattern and hasattr(self, "name_to_code_map"):
            building_name = chinese_pattern.group(1)
            building_code = self.name_to_code_map.get(building_name, "")
            classroom_name = classroom[len(building_name) :]
            return building_code, classroom_name

        # 默认情况：使用原逻辑
        building_code = classroom[:3] if len(classroom) >= 3 else ""
        classroom_name = classroom[3:] if len(classroom) > 3 else classroom
        if classroom_name and classroom_name.startswith("0"):
            classroom_name = classroom_name[1:]

        return building_code, classroom_name

    def _calculate_date(self, week_day, week_number):
        """
        根据星期几和周数计算具体日期
        逻辑：
        1. 计算本周一的日期
        2. 根据星期几计算具体日期
        3. 周日时，显示下一周的课程
        """
        # 定义星期几到天数的映射
        week_day_map = {
            "星期一": 0,
            "星期二": 1,
            "星期三": 2,
            "星期四": 3,
            "星期五": 4,
            "星期六": 5,
            "星期日": 6,
        }

        # 获取当前日期
        today = datetime.now()

        # 计算本周一的日期
        # today.weekday() 返回0-6，0是周一，6是周日
        days_since_monday = today.weekday()

        # 周日特殊处理：周日显示的是下一周的课表
        if days_since_monday == 6:
            monday_date = today + timedelta(days=1)
        else:
            monday_date = today - timedelta(days=days_since_monday)

        # 获取当前课程的星期几对应的数字
        course_weekday = week_day_map.get(week_day, 0)

        # 计算具体日期
        course_date = monday_date + timedelta(days=course_weekday)

        # 格式化为YYYY-MM-DD
        return course_date.strftime("%Y-%m-%d")

    def _get_schedule_type(self, building):
        """
        根据楼栋确定使用哪套时间安排
        """
        # 第一套时间安排的楼栋（仅使用代码）
        first_buildings = ["S01", "S02", "J01", "J04", "J14", "J15"]

        # 第二套时间安排的楼栋（仅使用代码）
        second_buildings = ["J02", "J03", "J06", "J10", "J11"]

        if building in first_buildings:
            return "first"
        elif building in second_buildings:
            return "second"
        else:
            # 默认使用第一套
            return "first"

    def _parse_time(self, time_str):
        """
        解析时间字符串为datetime对象
        """
        return datetime.strptime(time_str, "%H:%M")

    def _format_time(self, time_obj):
        """
        将datetime对象格式化为时间字符串
        """
        return time_obj.strftime("%H:%M")

    def process_courses(self):
        """
        处理课程数据，转换为结构化格式
        """
        headers = self.course_data["headers"]
        rows = self.course_data["rows"]

        # 遍历所有行（节次）
        for _row_idx, row in enumerate(rows):
            # 跳过无效行
            if len(row) == 0:
                continue

            period_name = row[0]  # 节次名称，如"第一节"

            # 跳过无效的节次名称
            if (
                not period_name
                or period_name in ["课程列表：", "打印预览", "实践专周课程列表:"]
                or period_name.isdigit()
            ):
                continue

            # 遍历每一天（从星期一到星期日）
            for day_idx, course_text in enumerate(row[1:]):
                if not course_text.strip():
                    continue

                # 一个单元格可能堆叠多门课（不同周次共用同一节次），
                # 用智能拆分按「课程名(代码)([」模式逐门切分
                for cell_part in self._split_cell_courses(course_text):
                    cell_part = cell_part.strip()
                    if not cell_part:
                        continue

                    # 提取课程信息
                    course_info = self._extract_course_info(cell_part)
                    if not course_info:
                        continue

                    # 解析教室信息
                    building, classroom_name = self._parse_classroom(course_info["classroom"])

                    # 确定星期几，确保索引在范围内
                    if day_idx + 1 < len(headers):
                        week_day = headers[day_idx + 1]
                    else:
                        # 跳过超出范围的列
                        continue

                    # 根据楼栋确定时间安排类型
                    schedule_type = self._get_schedule_type(building)

                    # 获取时间安排 - 根据楼栋确定的时间安排类型
                    start_time = ""
                    end_time = ""

                    # 遍历时间安排，找到对应节次和时间安排类型的时间
                    for slot in self.first_schedule["time_slots"]:
                        if slot["name"] == period_name and schedule_type == "first":
                            start_time = slot["start"]
                            end_time = slot["end"]
                            break

                    if not start_time:
                        for slot in self.second_schedule["time_slots"]:
                            if slot["name"] == period_name and schedule_type == "second":
                                start_time = slot["start"]
                                end_time = slot["end"]
                                break

                    # 构建课程对象
                    period_idx, periods = self._period_name_to_idx_periods(period_name)
                    course = {
                        "week_day": week_day,
                        "period_name": period_name,
                        "period_idx": period_idx,
                        "periods": periods,
                        "course_code": course_info.get("course_code", ""),
                        "course_name": course_info["course_name"],
                        "teacher": course_info["teacher"],
                        "building": building,
                        "classroom": classroom_name,
                        "weeks": course_info["weeks"],
                        "weeks_list": course_info.get("weeks_list", []),
                        "week_number": course_info["week_number"],
                        "start_time": start_time,
                        "end_time": end_time,
                    }

                    self.processed_courses.append(course)

    def _merge_teacher_from_map(self):
        """
        用 teacher_map（按 course_code）补全教师字段。

        仅当课程自身教师为空、且 course_code 命中映射时才写入；
        映射中不存在的课程保持空字符串（不写死、不臆造教师）。
        """
        if not self.teacher_map:
            return
        filled = 0
        for course in self.processed_courses:
            if not course.get("teacher") and course.get("course_code") in self.teacher_map:
                course["teacher"] = self.teacher_map[course["course_code"]]
                filled += 1
        if filled:
            self.logger.info(f"已从源 HTML 教师映射补全 {filled} 条课程的教师字段")

    def merge_consecutive_courses(self):
        """
        合并连续的相同课程（两节小课为一节大课，支持多组连堂）

        合并规则：
        - 每两节小课合并为一节大课（如第1-2节、第3-4节）
        - 大课连堂时（如1-4节同一门课）进一步合并为一个大时间段
        - 时间直接使用课表规定的时间，不做“提前10分钟下课”之类的调整
        """
        # 按星期和节次排序
        self.processed_courses.sort(key=lambda x: (x["week_day"], x["period_idx"]))

        i = 0
        while i < len(self.processed_courses):
            # 尝试向后查找所有连续相同的课程
            current_course = self.processed_courses[i]
            merge_count = 1  # 至少包含当前课程自身
            j = i + 1

            while j < len(self.processed_courses):
                next_course = self.processed_courses[j]
                # 判断是否为连续且相同的课程
                is_consecutive = (
                    current_course["week_day"] == next_course["week_day"]
                    and current_course["course_name"] == next_course["course_name"]
                    and current_course["teacher"] == next_course["teacher"]
                    and current_course["building"] == next_course["building"]
                    and current_course["classroom"] == next_course["classroom"]
                    and current_course["weeks"] == next_course["weeks"]
                    and self.processed_courses[j - 1]["period_idx"] + 1 == next_course["period_idx"]
                )
                if not is_consecutive:
                    break
                merge_count += 1
                j += 1

            # 构建合并后的课程
            merged_course = current_course.copy()
            last_course = self.processed_courses[i + merge_count - 1]
            merged_course["end_time"] = last_course["end_time"]

            # 构建节次名称（如"第一、二节"或"第一至四节"）
            first_num = current_course["period_name"][1:-1]
            if merge_count == 2:
                last_num = last_course["period_name"][1:-1]
                merged_course["period_name"] = f"第{first_num}、{last_num}节"
            elif merge_count > 2:
                last_num = last_course["period_name"][1:-1]
                merged_course["period_name"] = f"第{first_num}至{last_num}节"
            # merge_count == 1 时保持原名

            # 依据最终节次名重新计算权威的 period_idx 与 periods
            # （不再依赖 process_courses 里的行号，避免表头行导致的 +1 偏移）
            mp_idx, mp_periods = self._period_name_to_idx_periods(merged_course["period_name"])
            merged_course["period_idx"] = mp_idx
            merged_course["periods"] = mp_periods

            # 计算日期
            merged_course["date"] = self._calculate_date(
                merged_course["week_day"], merged_course["week_number"]
            )

            # 注：不再对下课时间做“提前10分钟”之类的调整，直接使用课表规定的时间
            # （用户要求：通知只推课表规定的时间，不要沿用什么减10分钟）

            # 添加合并后的课程
            self.final_courses.append(merged_course)

            # 跳过已合并的课程
            i += merge_count

        # 按星期顺序和节次排序
        week_order = {
            "星期一": 0,
            "星期二": 1,
            "星期三": 2,
            "星期四": 3,
            "星期五": 4,
            "星期六": 5,
            "星期日": 6,
        }

        self.final_courses.sort(key=lambda x: (week_order.get(x["week_day"], 7), x["period_idx"]))

    def _backup_file(self, file_path):
        """
        备份文件到历史目录

        Args:
            file_path (str): 要备份的文件路径
        """
        if os.path.exists(file_path):
            # 确定文件类型（images或processed）
            file_dir = os.path.dirname(file_path)
            if "images" in file_dir:
                file_type = "images"
            elif "processed" in file_dir:
                file_type = "processed"
            else:
                file_type = "other"

            # 从配置中获取历史目录
            processing_config = CONFIG["processing"]
            history_dir = processing_config["history_dir"]

            # 创建历史目录结构，按时间戳归档
            base_history_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", history_dir)
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            history_dir = os.path.join(base_history_dir, file_type, timestamp)
            os.makedirs(history_dir, exist_ok=True)

            # 生成备份文件名
            file_name = os.path.basename(file_path)
            backup_file_path = os.path.join(history_dir, file_name)

            # 移动文件到历史目录
            try:
                os.rename(file_path, backup_file_path)
                self.logger.info(f"历史文件已备份到: {backup_file_path}")
            except Exception as e:
                self.logger.error(f"备份文件失败: {e}")

    def _backup_all_old_files(self, output_dir, new_filenames):
        """
        备份目录中所有旧文件到历史目录

        Args:
            output_dir (str): 输出目录
            new_filenames (list): 新生成的文件文件名列表
        """
        # 确保目录存在
        if not os.path.exists(output_dir):
            self.logger.debug(f"输出目录不存在，跳过备份: {output_dir}")
            return

        # 遍历目录中的所有文件
        try:
            for file_name in os.listdir(output_dir):
                # 处理所有文件
                file_path = os.path.join(output_dir, file_name)
                self._backup_file(file_path)
        except Exception as e:
            self.logger.error(f"遍历备份文件时出错: {e}")

    def output_csv(self, output_dir):
        """
        输出CSV文件

        Args:
            output_dir (str): 输出目录
        """
        # 构建文件路径
        file_path = os.path.join(output_dir, "processed_course_table.csv")

        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

        headers = [
            "星期",
            "节次",
            "课程代码",
            "课程",
            "教师",
            "楼栋",
            "教室",
            "周次",
            "开始时间",
            "结束时间",
            "日期",
        ]

        # 获取周数，使用第一个课程的周数
        week_number = self.final_courses[0]["week_number"] if self.final_courses else 1

        # 生成带有周数的文件名
        base_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        name_without_ext = os.path.splitext(file_name)[0]
        ext = os.path.splitext(file_name)[1]
        week_file_path = os.path.join(base_dir, f"{name_without_ext}_week{week_number}{ext}")

        # 保存带有周数的文件
        try:
            with open(week_file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

                for course in self.final_courses:
                    # 转换楼栋代码为中文名称
                    building_code = course["building"]
                    building_name = self.building_name_map.get(building_code, building_code)

                    row = [
                        course["week_day"],
                        course["period_name"],
                        course.get("course_code", ""),
                        course["course_name"],
                        course["teacher"],
                        building_name,
                        course["classroom"],
                        course["weeks"],
                        course["start_time"],
                        course["end_time"],
                        course.get("date", ""),
                    ]
                    writer.writerow(row)

            self.logger.info(f"CSV文件已输出: {week_file_path}")
        except Exception as e:
            self.logger.error(f"保存CSV文件失败: {e}")

        # 同时保存默认文件名，以便兼容现有代码
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

                for course in self.final_courses:
                    # 转换楼栋代码为中文名称
                    building_code = course["building"]
                    building_name = self.building_name_map.get(building_code, building_code)

                    row = [
                        course["week_day"],
                        course["period_name"],
                        course.get("course_code", ""),
                        course["course_name"],
                        course["teacher"],
                        building_name,
                        course["classroom"],
                        course["weeks"],
                        course["start_time"],
                        course["end_time"],
                        course.get("date", ""),
                    ]
                    writer.writerow(row)

            self.logger.info(f"CSV文件已输出: {file_path}")
        except Exception as e:
            self.logger.error(f"保存CSV文件失败: {e}")

    def output_json(self, output_dir):
        """
        输出JSON文件

        Args:
            output_dir (str): 输出目录
        """
        # 构建文件路径
        file_path = os.path.join(output_dir, "processed_course_table.json")

        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

        # 获取周数，使用第一个课程的周数
        week_number = self.final_courses[0]["week_number"] if self.final_courses else 1

        # 生成带有周数的文件名
        base_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        name_without_ext = os.path.splitext(file_name)[0]
        ext = os.path.splitext(file_name)[1]
        week_file_path = os.path.join(base_dir, f"{name_without_ext}_week{week_number}{ext}")

        # 转换楼栋代码为中文名称
        courses_with_chinese_building = []
        for course in self.final_courses:
            course_copy = course.copy()
            building_code = course_copy["building"]
            building_name = self.building_name_map.get(building_code, building_code)
            course_copy["building"] = building_name
            courses_with_chinese_building.append(course_copy)

        # 构建带周数标记的 JSON 对象
        json_data = {
            "week_number": week_number,
            "week_str": f"第{week_number}周",
            "total_courses": len(courses_with_chinese_building),
            "courses": courses_with_chinese_building,
        }

        # 保存带有周数的文件
        with open(week_file_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"JSON文件已输出: {week_file_path}")

        # 同时保存默认文件名，以便兼容现有代码
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"JSON文件已输出: {file_path}")

    def run(self, course_data=None, raw_dir=None, processed_dir=None):
        """
        执行完整的处理流程

        Args:
            course_data (dict, optional): 课程数据
            raw_dir (str, optional): 原始数据目录
            processed_dir (str, optional): 处理后数据目录

        Returns:
            bool: 处理是否成功
        """
        # 如果传入了新数据，就用新数据
        if course_data is not None:
            self.course_data = course_data

        self.logger.info("开始处理课程数据...")

        # 处理课程
        self.process_courses()

        # 用源 HTML 解析出的教师映射补全教师字段（按 course_code，非写死）
        self._merge_teacher_from_map()

        # 合并连续课程
        self.merge_consecutive_courses()

        if not processed_dir:
            # 从配置中获取处理后数据目录
            processing_config = CONFIG["processing"]
            processed_data_dir = processing_config["processed_data_dir"]
            processed_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", processed_data_dir)
            )

        # 获取周数
        week_number = self.final_courses[0]["week_number"] if self.final_courses else 1

        # 生成所有新文件名
        new_filenames = [
            "processed_course_table.csv",
            f"processed_course_table_week{week_number}.csv",
            "processed_course_table.json",
            f"processed_course_table_week{week_number}.json",
        ]

        # 确保输出目录存在
        os.makedirs(processed_dir, exist_ok=True)

        # 先备份所有旧文件
        self._backup_all_old_files(processed_dir, new_filenames)

        # 输出结果
        self.output_csv(processed_dir)
        self.output_json(processed_dir)

        self.logger.info("课程数据处理完成！")
        return True


if __name__ == "__main__":
    processor = CourseProcessor()
    processor.run()
