# 让 pytest 在任意工作目录都能 import 到 app 包
import os
import sys

# 测试目录位于仓库根 /tests，后端代码包位于 /Push_System_Flask
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_ROOT = os.path.join(REPO_ROOT, "Push_System_Flask")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
