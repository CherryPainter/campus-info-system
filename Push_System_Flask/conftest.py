# 仓库根 conftest：测试启动时设置环境，避免连接真实 MySQL / Redis
import os
import sys

# 测试在无 MySQL / Redis 的环境下运行：
# - DATABASE_HOST 指向本地回环，连接被快速拒绝（不挂起）
# - REDIS_URL 留空，登录失败计数走内存降级
os.environ.setdefault("DATABASE_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_URL", "")

# 保证 app 包可导入
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
