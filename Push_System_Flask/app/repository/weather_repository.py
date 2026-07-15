#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气数据仓库

职责：
- 封装天气相关的数据库操作
- 提供类型安全的 CRUD 接口
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from app.model.weather import WeatherRecord, WeatherAlert


class WeatherRepository:
    """
    天气数据仓库类

    所有方法接收 session 参数，由调用方管理事务
    """

    @staticmethod
    def create_weather_record(
        session: Session,
        record_type: str,
        city_name: str,
        temp: Optional[float] = None,
        feels_like: Optional[float] = None,
        text: Optional[str] = None,
        humidity: Optional[int] = None,
        wind_dir: Optional[str] = None,
        wind_scale: Optional[str] = None,
        precip: Optional[float] = None,
        pop: Optional[int] = None,
        pressure: Optional[int] = None,
        vis: Optional[float] = None,
        cloud: Optional[int] = None,
        fx_time: Optional[datetime] = None,
    ) -> WeatherRecord:
        """
        创建天气记录

        Args:
            session: 数据库会话
            record_type: 记录类型 (now/hourly)
            city_name: 城市名称
            ...其他字段

        Returns:
            WeatherRecord: 创建的记录对象
        """
        record = WeatherRecord(
            record_type=record_type,
            city_name=city_name,
            temp=temp,
            feels_like=feels_like,
            text=text,
            humidity=humidity,
            wind_dir=wind_dir,
            wind_scale=wind_scale,
            precip=precip,
            pop=pop,
            pressure=pressure,
            vis=vis,
            cloud=cloud,
            fx_time=fx_time,
        )
        session.add(record)
        session.flush()  # 获取 ID，但不提交事务
        return record

    @staticmethod
    def get_latest_now_record(session: Session, city_name: str = '重庆') -> Optional[WeatherRecord]:
        """
        获取最新的实时天气记录

        Args:
            session: 数据库会话
            city_name: 城市名称

        Returns:
            Optional[WeatherRecord]: 最新记录或 None
        """
        return (
            session.query(WeatherRecord)
            .filter(
                and_(
                    WeatherRecord.record_type == 'now',
                    WeatherRecord.city_name == city_name,
                )
            )
            .order_by(desc(WeatherRecord.created_at))
            .first()
        )

    @staticmethod
    def get_hourly_records(
        session: Session,
        city_name: str = '重庆',
        limit: int = 24,
    ) -> List[WeatherRecord]:
        """
        获取逐小时预报记录

        Args:
            session: 数据库会话
            city_name: 城市名称
            limit: 返回条数

        Returns:
            List[WeatherRecord]: 逐小时预报列表
        """
        return (
            session.query(WeatherRecord)
            .filter(
                and_(
                    WeatherRecord.record_type == 'hourly',
                    WeatherRecord.city_name == city_name,
                )
            )
            .order_by(WeatherRecord.fx_time)
            .limit(limit)
            .all()
        )

    @staticmethod
    def delete_all_hourly_records(
        session: Session,
        city_name: str = '重庆',
    ) -> int:
        """
        删除该城市的所有逐小时预报记录（更新前清空）

        Args:
            session: 数据库会话
            city_name: 城市名称

        Returns:
            int: 删除的记录数
        """
        result = (
            session.query(WeatherRecord)
            .filter(
                and_(
                    WeatherRecord.record_type == 'hourly',
                    WeatherRecord.city_name == city_name,
                )
            )
            .delete(synchronize_session=False)
        )
        return result

    @staticmethod
    def delete_all_now_records(
        session: Session,
        city_name: str = '重庆',
    ) -> int:
        """
        删除该城市的所有实时天气记录（更新前清空）

        Args:
            session: 数据库会话
            city_name: 城市名称

        Returns:
            int: 删除的记录数
        """
        result = (
            session.query(WeatherRecord)
            .filter(
                and_(
                    WeatherRecord.record_type == 'now',
                    WeatherRecord.city_name == city_name,
                )
            )
            .delete(synchronize_session=False)
        )
        return result

    # ==================== 预警相关 ====================

    @staticmethod
    def create_alert(
        session: Session,
        alert_id: str,
        city_name: str,
        headline: str,
        event_type: str,
        severity: str,
        color_code: str,
        description: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> WeatherAlert:
        """
        创建天气预警记录

        Args:
            session: 数据库会话
            alert_id: 预警唯一标识
            city_name: 城市名称
            headline: 预警标题
            event_type: 预警类型
            severity: 严重程度
            color_code: 颜色代码
            description: 预警描述
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            WeatherAlert: 创建的预警对象
        """
        alert = WeatherAlert(
            alert_id=alert_id,
            city_name=city_name,
            headline=headline,
            event_type=event_type,
            severity=severity,
            color_code=color_code,
            description=description,
            start_time=start_time,
            end_time=end_time,
            is_active=True,
        )
        session.add(alert)
        session.flush()
        return alert

    @staticmethod
    def get_active_alerts(
        session: Session,
        city_name: str = '重庆',
    ) -> List[WeatherAlert]:
        """
        获取生效中的预警

        Args:
            session: 数据库会话
            city_name: 城市名称

        Returns:
            List[WeatherAlert]: 生效中的预警列表
        """
        return (
            session.query(WeatherAlert)
            .filter(
                and_(
                    WeatherAlert.is_active == True,
                    WeatherAlert.city_name == city_name,
                )
            )
            .order_by(desc(WeatherAlert.created_at))
            .all()
        )

    @staticmethod
    def deactivate_alert(session: Session, alert_id: str) -> bool:
        """
        将预警标记为失效

        Args:
            session: 数据库会话
            alert_id: 预警标识

        Returns:
            bool: 是否成功
        """
        alert = (
            session.query(WeatherAlert)
            .filter(WeatherAlert.alert_id == alert_id)
            .first()
        )
        if alert:
            alert.is_active = False
            return True
        return False

    @staticmethod
    def alert_exists(session: Session, alert_id: str) -> bool:
        """
        检查预警是否已存在

        Args:
            session: 数据库会话
            alert_id: 预警标识

        Returns:
            bool: 是否存在
        """
        return (
            session.query(WeatherAlert)
            .filter(WeatherAlert.alert_id == alert_id)
            .first()
            is not None
        )

    @staticmethod
    def is_alert_pushed(session: Session, alert_id: str) -> bool:
        """
        检查预警是否已推送过（去重比对用）

        Args:
            session: 数据库会话
            alert_id: 预警标识

        Returns:
            bool: 是否已推送过
        """
        return (
            session.query(WeatherAlert)
            .filter(
                and_(
                    WeatherAlert.alert_id == alert_id,
                    WeatherAlert.is_pushed == True,
                )
            )
            .first()
            is not None
        )

    @staticmethod
    def mark_alert_pushed(session: Session, alert_id: str) -> None:
        """
        标记某预警为已推送（去重真相源）

        若记录已存在则置 is_pushed=True；若不存在（入库失败等边界情况）
        则插入最小记录并置 is_pushed=True，保证去重逻辑一定生效。

        Args:
            session: 数据库会话
            alert_id: 预警标识
        """
        alert = (
            session.query(WeatherAlert)
            .filter(WeatherAlert.alert_id == alert_id)
            .first()
        )
        if alert:
            alert.is_pushed = True
        else:
            session.add(WeatherAlert(
                alert_id=alert_id,
                city_name='',
                headline='',
                event_type='',
                severity='',
                color_code='',
                is_active=False,
                is_pushed=True,
            ))
        session.flush()
