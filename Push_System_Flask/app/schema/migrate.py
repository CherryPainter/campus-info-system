"""增量迁移与清理（migrate / cleanup 命令）。"""
from app.schema.common import Style, _ensure_db, _import_all_models, _parse_yes_flag
from app.schema.fingerprint import _fingerprint_common


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
        elif isinstance(dfl, int | float):
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
            conn.execute(text('SET SESSION lock_wait_timeout = 3'))
            conn.execute(text('SET SESSION innodb_lock_wait_timeout = 3'))
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
            conn.execute(text('SET SESSION lock_wait_timeout = 3'))
            conn.execute(text('SET SESSION innodb_lock_wait_timeout = 3'))
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
                    conn.execute(sql_text('SET SESSION lock_wait_timeout = 3'))
                    conn.execute(sql_text('SET SESSION innodb_lock_wait_timeout = 3'))
                    conn.execute(sql_text(f'ALTER TABLE `{tbl_name}` DROP COLUMN `{col_name}`'))
                    conn.commit()
                print(f'  {Style.ok("✓")} DROP COLUMN {tbl_name}.{col_name}')
                cleaned += 1
            except Exception as e:
                print(f'  {Style.err(f"✗ DROP COLUMN {tbl_name}.{col_name} 失败")}: {e}')

    # 2) 删除多余配置键
    for m, k, _, *_ in extra_cfgs:
        try:
            with engine.connect() as conn:
                conn.execute(sql_text('SET SESSION lock_wait_timeout = 3'))
                conn.execute(sql_text('SET SESSION innodb_lock_wait_timeout = 3'))
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
                conn.execute(sql_text('SET SESSION lock_wait_timeout = 3'))
                conn.execute(sql_text('SET SESSION innodb_lock_wait_timeout = 3'))
                conn.execute(sql_text(f'DROP TABLE IF EXISTS `{tbl_name}`'))
                conn.commit()
            print(f'  {Style.ok("✓")} DROP TABLE {tbl_name}')
            cleaned += 1
        except Exception as e:
            print(f'  {Style.err(f"✗ DROP TABLE {tbl_name} 失败")}: {e}')

    # 4) 修正安全类型变更
    safe_text_types = {'varchar', 'text', 'longtext', 'mediumtext', 'char'}
    for tbl_name, cols in type_changed.items():
        for col_name, _ in cols.items():
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
                    conn.execute(sql_text('SET SESSION lock_wait_timeout = 3'))
                    conn.execute(sql_text('SET SESSION innodb_lock_wait_timeout = 3'))
                    conn.execute(sql_text(f'ALTER TABLE `{tbl_name}` MODIFY COLUMN `{col_name}` {new_type}'))
                    conn.commit()
                print(f'  {Style.ok("✓")} MODIFY {tbl_name}.{col_name} → {new_type}')
                cleaned += 1
            except Exception as e:
                print(f'  {Style.err(f"✗ MODIFY {tbl_name}.{col_name} 失败")}: {e}')

    # 5) 修正可空性变更（NULL ↔ NOT NULL）
    for tbl_name, cols in null_changed.items():
        for col_name, _ in cols.items():
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
    from sqlalchemy import text as sql_text
    from sqlalchemy.dialects.mysql import dialect as _md

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
            conn.execute(sql_text('SET SESSION lock_wait_timeout = 3'))
            conn.execute(sql_text('SET SESSION innodb_lock_wait_timeout = 3'))
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

