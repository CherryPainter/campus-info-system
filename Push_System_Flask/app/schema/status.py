"""数据库状态总览（status 命令）。"""
from app.schema.common import ALL_TABLES, Style, _ensure_db, _import_all_models


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
        # 防御：若某张表被其他会话持有元数据锁（如正在运行的后端连接、
        # 未提交的长时间事务、或卡住的迁移），默认 lock_wait_timeout 长达
        # 一年，会导致本命令无限挂起。这里把本会话的等待超时压到 3 秒，
        # 超时即被 except 捕获并报告 '?'，单张表锁住不会拖垮整条命令。
        try:
            conn.execute(text('SET SESSION lock_wait_timeout = 3'))
            conn.execute(text('SET SESSION innodb_lock_wait_timeout = 3'))
        except Exception:
            pass

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

    # 检查列差异（简要）—— 函数内部自建带超时连接派生 inspector，
    # 避免列检查卡在 MDL 上，也不依赖上方已关闭的会话连接。
    _check_columns_brief(engine, model_tables, existing)

    print()



def _check_columns_brief(engine, model_tables, existing_tables):
    """简要检查列差异（不修改，仅报告）。

    内部自建一条带 MDL 锁超时（3 秒）的连接派生 inspector，避免列检查
    因元数据锁挂起；该连接在函数内独立开闭，不依赖调用方的会话连接。
    """
    _import_all_models()
    from app.core.database import Base as Base2
    common = model_tables & existing_tables
    total_missing_cols = 0
    with engine.connect() as conn:
        from sqlalchemy import inspect, text
        try:
            conn.execute(text('SET SESSION lock_wait_timeout = 3'))
            conn.execute(text('SET SESSION innodb_lock_wait_timeout = 3'))
        except Exception:
            pass
        inspector = inspect(conn)
        for tbl_name in sorted(common):
            model_table = Base2.metadata.tables[tbl_name]
            model_columns = {c.name: c for c in model_table.columns}
            try:
                actual_columns = {c['name']: c for c in inspector.get_columns(tbl_name)}
            except Exception:
                # 锁超时等异常：跳过该表的列检查，不影响其他表
                actual_columns = {}
            missing_cols = set(model_columns.keys()) - set(actual_columns.keys())
            if missing_cols:
                total_missing_cols += len(missing_cols)
                print(f'  {Style.warn("⚠ " + tbl_name)}: 缺失字段 {", ".join(sorted(missing_cols))}')
    if total_missing_cols == 0 and common:
        print(Style.ok('  ✓ 所有表字段一致'))


# ══════════════════════════════════════════════════════════════
#  init - 完整初始化
# ══════════════════════════════════════════════════════════════

