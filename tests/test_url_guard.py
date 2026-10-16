#!/usr/bin/env python3
"""
出站 URL 安全校验（SSRF 防护）单元测试（2026-10-01）

对象：`app/utils/url_guard.py` 的 `validate_outbound_url()` —— 服务端准备发起出站请求
前对目标 URL 的校验（管理端 webhook 创建/编辑/测试三处都走它）。

不联网：DNS 解析被替换为桩函数（`_resolve_host_ips`），因此「解析到内网」
「解析失败」这类分支也能确定性覆盖。

运行：
    cd Push_System_Flask && python -m pytest tests/test_url_guard.py -v
"""

import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.url_guard import validate_outbound_url


@pytest.fixture
def public_dns(monkeypatch):
    """默认：域名解析到公网地址（测试保持离线、结果确定）"""
    monkeypatch.setattr(
        "app.utils.url_guard._resolve_host_ips", lambda host, port: {"1.2.3.4"}
    )


def _reject(url, **kw):
    ok, err = validate_outbound_url(url, **kw)
    assert ok is False, f"{url} 本应被拒绝"
    assert err, "拒绝时必须给出原因文案"
    return err


def _accept(url, **kw):
    ok, err = validate_outbound_url(url, **kw)
    assert ok is True, f"{url} 本应放行，实际：{err}"
    assert err is None


# ==================== 协议 / 凭据 ====================


def test_rejects_non_https(public_dns):
    assert "https://" in _reject("http://example.com/hook")


def test_rejects_embedded_credentials(public_dns):
    """https://user:pass@host/ 这类写法常被用来混淆真实目标"""
    assert "用户名或密码" in _reject("https://user:pass@example.com/hook")


def test_rejects_empty_url():
    _reject("")
    _reject("   ")
    _reject(None)


def test_rejects_missing_hostname(public_dns):
    _reject("https:///hook")


# ==================== 本机 / 内网 ====================


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://127.1.2.3/hook",
        "https://10.1.2.3/hook",
        "https://172.16.5.5/hook",
        "https://192.168.0.1/hook",
        "https://169.254.169.254/latest/meta-data/",  # 云元数据服务
        "https://0.0.0.0/hook",
        "https://[::1]/hook",
        "https://[fe80::1]/hook",
        "https://[fc00::1]/hook",
    ],
)
def test_rejects_private_and_reserved_ip_literals(public_dns, url):
    assert "内网或保留地址" in _reject(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/hook",
        "https://LOCALHOST/hook",
        "https://foo.local/hook",
        "https://db.internal/hook",
        "https://x.home.arpa/hook",
        "https://metadata.google.internal/hook",
    ],
)
def test_rejects_internal_hostnames(public_dns, url):
    assert "本机或内网域名" in _reject(url)


def test_accepts_public_ip_literal(public_dns):
    """公网 IP 字面量应放行（不强制要求域名）"""
    _accept("https://8.8.8.8/hook")
    _accept("https://[2001:4860:4860::8888]/hook")


# ==================== DNS 解析 ====================


def test_rejects_domain_resolving_to_private(monkeypatch):
    """域名指向内网：即使字面量正常也要拒（防「域名绕过网段判断」）"""
    monkeypatch.setattr(
        "app.utils.url_guard._resolve_host_ips", lambda host, port: {"10.0.0.8"}
    )
    assert "解析到内网" in _reject("https://relay.example.com/hook")


def test_rejects_when_any_resolved_address_is_private(monkeypatch):
    """多 A 记录里只要有一条是内网地址，整体拒绝"""
    monkeypatch.setattr(
        "app.utils.url_guard._resolve_host_ips",
        lambda host, port: {"1.2.3.4", "192.168.1.1"},
    )
    assert "解析到内网" in _reject("https://relay.example.com/hook")


def test_rejects_dns_failure(monkeypatch):
    """解析失败按 fail-closed 处理（未知目标不放行）"""

    def _boom(host, port):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr("app.utils.url_guard._resolve_host_ips", _boom)
    assert "无法解析" in _reject("https://no-such-host.example/hook")


def test_rejects_empty_dns_result(monkeypatch):
    monkeypatch.setattr("app.utils.url_guard._resolve_host_ips", lambda host, port: set())
    assert "无法解析" in _reject("https://no-such-host.example/hook")


def test_resolve_dns_false_skips_resolution(monkeypatch):
    """显式关闭解析时不做 DNS，但静态检查照旧"""

    def _boom(host, port):
        raise AssertionError("不应触发 DNS 解析")

    monkeypatch.setattr("app.utils.url_guard._resolve_host_ips", _boom)
    _accept("https://relay.example.com/hook", resolve_dns=False)
    _reject("https://10.0.0.1/hook", resolve_dns=False)


def test_accepts_public_domain(public_dns):
    _accept("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc")


# ==================== 白名单 / 逃生舱 ====================


def test_allowed_hosts_whitelist():
    """给定主机白名单时只放行名单内主机，其余直接拒（不再做网段判断）"""
    _accept("https://qyapi.weixin.qq.com/hook", allowed_hosts={"qyapi.weixin.qq.com"})
    assert "仅支持" in _reject(
        "https://evil.example.com/hook", allowed_hosts={"qyapi.weixin.qq.com"}
    )
    # 后缀伪装不得命中
    assert "仅支持" in _reject(
        "https://qyapi.weixin.qq.com.evil.example.com/hook",
        allowed_hosts={"qyapi.weixin.qq.com"},
    )


def test_env_escape_hatch(monkeypatch):
    """确需指向内网中转时，用环境变量显式放行（精确匹配，不隐式放宽）"""
    monkeypatch.setenv("WEBHOOK_URL_ALLOWED_HOSTS", "relay.campus.local,other.local")
    _accept("https://relay.campus.local/hook")
    _accept("https://relay.campus.local:8443/hook")
    # 未列入的主机仍被拦
    _reject("https://another.campus.local/hook")


def test_env_escape_hatch_is_exact_match(monkeypatch):
    monkeypatch.setenv("WEBHOOK_URL_ALLOWED_HOSTS", "relay.campus.local")
    _reject("https://relay.campus.local.evil.example.com/hook")
