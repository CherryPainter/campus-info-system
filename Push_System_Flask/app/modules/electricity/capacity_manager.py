#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电量容量管理器模块

采用面向对象设计，管理电量总量的检测、记录和计算

核心逻辑：
1. 当电量低于阈值（低电量警告）时，记录当前电量作为参考
2. 如果第二天电量突然增加（比前一天多），说明充值了，以新的电量为总量基准
3. 使用历史数据推算当前电量的百分比

类设计：
- ElectricityCapacityManager: 电量容量管理器，封装所有容量相关逻辑
- CapacityRecord: 容量记录数据类
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

from app.core.logger import get_logger
from app.core.database import get_db
from app.model.electricity import ElectricityTotalCapacity
from app.repository.electricity_repository import ElectricityRepository

logger = get_logger(__name__)


class RecordReason(Enum):
    """容量记录原因枚举"""
    AUTO_DETECT = "auto_detect"      # 自动检测（电量突然增加）
    LOW_POWER = "low_power"          # 低电量警告时记录
    MANUAL = "manual"                # 手动设置
    INITIAL = "initial"              # 初始记录


@dataclass
class CapacityRecord:
    """
    容量记录数据类

    Attributes:
        total_capacity: 总量（度）
        remaining_at_record: 记录时的剩余电量（度）
        recorded_at: 记录时间
        reason: 记录原因
    """
    total_capacity: float
    remaining_at_record: float
    recorded_at: datetime
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'total_capacity': self.total_capacity,
            'remaining_at_record': self.remaining_at_record,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
            'reason': self.reason,
        }


class ElectricityCapacityManager:
    """
    电量容量管理器类

    负责：
    1. 检测电量充值（容量变化）
    2. 记录容量历史
    3. 计算当前电量的百分比
    4. 提供低电量警告状态

    使用示例：
        manager = ElectricityCapacityManager()
        # 保存新的剩余电量记录，自动检测是否需要更新容量
        manager.update_remaining(15.5, low_power_threshold=10.0)
        # 获取当前电量状态
        status = manager.get_current_status()
    """

    # 默认总量（当没有历史数据时使用的初始值）
    DEFAULT_CAPACITY: float = 100.0

    # 电量增加阈值（超过此值认为是充值）
    RECHARGE_THRESHOLD: float = 5.0

    # 低电量警告阈值
    LOW_POWER_WARNING_THRESHOLD: float = 10.0

    def __init__(self, meter: str = 'default') -> None:
        """
        初始化容量管理器

        Args:
            meter: 电表名称，默认为'default'
        """
        self._meter = meter
        self._cache: Optional[CapacityRecord] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl: timedelta = timedelta(minutes=5)  # 缓存5分钟

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def update_remaining(
        self,
        current_remaining: float,
        low_power_threshold: float = LOW_POWER_WARNING_THRESHOLD,
    ) -> Tuple[bool, Optional[CapacityRecord]]:
        """
        更新剩余电量，检测是否需要记录新的容量

        检测逻辑：
        1. 获取上一次记录的剩余电量
        2. 如果当前电量 > 上一次电量 + 阈值，认为是充值，记录新容量
        3. 如果当前电量 <= low_power_threshold，记录低电量警告状态

        Args:
            current_remaining: 当前剩余电量
            low_power_threshold: 低电量警告阈值

        Returns:
            Tuple[bool, Optional[CapacityRecord]]: (是否检测到充值, 新的容量记录或None)
        """
        session = get_db()
        try:
            # 获取上一次记录的剩余电量（取第二条，跳过刚插入的最新条）
            last_remaining_record = ElectricityRepository.get_previous_remaining(session, self._meter)
            last_remaining = last_remaining_record.remaining if last_remaining_record else None

            # 检测是否充值（电量突然增加）—— 仅当有历史数据可比较时
            if last_remaining is not None and current_remaining > last_remaining + self.RECHARGE_THRESHOLD:
                # 检测到充值，记录新的容量
                # 新容量 = 当前剩余电量（假设充值后剩余即为新的总量参考）
                new_capacity = current_remaining
                record = self._record_capacity(
                    session=session,
                    total_capacity=new_capacity,
                    remaining_at_record=current_remaining,
                    reason=RecordReason.AUTO_DETECT.value,
                )
                logger.info(f'[CapacityManager] 检测到电量充值: {last_remaining} -> {current_remaining}度，'
                           f'记录新容量: {new_capacity}度（相比上一条记录增加 {current_remaining - last_remaining:.1f} 度）')
                return True, record

            # 检测是否低电量警告
            if current_remaining <= low_power_threshold:
                # 检查是否已经有低电量记录（避免重复记录）
                recent_low_record = self._get_recent_low_power_record(session)
                if not recent_low_record:
                    # 记录低电量警告时的容量参考
                    current_capacity = self.get_current_capacity(session)
                    record = self._record_capacity(
                        session=session,
                        total_capacity=current_capacity,
                        remaining_at_record=current_remaining,
                        reason=RecordReason.LOW_POWER.value,
                    )
                    logger.info(f'[CapacityManager] 低电量警告: {current_remaining}度，'
                               f'记录容量参考: {current_capacity}度')
                    return False, record

            return False, None

        except Exception as e:
            logger.error(f'[CapacityManager] 更新剩余电量失败: {e}')
            return False, None
        finally:
            session.close()

    def get_current_status(self) -> Dict[str, Any]:
        """
        获取当前电量状态

        Returns:
            Dict包含：
            - remaining: 当前剩余电量
            - total_capacity: 当前总量
            - percentage: 百分比 (0-100)
            - is_low_power: 是否低电量
            - last_record: 最近的容量记录
        """
        session = get_db()
        try:
            # 获取最新剩余电量
            remaining_record = ElectricityRepository.get_latest_remaining(session, self._meter)
            remaining = remaining_record.remaining if remaining_record else 0.0

            # 获取当前容量
            capacity = self.get_current_capacity(session)

            # 计算百分比
            percentage = self._calculate_percentage(remaining, capacity)

            # 判断是否低电量
            is_low_power = remaining <= self.LOW_POWER_WARNING_THRESHOLD

            # 获取最近的容量记录
            last_capacity_record = self._get_latest_capacity_record(session)

            return {
                'remaining': round(remaining, 2),
                'total_capacity': round(capacity, 2),
                'percentage': round(percentage, 1),
                'is_low_power': is_low_power,
                'last_record': last_capacity_record.to_dict() if last_capacity_record else None,
            }

        except Exception as e:
            logger.error(f'[CapacityManager] 获取当前状态失败: {e}')
            return {
                'remaining': 0.0,
                'total_capacity': self.DEFAULT_CAPACITY,
                'percentage': 0.0,
                'is_low_power': True,
                'last_record': None,
            }
        finally:
            session.close()

    def get_current_capacity(self, session=None) -> float:
        """
        获取当前总量容量

        策略：
        1. 如果有容量记录，返回最新的容量
        2. 如果没有容量记录，返回默认容量

        Args:
            session: 数据库会话，为None时自动创建

        Returns:
            float: 当前总量容量
        """
        should_close = False
        if session is None:
            session = get_db()
            should_close = True

        try:
            latest_record = self._get_latest_capacity_record(session)
            if latest_record:
                return latest_record.total_capacity
            return self.DEFAULT_CAPACITY
        finally:
            if should_close:
                session.close()

    def set_manual_capacity(self, capacity: float, remaining: float) -> CapacityRecord:
        """
        手动设置容量（用于初始化或修正）

        Args:
            capacity: 设置的总量
            remaining: 当前剩余电量

        Returns:
            CapacityRecord: 创建的容量记录
        """
        session = get_db()
        try:
            record = self._record_capacity(
                session=session,
                total_capacity=capacity,
                remaining_at_record=remaining,
                reason=RecordReason.MANUAL.value,
            )
            logger.info(f'[CapacityManager] 手动设置容量: {capacity}度，剩余: {remaining}度')
            return record
        finally:
            session.close()

    def get_capacity_history(self, days: int = 30) -> List[CapacityRecord]:
        """
        获取容量历史记录

        Args:
            days: 查询最近多少天

        Returns:
            List[CapacityRecord]: 容量记录列表
        """
        session = get_db()
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days)
            records = (
                session.query(ElectricityTotalCapacity)
                .filter(
                    ElectricityTotalCapacity.meter == self._meter,
                    ElectricityTotalCapacity.recorded_at >= cutoff_time,
                )
                .order_by(ElectricityTotalCapacity.recorded_at.desc())
                .all()
            )

            return [
                CapacityRecord(
                    total_capacity=r.total_capacity,
                    remaining_at_record=r.remaining_at_record,
                    recorded_at=r.recorded_at,
                    reason=r.record_reason,
                )
                for r in records
            ]
        finally:
            session.close()

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _record_capacity(
        self,
        session,
        total_capacity: float,
        remaining_at_record: float,
        reason: str,
    ) -> CapacityRecord:
        """
        记录容量到数据库

        Args:
            session: 数据库会话
            total_capacity: 总量
            remaining_at_record: 记录时的剩余电量
            reason: 记录原因

        Returns:
            CapacityRecord: 创建的容量记录
        """
        db_record = ElectricityTotalCapacity(
            meter=self._meter,
            total_capacity=total_capacity,
            remaining_at_record=remaining_at_record,
            record_reason=reason,
            recorded_at=datetime.utcnow(),
        )
        session.add(db_record)
        session.commit()

        # 更新缓存
        record = CapacityRecord(
            total_capacity=total_capacity,
            remaining_at_record=remaining_at_record,
            recorded_at=db_record.recorded_at,
            reason=reason,
        )
        self._cache = record
        self._cache_time = datetime.utcnow()

        return record

    def _get_latest_capacity_record(self, session) -> Optional[CapacityRecord]:
        """
        获取最新的容量记录

        Args:
            session: 数据库会话

        Returns:
            Optional[CapacityRecord]: 最新的容量记录或None
        """
        # 检查缓存
        if self._cache and self._cache_time:
            if datetime.utcnow() - self._cache_time < self._cache_ttl:
                return self._cache

        record = (
            session.query(ElectricityTotalCapacity)
            .filter(ElectricityTotalCapacity.meter == self._meter)
            .order_by(ElectricityTotalCapacity.recorded_at.desc())
            .first()
        )

        if record:
            capacity_record = CapacityRecord(
                total_capacity=record.total_capacity,
                remaining_at_record=record.remaining_at_record,
                recorded_at=record.recorded_at,
                reason=record.record_reason,
            )
            # 更新缓存
            self._cache = capacity_record
            self._cache_time = datetime.utcnow()
            return capacity_record

        return None

    def _get_recent_low_power_record(self, session) -> Optional[CapacityRecord]:
        """
        获取最近的低电量警告记录（24小时内）

        Args:
            session: 数据库会话

        Returns:
            Optional[CapacityRecord]: 低电量记录或None
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        record = (
            session.query(ElectricityTotalCapacity)
            .filter(
                ElectricityTotalCapacity.meter == self._meter,
                ElectricityTotalCapacity.record_reason == RecordReason.LOW_POWER.value,
                ElectricityTotalCapacity.recorded_at >= cutoff_time,
            )
            .order_by(ElectricityTotalCapacity.recorded_at.desc())
            .first()
        )

        if record:
            return CapacityRecord(
                total_capacity=record.total_capacity,
                remaining_at_record=record.remaining_at_record,
                recorded_at=record.recorded_at,
                reason=record.record_reason,
            )
        return None

    @staticmethod
    def _calculate_percentage(remaining: float, total: float) -> float:
        """
        计算百分比

        Args:
            remaining: 剩余电量
            total: 总量

        Returns:
            float: 百分比 (0-100)
        """
        if total <= 0:
            return 0.0
        percentage = (remaining / total) * 100
        return max(0.0, min(100.0, percentage))


# 单例实例（便于全局使用）
_default_manager: Optional[ElectricityCapacityManager] = None


def get_capacity_manager(meter: str = 'default') -> ElectricityCapacityManager:
    """
    获取容量管理器实例

    Args:
        meter: 电表名称

    Returns:
        ElectricityCapacityManager: 容量管理器实例
    """
    global _default_manager
    if _default_manager is None or _default_manager._meter != meter:
        _default_manager = ElectricityCapacityManager(meter)
    return _default_manager
