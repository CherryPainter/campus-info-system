"""
HTTPS / Cookie Secure 围栏回归测试（A 级修复项 A5）

背景（三个真实故障面）：
1. `cookie_secure` 只看 `FORCE_HTTPS` 配置项，生产漏设即让会话 cookie 静默失去
   Secure 标志（可经明文 http 回传）；且该写法在 auth_routes 里被复制了三处，
   改一处漏一处就会让「同一份 cookie 两种安全等级」。
2. 生产由 Nginx 终结 TLS 时后端 `wsgi.url_scheme` 是 http，未装 ProxyFix 则
   `request.is_secure` 恒 False —— 此时若设 `FORCE_HTTPS=true`，`force_https`
   会把每个请求 301 到自己，形成**无限重定向**（这正是生产 .env 一直没敢开它的根因）。
3. 生产漏开 FORCE_HTTPS 没有启动期拦截，属于「配置错了照样上线」。

覆盖：
- `cookie_security_flags`：http + 未开 → (False, Lax)；https 请求 → (True, Lax)；
  FORCE_HTTPS=true + http 请求 → (True, Lax)
- ProxyFix 生效：带 `X-Forwarded-Proto: https` 时 `request.is_secure` 为 True，
  且 `FORCE_HTTPS=true` 下不再触发 301（否则是死循环）
- `check_https_startup_guard`：production + FORCE_HTTPS=false → RuntimeError；
  非生产 → 不抛（打 error 日志）；production + true → 通过

运行：
    cd Push_System_Flask && python -m pytest tests/test_https_cookie_fence.py -v
"""

import os
import sys

import pytest
from flask import Flask, jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.security import check_https_startup_guard, cookie_security_flags


def _app(force_https=False, with_proxyfix=True):
    flask_app = Flask(__name__)
    flask_app.config.update(FORCE_HTTPS=force_https, SECRET_KEY="x" * 32)
    if with_proxyfix:
        # 与 app/__init__.py 的挂法保持一致
        flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_proto=1, x_for=0, x_host=0)

    @flask_app.route("/flags")
    def flags():
        secure, samesite = cookie_security_flags()
        return jsonify(secure=secure, samesite=samesite, is_secure=request.is_secure)

    @flask_app.route("/api/x")
    def api_x():
        return jsonify(ok=True)

    # 复刻 app/__init__.py 的 force_https 行为，验证不会形成重定向循环
    @flask_app.before_request
    def force_https_redirect():
        if flask_app.config.get("FORCE_HTTPS", False) and not request.is_secure:
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    return flask_app


# ============================================================
# 一、cookie 安全标志单一来源
# ============================================================


def test_flags_http_without_force_https():
    client = _app(force_https=False).test_client()
    body = client.get("/flags").get_json()
    assert body["secure"] is False
    assert body["samesite"] == "Lax"


def test_flags_https_request_gets_secure_even_without_force_https():
    """兜底：即使漏设 FORCE_HTTPS，只要请求真的经 https，cookie 仍带 Secure"""
    client = _app(force_https=False).test_client()
    body = client.get("/flags", headers={"X-Forwarded-Proto": "https"}).get_json()
    assert body["is_secure"] is True
    assert body["secure"] is True


def test_flags_force_https_true_on_plain_http():
    """FORCE_HTTPS=true 且请求为明文时，cookie 仍必须带 Secure。

    用请求上下文直接取值：走 test_client 会被 force_https 的 301 提前拦下，测不到该分支。
    """
    app = _app(force_https=True)
    with app.test_request_context("/flags"):
        secure, samesite = cookie_security_flags()
    assert secure is True
    assert samesite == "Lax"


def test_proxyfix_absent_means_is_secure_false():
    """反证用对照：不挂 ProxyFix 时 X-Forwarded-Proto 不被采信（说明第 2 个故障面真实存在）"""
    client = _app(force_https=False, with_proxyfix=False).test_client()
    body = client.get("/flags", headers={"X-Forwarded-Proto": "https"}).get_json()
    assert body["is_secure"] is False


# ============================================================
# 二、ProxyFix 消解「301 死循环」
# ============================================================


def test_force_https_no_redirect_loop_behind_nginx():
    """Nginx 终结 TLS 且转发 X-Forwarded-Proto 时，请求应直接 200，不能 301 回自己"""
    client = _app(force_https=True).test_client()
    resp = client.get(
        "/api/x",
        headers={"X-Forwarded-Proto": "https", "Host": "yuetang.cloud"},
    )
    assert resp.status_code == 200


def test_force_https_still_redirects_plain_http():
    """未带 X-Forwarded-Proto 的明文请求仍应被跳转到 https（行为不放宽）"""
    client = _app(force_https=True).test_client()
    resp = client.get("/api/x")
    assert resp.status_code == 301
    assert resp.headers["Location"].startswith("https://")


# ============================================================
# 三、启动期守卫
# ============================================================


def test_guard_raises_in_production_without_force_https(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    app = _app(force_https=False)
    with pytest.raises(RuntimeError) as exc:
        check_https_startup_guard(app)
    assert "FORCE_HTTPS" in str(exc.value)


def test_guard_passes_in_production_with_force_https(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    check_https_startup_guard(_app(force_https=True))


@pytest.mark.parametrize("env_key", ["APP_ENV", "FLASK_ENV", "ENV"])
@pytest.mark.parametrize("value", ["production", "prod", "PRODUCTION", " prod "])
def test_guard_ignores_case_and_padding(monkeypatch, env_key, value):
    for key in ("APP_ENV", "FLASK_ENV", "ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(env_key, value)
    with pytest.raises(RuntimeError):
        check_https_startup_guard(_app(force_https=False))


def test_guard_does_not_block_local_dev(monkeypatch):
    """本地 .env 就是 FORCE_HTTPS=false + DEBUG=false，不能被误判为生产"""
    for key in ("APP_ENV", "FLASK_ENV", "ENV"):
        monkeypatch.delenv(key, raising=False)
    check_https_startup_guard(_app(force_https=False))


def test_guard_ignores_unknown_env_value(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    check_https_startup_guard(_app(force_https=False))


# ============================================================
# 四、接线：应用工厂必须把 ProxyFix 挂上 wsgi_app
# ============================================================

import subprocess  # noqa: E402

PY = sys.executable
APP_DIR = ROOT


def test_create_app_wraps_wsgi_app_with_proxyfix():
    """上面几个用例里的 ProxyFix 是测试自建的，本用例才对 `app/__init__.py` 的接线取证。

    用子进程跑：create_app 会注册 APScheduler 任务，放主进程里会留后台线程。
    """
    code = (
        "from app import create_app;"
        "app=create_app();"
        "print('WSGI=' + type(app.wsgi_app).__name__)"
    )
    proc = subprocess.run(
        [PY, "-c", code],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert "WSGI=ProxyFix" in proc.stdout, proc.stdout[-2000:] + proc.stderr[-2000:]
