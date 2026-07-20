"""数据库指纹比对（fingerprint / check 命令）。"""
from app.schema.common import Style, _ensure_db, _import_all_models


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


