"""种子数据写入与校验（seed 命令）。"""
import os

from app.schema.common import Style, _ensure_db, _import_all_models


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
    from app.model.module_config import init_default_configs
    from app.model.user import User

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

