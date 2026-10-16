"""
测试公共路径常量。

`tests/` 目录现在位于**仓库根**（与 `Push_System_Flask/`、`admin-frontend/`、
`miniapp-frontend/` 平级）。但测试里大量 `ROOT` 常量需要指向**后端代码根**
`Push_System_Flask/`（即 `app` 包的父目录），用于读取 `.env.example`、`app/**`、
`requirements.txt`、爬虫目录等源码文件。

这里集中定义一次，供各测试文件 `from _paths import BACKEND_ROOT`，避免在每个文件里
重复推导路径、也避免目录搬迁时又漏改（2026-10-14 tests/ 迁移后 fence 用例集体
FileNotFoundError 即因此）。
"""

import os

# 仓库根：tests/ 的上一级
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 后端代码根：app 包所在目录（读取源码/示例配置的基准）
BACKEND_ROOT = os.path.join(REPO_ROOT, "Push_System_Flask")
