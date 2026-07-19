#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库指纹：定义码 vs 实例码 的漂移检测

用于在升级/改表后快速判断「运行实例」是否与「代码中的初始化定义」一致：

- 定义码（definition）：由代码推导 —— SQLAlchemy 模型 schema + DEFAULT_CONFIGS 配置键结构
  + 默认管理员「应当存在」。纯代码推导，无需数据库连接。
- 实例码（instance）：由当前数据库推导 —— INFORMATION_SCHEMA 实际表/列 + module_configs
  实际配置键 + 默认管理员是否存在。

比对两者：
- 一致  → 实例已对齐最新定义（如刚跑过 init_db migrate）。
- 不一致 → 有新增表/列/配置键未迁移，或实例发生漂移，需运行 `python init_db.py migrate`。

设计原则（避免误报）：
- 仅哈希「结构」，不哈希数据值。配置项只取 (module, key, value_type, is_editable, is_sensitive)，
  不取 value —— 管理员自定义配置值不会触发误报。
- 类型归一化：定义侧用 MySQL dialect compile，实例侧用 INFORMATION_SCHEMA.COLUMN_TYPE，
  两者统一小写并剥离整数显示宽度（int(11)→int），保证可比。
"""
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.mysql import dialect as _mysql_dialect


# 整数族统一为 int（MySQL 显示宽度 int(11) 是装饰性的，与定义侧 INTEGER 不可比，故抹平）
_INT_FAMILY = {'int', 'integer', 'bigint', 'smallint', 'tinyint', 'mediumint'}


def _normalize_type(raw: str) -> str:
    """把任意来源的类型串归一化：小写 + 整数族剥离显示宽度 + varchar/decimal 保留精度。"""
    if not raw:
        return ''
    s = raw.lower().strip()
    m = re.match(r'^([a-z]+)(?:\((\d+)(?:,(\d+))?\))?', s)
    if not m:
        return s
    base = m.group(1)
    if base in _INT_FAMILY:
        return 'int'
    if base in ('varchar', 'char'):
        return f'varchar({m.group(2)})' if m.group(2) else 'varchar'
    if base in ('decimal', 'numeric'):
        if m.group(3):
            return f'decimal({m.group(2)},{m.group(3)})'
        return f'decimal({m.group(2)})' if m.group(2) else 'decimal'
    if base in ('datetime', 'timestamp', 'date', 'time', 'year',
                'text', 'blob', 'json', 'float', 'double'):
        return base
    return s  # 兜底原样


def _col_desc(type_str: str, nullable: bool, pk: bool) -> str:
    return f"{_normalize_type(type_str)}|null={int(bool(nullable))}|pk={int(bool(pk))}"


def _ensure_all_models():
    """导入全部模型，确保 Base.metadata 包含全部 20 张表。

    与 init_db._import_all_models 保持一致的导入清单（电量/天气等子模块模型
    不会经 `from app import model` 自动注册，必须显式导入，否则定义码会漏表）。
    不直接 import init_db，避免 `python init_db.py` 以 __main__ 运行时产生循环/重复导入。
    """
    from app.model import (
        WeatherRecord, WeatherAlert,
        ElectricityRecord, ElectricityRemaining, ElectricityTotalCapacity,
        Course, CourseWeek, CustomPush, TaskProcess, ScheduledCrawlTask, PushTask,
        TokenBlacklist, UserMFA, User, LoginLog, ModuleConfig, Webhook,
    )
    from app.model.ip_blacklist import IPBlacklist, IPSecurityEvent
    from app.model.server_session import ServerSession
    from app.core.database import Base
    return Base


# ──────────────────────────────────────────────────────────
#  定义码（来自代码）
# ──────────────────────────────────────────────────────────
def _definition_schema() -> Dict[str, Dict[str, str]]:
    """从 SQLAlchemy 模型推导 schema 结构（需先 import 所有模型）。"""
    Base = _ensure_all_models()

    eng = _mysql_dialect()
    schema: Dict[str, Dict[str, str]] = {}
    for table_name in sorted(Base.metadata.tables.keys()):
        table = Base.metadata.tables[table_name]
        cols: Dict[str, str] = {}
        for col in sorted(table.columns, key=lambda c: c.name):
            try:
                type_str = col.type.compile(dialect=eng)
            except Exception:
                type_str = str(col.type)
            cols[col.name] = _col_desc(type_str, col.nullable, col.primary_key)
        schema[table_name] = cols
    return schema


def _definition_configs() -> List[Tuple[str, str, str, bool, bool]]:
    from app.model.module_config import DEFAULT_CONFIGS

    out: List[Tuple[str, str, str, bool, bool]] = []
    for c in DEFAULT_CONFIGS:
        out.append((
            c.get('module', ''),
            c.get('key', ''),
            c.get('value_type', ''),
            bool(c.get('is_editable', False)),
            bool(c.get('is_sensitive', False)),
        ))
    out.sort()
    return out


def _definition_admin() -> bool:
    # 初始化定义中「应当存在」默认管理员（用户名来自 JWT_ADMIN_USERNAME，默认 admin）
    return True


def compute_definition_fingerprint() -> Tuple[str, dict]:
    """返回 (sha256_hex, 结构化明细)。纯代码推导，无需数据库。"""
    struct = {
        'schema': _definition_schema(),
        'configs': _definition_configs(),
        'admin': _definition_admin(),
    }
    payload = json.dumps(struct, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest(), struct


# ──────────────────────────────────────────────────────────
#  实例码（来自当前数据库）
# ──────────────────────────────────────────────────────────
def _instance_schema(session, table_names: List[str]) -> Dict[str, Dict[str, str]]:
    db_name = session.bind.url.database
    rows = session.execute(
        text(
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY "
            "FROM information_schema.columns "
            "WHERE TABLE_SCHEMA = :db AND TABLE_NAME IN :tables "
            "ORDER BY TABLE_NAME, COLUMN_NAME"
        ),
        {'db': db_name, 'tables': table_names},
    ).fetchall()
    schema: Dict[str, Dict[str, str]] = {}
    for r in rows:
        tname, cname, ctype, nullable, ckey = r
        pk = (ckey or '') == 'PRI'
        schema.setdefault(tname, {})[cname] = _col_desc(ctype, nullable == 'YES', pk)
    return schema


def _instance_configs(session) -> List[Tuple[str, str, str, bool, bool]]:
    rows = session.execute(
        text(
            "SELECT module, `key`, value_type, is_editable, is_sensitive "
            "FROM module_configs ORDER BY module, `key`"
        )
    ).fetchall()
    out: List[Tuple[str, str, str, bool, bool]] = []
    for r in rows:
        out.append((r[0], r[1], r[2] or '', bool(r[3]), bool(r[4])))
    out.sort()
    return out


def _instance_admin(session) -> bool:
    from app.model.user import User
    username = os.getenv('JWT_ADMIN_USERNAME', 'admin')
    return session.query(User).filter_by(username=username).first() is not None


def compute_instance_fingerprint(session) -> Tuple[str, dict]:
    """返回 (sha256_hex, 结构化明细)。需要数据库会话。"""
    Base = _ensure_all_models()

    table_names = sorted(Base.metadata.tables.keys())
    struct = {
        'schema': _instance_schema(session, table_names),
        'configs': _instance_configs(session),
        'admin': _instance_admin(session),
    }
    payload = json.dumps(struct, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest(), struct


# ──────────────────────────────────────────────────────────
#  比对
# ──────────────────────────────────────────────────────────
def diff_fingerprints(def_struct: dict, inst_struct: dict) -> dict:
    """结构化 diff：逐项列出缺失/多余的表、列、类型变更、配置键，以及管理员一致性。"""
    ds = def_struct['schema']
    isc = inst_struct['schema']

    missing_tables = sorted(set(ds) - set(isc))
    extra_tables = sorted(set(isc) - set(ds))
    missing_columns: Dict[str, List[str]] = {}
    extra_columns: Dict[str, List[str]] = {}
    type_changed: Dict[str, Dict[str, List[str]]] = {}

    for t in sorted(set(ds) & set(isc)):
        dc = ds[t]
        ic = isc[t]
        miss = sorted(set(dc) - set(ic))
        extra = sorted(set(ic) - set(dc))
        changed = {c: [dc[c], ic[c]] for c in dc if c in ic and dc[c] != ic[c]}
        if miss:
            missing_columns[t] = miss
        if extra:
            extra_columns[t] = extra
        if changed:
            type_changed[t] = changed

    dk = set(def_struct['configs'])
    ik = set(inst_struct['configs'])
    missing_config_keys = sorted(dk - ik)
    extra_config_keys = sorted(ik - dk)

    admin_match = bool(def_struct['admin']) == bool(inst_struct['admin'])

    diff = {
        'missing_tables': missing_tables,
        'extra_tables': extra_tables,
        'missing_columns': missing_columns,
        'extra_columns': extra_columns,
        'type_changed': type_changed,
        'missing_config_keys': missing_config_keys,
        'extra_config_keys': extra_config_keys,
        'admin': {
            'definition_expects_admin': bool(def_struct['admin']),
            'instance_admin_present': bool(inst_struct['admin']),
            'match': admin_match,
        },
    }
    diff['match'] = not any([
        missing_tables, extra_tables, missing_columns, extra_columns,
        type_changed, missing_config_keys, extra_config_keys, not admin_match,
    ])
    return diff


def check_db_fingerprint(session) -> dict:
    """高层入口：返回 {definition_hash, instance_hash, match, ...diff}。"""
    def_hash, def_struct = compute_definition_fingerprint()
    inst_hash, inst_struct = compute_instance_fingerprint(session)
    diff = diff_fingerprints(def_struct, inst_struct)
    diff['definition_hash'] = def_hash
    diff['instance_hash'] = inst_hash
    diff['match'] = (def_hash == inst_hash)
    return diff


def summarize_diff(diff: dict) -> str:
    """把 diff 渲染成一行人话摘要（用于启动告警 / CLI）。"""
    if diff['match']:
        return '实例与初始化定义一致'
    parts: List[str] = []
    if diff['missing_tables']:
        parts.append(f"缺失表:{','.join(diff['missing_tables'])}")
    if diff['extra_tables']:
        parts.append(f"多余表:{','.join(diff['extra_tables'])}")
    if diff['missing_columns']:
        parts.append('缺失列:' + ';'.join(f"{t}({','.join(c)})" for t, c in diff['missing_columns'].items()))
    if diff['extra_columns']:
        parts.append('多余列:' + ';'.join(f"{t}({','.join(c)})" for t, c in diff['extra_columns'].items()))
    if diff['type_changed']:
        parts.append('类型变更:' + ';'.join(f"{t}:{len(v)}列" for t, v in diff['type_changed'].items()))
    if diff['missing_config_keys']:
        parts.append(f"缺失配置键:{len(diff['missing_config_keys'])}个")
    if diff['extra_config_keys']:
        parts.append(f"多余配置键:{len(diff['extra_config_keys'])}个")
    if not diff['admin']['match']:
        parts.append('默认管理员缺失' if not diff['admin']['instance_admin_present'] else '默认管理员状态不符')
    return '实例与初始化定义不一致 → ' + ' | '.join(parts) if parts else '实例与初始化定义不一致'
