"""数据库重置（reset 命令，危险）。"""
from app.schema.common import Style, _ensure_db, _import_all_models
from app.schema.seed import _seed_data, _verify_tables


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


