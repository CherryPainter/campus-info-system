#!/usr/bin/env python3
"""
出站 URL 安全校验（SSRF 防护）

背景
----
服务端会主动向「配置里填的 URL」发起请求（管理端 webhook 的测试与推送）。
前端校验可被绕过（直接调 API），所以服务端必须做同样的判断，否则一个管理员
（或被盗用的管理员令牌）就能让服务器去请求内网地址，把本机/内网当探针用。

校验项（逐条拒绝，错误文案可直接回给前端）
------------------------------------------
1. scheme 必须是允许的协议（默认仅 https）
2. 不允许 URL 内嵌用户名/密码（`https://user:pass@host/` 这类易被用于混淆真实目标）
3. 主机名不能是 localhost / *.local / *.internal 等本机与内网专用名
4. 主机若是 IP 字面量：必须是「公网可路由地址」（`ipaddress.is_global`），
   排除私网、回环、链路本地、保留、未指定、组播等
5. 可选域名白名单 `allowed_hosts`（命中即收口，不再做网段判断）
6. 可选 DNS 解析校验：域名解析出的**每个**地址都必须是公网可路由地址，
   防止「域名指向内网」绕过第 4 条

逃生舱
------
确有指向内网中转服务的合法需求时，用环境变量 `WEBHOOK_URL_ALLOWED_HOSTS`
（逗号分隔的精确主机名）显式放行，不使用「猜默认值」的方式放宽：

    WEBHOOK_URL_ALLOWED_HOSTS=intranet-relay.campus.local

已知残余风险（本模块解决不了，需网络层）
----------------------------------------
- **DNS Rebinding**：保存时解析到公网、真正发送时解析到内网。彻底防护要靠出站
  防火墙 / 正向代理白名单，应用层只能挡住「明显」的目标。
- 本模块只做静态与解析层面的校验，不改变实际发送逻辑（发送仍由 requests 完成）。
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

from app.core.logger import get_logger

logger = get_logger(__name__)

# 本机 / 内网专用主机名（不区分大小写）
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
}

# 内网专用后缀（RFC 6761 / RFC 8375 等）
_BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".home.arpa",
)

# 逃生舱：显式放行的主机名（精确匹配，逗号分隔）
_URL_GUARD_ALLOWED_HOSTS_ENV = "WEBHOOK_URL_ALLOWED_HOSTS"


def _allowed_hosts_override() -> set:
    """读取环境变量里显式放行的主机名（精确匹配）。"""
    raw = os.getenv(_URL_GUARD_ALLOWED_HOSTS_ENV, "") or ""
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _parse_ip(host: str):
    """把主机名解析成 ipaddress 对象；不是 IP 字面量则返回 None。"""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _resolve_host_ips(host: str, port: int) -> set:
    """解析域名得到全部 IP（字符串集合）。

    单独抽成函数，便于测试替换（避免测试真发 DNS 请求）。
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addrs = set()
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0]:
            # IPv6 可能带 zone id（fe80::1%eth0），取其前面的地址部分
            addrs.add(str(sockaddr[0]).split("%")[0])
    return addrs


def validate_outbound_url(
    url,
    *,
    allowed_schemes=("https",),
    allowed_hosts=None,
    resolve_dns: bool = True,
    label: str = "URL",
):
    """
    校验一个「服务端将要请求」的 URL。

    Args:
        url: 待校验 URL
        allowed_schemes: 允许的协议（小写），默认仅 https
        allowed_hosts: 可选主机名白名单（精确匹配）；给定后只放行这些主机，
            并跳过后续网段判断（白名单本身已足够收口）
        resolve_dns: 是否解析域名并校验解析结果（默认 True）。
            测试里应传 False 或替换 `_resolve_host_ips`，避免真发 DNS 请求。
        label: 错误文案里的字段名（如 "Webhook URL"）

    Returns:
        (ok, error_message)：ok 为 True 时 error_message 为 None；
        否则 error_message 是可直接回给前端的中文原因。
    """
    if not isinstance(url, str) or not url.strip():
        return False, f"{label} 不能为空"

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return False, f"{label} 格式非法"

    scheme = (parsed.scheme or "").lower()
    schemes = tuple(s.lower() for s in allowed_schemes)
    if scheme not in schemes:
        return False, f"{label} 必须以 {'/'.join(schemes)}:// 开头"

    if parsed.username or parsed.password:
        return False, f"{label} 不能包含用户名或密码"

    host = (parsed.hostname or "").lower()
    if not host:
        return False, f"{label} 缺少主机名"

    # 主机名白名单：命中即收口（调用方明确知道允许哪些主机，无需再判网段）
    if allowed_hosts is not None:
        allowed = {h.lower() for h in allowed_hosts}
        if host not in allowed:
            return False, f"{label} 仅支持 {'、'.join(sorted(allowed))}"
        return True, None

    # 逃生舱：显式放行的主机
    if host in _allowed_hosts_override():
        return True, None

    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False, f"{label} 不能指向本机或内网域名（{host}）"

    # IP 字面量：必须是公网可路由地址
    ip = _parse_ip(host)
    if ip is not None:
        if not ip.is_global:
            return False, f"{label} 不能使用内网或保留地址（{host}）"
        return True, None

    if not resolve_dns:
        return True, None

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return False, f"{label} 端口非法"

    try:
        addrs = _resolve_host_ips(host, port)
    except socket.gaierror:
        return False, f"{label} 域名无法解析（{host}）"
    except Exception as exc:  # 解析器异常，按失败处理，避免放行未知目标
        logger.warning(f"[URL 校验] 解析 {host} 失败: {exc}")
        return False, f"{label} 域名解析失败（{host}）"

    if not addrs:
        return False, f"{label} 域名无法解析（{host}）"

    for addr in sorted(addrs):
        ip_obj = _parse_ip(addr)
        if ip_obj is None or not ip_obj.is_global:
            return False, f"{label} 解析到内网或保留地址（{host} → {addr}）"

    return True, None
