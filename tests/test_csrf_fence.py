"""
CSRF 豁免口径回归测试（A 级修复项 A4）

背景：此前 `CSRF_EXEMPT_PREFIXES = ["/api/"]` 把整个 `/api/` 前缀**无条件**豁免，
理由写的是「所有 API 接口使用 JWT 认证」——前提不成立：`_extract_token` 与
`get_identity_key` 都是「Authorization 头 → 退 access_token cookie」，登录/刷新还会
种下 httpOnly 的 access_token / refresh_token / session_id。也就是说同一端点既能被
Bearer 调、也能被 Cookie 调，而 Cookie 由浏览器自动附加，正是 CSRF 成立的前提。

新口径：`/api/` 写请求只在
  ① 显式带 `Authorization: Bearer`（浏览器不会自动补该头），或
  ② 完全不带任何认证 cookie（纯匿名，无环境凭证可被冒用）
时豁免；否则走同源校验（Origin 优先，退 Referer；两者皆无 = 非浏览器客户端 → 放行）。

覆盖：
- 豁免：安全方法 / 精确豁免路径 / @csrf_exempt 标记 / Bearer / 纯匿名
- 拦截：带认证 cookie + 无 Bearer + 跨站 Origin → 403
- 放行：带认证 cookie + 同源 Origin / Referer / 无 Origin（非浏览器客户端）
- 拦截：`Origin: null`（沙箱 iframe / file:）不在允许集合内
- 配置：CSRF_ALLOWED_ORIGINS 额外放行来源

运行：
    cd Push_System_Flask && python -m pytest tests/test_csrf_fence.py -v
"""

import os
import sys

import pytest
from flask import Flask, jsonify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.csrf_protect import (
    CSRFProtect,
    check_same_site_origin,
    csrf_exempt,
    is_csrf_exempt_request,
)


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    flask_app.config.update(CSRF_ALLOWED_ORIGINS=[], SECRET_KEY="x" * 32)
    CSRFProtect().init_app(flask_app)

    @flask_app.route("/api/write", methods=["POST", "PUT", "DELETE", "GET"])
    def api_write():
        return jsonify({"ok": True})

    @flask_app.route("/api/auth/login", methods=["POST"])
    def api_login():
        return jsonify({"ok": True})

    @flask_app.route("/api/marked", methods=["POST"])
    @csrf_exempt
    def api_marked():
        return jsonify({"ok": True})

    @flask_app.route("/web/form", methods=["POST"])
    def web_form():
        return jsonify({"ok": True})

    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


AUTH_COOKIE = {"access_token": "jwt-cookie"}
SITE = "https://yuetang.cloud"


def _post(client, path="/api/write", headers=None, cookies=None):
    """cookies 通过 test_client.set_cookie 注入。

    注意：本环境 werkzeug 3.1 会在 EnvironBuilder 里**丢弃**手工传入的 `Cookie` 头
    （实测 request.headers["Cookie"] 为 None），故不能用 headers 伪造 cookie 登录态。
    """
    for name, value in (cookies or {}).items():
        client.set_cookie(name, value)
    try:
        return client.post(path, headers=headers or {}, json={})
    finally:
        for name in (cookies or {}):
            client.delete_cookie(name)


# ============================================================
# 一、豁免形态
# ============================================================


def test_safe_method_exempt(client):
    assert client.get("/api/write").status_code == 200


def test_exempt_auth_path(client):
    """认证流程端点整体豁免（换号时可能残留上一段会话 cookie）"""
    assert _post(client, "/api/auth/login", cookies=AUTH_COOKIE).status_code == 200


def test_bearer_exempt_even_with_cookies(client):
    """带显式 Bearer：凭证由调用方主动携带，浏览器不会自动附加 → 免疫 CSRF"""
    resp = _post(client, headers={"Authorization": "Bearer abc"}, cookies=AUTH_COOKIE)
    assert resp.status_code == 200


def test_anonymous_exempt(client):
    """无任何认证 cookie：没有可被冒用的环境凭证"""
    assert _post(client).status_code == 200


def test_csrf_exempt_marker(client):
    assert _post(client, "/api/marked", cookies=AUTH_COOKIE).status_code == 200


def test_bearer_like_header_must_be_wellformed(client):
    """畸形 Authorization 头不构成「显式凭证」→ 不豁免，仍受同源校验约束。

    （若它被误判为豁免，本用例会因跳过同源校验而返回 200）
    """
    resp = _post(
        client,
        headers={"Authorization": "Bearer", "Origin": "https://evil.example.com"},
        cookies=AUTH_COOKIE,
    )
    assert resp.status_code == 403


# ============================================================
# 二、核心：带认证 cookie 的写请求必须同源
# ============================================================


def test_cross_site_origin_blocked(client):
    """本围栏的核心用例：去掉 cookie 分支的判定后，本用例会由 403 变为 200"""
    resp = _post(
        client,
        headers={"Origin": "https://evil.example.com"},
        cookies=AUTH_COOKIE,
    )
    assert resp.status_code == 403


def test_null_origin_blocked(client):
    """`Origin: null`（沙箱 iframe / 本地文件）不应被信任"""
    resp = _post(client, headers={"Origin": "null"}, cookies=AUTH_COOKIE)
    assert resp.status_code == 403


def test_same_site_origin_allowed(client):
    resp = _post(client, headers={"Origin": f"http://{_host(client)}"}, cookies=AUTH_COOKIE)
    assert resp.status_code == 200


def test_same_site_origin_allowed_with_trailing_slash(client):
    resp = _post(
        client, headers={"Origin": f"http://{_host(client)}/"}, cookies=AUTH_COOKIE
    )
    assert resp.status_code == 200


def test_cross_site_referer_blocked(client):
    resp = _post(client, headers={"Referer": "https://evil.example.com/page"}, cookies=AUTH_COOKIE)
    assert resp.status_code == 403


def test_same_site_referer_allowed(client):
    resp = _post(
        client,
        headers={"Referer": f"http://{_host(client)}/admin/index.html"},
        cookies=AUTH_COOKIE,
    )
    assert resp.status_code == 200


def test_no_origin_no_referer_allowed(client):
    """小程序 / 脚本调用既无 Origin 也无 Referer：浏览器发起的跨站写请求必带 Origin，
    两皆无说明不是浏览器，第三方页面无法触发它，故放行（避免打断小程序匿名流程）。"""
    resp = _post(client, cookies=AUTH_COOKIE)
    assert resp.status_code == 200


def test_configured_extra_origin_allowed(app, client):
    app.config["CSRF_ALLOWED_ORIGINS"] = ["http://localhost:5173"]
    resp = _post(
        client,
        headers={"Origin": "http://localhost:5173"},
        cookies=AUTH_COOKIE,
    )
    assert resp.status_code == 200


def test_configured_origin_does_not_open_others(app, client):
    app.config["CSRF_ALLOWED_ORIGINS"] = ["http://localhost:5173"]
    resp = _post(client, headers={"Origin": "http://localhost:5174"}, cookies=AUTH_COOKIE)
    assert resp.status_code == 403


def test_refresh_token_cookie_alone_is_enough_to_require_check(client):
    """只有 refresh_token cookie 也算 cookie 登录态（它同样由浏览器自动携带）"""
    resp = _post(
        client,
        headers={"Origin": "https://evil.example.com"},
        cookies={"refresh_token": "r"},
    )
    assert resp.status_code == 403


def test_web_non_api_path_still_uses_token_check(client):
    """非 /api/ 的 Web 表单路径维持原有 CSRF Token 校验（行为不变）"""
    resp = client.post("/web/form", json={})
    assert resp.status_code == 403


# ============================================================
# 三、工具函数
# ============================================================


def _host(client):
    """取测试客户端实际访问的主机（werkzeug 默认 localhost）"""
    return "localhost"


def test_is_csrf_exempt_request_anonymous(app):
    with app.test_request_context("/api/write", method="POST"):
        assert is_csrf_exempt_request() is True


def test_is_csrf_exempt_request_cookie_not_exempt(app):
    with app.test_request_context(
        "/api/write", method="POST", headers={"Cookie": "access_token=t"}
    ):
        assert is_csrf_exempt_request() is False


def test_check_same_site_origin_no_headers(app):
    with app.test_request_context("/api/write", method="POST"):
        allowed, source = check_same_site_origin()
    assert allowed is True
    assert source == ""


def test_check_same_site_origin_foreign(app):
    with app.test_request_context(
        "/api/write", method="POST", headers={"Origin": "https://a.example"}
    ):
        allowed, source = check_same_site_origin()
    assert allowed is False
    assert source == "https://a.example"
