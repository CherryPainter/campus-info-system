"""
回归守卫：禁止在 SQLAlchemy 过滤条件里使用 `Column is True / is False`。

`X is True` 在 Python 中是身份比较，Column 对象 `is True` 恒为 False，
编译成 `0 = 1`，导致查询永远返回空集。这曾造成：
- IP 黑名单 is_ip_blocked 永远返回 False（黑名单失效）
- ServerSession.is_active is True 查不到活跃会话（登录态校验异常）
- Course.is_deleted is False 课程列表返回空
等生产级 bug。正确写法是用 SQLAlchemy 惯用的 `.is_(True)` / `.is_(False)`。

本测试静态扫描 app/ 下所有源码的 AST，发现 `属性 is True/False` 即报错，
从源头阻止该反模式回归（比单点单测覆盖面更广）。
"""

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VIOLATIONS = []

for dirpath, _, filenames in os.walk(APP):
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(dirpath, fn)
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for op, comp in zip(node.ops, node.comparators):
                is_identity = isinstance(op, ast.Is | ast.IsNot)
                is_bool_const = isinstance(comp, ast.Constant) and isinstance(comp.value, bool)
                left_is_column = isinstance(node.left, ast.Attribute)
                if is_identity and is_bool_const and left_is_column:
                    rel = os.path.relpath(path, ROOT)
                    VIOLATIONS.append(f"{rel}:{node.lineno}: {ast.unparse(node.left)} {type(op).__name__} {comp.value}")


def test_no_is_true_false_in_column_filters():
    assert VIOLATIONS == [], (
        "发现 Column is True/False 反模式（应改为 .is_(True)/.is_(False)）：\n"
        + "\n".join(VIOLATIONS)
    )
