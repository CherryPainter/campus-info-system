#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气数据采集器
封装和风天气 API，支持实时天气、24小时预报、天气预警
使用 Ed25519 (EdDSA) 算法进行 JWT 签名
"""

import time
import base64
import requests
from typing import Dict, List, Optional
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.logger import get_logger

logger = get_logger(__name__)


def generate_qweather_jwt_ed25519(credential_id: str, project_id: str, private_key_path: str) -> str:
    """生成和风天气 JWT Token (Ed25519/EdDSA 算法)

    Args:
        credential_id: 凭据 ID (kid)
        project_id: 项目 ID (sub)
        private_key_path: Ed25519 私钥文件路径

    Returns:
        JWT Token 字符串
    """
    # 读取私钥
    with open(private_key_path, 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # 构造 Header
    header = {
        'alg': 'EdDSA',
        'kid': credential_id
    }

    # 构造 Payload
    now = int(time.time())
    payload = {
        'sub': project_id,
        'iat': now - 30,  # 提前30秒，防止时间误差
        'exp': now + 900  # 15分钟过期
    }

    # Base64URL 编码
    def base64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

    header_encoded = base64url_encode(str.encode(str(header).replace("'", '"')))
    payload_encoded = base64url_encode(str.encode(str(payload).replace("'", '"')))

    # 使用标准 JSON 序列化确保格式正确
    import json
    header_encoded = base64url_encode(json.dumps(header, separators=(',', ':')).encode())
    payload_encoded = base64url_encode(json.dumps(payload, separators=(',', ':')).encode())

    # 待签名数据
    signing_input = f"{header_encoded}.{payload_encoded}"

    # 使用 Ed25519 签名
    signature = private_key.sign(signing_input.encode())
    signature_encoded = base64url_encode(signature)

    # 组合 JWT
    return f"{signing_input}.{signature_encoded}"


class WeatherFetcher:
    """和风天气数据采集器

    封装和风天气 3 类 API:
    - /v7/weather/now  实时天气
    - /v7/weather/24h  24 小时逐时预报
    - /weatheralert/v1/current/{lat}/{lon}  天气预警

    使用 Ed25519 (EdDSA) 算法进行 JWT 身份认证
    """

    def __init__(
        self,
        api_key: str = '',
        api_host: str = 'https://devapi.qweather.com',
        location: str = '106.55,29.56',
        credential_id: str = '',
        project_id: str = '',
        private_key_path: str = '',
    ) -> None:
        """初始化采集器

        Args:
            api_key: 和风天气 API KEY (兼容旧版，不推荐使用)
            api_host: API 主机地址，默认开发环境
            location: 查询位置，支持 LocationID 或 "lat,lon" 格式
            credential_id: 凭据 ID (kid，JWT 认证用)
            project_id: 项目 ID (sub，JWT 认证用)
            private_key_path: Ed25519 私钥文件路径 (JWT 认证用)
        """
        self._credential_id = credential_id
        self._project_id = project_id
        self._private_key_path = private_key_path
        self._api_key = api_key  # 兼容旧版 API KEY
        self._api_host = api_host.rstrip('/')
        self._location = location

    def _get_jwt_token(self) -> str:
        """获取 JWT Token

        如果使用 Ed25519 私钥，则动态生成 JWT；
        否则使用 api_key 作为固定 token（兼容旧版）
        """
        if self._private_key_path and self._credential_id and self._project_id:
            return generate_qweather_jwt_ed25519(
                self._credential_id,
                self._project_id,
                self._private_key_path
            )
        return self._api_key

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def fetch_now(self) -> Optional[Dict]:
        """获取实时天气

        Returns:
            标准化 now 字典，API 失败时返回 None
        """
        url = f'{self._api_host}/v7/weather/now'
        params = {'location': self._location}
        headers = {'Authorization': f'Bearer {self._get_jwt_token()}'}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f'[天气] fetch_now 请求异常: {exc}')
            return None

        if data.get('code') != '200':
            logger.error(f'[天气] fetch_now API 返回错误: code={data.get("code")}, response={data}')
            return None

        now = data.get('now', {})
        from app.core.config import Config
        city_name = getattr(Config, 'QWEATHER_CITY_NAME', '')

        return {
            'city_name': city_name,
            'update_time': data.get('updateTime', ''),
            'temp': now.get('temp', ''),
            'feels_like': now.get('feelsLike', ''),
            'text': now.get('text', ''),
            'humidity': now.get('humidity', ''),
            'wind_dir': now.get('windDir', ''),
            'wind_scale': now.get('windScale', ''),
            'vis': now.get('vis', ''),
            'precip': now.get('precip', ''),
        }

    def fetch_hourly(self) -> List[Dict]:
        """获取 24 小时逐时预报

        Returns:
            hourly 列表，每项含 time/temp/text/pop/precip/humidity/wind_dir/wind_scale
            API 失败时返回空列表
        """
        url = f'{self._api_host}/v7/weather/24h'
        params = {'location': self._location}
        headers = {'Authorization': f'Bearer {self._get_jwt_token()}'}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f'[天气] fetch_hourly 请求异常: {exc}')
            return []

        if data.get('code') != '200':
            logger.error(f'[天气] fetch_hourly API 返回错误: code={data.get("code")}, response={data}')
            return []

        result = []
        for item in data.get('hourly', []):
            result.append({
                'time': item.get('fxTime', ''),
                'temp': item.get('temp', ''),
                'text': item.get('text', ''),
                'pop': item.get('pop', ''),
                'precip': item.get('precip', ''),
                'humidity': item.get('humidity', ''),
                'wind_dir': item.get('windDir', ''),
                'wind_scale': item.get('windScale', ''),
            })
        return result

    def fetch_alert(self) -> List[Dict]:
        """获取天气预警

        Returns:
            alerts 列表，每项含 headline/event_type/severity/description/
            color_code/effective_time/expire_time
            API 失败或无预警时返回空列表
        """
        # 从 location 解析经纬度 (格式: "longitude,latitude")
        loc_parts = self._location.split(',')
        if len(loc_parts) >= 2:
            longitude = loc_parts[0].strip()
            latitude = loc_parts[1].strip()
        else:
            # 默认使用重庆坐标
            longitude = '106.55'
            latitude = '29.56'

        url = f'{self._api_host}/weatheralert/v1/current/{latitude}/{longitude}'
        headers = {'Authorization': f'Bearer {self._get_jwt_token()}'}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f'[天气] fetch_alerts 请求异常: {exc}')
            return []

        # 预警 API 响应格式与天气 API 不同：
        # - 有预警时: {'alerts': [...]}
        # - 无预警时: {'metadata': {'zeroResult': True}, 'alerts': []}
        # - 错误时: {'error': {...}}
        if 'error' in data:
            logger.error(f'[天气] fetch_alerts API 返回错误: response={data}')
            return []

        result = []
        for alert in data.get('alerts', []):
            event_type_obj = alert.get('eventType', {})
            if isinstance(event_type_obj, dict):
                event_type_name = event_type_obj.get('name', '')
            else:
                event_type_name = str(event_type_obj)

            color_obj = alert.get('color', {})
            if isinstance(color_obj, dict):
                color_code = color_obj.get('code', '')
            else:
                color_code = str(color_obj)

            # 生成唯一ID：使用 API 返回的 id 或根据内容生成
            alert_id = alert.get('id', '')
            if not alert_id:
                # 如果没有 id，根据内容生成一个稳定的 ID
                alert_id = f"{alert.get('effectiveTime', '')}_{event_type_name}_{alert.get('headline', '')}"

            result.append({
                'id': alert_id,
                'headline': alert.get('headline', ''),
                'event_type': event_type_name,
                'severity': alert.get('severity', ''),
                'description': alert.get('description', ''),
                'color_code': color_code,
                'effective_time': alert.get('effectiveTime', ''),
                'expire_time': alert.get('expireTime', ''),
            })
        return result
