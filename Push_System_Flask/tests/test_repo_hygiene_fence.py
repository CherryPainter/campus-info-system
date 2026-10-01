"""
仓库卫生围栏回归测试（B 级修复项 B13 + B14）

B13 —— 示例配置不得给出可照抄的弱口令：
  `.env.example` 原本写着 `DATABASE_PASSWORD=123456`。示例文件的用途是「告诉你要配
  哪些变量」，一旦写成具体弱口令，最省事的做法就是原样复制进生产。现留空并注明
  「留空即用代码内默认值，生产必须显式填强密码」。
  注意：本项只约束**示例文件**，不约束本地 `.env`（本地库密码就是 123456）。

B14 —— 学生 webhook 校验里的死代码：
  `_validate_webhook_url` 原先在「https + 仅 qyapi.weixin.qq.com」之后，还跟着一段
  「拒绝内网 IP / 私有网段」的分支，并为此维护 `_PRIVATE_NETWORKS` 与 `import ipaddress`。
  但主机名白名单是**等值判断**，任何 IP 字面量都不可能等于该域名 —— 那段分支永远
  走不到，是纯死代码。删掉后拦截能力不变（用下面的用例锁定这一点）。

覆盖：
- `.env.example`：DATABASE_PASSWORD 存在且为空；不得出现具体弱口令
- webhook 校验：内网/环回/非法协议一律仍被拒；合法企业微信机器人地址仍放行
- 源码守卫：`_PRIVATE_NETWORKS` / `import ipaddress` 不得复活

运行：
    cd Push_System_Flask && python -m pytest tests/test_repo_hygiene_fence.py -v
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ENV_EXAMPLE = os.path.join(ROOT, ".env.example")
MINIAPP_ROUTES = os.path.join(ROOT, "app", "api", "miniapp_routes.py")

HOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd-1234"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ============================================================
# 一、B13：示例配置弱口令
# ============================================================


def test_env_example_has_database_password_key():
    """变量本身必须保留（否则使用者不知道要配这个）。"""
    hits = [ln for ln in _read(ENV_EXAMPLE).splitlines() if ln.startswith("DATABASE_PASSWORD=")]
    assert hits, ".env.example 缺少 DATABASE_PASSWORD"


def test_env_example_database_password_is_empty():
    hits = [ln for ln in _read(ENV_EXAMPLE).splitlines() if ln.startswith("DATABASE_PASSWORD=")]
    assert hits[0] == "DATABASE_PASSWORD=", "示例文件不得给出具体密码值"


@pytest.mark.parametrize("weak", ["123456", "password", "root", "admin", "123456789"])
def test_env_example_has_no_weak_password_literal(weak):
    src = _read(ENV_EXAMPLE)
    assert f"DATABASE_PASSWORD={weak}" not in src


def test_env_example_blank_password_is_documented():
    """空值必须就近解释，否则使用者会以为「忘了填」。"""
    src = _read(ENV_EXAMPLE)
    idx = src.index("DATABASE_PASSWORD=")
    nearby = src[max(0, idx - 300) : idx]
    assert "生产" in nearby, "留空需在注释里说明生产必须显式填写"


# ============================================================
# 二、B14：webhook 校验拦截能力不变
# ============================================================


@pytest.fixture(scope="module")
def validate_url():
    from app.api.miniapp_routes import _validate_webhook_url

    return _validate_webhook_url


def test_valid_wechat_hook_passes(validate_url):
    ok, err = validate_url(HOOK)
    assert ok is True
    assert err is None


def test_plain_http_rejected(validate_url):
    ok, err = validate_url("http://qyapi.weixin.qq.com/cgi-bin/webhook/send")
    assert ok is False
    assert "https" in err


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/cgi-bin/webhook/send",
        "https://10.0.0.1/cgi-bin/webhook/send",
        "https://192.168.1.1/cgi-bin/webhook/send",
        "https://172.16.0.1/cgi-bin/webhook/send",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/cgi-bin/webhook/send",
        "https://evil.example.com/cgi-bin/webhook/send",
        "https://qyapi.weixin.qq.com.evil.example.com/hook",
    ],
)
def test_non_whitelisted_hosts_rejected(validate_url, url):
    """删掉死代码后拦截能力必须不变：这些地址一个都不能通。"""
    ok, err = validate_url(url)
    assert ok is False
    assert err


def test_empty_and_missing_host_rejected(validate_url):
    assert validate_url("")[0] is False
    assert validate_url("https://")[0] is False


# ============================================================
# 三、源码守卫：死代码不得复活
# ============================================================


def test_dead_private_network_code_not_reintroduced():
    src = _read(MINIAPP_ROUTES)
    assert "_PRIVATE_NETWORKS" not in src
    assert "import ipaddress" not in src
    # 白名单判定必须仍在（这是真正的拦截手段）
    assert "_STUDENT_WEBHOOK_HOST" in src
