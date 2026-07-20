#!/usr/bin/env python3
"""数据库指纹：可空性变更拆分 + 默认值填充回归测试（纯结构，无需数据库）。"""

from sqlalchemy import Boolean, Column, Integer, String

from app.core import db_fingerprint
from init_db import _null_fill_value


def _struct(schema):
    return {"schema": schema, "configs": [], "admin": True}


def test_nullability_change_goes_to_null_changed_not_type_changed():
    """同类型仅可空性不同 → 归入 null_changed，且不应误报为类型变更。"""
    def_struct = _struct({"users": {"id": "int|null=0|pk=1", "is_active": "bool|null=0|pk=0"}})
    inst_struct = _struct({"users": {"id": "int|null=0|pk=1", "is_active": "bool|null=1|pk=0"}})
    diff = db_fingerprint.diff_fingerprints(def_struct, inst_struct)
    assert "users" in diff["null_changed"]
    assert diff["null_changed"]["users"].get("is_active") is not None
    assert "users" not in diff["type_changed"]
    assert not diff["match"]


def test_true_type_change_goes_to_type_changed():
    """逻辑类型族不同 → 归入 type_changed。"""
    def_struct = _struct({"users": {"is_active": "bool|null=0|pk=0"}})
    inst_struct = _struct({"users": {"is_active": "int|null=0|pk=0"}})
    diff = db_fingerprint.diff_fingerprints(def_struct, inst_struct)
    assert "users" in diff["type_changed"]
    assert "users" not in diff["null_changed"]


def test_no_change_is_match():
    def_struct = _struct({"users": {"is_active": "bool|null=0|pk=0"}})
    inst_struct = _struct({"users": {"is_active": "bool|null=0|pk=0"}})
    diff = db_fingerprint.diff_fingerprints(def_struct, inst_struct)
    assert diff["match"]
    assert "users" not in diff["null_changed"]
    assert "users" not in diff["type_changed"]


def test_summarize_labels_nullability():
    def_struct = _struct({"users": {"is_active": "bool|null=0|pk=0"}})
    inst_struct = _struct({"users": {"is_active": "bool|null=1|pk=0"}})
    diff = db_fingerprint.diff_fingerprints(def_struct, inst_struct)
    summary = db_fingerprint.summarize_diff(diff)
    assert "可空性变更" in summary
    assert "类型变更" not in summary


def test_null_fill_value():
    """模型标量默认值用于 NOT NULL 化前填充 NULL 行。"""
    assert _null_fill_value(Column(Boolean, default=True)) == 1
    assert _null_fill_value(Column(Boolean, default=False)) == 0
    assert _null_fill_value(Column(Integer, default=5)) == 5
    # 无标量默认 → None（交由人工处理）
    assert _null_fill_value(Column(String(50))) is None
