#!/usr/bin/env python3
"""
数据库初始化 & 迁移工具 (MySQL) —— CLI 装配入口

建表/迁移/种子/状态/指纹/清理等具体逻辑已拆分到 app/schema/* 包，
本文件仅负责：解析命令行、装配 COMMANDS、调用对应子模块。

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

# Windows 中文编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 从 app.schema.* 引入全部命令实现（保持 python init_db.py <cmd> 与
# from init_db import cmd_migrate / cmd_cleanup / _null_fill_value 兼容）
from app.schema.common import Style
from app.schema.create_tables import cmd_init
from app.schema.fingerprint import cmd_check, cmd_fingerprint
from app.schema.migrate import _null_fill_value, cmd_cleanup, cmd_migrate  # noqa: F401
from app.schema.reset import cmd_reset
from app.schema.seed import cmd_seed
from app.schema.status import cmd_status

# ══════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════

COMMANDS = {
    "status": cmd_status,
    "init": cmd_init,
    "migrate": cmd_migrate,
    "seed": cmd_seed,
    "reset": cmd_reset,
    "fingerprint": cmd_fingerprint,
    "check": cmd_check,
    "cleanup": cmd_cleanup,
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(HELP_TEXT)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd in ("-h", "--help", "help"):
        print(HELP_TEXT)
        sys.exit(0)

    if cmd not in COMMANDS:
        print(Style.err(f"未知命令: {cmd}"))
        print(HELP_TEXT)
        sys.exit(1)

    try:
        COMMANDS[cmd]()
    except Exception as e:
        print()
        print(Style.err(f"执行失败: {e}"))
        import traceback

        traceback.print_exc()
        sys.exit(1)
