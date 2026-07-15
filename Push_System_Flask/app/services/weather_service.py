#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气业务服务

职责：
- 天气数据获取与存储业务逻辑
- 天气分析与推送业务逻辑
- 协调 Repository 完成数据操作
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from app.core.database import get_db
from app.repository.weather_repository import WeatherRepository
from app.modules.weather.fetcher import WeatherFetcher

logger = logging.getLogger(__name__)


class WeatherService:
    """
    天气业务服务类

    封装所有天气相关的业务逻辑
    """

    def __init__(self, fetcher: Optional[WeatherFetcher] = None) -> None:
        """
        初始化服务

        Args:
            fetcher: 天气数据获取器，为 None 时自动创建
        """
        self._fetcher = fetcher

    def _get_fetcher(self) -> WeatherFetcher:
        """获取或创建 fetcher"""
        if self._fetcher is None:
            from app.modules.weather.tasks import _make_fetcher
            self._fetcher = _make_fetcher()
        return self._fetcher

    def fetch_and_save_now(self, city_name: str = '重庆') -> Optional[Dict[str, Any]]:
        """
        获取并保存实时天气

        Args:
            city_name: 城市名称

        Returns:
            Optional[Dict]: 保存的天气数据或 None
        """
        try:
            fetcher = self._get_fetcher()
            data = fetcher.fetch_now()

            if not data:
                logger.warning('[WeatherService] 获取实时天气失败')
                return None

            session = get_db()
            try:
                # 清理所有旧数据
                deleted = WeatherRepository.delete_all_now_records(
                    session=session,
                    city_name=data.get('city_name', city_name),
                )
                logger.debug(f'[WeatherService] 清理 {deleted} 条旧实时天气')

                # 保存新数据
                record = WeatherRepository.create_weather_record(
                    session=session,
                    record_type='now',
                    city_name=data.get('city_name', city_name),
                    temp=float(data.get('temp')) if data.get('temp') else None,
                    feels_like=float(data.get('feels_like')) if data.get('feels_like') else None,
                    text=data.get('text'),
                    humidity=int(data.get('humidity')) if data.get('humidity') else None,
                    wind_dir=data.get('wind_dir'),
                    wind_scale=data.get('wind_scale'),
                    pressure=int(data.get('pressure')) if data.get('pressure') else None,
                    vis=float(data.get('vis')) if data.get('vis') else None,
                    cloud=int(data.get('cloud')) if data.get('cloud') else None,
                )
                session.commit()
                logger.info(f'[WeatherService] 实时天气已保存: {record.id}')
                return record.to_dict()
            except Exception as e:
                session.rollback()
                raise
            finally:
                session.close()

        except Exception as e:
            logger.error(f'[WeatherService] 获取并保存实时天气失败: {e}')
            return None

    def fetch_and_save_hourly(self, city_name: str = '重庆') -> List[Dict[str, Any]]:
        """
        获取并保存24小时预报

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 保存的天气数据列表
        """
        try:
            fetcher = self._get_fetcher()
            data_list = fetcher.fetch_hourly()

            if not data_list:
                logger.warning('[WeatherService] 获取24h预报失败')
                return []

            session = get_db()
            try:
                # 清理所有旧数据
                deleted = WeatherRepository.delete_all_hourly_records(
                    session=session,
                    city_name=city_name,
                )
                logger.debug(f'[WeatherService] 清理 {deleted} 条旧预报')

                # 保存新数据
                saved = []
                for data in data_list:
                    fx_time = None
                    if data.get('time'):
                        try:
                            fx_time = datetime.fromisoformat(data['time'].replace('Z', '+00:00'))
                        except:
                            pass

                    record = WeatherRepository.create_weather_record(
                        session=session,
                        record_type='hourly',
                        city_name=city_name,
                        temp=float(data.get('temp')) if data.get('temp') else None,
                        text=data.get('text'),
                        humidity=int(data.get('humidity')) if data.get('humidity') else None,
                        wind_dir=data.get('wind_dir'),
                        wind_scale=data.get('wind_scale'),
                        precip=float(data.get('precip')) if data.get('precip') else None,
                        pop=int(data.get('pop')) if data.get('pop') else None,
                        fx_time=fx_time,
                    )
                    saved.append(record.to_dict())

                session.commit()
                logger.info(f'[WeatherService] 24h预报已保存: {len(saved)} 条')
                return saved

            except Exception as e:
                session.rollback()
                raise
            finally:
                session.close()

        except Exception as e:
            logger.error(f'[WeatherService] 获取并保存24h预报失败: {e}')
            return []

    def get_now_weather(self, city_name: str = '重庆') -> Optional[Dict[str, Any]]:
        """
        获取最新实时天气（优先从数据库读取）

        Args:
            city_name: 城市名称

        Returns:
            Optional[Dict]: 天气数据或 None
        """
        session = get_db()
        try:
            record = WeatherRepository.get_latest_now_record(session, city_name)
            if record:
                # 检查数据是否过期（超过30分钟）
                if record.created_at and datetime.utcnow() - record.created_at < timedelta(minutes=30):
                    return record.to_dict()
                else:
                    # 数据已过期，先返回旧数据，然后异步刷新
                    old_data = record.to_dict()
                    # 在后台线程中刷新数据，不阻塞当前请求
                    import threading
                    thread = threading.Thread(
                        target=self.fetch_and_save_now,
                        args=(city_name,),
                        daemon=True
                    )
                    thread.start()
                    logger.info(f'[WeatherService] 实时天气数据已过期，返回旧数据并在后台刷新')
                    return old_data

            # 数据库无数据，重新获取
            return self.fetch_and_save_now(city_name)
        finally:
            session.close()

    def get_hourly_forecast(self, city_name: str = '重庆') -> List[Dict[str, Any]]:
        """
        获取24小时预报（优先从数据库读取）

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 预报数据列表
        """
        session = get_db()
        try:
            records = WeatherRepository.get_hourly_records(session, city_name, limit=24)
            if records:
                # 检查数据是否过期（超过60分钟）
                latest_record = max(records, key=lambda r: r.created_at)
                if latest_record.created_at and datetime.utcnow() - latest_record.created_at < timedelta(minutes=60):
                    return [r.to_dict() for r in records]
                else:
                    # 数据已过期，先返回旧数据，然后异步刷新
                    old_data = [r.to_dict() for r in records]
                    # 在后台线程中刷新数据，不阻塞当前请求
                    import threading
                    thread = threading.Thread(
                        target=self.fetch_and_save_hourly,
                        args=(city_name,),
                        daemon=True
                    )
                    thread.start()
                    logger.info(f'[WeatherService] 24h预报数据已过期，返回旧数据并在后台刷新')
                    return old_data

            # 数据库无数据，重新获取
            return self.fetch_and_save_hourly(city_name)
        finally:
            session.close()

    def fetch_and_save_alerts(self, city_name: str = '重庆') -> List[Dict[str, Any]]:
        """
        获取并保存天气预警

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 保存的预警数据列表
        """
        try:
            fetcher = self._get_fetcher()
            alerts = fetcher.fetch_alert()

            if not alerts:
                return []

            session = get_db()
            try:
                saved = []
                for alert in alerts:
                    alert_id = alert.get('id')
                    if not alert_id:
                        continue

                    # 检查是否已存在
                    if WeatherRepository.alert_exists(session, alert_id):
                        continue

                    record = WeatherRepository.create_alert(
                        session=session,
                        alert_id=alert_id,
                        city_name=city_name,
                        headline=alert.get('headline', ''),
                        event_type=alert.get('event_type', ''),
                        severity=alert.get('severity', ''),
                        color_code=alert.get('color_code', ''),
                        description=alert.get('description'),
                    )
                    saved.append(record.to_dict())

                session.commit()
                logger.info(f'[WeatherService] 新增预警: {len(saved)} 条')
                return saved

            except Exception as e:
                session.rollback()
                raise
            finally:
                session.close()

        except Exception as e:
            logger.error(f'[WeatherService] 获取并保存预警失败: {e}')
            return []

    def get_active_alerts(self, city_name: str = '重庆') -> List[Dict[str, Any]]:
        """
        获取生效中的预警

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 预警数据列表
        """
        session = get_db()
        try:
            records = WeatherRepository.get_active_alerts(session, city_name)
            return [r.to_dict() for r in records]
        finally:
            session.close()


# 模块级单例：供路由与任务模块直接引用，避免每次调用重复实例化
weather_service = WeatherService()
