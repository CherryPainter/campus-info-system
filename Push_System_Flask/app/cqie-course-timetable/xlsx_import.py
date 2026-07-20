"""
从教务系统导出的「全部」课表 xlsx 解析课程数据。

为什么需要它：
  eams 网页端「全部」视图（及按周视图）在渲染时会**漏掉部分课程实例**
  （实测 物联网/小程序端开发 在网页端只渲染 6 个实例，而 xlsx 导出有 9 个，
   其中第 19 周网页端漏了 3 个）。而 xlsx 是**服务端计算后导出**的，数据完整。
  因此用 xlsx 作为整学期课程的权威数据源，再从网页爬取的 TaskActivity 中
  补全教师信息（xlsx 本身不含教师）。

xlsx 结构（已核对）：
  - 第 3 行：表头，A3=节次/周次，B3..H3 = 星期一..星期日
  - A 列：节次名，A4=第一节 .. A15=第十二节（共 12 节）
  - B..H 列（4..15 行）：课程单元格，文本形如
       课程名(代码)\n([周次]周,教室(校本部))
    一个单元格可能堆叠多门课（用换行分隔）。
"""

import re
import xml.etree.ElementTree as ET
import zipfile

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DAY_COLS = ["B", "C", "D", "E", "F", "G", "H"]  # 星期一..星期日

# 节次行映射：行号 -> period_idx(从1起)
_PERIOD_ROWS = {
    4: 1,
    5: 2,
    6: 3,
    7: 4,
    8: 5,
    9: 6,
    10: 7,
    11: 8,
    12: 9,
    13: 10,
    14: 11,
    15: 12,
}


def _col_letter(ref):
    return re.match(r"([A-Z]+)", ref).group(1)


def _read_sheet_cells(path):
    """读取 xlsx 工作表全部单元格，返回 {(row,col): text}。兼容 inlineStr（无 sharedStrings）。"""
    z = zipfile.ZipFile(path)
    # 找到 sheet1
    sheet_name = "xl/worksheets/sheet1.xml"
    if sheet_name not in z.namelist():
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
        sheet_name = sheets[0]
    sx = z.read(sheet_name).decode("utf-8", "ignore")
    root = ET.fromstring(sx)
    cells = {}
    for c in root.iter(_NS + "c"):
        ref = c.get("r")
        if not ref:
            continue
        t = c.get("t")
        val = None
        if t == "inlineStr":
            is_el = c.find(_NS + "is")
            if is_el is not None:
                val = "".join(t2.text or "" for t2 in is_el.iter(_NS + "t"))
        else:
            v = c.find(_NS + "v")
            if v is not None:
                val = v.text
        if val is not None:
            cells[ref] = val
    return cells


def _expand_weeks(weeks_bracket):
    """
    将周次标注展开为整数列表。支持：
      [2-5]            -> 2,3,4,5
      [7-11单]         -> 7,9,11
      [12-18]          -> 12..18
      [2-4双]          -> 2,4
      [2-5] [7-11单] [12-18]  -> 合并
    """
    weeks = set()
    # 去掉最外层括号，按 ']' 切分各段
    segs = re.findall(r"\[([^\]]*)\]", weeks_bracket)
    if not segs:
        segs = [weeks_bracket]
    for seg in segs:
        # 每段可能含 单/双 标记
        parity = None
        m_par = re.search(r"(单|双)", seg)
        if m_par:
            parity = m_par.group(1)
            seg = seg.replace("单", "").replace("双", "")
        for part in seg.split():
            if "-" in part:
                mm = re.match(r"(\d+)-(\d+)", part)
                if mm:
                    a, b = int(mm.group(1)), int(mm.group(2))
                    for w in range(a, b + 1):
                        weeks.add(w)
            else:
                mm = re.match(r"(\d+)", part)
                if mm:
                    weeks.add(int(mm.group(1)))
    if parity == "单":
        weeks = {w for w in weeks if w % 2 == 1}
    elif parity == "双":
        weeks = {w for w in weeks if w % 2 == 0}
    return sorted(weeks)


def _split_courses(cell_text):
    """把单元格文本拆成若干门课程块。每门课以「课程名(代码)」开头。"""
    lines = cell_text.split("\n")
    courses = []
    cur = None
    course_re = re.compile(r"^(.*?)\((\d+\.\d+)\)\s*$")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = course_re.match(line)
        if m:
            if cur is not None:
                courses.append(cur)
            cur = {"name": m.group(1).strip(), "code": m.group(2), "rest": ""}
        else:
            if cur is not None:
                cur["rest"] += line
            # 否则忽略游离行
    if cur is not None:
        courses.append(cur)
    return courses


def parse_xlsx(path):
    """
    解析课表 xlsx，返回课程列表，每项：
      {course_name, course_code, week_day(1-7), period_idx(1-12),
       weeks(list[int]), classroom, weeks_raw(str)}
    """
    cells = _read_sheet_cells(path)
    results = []
    for ref, text in cells.items():
        col = _col_letter(ref)
        row = int(re.search(r"(\d+)", ref).group(1))
        if col not in _DAY_COLS:
            continue
        if row not in _PERIOD_ROWS:
            continue
        week_day = _DAY_COLS.index(col) + 1
        period_idx = _PERIOD_ROWS[row]
        for c in _split_courses(text):
            # 解析周次与教室：rest 形如 ([2-5] [7-11单] [12-18]周,教室(校本部))
            wm = re.search(r"\[([^\]]*)\]", c["rest"])
            weeks_raw = wm.group(1) if wm else ""
            weeks = _expand_weeks(weeks_raw) if weeks_raw else []
            # 教室：周次括号之后，逗号后到行尾
            room = ""
            rm = re.search(r"\]\s*周\s*[,，]\s*(.+)$", c["rest"])
            if rm:
                room = rm.group(1).strip()
            results.append(
                {
                    "course_name": c["name"],
                    "course_code": c["code"],
                    "week_day": week_day,
                    "period_idx": period_idx,
                    "weeks": weeks,
                    "weeks_raw": weeks_raw,
                    "classroom": room,
                    "teacher": "",
                }
            )
    return results


def merge_teacher_from_activities(xlsx_courses, web_activities):
    """
    用网页爬取的 TaskActivity（含教师）补全 xlsx 课程的教师。
    web_activities 每项含 code / teacher / slots（[(day,period), ...]，0-based）。
    xlsx_courses 每项含 course_code / week_day / period_idx（1-based）。

    匹配优先级：
      1) 精确匹配 (code, week_day, period_idx)；
      2) 退而求其次：同一 course_code 的任意实例教师（同一门课教师一致）。
    这样即使网页端「全部」视图漏渲染了某些周次实例（如第19周），
    只要该课程在其它周次出现，教师仍可被补全。
    """
    teacher_map = {}
    code_teacher = {}
    for a in web_activities:
        code = a.get("code")
        teacher = a.get("teacher")
        if not teacher or not code:
            continue
        code_teacher.setdefault(code, teacher)
        for d, p in a.get("slots", []):
            teacher_map[(code, d + 1, p + 1)] = teacher
    for c in xlsx_courses:
        key = (c["course_code"], c["week_day"], c["period_idx"])
        t = teacher_map.get(key) or code_teacher.get(c["course_code"])
        if t:
            c["teacher"] = t
    return xlsx_courses


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/blueberry/Downloads/课表.xlsx"
    courses = parse_xlsx(p)
    from collections import Counter

    print(f"总课程实例数: {len(courses)}")
    cov = Counter()
    for c in courses:
        for w in c["weeks"]:
            cov[w] += 1
    print("各周覆盖:")
    for w in sorted(cov):
        print(f"  周{w:2}: {cov[w]}")
    wl = [c for c in courses if 19 in c["weeks"]]
    print(f"\n第19周课程 ({len(wl)}个):")
    for c in wl:
        print(
            f"  {c['course_name']:20} 星期{c['week_day']} 第{c['period_idx']}节 weeks={c['weeks']} @{c['classroom']}"
        )
