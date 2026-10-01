#!/usr/bin/env python3
"""
天气数据采集器
封装和风天气 API，支持实时天气、24小时预报、天气预警
使用 Ed25519 (EdDSA) 算法进行 JWT 签名
"""

import base64
import time

import requests
from cryptography.hazmat.primitives import serialization

from app.core.logger import get_logger

logger = get_logger(__name__)


def generate_qweather_jwt_ed25519(
    credential_id: str, project_id: str, private_key_path: str
) -> str:
    """生成和风天气 JWT Token (Ed25519/EdDSA 算法)

    Args:
        credential_id: 凭据 ID (kid)
        project_id: 项目 ID (sub)
        private_key_path: Ed25519 私钥文件路径

    Returns:
        JWT Token 字符串
    """
    # 读取私钥
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # 构造 Header
    header = {"alg": "EdDSA", "kid": credential_id}

    # 构造 Payload
    now = int(time.time())
    payload = {
        "sub": project_id,
        "iat": now - 30,  # 提前30秒，防止时间误差
        "exp": now + 900,  # 15分钟过期
    }

    # Base64URL 编码
    def base64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_encoded = base64url_encode(str.encode(str(header).replace("'", '"')))
    payload_encoded = base64url_encode(str.encode(str(payload).replace("'", '"')))

    # 使用标准 JSON 序列化确保格式正确
    import json

    header_encoded = base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_encoded = base64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    # 待签名数据
    signing_input = f"{header_encoded}.{payload_encoded}"

    # 使用 Ed25519 签名
    signature = private_key.sign(signing_input.encode())
    signature_encoded = base64url_encode(signature)

    # 组合 JWT
    return f"{signing_input}.{signature_encoded}"


class WeatherFetcher:
    """和风天气数据采集器

    封装和风天气 7 类 API:
    - /v7/weather/now                      实时天气
    - /v7/weather/24h                      24 小时逐时预报
    - /weatheralert/v1/current/{lat}/{lon} 天气预警
    - /v7/weather/{n}d                     逐天预报（默认 7 天）
    - /v7/indices/1d                       生活指数
    - /airquality/v1/current/{lat}/{lon}   实时空气质量 AQI
    - /v7/minutely/5m                      分钟级降水

    使用 Ed25519 (EdDSA) 算法进行 JWT 身份认证
    """

    def __init__(
        self,
        api_key: str = "",
        api_host: str = "",
        location: str = "106.55,29.56",
        credential_id: str = "",
        project_id: str = "",
        private_key_path: str = "",
    ) -> None:
        """初始化采集器

        Args:
            api_key: 和风天气 API KEY (兼容旧版，不推荐使用)
            api_host: 和风天气账号专属 API Host（非公共域名，控制台「设置」页查看）
            location: 查询位置，支持 LocationID 或 "lat,lon" 格式
            credential_id: 凭据 ID (kid，JWT 认证用)
            project_id: 项目 ID (sub，JWT 认证用)
            private_key_path: Ed25519 私钥文件路径 (JWT 认证用)
        """
        self._credential_id = credential_id
        self._project_id = project_id
        self._private_key_path = private_key_path
        self._api_key = api_key  # 兼容旧版 API KEY
        self._api_host = api_host.rstrip("/")
        self._location = location

    def _get_jwt_token(self) -> str:
        """获取 JWT Token

        如果使用 Ed25519 私钥，则动态生成 JWT；
        否则使用 api_key 作为固定 token（兼容旧版）
        """
        if self._private_key_path and self._credential_id and self._project_id:
            return generate_qweather_jwt_ed25519(
                self._credential_id, self._project_id, self._private_key_path
            )
        return self._api_key

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def fetch_now(self) -> dict | None:
        """获取实时天气

        Returns:
            标准化 now 字典，API 失败时返回 None
        """
        url = f"{self._api_host}/v7/weather/now"
        params = {"location": self._location}
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_now 请求异常: {exc}")
            return None

        if data.get("code") != "200":
            logger.error(f'[天气] fetch_now API 返回错误: code={data.get("code")}, response={data}')
            return None

        now = data.get("now", {})
        from app.core.config import Config

        city_name = getattr(Config, "QWEATHER_CITY_NAME", "")

        return {
            "city_name": city_name,
            "update_time": data.get("updateTime", ""),
            "temp": now.get("temp", ""),
            "feels_like": now.get("feelsLike", ""),
            "text": now.get("text", ""),
            "humidity": now.get("humidity", ""),
            "wind_dir": now.get("windDir", ""),
            "wind_scale": now.get("windScale", ""),
            "vis": now.get("vis", ""),
            "precip": now.get("precip", ""),
        }

    def fetch_hourly(self) -> list[dict]:
        """获取 24 小时逐时预报

        Returns:
            hourly 列表，每项含 time/temp/text/pop/precip/humidity/wind_dir/wind_scale
            API 失败时返回空列表
        """
        url = f"{self._api_host}/v7/weather/24h"
        params = {"location": self._location}
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_hourly 请求异常: {exc}")
            return []

        if data.get("code") != "200":
            logger.error(
                f'[天气] fetch_hourly API 返回错误: code={data.get("code")}, response={data}'
            )
            return []

        result = []
        for item in data.get("hourly", []):
            result.append(
                {
                    "time": item.get("fxTime", ""),
                    "temp": item.get("temp", ""),
                    "text": item.get("text", ""),
                    "pop": item.get("pop", ""),
                    "precip": item.get("precip", ""),
                    "humidity": item.get("humidity", ""),
                    "wind_dir": item.get("windDir", ""),
                    "wind_scale": item.get("windScale", ""),
                }
            )
        return result

    def fetch_alert(self) -> list[dict]:
        """获取天气预警

        Returns:
            alerts 列表，每项含 headline/event_type/severity/description/
            color_code/effective_time/expire_time
            API 失败或无预警时返回空列表
        """
        # 从 location 解析经纬度 (格式: "longitude,latitude")
        loc_parts = self._location.split(",")
        if len(loc_parts) >= 2:
            longitude = loc_parts[0].strip()
            latitude = loc_parts[1].strip()
        else:
            # 默认使用重庆坐标
            longitude = "106.55"
            latitude = "29.56"

        url = f"{self._api_host}/weatheralert/v1/current/{latitude}/{longitude}"
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_alerts 请求异常: {exc}")
            return []

        # 预警 API 响应格式与天气 API 不同：
        # - 有预警时: {'alerts': [...]}
        # - 无预警时: {'metadata': {'zeroResult': True}, 'alerts': []}
        # - 错误时: {'error': {...}}
        if "error" in data:
            logger.error(f"[天气] fetch_alerts API 返回错误: response={data}")
            return []

        result = []
        for alert in data.get("alerts", []):
            event_type_obj = alert.get("eventType", {})
            if isinstance(event_type_obj, dict):
                event_type_name = event_type_obj.get("name", "")
            else:
                event_type_name = str(event_type_obj)

            color_obj = alert.get("color", {})
            if isinstance(color_obj, dict):
                color_code = color_obj.get("code", "")
            else:
                color_code = str(color_obj)

            # 生成唯一ID：使用 API 返回的 id 或根据内容生成
            alert_id = alert.get("id", "")
            if not alert_id:
                # 如果没有 id，根据内容生成一个稳定的 ID
                alert_id = f"{alert.get('effectiveTime', '')}_{event_type_name}_{alert.get('headline', '')}"

            result.append(
                {
                    "id": alert_id,
                    "headline": alert.get("headline", ""),
                    "event_type": event_type_name,
                    "severity": alert.get("severity", ""),
                    "description": alert.get("description", ""),
                    "color_code": color_code,
                    "effective_time": alert.get("effectiveTime", ""),
                    "expire_time": alert.get("expireTime", ""),
                }
            )
        return result

    def fetch_daily(self, days: int = 7) -> list[dict]:
        """获取逐天预报（默认 7 天）

        Returns:
            列表，每项含 fx_date/temp_max/temp_min/text_day/text_night/pop 等
            API 失败时返回空列表
        """
        url = f"{self._api_host}/v7/weather/{days}d"
        params = {"location": self._location}
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_daily 请求异常: {exc}")
            return []

        if data.get("code") != "200":
            logger.error(
                f'[天气] fetch_daily API 返回错误: code={data.get("code")}, response={data}'
            )
            return []

        result = []
        for d in data.get("daily", []):
            result.append(
                {
                    "fx_date": d.get("fxDate", ""),
                    "temp_max": d.get("tempMax", ""),
                    "temp_min": d.get("tempMin", ""),
                    "text_day": d.get("textDay", ""),
                    "text_night": d.get("textNight", ""),
                    "icon_day": d.get("iconDay", ""),
                    "pop": d.get("precipProb", "") or d.get("pop", ""),
                    "wind_dir_day": d.get("windDirDay", ""),
                    "wind_scale_day": d.get("windScaleDay", ""),
                }
            )
        return result

    def fetch_indices(self, types: str = "1,2,3,5,8,9,14,15,16") -> list[dict]:
        """获取生活指数（默认常用一组）

        Args:
            types: 指数类型，逗号分隔
                   （1 穿衣 / 2 洗车 / 3 感冒 / 5 运动 / 8 紫外线 /
                    9 空调 / 12 防晒 / 13 钓鱼 / 15 晾晒）

        Returns:
            列表，每项含 type/name/category/text
            API 失败时返回空列表
        """
        url = f"{self._api_host}/v7/indices/1d"
        params = {"location": self._location, "type": types}
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_indices 请求异常: {exc}")
            return []

        if data.get("code") != "200":
            logger.error(
                f'[天气] fetch_indices API 返回错误: code={data.get("code")}, response={data}'
            )
            return []

        result = []
        # 和风 /v7/indices/1d 返回字段为 daily（实测，非 indices）
        for it in data.get("daily", data.get("indices", [])):
            result.append(
                {
                    "type": it.get("type", ""),
                    "name": it.get("name", ""),
                    "category": it.get("category", ""),
                    "text": it.get("text", ""),
                }
            )
        return result

    def fetch_airquality(self) -> dict | None:
        """获取实时空气质量（AQI，和风 GeoAPI /airquality/v1/current/{lat}/{lon}）

        注意：和风空气质量走 GeoAPI v1 风格（与 weatheralert 同系列），
        而非 /v7/airquality/now。成功返回可能为 {"now": {...}} 或顶层扁平，
        此处两者兼容。

        Returns:
            标准化字典（aqi/category/primary/level/pm2p5/pm10/update_time）
            API 失败时返回 None
        """
        # 从 location 解析经纬度 (格式: "longitude,latitude")
        loc_parts = self._location.split(",")
        if len(loc_parts) >= 2:
            longitude = loc_parts[0].strip()
            latitude = loc_parts[1].strip()
        else:
            longitude = "106.55"
            latitude = "29.56"

        url = f"{self._api_host}/airquality/v1/current/{latitude}/{longitude}"
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_airquality 请求异常: {exc}")
            return None

        # GeoAPI 风格：错误时返回 {"error": {...}}（无 code 字段）
        if "error" in data:
            logger.error(f"[天气] fetch_airquality API 返回错误: response={data}")
            return None

        # 和风 GeoAPI v1 空气质量返回结构：indexes[]（aqi/category/level/primaryPollutant）
        # + pollutants[]（pm2p5/pm10 等，浓度在 concentration.value）
        # 顶层无 now 字段，故不从 data.now 取值
        indexes = data.get("indexes", [])
        idx0 = indexes[0] if indexes else {}
        pollutants = {p.get("code"): p for p in data.get("pollutants", [])}
        pm25 = pollutants.get("pm2p5", {}).get("concentration", {}).get("value", "")
        pm10 = pollutants.get("pm10", {}).get("concentration", {}).get("value", "")
        return {
            "aqi": idx0.get("aqi", ""),
            "category": idx0.get("category", ""),
            "primary": idx0.get("primaryPollutant") or "",
            "level": idx0.get("level", ""),
            "pm2p5": pm25,
            "pm10": pm10,
            "update_time": data.get("updateTime", ""),
        }

    def fetch_minutely(self) -> dict | None:
        """获取分钟级降水（未来 1-2 小时，每 5 分钟粒度）

        Returns:
            字典 { summary, minutely: [{fx_time, precip, type}] }
            API 失败时返回 None
        """
        url = f"{self._api_host}/v7/minutely/5m"
        params = {"location": self._location}
        headers = {"Authorization": f"Bearer {self._get_jwt_token()}"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as exc:
            logger.error(f"[天气] fetch_minutely 请求异常: {exc}")
            return None

        if data.get("code") != "200":
            logger.error(
                f'[天气] fetch_minutely API 返回错误: code={data.get("code")}, response={data}'
            )
            return None

        return {
            "summary": data.get("summary", ""),
            "minutely": [
                {
                    "fx_time": m.get("fxTime", ""),
                    "precip": m.get("precip", ""),
                    "type": m.get("type", ""),
                }
                for m in data.get("minutely", [])
            ],
        }
