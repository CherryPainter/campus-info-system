#!/usr/bin/env python3
"""课表解析的纯函数工具（与浏览器状态无关）。

从 main.py 的 CourseTableTool 中抽取，单独成模块以便复用与单测，
不改变 spider_runner 以 subprocess 调用 main.py 的契约。
"""

import re


def _split_js_args(s):
    """
    按顶层逗号切分 JavaScript 函数实参字符串。

    会正确跳过字符串字面量与括号（()/[]/{}）内部的逗号，
    因此像 new TaskActivity(a,b,"x(y)",...) 这样的调用能被正确拆分。

    Args:
        s: TaskActivity(...) 括号内的原始实参字符串

    Returns:
        list: 拆分后的实参列表（保留原始引号，未去引号）
    """
    args = []  # 拆分结果
    buf = []  # 当前实参的字符缓冲
    depth = 0  # 括号嵌套深度
    in_str = False  # 是否处于字符串字面量中
    quote = ""  # 当前字符串使用的引号字符
    escaped = False  # 上一个字符是否为转义符 '\'

    for ch in s:
        if in_str:
            # 字符串内部：仅关注转义与闭合引号
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_str = False
            continue

        if ch in ('"', "'"):
            in_str = True
            quote = ch
            buf.append(ch)
        elif ch in ("(", "[", "{"):
            depth += 1
            buf.append(ch)
        elif ch in (")", "]", "}"):
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            # 顶层逗号：切分出一个实参
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)

    if buf:
        args.append("".join(buf).strip())

    return args

def _unquote(s):
    """去掉字符串两端成对的引号"""
    s = s.strip()
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    return s

def _weeks_bitmap_to_str(bitmap):
    """
    将整学期周次位图转换为紧凑区间字符串。

    位图为 '0'/'1' 组成的字符串，下标即周次号（下标 0 不使用，
    下标 19 为 '1' 表示第 19 周有课）。

    示例:
        '...1...'(仅第19位为1) -> '19'
        连续 1-16 周           -> '1-16'
        1-8 与 10-16 周        -> '1-8 10-16'

    Args:
        bitmap: 周次位图字符串

    Returns:
        str: 紧凑周次区间字符串，无课时返回空串
    """
    weeks = [i for i, ch in enumerate(bitmap) if ch == "1"]
    if not weeks:
        return ""

    parts = []
    start = prev = weeks[0]
    for w in weeks[1:]:
        if w == prev + 1:
            # 周次连续，延伸当前区间
            prev = w
        else:
            # 出现断点，收尾当前区间并开启新区间
            parts.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = w
    parts.append(f"{start}-{prev}" if start != prev else f"{start}")

    return " ".join(parts)

def _expand_weeks_str(weeks_str):
    """
    将紧凑周次区间字符串展开为周次数字集合。

    示例: '2-5 7 9 11 12-18' -> {2,3,4,5,7,9,11,12,...,18}

    Args:
        weeks_str: _weeks_bitmap_to_str 的输出

    Returns:
        set: 周次数字集合
    """
    weeks = set()
    if not weeks_str:
        return weeks
    for part in weeks_str.split():
        if "-" in part:
            m = re.match(r"(\d+)-(\d+)", part)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                weeks.update(range(a, b + 1))
        else:
            m = re.match(r"(\d+)", part)
            if m:
                weeks.add(int(m.group(1)))
    return weeks

def _count_distinct_weeks(activities):
    """
    统计解析出的课程活动覆盖了多少个不同的教学周。

    用于在"全部"视图渲染后校验是否真的拿到了整学期数据
    （而非只拿到默认当前周）。

    Args:
        activities: _parse_activities 返回的课程活动列表

    Returns:
        int: 覆盖的不同教学周数量
    """
    weeks = set()
    for act in activities:
        weeks.update(_expand_weeks_str(act.get("weeks_str", "")))
    return len(weeks)

