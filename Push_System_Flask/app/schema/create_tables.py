"""建表命令（init：建表 + 种子 + 校验）。"""
from app.schema.common import Style, _ensure_db, _import_all_models
from app.schema.seed import _seed_data, _verify_tables


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

