#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电表数据爬虫模块
从重庆工程学院电表系统（dk.cqie.cn）采集用电记录与剩余电量
"""

import re
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from app.core.logger import get_logger

logger = get_logger(__name__)

# 电量爬虫全局状态
_electricity_spider_status = {
    'running': False,
    'last_run': None,
    'last_status': None,
}

_DEFAULT_UA = (
    'Mozilla/5.0 (Linux; Android 11; V2123A Build/RP1A.200720.012; wv) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.177 '
    'Mobile Safari/537.36 XWEB/1460075 MMWEBSDK/20260101 MMWEBID/6548 '
    'MicroMessenger/8.0.69.3040(0x28004530) WeChat/arm64 Weixin NetType/4G '
    'Language/zh_CN ABI/arm64'
)


class ElectricityCrawler:
    """电表数据爬虫，采集用电记录与剩余电量"""

    def __init__(
        self,
        base_url: str = 'http://dk.cqie.cn',
        cookie: str = '',
        user_agent: str = _DEFAULT_UA,
        max_pages: int = 50,
        timeout: int = 15,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self._cookie = cookie
        self.user_agent = user_agent
        self.max_pages = max_pages
        self.timeout = timeout
        self._session = requests.Session()
        self._update_session_headers()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def set_cookie(self, cookie: str) -> None:
        """运行时更新 Cookie（动态接口调用后立即生效）"""
        self._cookie = cookie
        self._update_session_headers()
        logger.info('ElectricityCrawler: Cookie 已更新')

    def fetch_remaining_power(self) -> Dict[str, float]:
        """
        获取各电表剩余电量

        Returns:
            {'default': float}，失败返回 {}
        """
        url = f'{self.base_url}/pay/home'
        try:
            resp = self._session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return self._parse_remaining_power(resp.text)
        except requests.exceptions.Timeout:
            logger.error('fetch_remaining_power: 请求超时')
        except requests.exceptions.RequestException as exc:
            logger.error(f'fetch_remaining_power: 请求异常 {exc}')
        except Exception as exc:
            logger.exception(f'fetch_remaining_power: 未知错误 {exc}')
        return {}

    def fetch_usage_records(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        分页爬取用电记录

        Args:
            max_pages: 最大爬取页数，None 时使用初始化值

        Returns:
            用电记录列表，每条记录含 time / usage / meter 字段
        """
        pages = max_pages or self.max_pages
        all_records: List[Dict] = []
        last_page_with_data = 0

        for page in range(1, pages + 1):
            try:
                records = self._fetch_page(page)
                if not records:
                    logger.info(f'第 {page} 页无数据，停止翻页（已累计 {len(all_records)} 条记录）')
                    break
                all_records.extend(records)
                last_page_with_data = page
                logger.info(f'第 {page} 页获取 {len(records)} 条记录（累计 {len(all_records)} 条）')

                # 只有当返回空数据时才停止，不再根据记录数判断是否最后一页
                # 因为学校API可能每页返回的记录数不固定
                if page < pages:
                    time.sleep(0.5)  # 减少等待时间，加快爬取

                # 安全保护：如果单页返回异常多的记录，可能是解析错误，暂停检查
                if len(records) > 100:
                    logger.warning(f'第 {page} 页返回 {len(records)} 条记录，数量异常，请检查解析逻辑')

            except Exception as exc:
                logger.error(f'第 {page} 页爬取失败: {exc}')
                break

        total_pages_fetched = min(last_page_with_data, pages) if last_page_with_data > 0 else 0
        if max_pages is not None and total_pages_fetched < max_pages and total_pages_fetched > 0:
            logger.warning(
                f'[电量] 爬取提前结束: 请求 {max_pages} 页但仅获取 {total_pages_fetched} 页有效数据。'
                f'可能原因: 1) 学校API确实只有 {total_pages_fetched} 页数据; '
                f'2) 第 {total_pages_fetched + 1} 页返回格式变化导致解析失败; '
                f'3) 需要检查 Cookie 是否有足够权限访问历史数据'
            )

        logger.info(f'fetch_usage_records: 共获取 {len(all_records)} 条记录（实际爬取 {max(last_page_with_data, 0)} 页，请求上限 {pages} 页）')
        return all_records

    def check_cookie_valid(self) -> Tuple[bool, str]:
        """
        检测当前 Cookie 是否仍然有效

        Returns:
            (is_valid, reason)
        """
        if not self._cookie:
            return False, 'Cookie 未配置'

        url = f'{self.base_url}/home'
        try:
            resp = self._session.get(url, timeout=self.timeout, allow_redirects=False)
            if resp.status_code in (301, 302, 303):
                return False, f'Cookie 已失效，被重定向（{resp.status_code}）'
            if resp.status_code == 200:
                login_kws = ['登录', 'login', 'signin', '用户名', 'password']
                if any(kw in resp.text.lower() for kw in login_kws):
                    return False, 'Cookie 已失效，页面返回登录页'
                return True, 'Cookie 有效'
            return False, f'Cookie 检测异常: HTTP {resp.status_code}'
        except requests.exceptions.Timeout:
            return False, 'Cookie 检测超时'
        except requests.exceptions.RequestException as exc:
            return False, f'Cookie 检测连接失败: {exc}'

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _update_session_headers(self) -> None:
        self._session.headers.update({
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7'
            ),
            'X-Requested-With': 'com.tencent.mm',
            'Referer': f'{self.base_url}/home',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cookie': self._cookie,
        })

    def _fetch_page(self, page_num: int) -> List[Dict]:
        """获取指定页的用电记录"""
        url = f'{self.base_url}/use/record/{page_num}'
        logger.debug(f'请求第 {page_num} 页: {url}')
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        logger.debug(f'第 {page_num} 页响应长度: {len(resp.text)} 字符')
        # 优先尝试 JSON 解析，失败则回退到 HTML
        try:
            records = self._parse_json(resp.text)
        except Exception:
            records = self._parse_html(resp.text)
        logger.debug(f'第 {page_num} 页解析结果: {len(records)} 条记录')
        return records

    def _parse_remaining_power(self, html: str) -> Dict[str, float]:
        """从 /pay/home 页面解析剩余电量"""
        pattern = r'剩余购电[^<]*</div>\s*<div[^>]*class="item-after"[^>]*>([\d.]+)度</div>'
        m = re.search(pattern, html)
        if m:
            value = float(m.group(1))
            logger.info(f'解析剩余电量: {value} 度')
            return {'default': value}

        # 备用：BeautifulSoup 扫描 item-after
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for elem in soup.find_all('div', class_='item-after'):
                text = elem.get_text(strip=True)
                nm = re.search(r'([\d.]+)度', text)
                if nm:
                    value = float(nm.group(1))
                    logger.info(f'备用方案解析剩余电量: {value} 度')
                    return {'default': value}
        except Exception as exc:
            logger.warning(f'BeautifulSoup 解析剩余电量失败: {exc}')

        logger.warning('未能解析到剩余电量')
        return {}

    def _parse_json(self, text: str) -> List[Dict]:
        """从 JSON 响应中提取用电记录"""
        # 匹配 ["时间",数值,"电表名","电表"] 格式
        pattern = r'\["([^"]+)",([0-9.]+),"([^"]+)","([^"]+)"\]'
        matches = re.findall(pattern, text)
        if not matches:
            raise ValueError('未找到 JSON 格式用电记录')
        records = []
        for time_str, usage_str, meter_name, meter_type in matches:
            records.append({
                'time': time_str,
                'usage': float(usage_str),
                'meter': f'{meter_type}: {meter_name}',
            })
        return records

    def _parse_html(self, html: str) -> List[Dict]:
        """从 HTML 响应中提取用电记录（备用）"""
        records = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for item in soup.find_all('li', class_='item-content'):
                if not item.find('div', class_='item-subtitle'):
                    continue
                record: Dict = {}
                time_elem = item.find('div', class_='item-title')
                if time_elem:
                    record['time'] = time_elem.get_text(strip=True)
                usage_elem = item.find('div', class_='item-after')
                if usage_elem:
                    usage_text = usage_elem.get_text(strip=True)
                    num = ''.join(c for c in usage_text if c.isdigit() or c == '.')
                    record['usage'] = float(num) if num else 0.0
                meter_elem = item.find('div', class_='item-subtitle')
                if meter_elem:
                    record['meter'] = meter_elem.get_text(strip=True)
                if all(k in record for k in ('time', 'usage', 'meter')):
                    records.append(record)
        except Exception as exc:
            logger.warning(f'HTML 解析用电记录失败: {exc}')
        return records


# ------------------------------------------------------------------
# 全局状态管理
# ------------------------------------------------------------------

def get_electricity_spider_status():
    """获取电量爬虫状态"""
    return _electricity_spider_status.copy()


def set_electricity_spider_running(running: bool, status: str = None):
    """设置电量爬虫运行状态"""
    _electricity_spider_status['running'] = running
    if not running:
        _electricity_spider_status['last_run'] = datetime.now().isoformat()
        _electricity_spider_status['last_status'] = status or 'completed'
