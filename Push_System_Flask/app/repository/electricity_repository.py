#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电量数据仓库

职责：
- 封装电量相关的数据库操作
- 提供类型安全的 CRUD 接口
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_

from app.model.electricity import ElectricityRecord, ElectricityRemaining, ElectricityTotalCapacity


class ElectricityRepository:
    """
    电量数据仓库类

    所有方法接收 session 参数，由调用方管理事务
    """

    @staticmethod
    def create_record(
        session: Session,
        record_time: datetime,
        usage: float,
        meter: str,
    ) -> ElectricityRecord:
        """
        创建用电记录

        Args:
            session: 数据库会话
            record_time: 记录时间
            usage: 用电量
            meter: 电表名称

        Returns:
            ElectricityRecord: 创建的记录对象
        """
        record = ElectricityRecord(
            record_time=record_time,
            usage=usage,
            meter=meter,
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def create_records_batch(
        session: Session,
        records: List[Tuple[datetime, float, str]],
    ) -> int:
        """
        批量创建用电记录（自动去重）

        去重逻辑：同一时间 + 同一电表 视为重复记录（不管用电量是否相同）
        因为一天一个电表只有一条记录，用电量可能因爬虫多次获取而略有不同

        Args:
            session: 数据库会话
            records: [(record_time, usage, meter), ...]

        Returns:
            int: 实际创建的记录数（去重后）
        """
        created_count = 0
        for record_time, usage, meter in records:
            # 按时间+电表去重（不比较用电量）
            existing = (
                session.query(ElectricityRecord)
                .filter(
                    and_(
                        ElectricityRecord.record_time == record_time,
                        ElectricityRecord.meter == meter,
                    )
                )
                .first()
            )
            if existing:
                # 更新用电量（可能有细微差异），删除旧记录插入新的
                session.delete(existing)
            
            record = ElectricityRecord(
                record_time=record_time,
                usage=usage,
                meter=meter,
            )
            session.add(record)
            created_count += 1
        session.flush()
        return created_count

    @staticmethod
    def get_records(
        session: Session,
        meter: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[ElectricityRecord]:
        """
        查询用电记录

        Args:
            session: 数据库会话
            meter: 电表名称筛选
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回条数限制

        Returns:
            List[ElectricityRecord]: 用电记录列表
        """
        query = session.query(ElectricityRecord)

        if meter:
            query = query.filter(ElectricityRecord.meter == meter)
        if start_time:
            query = query.filter(ElectricityRecord.record_time >= start_time)
        if end_time:
            query = query.filter(ElectricityRecord.record_time <= end_time)

        return (
            query.order_by(desc(ElectricityRecord.record_time))
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_daily_statistics(
        session: Session,
        target_date: datetime,
        meter: Optional[str] = None,
    ) -> Tuple[float, int]:
        """
        获取某日用电统计

        Args:
            session: 数据库会话
            target_date: 目标日期
            meter: 电表名称筛选

        Returns:
            Tuple[float, int]: (总用电量, 记录数)
        """
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        query = session.query(
            func.sum(ElectricityRecord.usage),
            func.count(ElectricityRecord.id),
        ).filter(
            and_(
                ElectricityRecord.record_time >= start_of_day,
                ElectricityRecord.record_time < end_of_day,
            )
        )

        if meter:
            query = query.filter(ElectricityRecord.meter == meter)

        result = query.first()
        total = result[0] or 0.0
        count = result[1] or 0
        return float(total), int(count)

    @staticmethod
    def get_usage_by_meter(
        session: Session,
        days: int = 30,
    ) -> List[Tuple[str, float]]:
        """
        按电表统计用电量

        Args:
            session: 数据库会话
            days: 统计最近多少天

        Returns:
            List[Tuple[str, float]]: [(meter, total_usage), ...]
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        results = (
            session.query(
                ElectricityRecord.meter,
                func.sum(ElectricityRecord.usage),
            )
            .filter(ElectricityRecord.record_time >= cutoff_time)
            .group_by(ElectricityRecord.meter)
            .order_by(desc(func.sum(ElectricityRecord.usage)))
            .all()
        )

        return [(meter, float(usage or 0)) for meter, usage in results]

    @staticmethod
    def get_usage_by_meter_and_range(
        session: Session,
        start_time: datetime,
        end_time: datetime,
        meter: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """
        按电表统计指定时间范围的用电量

        Args:
            session: 数据库会话
            start_time: 开始时间
            end_time: 结束时间
            meter: 电表名称筛选（可选）

        Returns:
            List[Tuple[str, float]]: [(meter, total_usage), ...]
        """
        query = (
            session.query(
                ElectricityRecord.meter,
                func.sum(ElectricityRecord.usage),
            )
            .filter(
                and_(
                    ElectricityRecord.record_time >= start_time,
                    ElectricityRecord.record_time < end_time,
                )
            )
        )

        if meter:
            query = query.filter(ElectricityRecord.meter == meter)

        results = (
            query.group_by(ElectricityRecord.meter)
            .order_by(desc(func.sum(ElectricityRecord.usage)))
            .all()
        )

        return [(m, float(usage or 0)) for m, usage in results]

    # ==================== 剩余电量相关 ====================

    @staticmethod
    def create_remaining(
        session: Session,
        remaining: float,
        meter: str = 'default',
    ) -> ElectricityRemaining:
        """
        创建剩余电量记录

        Args:
            session: 数据库会话
            remaining: 剩余电量
            meter: 电表名称

        Returns:
            ElectricityRemaining: 创建的记录对象
        """
        record = ElectricityRemaining(
            meter=meter,
            remaining=remaining,
            recorded_at=datetime.utcnow(),
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def get_latest_remaining(
        session: Session,
        meter: str = 'default',
    ) -> Optional[ElectricityRemaining]:
        """
        获取最新剩余电量

        Args:
            session: 数据库会话
            meter: 电表名称

        Returns:
            Optional[ElectricityRemaining]: 最新记录或 None
        """
        return (
            session.query(ElectricityRemaining)
            .filter(ElectricityRemaining.meter == meter)
            .order_by(desc(ElectricityRemaining.recorded_at))
            .first()
        )

    @staticmethod
    def get_previous_remaining(
        session: Session,
        meter: str = 'default',
    ) -> Optional[ElectricityRemaining]:
        """
        获取上一条剩余电量（跳过最新条，用于容量充值对比）

        因为最新条通常是本次爬取刚插入的，用次新条来对比才能发现"昨天 < 今天"的充值场景。
        """
        return (
            session.query(ElectricityRemaining)
            .filter(ElectricityRemaining.meter == meter)
            .order_by(desc(ElectricityRemaining.recorded_at))
            .offset(1)
            .limit(1)
            .first()
        )

    @staticmethod
    def get_remaining_history(
        session: Session,
        meter: str = 'default',
        days: int = 30,
    ) -> List[ElectricityRemaining]:
        """
        获取剩余电量历史

        Args:
            session: 数据库会话
            meter: 电表名称
            days: 查询最近多少天

        Returns:
            List[ElectricityRemaining]: 剩余电量记录列表
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        return (
            session.query(ElectricityRemaining)
            .filter(
                and_(
                    ElectricityRemaining.meter == meter,
                    ElectricityRemaining.recorded_at >= cutoff_time,
                )
            )
            .order_by(ElectricityRemaining.recorded_at)
            .all()
        )

    # ==================== 电量容量相关 ====================

    @staticmethod
    def create_capacity_record(
        session: Session,
        total_capacity: float,
        remaining_at_record: float,
        meter: str = 'default',
        reason: str = 'auto_detect',
    ) -> ElectricityTotalCapacity:
        """
        创建电量容量记录

        Args:
            session: 数据库会话
            total_capacity: 总量（度）
            remaining_at_record: 记录时的剩余电量（度）
            meter: 电表名称
            reason: 记录原因

        Returns:
            ElectricityTotalCapacity: 创建的记录对象
        """
        record = ElectricityTotalCapacity(
            meter=meter,
            total_capacity=total_capacity,
            remaining_at_record=remaining_at_record,
            record_reason=reason,
            recorded_at=datetime.utcnow(),
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def get_latest_capacity_record(
        session: Session,
        meter: str = 'default',
    ) -> Optional[ElectricityTotalCapacity]:
        """
        获取最新容量记录

        Args:
            session: 数据库会话
            meter: 电表名称

        Returns:
            Optional[ElectricityTotalCapacity]: 最新记录或 None
        """
        return (
            session.query(ElectricityTotalCapacity)
            .filter(ElectricityTotalCapacity.meter == meter)
            .order_by(desc(ElectricityTotalCapacity.recorded_at))
            .first()
        )

    @staticmethod
    def get_capacity_history(
        session: Session,
        meter: str = 'default',
        days: int = 30,
    ) -> List[ElectricityTotalCapacity]:
        """
        获取容量历史记录

        Args:
            session: 数据库会话
            meter: 电表名称
            days: 查询最近多少天

        Returns:
            List[ElectricityTotalCapacity]: 容量记录列表
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        return (
            session.query(ElectricityTotalCapacity)
            .filter(
                and_(
                    ElectricityTotalCapacity.meter == meter,
                    ElectricityTotalCapacity.recorded_at >= cutoff_time,
                )
            )
            .order_by(desc(ElectricityTotalCapacity.recorded_at))
            .all()
        )
