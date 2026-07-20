"""IP 地理解析服务（境外拦截用）。

基于本地 ip2region 离线库（ip2region_v4.xdb）判断 IP 所属国家，
用于「仅允许中国 IP 访问」的防火墙策略。整库载入内存，线程安全、无外部网络依赖。

数据文件：项目根目录 ip2region.xdb（与 vendored 的 ip2region 包同层）
解析引擎：Push_System_Flask/ip2region（官方 Python 绑定，已 vendoring 进仓库，含 LICENSE）
"""

import ipaddress
import logging
import threading
from pathlib import Path

from ip2region import util
from ip2region.searcher import new_with_buffer

logger = logging.getLogger(__name__)

# 数据文件位置：本文件在 app/services/，向上两级即项目根 Push_System_Flask
_DB_PATH = Path(__file__).resolve().parents[2] / "ip2region.xdb"

_searcher = None
_init_lock = threading.Lock()

# IP -> 是否中国 IP 的缓存，避免重复查询
_cache = {}
_CACHE_MAX = 20000


def _is_private_or_local(ip: str) -> bool:
    """私有/本地/保留地址一律视为可放行（含内网、回环、链路本地等）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


def _get_searcher():
    """懒加载 Searcher 单例（整库载入内存，线程安全）。

    返回 None 表示数据库不可用，此时调用方应降级放行，避免误杀全站。
    """
    global _searcher
    if _searcher is not None:
        return _searcher
    with _init_lock:
        if _searcher is not None:
            return _searcher
        if not _DB_PATH.exists():
            logger.critical("ip2region 数据库缺失: %s，境外拦截降级为放行", _DB_PATH)
            return None
        try:
            c_buffer = util.load_content_from_file(str(_DB_PATH))
            header = util.load_header_from_file(str(_DB_PATH))
            version = util.version_from_header(header)
            if version is None:
                logger.critical("无法识别 ip2region 数据库版本，境外拦截降级为放行")
                return None
            _searcher = new_with_buffer(version, c_buffer)
            logger.info(
                "ip2region 离线库已加载（%s，%.1f MB）", _DB_PATH.name, len(c_buffer) / 1024 / 1024
            )
        except Exception as e:
            logger.critical("加载 ip2region 数据库失败: %s，境外拦截降级为放行", e)
            return None
        return _searcher


def _cache_set(ip: str, value: bool) -> None:
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[ip] = value


def is_china_ip(ip: str) -> bool:
    """判断是否为中国 IP。

    返回 True 表示中国/本地/异常降级放行；False 表示境外/未知（应被拦截）。
    策略（fail-closed）：只有明确为中国 IP 才放行，其余一律视为境外。
    """
    if not ip:
        return False
    ip = ip.strip()

    # 1. 私有/本地地址直接放行
    if _is_private_or_local(ip):
        return True

    # 2. 缓存命中直接返回
    cached = _cache.get(ip)
    if cached is not None:
        return cached

    # 3. IPv6 无法用 v4 库判定，按境外处理（fail-closed）
    try:
        if ipaddress.ip_address(ip).version == 6:
            _cache_set(ip, False)
            return False
    except ValueError:
        # 非法 IP 字符串，按境外拦截
        _cache_set(ip, False)
        return False

    # 4. 查询离线库
    searcher = _get_searcher()
    if searcher is None:
        # 数据库不可用：降级放行，避免把全站打死
        return True
    try:
        region = searcher.search(ip)
    except Exception as e:
        logger.error("ip2region 查询异常 %s: %s，降级放行", ip, e)
        return True

    if not region:
        result = False
    else:
        country = region.split("|")[0].strip()
        result = country == "中国"
    _cache_set(ip, result)
    return result
