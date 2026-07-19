#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化 & 迁移工具 (MySQL)

覆盖项目所有 20 张表。

用法:
    python init_db.py status        查看数据库状态（表清单、行数）
    python init_db.py init          完整初始化：建表 + 种子数据（首次部署）
    python init_db.py migrate       增量迁移：对比模型定义，补建缺失的表/列/索引
    python init_db.py seed          仅写入种子数据（admin 用户、模块配置等）
    python init_db.py reset         删除所有表 → 重建 → 种子数据（危险，需确认）
    python init_db.py fingerprint   数据库指纹比对：打印定义码、实例码与差异
    python init_db.py check         静默比对（CI/脚本用），一致 exit 0 否则 1
    python init_db.py cleanup       清理多余字段（模型中未定义的列和配置键）

环境变量:
    DATABASE_HOST / DATABASE_PORT / DATABASE_USER
    DATABASE_PASSWORD / DATABASE_NAME
"""

import os
import sys
from datetime import datetime

# Windows 中文编码修复
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 颜色支持 ──────────────────────────────────────────────
class Style:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'

    @staticmethod
    def ok(text: str) -> str:   return f'{Style.GREEN}{text}{Style.RESET}'
    @staticmethod
    def warn(text: str) -> str: return f'{Style.YELLOW}{text}{Style.RESET}'
    @staticmethod
    def err(text: str) -> str:  return f'{Style.RED}{text}{Style.RESET}'
    @staticmethod
    def info(text: str) -> str: return f'{Style.CYAN}{text}{Style.RESET}'
    @staticmethod
    def dim(text: str) -> str:  return f'{Style.DIM}{text}{Style.RESET}'
    @staticmethod
    def bold(text: str) -> str: return f'{Style.BOLD}{text}{Style.RESET}'


# ── 所有表的定义（名称 + 描述 + 模型类名） ─────────────────
ALL_TABLES = [
    ('users',                        '用户表',                  'User'),
    ('token_blacklist',              'Token 黑名单',            'TokenBlacklist'),
    ('user_mfa',                     '用户 MFA 配置',           'UserMFA'),
    ('login_logs',                   '登录日志',                'LoginLog'),
    ('module_configs',               '模块配置',                'ModuleConfig'),
    ('courses',                      '课程表',                  'Course'),
    ('course_weeks',                 '课程周次',                'CourseWeek'),
    ('custom_pushes',                '自定义推送',              'CustomPush'),
    ('task_processes',               '任务进程',                'TaskProcess'),
    ('scheduled_crawl_tasks',        '爬取预约任务',            'ScheduledCrawlTask'),
    ('push_task_queue',              '推送任务队列',            'PushTask'),
    ('weather_records',              '天气记录',                'WeatherRecord'),
    ('weather_alerts',               '天气预警',                'WeatherAlert'),
    ('electricity_records',          '电量使用记录',            'ElectricityRecord'),
    ('electricity_remaining',        '剩余电量',                'ElectricityRemaining'),
    ('electricity_total_capacity',   '电量总量记录',            'ElectricityTotalCapacity'),
    ('webhooks',                     'Webhook 配置',            'Webhook'),
    ('server_sessions',              '服务端会话',              'ServerSession'),
    ('ip_blacklist',                 'IP 黑名单',               'IPBlacklist'),
    ('ip_security_events',           'IP 安全事件',             'IPSecurityEvent'),
]


def _ensure_db():
    """确保数据库引擎已初始化，返回 db_manager 实例"""
    from app.core.database import db_manager
    return db_manager


def _import_all_models():
    """导入所有模型，确保 Base.metadata 包含全部表"""
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


# ══════════════════════════════════════════════════════════════
#  status - 数据库状态总览
# ══════════════════════════════════════════════════════════════

def cmd_status():
    """显示数据库状态"""
    dbm = _ensure_db()
    engine = dbm.engine

    print()
    print(Style.bold('═══ 数据库状态 ═══'))
    print(f'  类型: {Style.info("MySQL")}')

    # 安全显示连接地址（隐藏密码）
    url_str = str(engine.url)
    if engine.url.password:
        url_str = url_str.replace(engine.url.password, '***')
    print(f'  地址: {Style.dim(url_str)}')
    print()

    # 现有表
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    # 模型中的表
    _import_all_models()
    from app.core.database import Base
    model_tables = set(Base.metadata.tables.keys())

    # 汇总
    missing_tables = model_tables - existing
    extra_tables = existing - model_tables
    print(f'  模型定义: {len(model_tables)} 张表')
    print(f'  数据库中: {len(existing)} 张表')

    if missing_tables:
        print(f'  {Style.warn("缺失表:")} {", ".join(sorted(missing_tables))}')
    if extra_tables:
        print(f'  {Style.dim("多余表:")} {", ".join(sorted(extra_tables))}')
    print()

    # 逐表详情
    print(Style.bold(f'  {"表名":<32} {"状态":<10} {"行数":>8}   说明'))
    print('  ' + '-' * 70)

    with engine.connect() as conn:
        for table_name, description, _ in ALL_TABLES:
            if table_name in existing:
                try:
                    result = conn.execute(text(f'SELECT COUNT(*) FROM `{table_name}`'))
                    count = result.scalar()
                except Exception:
                    count = '?'
                status_icon = Style.ok('OK')
                print(f'  {table_name:<30} {status_icon:<10} {str(count):>8}  {Style.dim(description)}')
            elif table_name in model_tables:
                status_icon = Style.warn('MISSING')
                print(f'  {Style.warn(table_name):<30} {status_icon:<10} {"-":>8}  {Style.warn(description)}')
            else:
                status_icon = Style.dim('?')
                print(f'  {Style.dim(table_name):<30} {status_icon:<10} {"-":>8}  {Style.dim(description)}')

        # 额外表
        for extra in sorted(extra_tables):
            try:
                result = conn.execute(text(f'SELECT COUNT(*) FROM `{extra}`'))
                count = result.scalar()
            except Exception:
                count = '?'
            print(f'  {Style.dim(extra):<30} {Style.dim("extra"):<10} {str(count):>8}  {Style.dim("不在模型定义中")}')

    print()
    if missing_tables:
        print(Style.warn('  ⚠ 有表缺失，请运行: python init_db.py migrate'))
    else:
        print(Style.ok('  ✓ 所有模型表已就绪'))

    # 检查列差异（简要）
    _check_columns_brief(engine, inspector, model_tables, existing)

    print()


def _check_columns_brief(engine, inspector, model_tables, existing_tables):
    """简要检查列差异（不修改，仅报告）"""
    Base = _import_all_models()
    from app.core.database import Base as Base2
    common = model_tables & existing_tables
    total_missing_cols = 0
    for tbl_name in sorted(common):
        model_table = Base2.metadata.tables[tbl_name]
        model_columns = {c.name: c for c in model_table.columns}
        actual_columns = {c['name']: c for c in inspector.get_columns(tbl_name)}
        missing_cols = set(model_columns.keys()) - set(actual_columns.keys())
        if missing_cols:
            total_missing_cols += len(missing_cols)
            print(f'  {Style.warn("⚠ " + tbl_name)}: 缺失字段 {", ".join(sorted(missing_cols))}')
    if total_missing_cols == 0 and common:
        print(Style.ok('  ✓ 所有表字段一致'))


# ══════════════════════════════════════════════════════════════
#  init - 完整初始化
# ══════════════════════════════════════════════════════════════

def cmd_init():
    """完整初始化：建表 + 种子数据"""
    print()
    print(Style.bold('═══ 数据库初始化 (MySQL) ═══'))

    dbm = _ensure_db()
    engine = dbm.engine

    print(f'  数据库: {Style.info("MySQL")}')
    print()

    # 1. 创建所有表
    print('  [1/3] 创建数据库表...')
    Base = _import_all_models()
    Base.metadata.create_all(bind=engine)

    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())
    created = len(model_tables & existing)

    print(f'  {Style.ok(f"✓ 已创建/确认 {created}/{len(model_tables)} 张表")}')

    # 列出所有表
    for tbl in sorted(model_tables):
        print(f'    {Style.ok("✓")} {tbl}')

    # 2. 写入种子数据
    print()
    print('  [2/3] 写入种子数据...')
    _seed_data(interactive=False)

    # 3. 验证
    print()
    print('  [3/3] 验证...')
    _verify_tables(engine)

    print()
    print(Style.ok('═══ 初始化完成 ═══'))
    print()


# ══════════════════════════════════════════════════════════════
#  migrate - 增量迁移
# ══════════════════════════════════════════════════════════════

def cmd_migrate(quiet: bool = False):
    """增量迁移：对比模型定义，补建缺失的表、列、索引。

    Args:
        quiet: True 时仅打印实际变更（表/列/索引被补建时）和错误，
               跳过"全部正常"的逐表 checklist。用于应用启动时静默调用。
    """
    if not quiet:
        print()
        print(Style.bold('═══ 数据库迁移 (MySQL) ═══'))

    dbm = _ensure_db()
    engine = dbm.engine

    if not quiet:
        print(f'  数据库: {Style.info("MySQL")}')
        print()

    Base = _import_all_models()
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())

    changes_made = 0

    # ── 阶段 A：补建缺失的表 ────────────────────────────────
    missing = model_tables - existing_tables
    if missing:
        print(f'  {Style.warn(f"发现 {len(missing)} 张缺失表")}，正在创建...')
        for tbl in sorted(missing):
            print(f'    {Style.info("创建表:")} {tbl}')
        Base.metadata.create_all(bind=engine, tables=[
            Base.metadata.tables[t] for t in missing
        ])
        changes_made += len(missing)
        print(f'  {Style.ok(f"✓ 已创建 {len(missing)} 张表")}')
    else:
        if not quiet:
            print(f'  {Style.ok("✓ 所有表已存在")}')

    # 刷新 inspector
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    existing_after_create = model_tables & existing_tables

    # ── 阶段 B：补建缺失的列 ────────────────────────────────
    if not quiet:
        print()
        print('  [检查各表字段...]')

    for tbl_name in sorted(existing_after_create):
        model_table = Base.metadata.tables[tbl_name]
        model_columns = {c.name: c for c in model_table.columns}
        actual_columns = {c['name']: c for c in inspector.get_columns(tbl_name)}

        missing_cols = set(model_columns.keys()) - set(actual_columns.keys())
        if missing_cols:
            print(f'    {Style.warn(tbl_name)}: 缺失字段 {", ".join(sorted(missing_cols))}')
            for col_name in sorted(missing_cols):
                col = model_columns[col_name]
                success = _add_column(engine, tbl_name, col)
                if success:
                    changes_made += 1
        else:
            # 检查类型是否变化
            type_mismatches = []
            for col_name, model_col in model_columns.items():
                if col_name in actual_columns:
                    actual_type = str(actual_columns[col_name]['type'])
                    model_type = str(model_col.type)
                    if not _types_compatible(model_type, actual_type):
                        type_mismatches.append((col_name, model_type, actual_type))

            if type_mismatches:
                print(f'    {Style.warn(tbl_name)}: 类型差异')
                for col_name, model_type, actual_type in type_mismatches:
                    print(f'      {col_name}: 模型={model_type} vs 数据库={actual_type}')
                print(f'      {Style.dim("(类型差异需手动处理，ALTER MODIFY 可能丢数据)")}')
            else:
                if not quiet:
                    print(f'    {Style.dim(tbl_name)}: {Style.ok("✓")}')

    # ── 阶段 C：补建缺失的索引 ──────────────────────────────
    if not quiet:
        print()
        print('  [检查索引...]')
    inspector = inspect(engine)

    for tbl_name in sorted(existing_after_create):
        model_table = Base.metadata.tables[tbl_name]
        model_indexes = {}
        for idx in model_table.indexes:
            col_names = tuple(sorted(c.name for c in idx.columns))
            model_indexes[idx.name] = col_names

        actual_indexes = {}
        try:
            for idx in inspector.get_indexes(tbl_name):
                col_names = tuple(sorted(idx.get('column_names', [])))
                actual_indexes[idx.get('name', '')] = col_names
        except Exception:
            pass

        try:
            for uc in inspector.get_unique_constraints(tbl_name):
                col_names = tuple(sorted(uc.get('column_names', [])))
                idx_name = uc.get('name', '')
                if idx_name:
                    actual_indexes[idx_name] = col_names
        except Exception:
            pass

        missing_indexes = set(model_indexes.keys()) - set(actual_indexes.keys())

        existing_col_sets = set(actual_indexes.values())
        for idx_name, col_set in model_indexes.items():
            if idx_name not in missing_indexes:
                continue
            if col_set in existing_col_sets:
                continue
            print(f'    {Style.warn(tbl_name)}: 缺失索引 {idx_name} ({", ".join(sorted(col_set))})')
            success = _add_index(engine, tbl_name, idx_name, model_table.indexes)
            if success:
                changes_made += 1

    if not quiet:
        print()
    if changes_made > 0:
        print(Style.ok(f'═══ 迁移完成，共 {changes_made} 处变更 ═══'))
    else:
        if not quiet:
            print(Style.ok('═══ 无需迁移，数据库已是最新 ═══'))
    if not quiet:
        print()


def _types_compatible(model_type: str, actual_type: str) -> bool:
    """粗略比较两个类型字符串是否兼容"""
    def normalize(t: str) -> str:
        t = t.upper().strip()
        # 去掉 COLLATE 子句（如 TEXT COLLATE "utf8mb4_unicode_ci" → TEXT）
        t = t.split(' COLLATE')[0].strip()
        # 去掉长度/精度声明（如 VARCHAR(255) → VARCHAR）
        base = t.split('(')[0].strip()
        return base

    model_base = normalize(model_type)
    actual_base = normalize(actual_type)

    compatible_pairs = [
        {'INTEGER', 'INT', 'BIGINT', 'SMALLINT'},
        {'VARCHAR', 'TEXT', 'STRING', 'CHAR'},
        {'DATETIME', 'TIMESTAMP'},
        {'FLOAT', 'REAL', 'DOUBLE', 'NUMERIC', 'DECIMAL'},
        {'BOOLEAN', 'BOOL', 'TINYINT'},
        {'JSON'},
        {'DATE'},
    ]

    for group in compatible_pairs:
        if model_base in group and actual_base in group:
            return True

    return model_base == actual_base


def _add_column(engine, table_name: str, column) -> bool:
    """为 MySQL 表添加列"""
    from sqlalchemy import text

    col_name = column.name
    col_type = _column_type_to_sql(column.type)

    parts = [f'ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type}']

    # NOT NULL
    if not column.nullable:
        parts.append('NOT NULL')

    # DEFAULT
    if column.default and column.default.arg is not None:
        dfl = column.default.arg
        if isinstance(dfl, bool):
            parts.append(f'DEFAULT {1 if dfl else 0}')
        elif isinstance(dfl, (int, float)):
            parts.append(f'DEFAULT {dfl}')
        elif isinstance(dfl, str):
            escaped = dfl.replace("'", "''")
            parts.append(f"DEFAULT '{escaped}'")
        elif callable(dfl):
            # 可调用默认值（如 datetime.now）
            # MySQL ALTER ADD COLUMN 不支持函数默认值
            pass

    sql = ' '.join(parts)
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        print(f'      → {Style.ok("添加")} {col_name} ({col_type})')
        return True
    except Exception as e:
        print(f'      → {Style.err("失败")} {col_name}: {e}')
        return False


def _add_index(engine, table_name: str, index_name: str, model_indexes) -> bool:
    """为 MySQL 表添加索引"""
    from sqlalchemy import text

    target_idx = None
    for idx in model_indexes:
        if idx.name == index_name:
            target_idx = idx
            break

    if not target_idx:
        print(f'      → {Style.err("未找到索引定义")}: {index_name}')
        return False

    col_names = ', '.join(f'`{c.name}`' for c in target_idx.columns)
    unique = 'UNIQUE ' if target_idx.unique else ''

    sql = f'CREATE {unique}INDEX `{index_name}` ON `{table_name}` ({col_names})'

    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        print(f'      → {Style.ok("创建索引")} {index_name}')
        return True
    except Exception as e:
        if 'exists' in str(e).lower() or 'duplicate' in str(e).lower():
            print(f'      → {Style.dim("索引已存在")} {index_name}')
            return False
        print(f'      → {Style.err("索引创建失败")} {index_name}: {e}')
        return False


def _column_type_to_sql(col_type) -> str:
    """
    将 SQLAlchemy Column 类型转为 MySQL SQL 字符串

    处理标准类型和自定义类型（如 JSONEncodedList）
    """
    from sqlalchemy import types as sa_types

    # ── 处理 TypeDecorator（自定义类型，如 JSONEncodedList） ──
    if hasattr(col_type, 'impl') and hasattr(col_type, 'load_dialect_impl'):
        # 自定义类型，通常包装 Text → MySQL 用 JSON 存储
        return 'JSON'

    # ── 标准类型处理 ──
    # 注意检查顺序：先检查子类（更具体的类型），再检查父类
    if isinstance(col_type, sa_types.Text):
        return 'TEXT'
    elif isinstance(col_type, sa_types.JSON):
        return 'JSON'
    elif isinstance(col_type, sa_types.Boolean):
        return 'TINYINT(1)'
    elif isinstance(col_type, sa_types.BigInteger):
        return 'BIGINT'
    elif isinstance(col_type, sa_types.SmallInteger):
        return 'SMALLINT'
    elif isinstance(col_type, sa_types.Integer):
        return 'INT'
    elif isinstance(col_type, sa_types.Float):
        return 'FLOAT'
    elif isinstance(col_type, sa_types.Numeric):
        if col_type.precision and col_type.scale:
            return f'DECIMAL({col_type.precision},{col_type.scale})'
        return 'DECIMAL'
    elif isinstance(col_type, sa_types.DateTime):
        return 'DATETIME'
    elif isinstance(col_type, sa_types.Date):
        return 'DATE'
    elif isinstance(col_type, sa_types.String):
        if col_type.length:
            return f'VARCHAR({col_type.length})'
        return 'TEXT'
    else:
        try:
            return str(col_type)
        except Exception:
            return 'TEXT'


# ══════════════════════════════════════════════════════════════
#  seed - 种子数据
# ══════════════════════════════════════════════════════════════

def cmd_seed():
    """写入种子数据"""
    print()
    print(Style.bold('═══ 种子数据 ═══'))
    print()
    dbm = _ensure_db()
    _import_all_models()

    from sqlalchemy import inspect
    inspector = inspect(dbm.engine)
    existing = set(inspector.get_table_names())

    if 'users' not in existing:
        print(Style.err('  ✗ users 表不存在，请先运行: python init_db.py init'))
        print()
        return

    _seed_data(interactive=False)


def _seed_data(interactive: bool = False):
    """写入种子数据（admin 用户 + 模块配置 + webhooks）"""
    from app.core.database import get_db
    from app.model.user import User
    from app.model.module_config import init_default_configs

    session = get_db()
    try:
        # 初始化默认管理员账号（用户名与 JWT_ADMIN_USERNAME / 指纹比对一致）
        from app.core.db_fingerprint import default_admin_username
        admin_username = default_admin_username()
        admin = session.query(User).filter_by(username=admin_username).first()
        if not admin:
            import bcrypt

            # 密码优先级：JWT_ADMIN_PASSWORD → ADMIN_TOKEN → 'admin'
            password = (
                os.environ.get('JWT_ADMIN_PASSWORD', '').strip()
                or os.environ.get('ADMIN_TOKEN', '').strip()
                or 'admin'
            )

            password_hash = bcrypt.hashpw(
                password.encode('utf-8'), bcrypt.gensalt()
            ).decode('utf-8')

            admin = User(
                username=admin_username,
                password_hash=password_hash,
                role='admin',
                is_active=True,
                is_primary=True,
            )
            session.add(admin)
            session.flush()
            print(f'  {Style.ok("✓")} 创建管理员: {admin_username}')

            if password == 'admin':
                print(f'  {Style.warn("⚠ 使用默认密码 admin，请尽快修改！")}')
            elif password == os.environ.get('ADMIN_TOKEN', '').strip():
                print(f'  {Style.info("ℹ 管理员密码使用 ADMIN_TOKEN，建议登录后修改")}')
        else:
            print(f'  {Style.dim(f"✓ 管理员已存在: {admin_username}")}')

        # ── 模块配置 ────────────────────────────────────────
        init_default_configs(session)
        session.commit()
        print(f'  {Style.ok("✓")} 模块配置已就绪')

    except Exception as e:
        session.rollback()
        print(f'  {Style.err(f"✗ 种子数据写入失败: {e}")}')
        raise
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
#  reset - 重置数据库
# ══════════════════════════════════════════════════════════════

def cmd_reset():
    """删除所有表 → 重建 → 种子数据（需要确认）"""
    print()
    print(Style.bold('═══ 数据库重置（危险操作） ═══'))
    print()

    dbm = _ensure_db()
    engine = dbm.engine

    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing = inspector.get_table_names()

    print(f'  {Style.err(f"将删除 {len(existing)} 张表及其全部数据！")}')
    print(f'  表: {", ".join(existing) if existing else "(空)"}')
    print()
    print(f'  {Style.warn("⚠ 此操作不可逆！请确保已备份数据。")}')

    confirm = input(f'\n  {Style.warn("输入 YES 确认重置: ")}')
    if confirm.strip() != 'YES':
        print(f'  {Style.info("已取消")}')
        print()
        return

    print()
    print('  正在删除所有表...')
    _import_all_models()
    from app.core.database import Base
    Base.metadata.drop_all(bind=engine)
    print(f'  {Style.ok("✓ 已删除所有表")}')

    print('  正在重建所有表...')
    Base.metadata.create_all(bind=engine)
    print(f'  {Style.ok("✓ 已重建所有表")}')

    print('  正在写入种子数据...')
    _seed_data(interactive=False)

    # 验证
    _verify_tables(engine)

    print()
    print(Style.ok('═══ 重置完成 ═══'))
    print()


def _verify_tables(engine):
    """验证所有表是否就绪"""
    from sqlalchemy import inspect
    _import_all_models()
    from app.core.database import Base

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())
    missing = model_tables - existing

    if missing:
        missing_str = ', '.join(sorted(missing))
        print(f'  {Style.err(f"⚠ 仍有 {len(missing)} 张表缺失: {missing_str}")}')
    else:
        print(f'  {Style.ok(f"✓ 全部 {len(model_tables)} 张表验证通过")}')

    # 验证关键表的字段
    for tbl_name in sorted(model_tables & existing):
        model_table = Base.metadata.tables[tbl_name]
        model_columns = {c.name for c in model_table.columns}
        actual_columns = {c['name'] for c in inspector.get_columns(tbl_name)}
        missing_cols = model_columns - actual_columns
        if missing_cols:
            missing_cols_str = ', '.join(sorted(missing_cols))
            print(f'  {Style.warn(f"⚠ {tbl_name} 缺失字段: {missing_cols_str}")}')


# ══════════════════════════════════════════════════════════════
#  fingerprint / check - 数据库指纹漂移检测
# ══════════════════════════════════════════════════════════════

def _fingerprint_common():
    """获取 DB 会话并运行指纹比对，返回 check 结果 dict。"""
    dbm = _ensure_db()
    _import_all_models()
    session = dbm.create_session()
    try:
        from app.core.db_fingerprint import check_db_fingerprint, summarize_diff
        result = check_db_fingerprint(session)
        return result, summarize_diff(result)
    finally:
        session.close()


def cmd_fingerprint():
    """打印定义码、实例码与结构化差异"""
    result, summary = _fingerprint_common()
    print()
    print(Style.bold('═══ 数据库指纹比对 ═══'))
    print()
    print(f'  定义码: {Style.info(result["definition_hash"])}  (代码推导)')
    print(f'  实例码: {Style.info(result["instance_hash"])}    (当前数据库)')
    print(f'  比对结果: {Style.ok("[一致]") if result["match"] else Style.err("[不一致]")}')
    print(f'  {summary}')

    # 结构化差异明细
    if not result['match']:
        print()
        print(Style.bold('  差异明细:'))
        d = result
        if d.get('missing_tables'):
            print(f'    缺失表: {Style.err(", ".join(d["missing_tables"]))}')
        if d.get('extra_tables'):
            print(f'    多余表: {Style.warn(", ".join(d["extra_tables"]))}')
        if d.get('missing_columns'):
            for t, cols in d['missing_columns'].items():
                print(f'    {Style.err(t)} 缺失列: {", ".join(cols)}')
        if d.get('extra_columns'):
            for t, cols in d['extra_columns'].items():
                print(f'    {Style.warn(t)} 多余列: {", ".join(cols)}')
        if d.get('type_changed'):
            for t, cols in d['type_changed'].items():
                print(f'    {Style.warn(t)} 类型变更:')
                for c, v in cols.items():
                    print(f'      {c}: 定义={v[0]} → 实例={v[1]}')
        if d.get('null_changed'):
            for t, cols in d['null_changed'].items():
                print(f'    {Style.warn(t)} 可空性变更:')
                for c, v in cols.items():
                    def_null = v[0].split('|')[1] if '|' in v[0] else '?'
                    inst_null = v[1].split('|')[1] if '|' in v[1] else '?'
                    print(f'      {c}: 定义={def_null} → 实例={inst_null}')
        if d.get('missing_config_keys'):
            print(f'    缺失配置键 ({len(d["missing_config_keys"])}):')
            for m, k, vt, *_ in d['missing_config_keys']:
                print(f'      {m}.{k} ({vt})')
        if d.get('extra_config_keys'):
            print(f'    多余配置键 ({len(d["extra_config_keys"])}):')
            for m, k, vt, *_ in d['extra_config_keys']:
                print(f'      {m}.{k} ({vt})')
        if not d['admin']['match']:
            print(f'    默认管理员: {Style.warn("缺失" if not d["admin"]["instance_admin_present"] else "状态不符")}')
    print()


def cmd_check():
    """静默模式：一致 exit 0，不一致 exit 1（用于 CI/脚本）。"""
    result, summary = _fingerprint_common()
    if result['match']:
        print(Style.ok(f'[OK] {summary}'))
        exit(0)
    else:
        print(Style.err(f'[FAIL] {summary}'))
        print('  (可用 python init_db.py fingerprint 查看详情)')
        exit(1)


def _parse_yes_flag() -> bool:
    """检测命令行是否含 --yes 或 -y 标志。"""
    return any(a in ('--yes', '-y') for a in sys.argv)


def cmd_cleanup(auto: bool = False, quiet: bool = False):
    """清理数据库多余内容：额外表、多余列、多余配置键、类型差异。

    基于指纹 diff 的 extra_tables / extra_columns / extra_config_keys / type_changed。
    缺失项（missing_*）不在清理范围内，请用 migrate 补。
    默认需要确认；传 --yes 或 auto=True 可直接执行。
    """
    auto_confirm = auto or _parse_yes_flag()
    result, summary = _fingerprint_common()
    extra_tables = result.get('extra_tables', [])
    extra_cols = result.get('extra_columns', {})
    extra_cfgs = result.get('extra_config_keys', [])
    type_changed = _filter_actionable_type_changes(result.get('type_changed', {}))
    null_changed = result.get('null_changed', {})

    no_items = not any([extra_tables, extra_cols, extra_cfgs, type_changed, null_changed])
    if no_items:
        if not quiet:
            print()
            print(Style.ok('═══ 数据库已整洁，没有多余字段/表/配置键/类型差异 ═══'))
            print()
        return

    # ═══════════════════ 展示 ═══════════════════
    if not quiet:
        print()
        print(Style.bold('═══ 数据库清理 ═══'))
        print()

    if extra_tables:
        if not quiet:
            print(Style.warn(f'  发现 {len(extra_tables)} 个多余表（模型中未定义）:'))
        for t in extra_tables:
            if not quiet:
                print(f'    {Style.err("DROP TABLE")} {t}')
    if extra_cols:
        if not quiet:
            print(Style.warn(f'  发现 {sum(len(v) for v in extra_cols.values())} 个多余列（模型中未定义）:'))
        for t, cols in extra_cols.items():
            for c in cols:
                if not quiet:
                    print(f'    {Style.err("DROP COLUMN")} {t}.{c}')
    if extra_cfgs:
        if not quiet:
            print(Style.warn(f'  发现 {len(extra_cfgs)} 个多余配置键:'))
        for m, k, vt, *_ in extra_cfgs:
            if not quiet:
                print(f'    {Style.err("DELETE")} module_configs.{m}.{k} ({vt})')
    if type_changed:
        # 区分安全变更与需手动的变更
        safe_text_types = {'varchar', 'text', 'longtext', 'mediumtext', 'char'}
        if not quiet:
            print(Style.warn(f'  发现 {sum(len(v) for v in type_changed.values())} 个类型差异:'))
        for t, cols in type_changed.items():
            for c, (def_type, inst_type) in cols.items():
                def_base = def_type.split('|')[0] if def_type else ''
                inst_base = inst_type.split('|')[0] if inst_type else ''
                if def_base in safe_text_types and inst_base in safe_text_types:
                    if not quiet:
                        print(f'    {Style.warn("MODIFY")} {t}.{c}: {inst_base}→{def_base} {Style.dim("(安全，仅文本类型调整)")}')
                elif def_base == 'int' and inst_base == 'int':
                    if not quiet:
                        print(f'    {Style.warn("MODIFY")} {t}.{c}: {inst_base}→{def_base} {Style.dim("(安全，整数族调整)")}')
                else:
                    if not quiet:
                        print(f'    {Style.err("⚠ SKIP")} {t}.{c}: {inst_base}→{def_base} {Style.dim("(需手动评估后再 ALTER)")}')
    if null_changed:
        if not quiet:
            print(Style.warn(f'  发现 {sum(len(v) for v in null_changed.values())} 个可空性变更:'))
        for t, cols in null_changed.items():
            for c, (def_type, inst_type) in cols.items():
                def_null = def_type.split('|')[1] if '|' in def_type else ''
                inst_null = inst_type.split('|')[1] if '|' in inst_type else ''
                target = 'NOT NULL' if def_null == 'null=0' else 'NULL'
                if not quiet:
                    print(f'    {Style.warn("MODIFY")} {t}.{c}: {inst_null}→{def_null} {Style.dim(f"(自动修正为 {target})")}')

    # ═══════════════════ 确认 ═══════════════════
    if not auto_confirm:
        print()
        confirm = input(f'  {Style.warn("输入 YES 确认清理（或 ctrl+C 取消 / 传 --yes 跳过确认）: ")}')
        if confirm.strip() != 'YES':
            print(f'  {Style.info("已取消")}')
            print()
            return

    # ═══════════════════ 执行 ═══════════════════
    dbm = _ensure_db()
    engine = dbm.engine
    from sqlalchemy import text as sql_text
    cleaned = 0

    # 1) 删除多余列
    for tbl_name, col_names in extra_cols.items():
        for col_name in col_names:
            try:
                with engine.connect() as conn:
                    conn.execute(sql_text(f'ALTER TABLE `{tbl_name}` DROP COLUMN `{col_name}`'))
                    conn.commit()
                print(f'  {Style.ok("✓")} DROP COLUMN {tbl_name}.{col_name}')
                cleaned += 1
            except Exception as e:
                print(f'  {Style.err(f"✗ DROP COLUMN {tbl_name}.{col_name} 失败")}: {e}')

    # 2) 删除多余配置键
    for m, k, vt, *_ in extra_cfgs:
        try:
            with engine.connect() as conn:
                conn.execute(sql_text(
                    'DELETE FROM module_configs WHERE module = :m AND `key` = :k'
                ), {'m': m, 'k': k})
                conn.commit()
            print(f'  {Style.ok("✓")} DELETE config {m}.{k}')
            cleaned += 1
        except Exception as e:
            print(f'  {Style.err(f"✗ DELETE config {m}.{k} 失败")}: {e}')

    # 3) 删除多余表
    for tbl_name in extra_tables:
        try:
            with engine.connect() as conn:
                conn.execute(sql_text(f'DROP TABLE IF EXISTS `{tbl_name}`'))
                conn.commit()
            print(f'  {Style.ok("✓")} DROP TABLE {tbl_name}')
            cleaned += 1
        except Exception as e:
            print(f'  {Style.err(f"✗ DROP TABLE {tbl_name} 失败")}: {e}')

    # 4) 修正安全类型变更
    safe_text_types = {'varchar', 'text', 'longtext', 'mediumtext', 'char'}
    for tbl_name, cols in type_changed.items():
        for col_name, (def_type, inst_type) in cols.items():
            def_base = def_type.split('|')[0] if def_type else ''
            inst_base = inst_type.split('|')[0] if inst_type else ''
            # 仅自动处理同族调整
            is_safe = (def_base in safe_text_types and inst_base in safe_text_types) or \
                      (def_base == 'int' and inst_base == 'int')
            if not is_safe:
                continue
            try:
                # 从模型获取准确列类型
                _import_all_models()
                from app.core.database import Base
                tbl = Base.metadata.tables.get(tbl_name)
                if tbl is None:
                    continue
                col = tbl.columns.get(col_name)
                if col is None:
                    continue
                from sqlalchemy.dialects.mysql import dialect as _md
                new_type = col.type.compile(dialect=_md())
                with engine.connect() as conn:
                    conn.execute(sql_text(f'ALTER TABLE `{tbl_name}` MODIFY COLUMN `{col_name}` {new_type}'))
                    conn.commit()
                print(f'  {Style.ok("✓")} MODIFY {tbl_name}.{col_name} → {new_type}')
                cleaned += 1
            except Exception as e:
                print(f'  {Style.err(f"✗ MODIFY {tbl_name}.{col_name} 失败")}: {e}')

    # 5) 修正可空性变更（NULL ↔ NOT NULL）
    for tbl_name, cols in null_changed.items():
        for col_name, (def_type, inst_type) in cols.items():
            ok, detail = _fix_nullability(engine, tbl_name, col_name)
            if ok:
                print(f'  {Style.ok("✓")} MODIFY {tbl_name}.{col_name} 可空性 → {detail}')
                cleaned += 1
            else:
                print(f'  {Style.err(f"✗ MODIFY {tbl_name}.{col_name} 可空性失败")}: {detail}')

    print()
    if cleaned > 0:
        msg = Style.ok(f'═══ 清理完成，共 {cleaned} 项 ═══')
    else:
        msg = Style.info('═══ 没有可自动修复的项 ═══')
    if not quiet:
        print(msg)
        print()


def _filter_actionable_type_changes(type_changed: dict) -> dict:
    """过滤出可安全自动修正的同族类型变更（文本↔文本、整数↔整数）。

    注意：可空性差异已移至指纹 diff 的 null_changed 并由 _fix_nullability 处理，
    此处 type_changed 仅含逻辑类型族真正不同的项；跨类型（如 varchar↔int）
    不在此自动处理，避免丢数据。
    """
    safe_text_types = {'varchar', 'text', 'longtext', 'mediumtext', 'char'}
    filtered = {}
    for tbl, cols in type_changed.items():
        actionable = {}
        for col, (def_type, inst_type) in cols.items():
            def_base = def_type.split('|')[0] if def_type else ''
            inst_base = inst_type.split('|')[0] if inst_type else ''
            if def_base in safe_text_types and inst_base in safe_text_types:
                actionable[col] = (def_type, inst_type)
            elif def_base == 'int' and inst_base == 'int':
                actionable[col] = (def_type, inst_type)
            # 其余（跨类型）保持原样字符串，由执行阶段按 is_safe 跳过并提示手动
            else:
                actionable[col] = (def_type, inst_type)
        if actionable:
            filtered[tbl] = actionable
    return filtered


def _null_fill_value(col):
    """取模型列的标量默认值，用于 NOT NULL 化前填充现存 NULL 行。

    仅支持标量默认（如 Boolean default=True）；可调用默认 / 无默认返回 None。
    bool 归一为 0/1 以适配 MySQL TINYINT 存储。
    """
    d = getattr(col, 'default', None)
    if d is not None:
        arg = getattr(d, 'arg', None)
        if isinstance(arg, bool):
            return 1 if arg else 0
        if arg is not None:
            return arg
    return None


def _fix_nullability(engine, table_name: str, column_name: str):
    """依据模型重新 ALTER 单列可空性（NULL ↔ NOT NULL）。返回 (成功, 说明)。

    - 目标为 NOT NULL 且存在 NULL 行：先用模型标量默认值填充，避免 ALTER 失败 / 丢数据；
      无可用默认值时返回失败，交由人工处理。
    - 目标为 NULL，或 NOT NULL 但无非空数据时，均为元数据操作，可安全即时执行。
    """
    from sqlalchemy.dialects.mysql import dialect as _md
    from sqlalchemy import text as sql_text

    _import_all_models()
    from app.core.database import Base
    tbl = Base.metadata.tables.get(table_name)
    if tbl is None:
        return False, '模型无该表定义'
    col = tbl.columns.get(column_name)
    if col is None:
        return False, '模型无该列定义'

    new_type = col.type.compile(dialect=_md())
    target_not_null = not col.nullable

    # 探测现存 NULL 行数
    null_count = 0
    try:
        with engine.connect() as conn:
            null_count = conn.execute(
                sql_text(f'SELECT COUNT(*) FROM `{table_name}` WHERE `{column_name}` IS NULL')
            ).scalar() or 0
    except Exception:
        null_count = 0

    # NOT NULL 化前，若已有 NULL 行，用模型默认值填充
    if target_not_null and null_count > 0:
        fill = _null_fill_value(col)
        if fill is None:
            return False, f'存在 {null_count} 条 NULL 且无模型标量默认值，需手动处理'
        try:
            with engine.connect() as conn:
                conn.execute(
                    sql_text(
                        f'UPDATE `{table_name}` SET `{column_name}` = :v '
                        f'WHERE `{column_name}` IS NULL'
                    ),
                    {'v': fill},
                )
                conn.commit()
        except Exception as e:
            return False, f'填充 NULL 失败: {e}'

    modifier = 'NOT NULL' if target_not_null else 'NULL'
    try:
        with engine.connect() as conn:
            conn.execute(
                sql_text(
                    f'ALTER TABLE `{table_name}` MODIFY COLUMN '
                    f'`{column_name}` {new_type} {modifier}'
                )
            )
            conn.commit()
        return True, modifier
    except Exception as e:
        return False, f'MODIFY 失败: {e}'



# ══════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════

COMMANDS = {
    'status':  cmd_status,
    'init':    cmd_init,
    'migrate': cmd_migrate,
    'seed':    cmd_seed,
    'reset':   cmd_reset,
    'fingerprint': cmd_fingerprint,
    'check':   cmd_check,
    'cleanup': cmd_cleanup,
}

HELP_TEXT = f"""
{Style.bold('数据库初始化 & 迁移工具 (MySQL)')}

用法: python init_db.py <命令>

命令:
  {Style.info('status')}      查看数据库状态（表清单、行数、缺失表/字段）
  {Style.info('init')}        完整初始化：建表 + 种子数据（首次部署用）
  {Style.info('migrate')}     增量迁移：对比模型定义，补建缺失的表/列/索引
  {Style.info('seed')}        仅写入种子数据（admin 用户、模块配置等）
  {Style.info('reset')}       删除所有表 → 重建 → 种子数据（{Style.err('危险，需确认')}）
  {Style.info('fingerprint')} 数据库指纹比对：打印定义码、实例码与结构化差异
  {Style.info('check')}       静默比对模式：一致 exit 0，不一致 exit 1（CI/脚本用）
  {Style.info('cleanup')}     清理数据库多余项：额外表/列/配置键 + 安全类型变更自动修正

覆盖 20 张表:
  users, token_blacklist, user_mfa, login_logs, module_configs,
  courses, course_weeks, custom_pushes, task_processes,
  scheduled_crawl_tasks, push_task_queue,
  weather_records, weather_alerts, electricity_records,
  electricity_remaining, electricity_total_capacity, webhooks,
  server_sessions, ip_blacklist, ip_security_events

环境变量:
  DATABASE_HOST / DATABASE_PORT / DATABASE_USER
  DATABASE_PASSWORD / DATABASE_NAME

种子数据:
  admin 用户密码优先级: JWT_ADMIN_PASSWORD > ADMIN_TOKEN > 'admin'
"""


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(HELP_TEXT)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd in ('-h', '--help', 'help'):
        print(HELP_TEXT)
        sys.exit(0)

    if cmd not in COMMANDS:
        print(Style.err(f'未知命令: {cmd}'))
        print(HELP_TEXT)
        sys.exit(1)

    try:
        COMMANDS[cmd]()
    except Exception as e:
        print()
        print(Style.err(f'执行失败: {e}'))
        import traceback
        traceback.print_exc()
        sys.exit(1)
