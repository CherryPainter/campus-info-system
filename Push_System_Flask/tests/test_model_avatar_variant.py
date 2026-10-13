"""
头像列类型变体锁定测试（2026-10-13）

背景：`users.avatar` / `student_profiles.avatar` 存头像 URL 或 Base64，
Base64 图片可达 16MB，MySQL 侧需要 MEDIUMTEXT（64KB 的 Text 不够）。
但 MEDIUMTEXT 没有 SQLite 方言实现——直接用 `Column(MEDIUMTEXT)` 会让所有
SQLite 内存库测试 fixture 在 `create_all` 建表时直接抛
UnsupportedCompilationError（曾导致 35 个 miniapp/bind 测试 ERROR）。

修复口径：`Text().with_variant(MEDIUMTEXT, "mysql")`
- MySQL 方言渲染 MEDIUMTEXT（生产 DDL 不变，容量不变）；
- SQLite 等方言渲染 TEXT（测试 fixture 可正常建表）。

本测试用 mysql 方言**离线编译** CreateTable（不需要连接数据库），
锁住生产库列类型不被改坏——若有人把 variant 去掉改回裸 MEDIUMTEXT，
SQLite 测试会炸；若有人把 MEDIUMTEXT 改成 Text，本测试会红。
"""

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.model.student_profile import StudentProfile
from app.model.user import User


def _mysql_ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))


def test_users_avatar_is_mediumtext_on_mysql():
    """users.avatar 在 MySQL 方言下必须渲染为 MEDIUMTEXT"""
    ddl = _mysql_ddl(User)
    assert "avatar MEDIUMTEXT" in ddl, f"users.avatar 的 MySQL DDL 不是 MEDIUMTEXT:\n{ddl}"


def test_student_profiles_avatar_is_mediumtext_on_mysql():
    """student_profiles.avatar 在 MySQL 方言下必须渲染为 MEDIUMTEXT"""
    ddl = _mysql_ddl(StudentProfile)
    assert "avatar MEDIUMTEXT" in ddl, f"student_profiles.avatar 的 MySQL DDL 不是 MEDIUMTEXT:\n{ddl}"
