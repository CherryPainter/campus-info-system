#!/usr/bin/env python3
"""
电量业务服务

职责：
- 电量数据获取与存储业务逻辑
- 电量统计分析与推送业务逻辑
- 协调 Repository 完成数据操作
- 集成容量管理器，提供百分比计算
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from app.core.database import get_db
from app.modules.electricity.capacity_manager import (
    get_capacity_manager,
)
from app.modules.electricity.crawler import ElectricityCrawler
from app.repository.electricity_repository import ElectricityRepository

logger = logging.getLogger(__name__)


class ElectricityService:
    """
    电量业务服务类

    封装所有电量相关的业务逻辑
    """

    def __init__(self, crawler: ElectricityCrawler | None = None, meter: str = "default") -> None:
        """
        初始化服务

        Args:
            crawler: 电量爬虫，为 None 时自动创建
            meter: 电表名称，默认为'default'
        """
        self._crawler = crawler
        self._meter = meter
        self._capacity_manager = get_capacity_manager(meter)

    def _get_crawler(self) -> ElectricityCrawler:
        """获取或创建 crawler"""
        if self._crawler is None:
            from app.modules.electricity.tasks import _make_crawler

            self._crawler = _make_crawler()
        return self._crawler

    def fetch_and_save_data(self, max_pages: int | None = None) -> tuple[bool, str]:
        """
        获取并保存电量数据

        Args:
            max_pages: 爬取页数，None 时使用默认值（50页）

        Returns:
            Tuple[bool, str]: (是否成功, 消息)
        """
        try:
            crawler = self._get_crawler()

            # 获取剩余电量
            remaining = crawler.fetch_remaining_power()
            if remaining is None:
                return False, "获取剩余电量失败"

            # 获取用电记录
            records = crawler.fetch_usage_records(max_pages=max_pages)
            if not records:
                return False, "获取用电记录失败"

            session = get_db()
            try:
                # 保存剩余电量（处理 dict 格式 {'default': 128.5} 或单个数值）
                remaining_value = remaining
                if isinstance(remaining, dict):
                    remaining_value = remaining.get("default", 0)
                remaining_float = float(remaining_value) if remaining_value else 0.0

                ElectricityRepository.create_remaining(
                    session=session,
                    remaining=remaining_float,
                    meter=self._meter,
                )

                # 更新容量管理器，检测充值和低电量
                session.commit()  # 先提交剩余电量记录
                self._capacity_manager.update_remaining(
                    current_remaining=remaining_float,
                    low_power_threshold=10.0,
                )

                # 批量保存用电记录
                record_tuples = []
                for r in records:
                    record_time = None
                    if r.get("time"):
                        try:
                            record_time = datetime.fromisoformat(r["time"].replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            record_time = datetime.utcnow()
                    else:
                        record_time = datetime.utcnow()

                    record_tuples.append(
                        (
                            record_time,
                            float(r.get("usage", 0)) if r.get("usage") else 0.0,
                            r.get("meter", "default"),
                        )
                    )

                ElectricityRepository.create_records_batch(session, record_tuples)

                session.commit()
                logger.info(
                    f"[ElectricityService] 电量数据已保存: {len(records)} 条记录，剩余 {remaining} 度"
                )
                return True, f"成功保存 {len(records)} 条用电记录"

            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        except Exception as e:
            logger.error(f"[ElectricityService] 获取并保存电量数据失败: {e}")
            return False, f"获取失败: {str(e)}"

    def get_remaining_power(self, meter: str = None) -> dict[str, Any] | None:
        """
        获取最新剩余电量（包含百分比信息）

        Args:
            meter: 电表名称，为None时使用初始化时的meter

        Returns:
            Optional[Dict]: 剩余电量数据或 None，包含百分比和总量信息
        """
        target_meter = meter or self._meter
        session = get_db()
        try:
            record = ElectricityRepository.get_latest_remaining(session, target_meter)
            if record:
                data = record.to_dict()
                # 获取容量管理器的状态信息
                capacity_status = self._capacity_manager.get_current_status()
                # 合并容量信息到返回数据
                data["total_capacity"] = capacity_status.get("total_capacity", 100.0)
                data["percentage"] = capacity_status.get("percentage", 0.0)
                data["is_low_power"] = capacity_status.get("is_low_power", False)
                return data
            return None
        finally:
            session.close()

    def get_usage_records(
        self,
        meter: str | None = None,
        days: int | None = 30,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        获取用电记录

        Args:
            meter: 电表名称筛选
            days: 查询最近多少天；为 None 时不做时间过滤，仅按 limit 返回最新记录
            limit: 返回条数限制

        Returns:
            List[Dict]: 用电记录列表

        说明：
            入库的 record_time 为爬虫返回的本地（北京）时间，而 datetime.utcnow()
            为 UTC 时间，两者存在约 8 小时偏差。若用 utcnow 作为查询上界，会把最近
            数小时内的记录误判为"未来记录"而过滤掉，导致前端显示不全。
            因此展示全部记录列表时应传 days=None，避免时区错配造成的截断。
        """
        session = get_db()
        try:
            start_time = None
            end_time = None
            # 仅当显式指定天数时才做时间过滤
            if days is not None:
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(days=days)

            records = ElectricityRepository.get_records(
                session=session,
                meter=meter,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            return [r.to_dict() for r in records]
        finally:
            session.close()

    def get_statistics(self, days: int = 30) -> dict[str, Any]:
        """
        获取用电统计

        Args:
            days: 统计最近多少天

        Returns:
            Dict: 统计数据
        """
        session = get_db()
        try:
            # 按电表统计
            by_meter = ElectricityRepository.get_usage_by_meter(session, days)

            # 计算汇总
            total_usage = sum(usage for _, usage in by_meter)
            meter_count = len(by_meter)

            # 获取每日统计（简化版，取最近7天）
            daily = []
            for i in range(min(days, 7)):
                target_date = datetime.utcnow() - timedelta(days=i)
                total, count = ElectricityRepository.get_daily_statistics(session, target_date)
                daily.append(
                    {
                        "date": target_date.strftime("%Y-%m-%d"),
                        "usage": total,
                        "count": count,
                    }
                )
            daily.reverse()

            return {
                "total_usage": round(total_usage, 2),
                "meter_count": meter_count,
                "by_meter": [{"meter": m, "usage": round(u, 2)} for m, u in by_meter],
                "daily": daily,
            }
        finally:
            session.close()

    def get_statistics_by_range(
        self,
        start_time: datetime,
        end_time: datetime,
        local_start_time: datetime | None = None,
        local_end_time: datetime | None = None,
        meter: str | None = None,
    ) -> dict[str, Any]:
        """
        获取指定时间范围的用电统计

        Args:
            start_time: 开始时间（UTC，用于数据库查询）
            end_time: 结束时间（UTC，用于数据库查询）
            local_start_time: 本地开始时间（用于显示，可选）
            local_end_time: 本地结束时间（用于显示，可选）
            meter: 电表名称筛选（可选）

        Returns:
            Dict: 统计数据
        """
        session = get_db()
        try:
            # 按电表统计（指定时间范围）
            by_meter = ElectricityRepository.get_usage_by_meter_and_range(
                session=session,
                start_time=start_time,
                end_time=end_time,
                meter=meter,
            )

            # 计算汇总
            total_usage = sum(usage for _, usage in by_meter)
            meter_count = len(by_meter)

            # 获取每日统计（时间范围内的每一天）
            # 使用本地时间计算日期范围，确保正确显示
            display_start = local_start_time or (start_time + timedelta(hours=8))
            display_end = local_end_time or (end_time + timedelta(hours=8))

            daily = []
            current_date = display_start.replace(hour=0, minute=0, second=0, microsecond=0)
            while current_date < display_end:
                # 将本地日期转换为UTC时间范围进行查询
                utc_day_start = current_date - timedelta(hours=8)
                utc_day_end = utc_day_start + timedelta(days=1)

                # 查询当天的用电量（使用范围查询）
                day_records = ElectricityRepository.get_records(
                    session=session,
                    meter=meter,
                    start_time=utc_day_start,
                    end_time=utc_day_end,
                )
                day_total = sum(r.usage for r in day_records)
                day_count = len(day_records)

                # 显示日期使用本地时间
                daily.append(
                    {
                        "date": current_date.strftime("%Y-%m-%d"),
                        "usage": round(day_total, 2),
                        "count": day_count,
                    }
                )
                current_date += timedelta(days=1)

            return {
                "total_usage": round(total_usage, 2),
                "meter_count": meter_count,
                "by_meter": [{"meter": m, "usage": round(u, 2)} for m, u in by_meter],
                "daily": daily,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            }
        finally:
            session.close()

    def check_low_power(
        self, threshold: float = 10.0, meter: str = "default"
    ) -> tuple[bool, float]:
        """
        检查是否低电量

        Args:
            threshold: 低电量阈值
            meter: 电表名称

        Returns:
            Tuple[bool, float]: (是否低电量, 当前剩余电量)
        """
        session = get_db()
        try:
            record = ElectricityRepository.get_latest_remaining(session, meter)
            if not record:
                return False, 0.0

            remaining = record.remaining
            is_low = remaining < threshold
            return is_low, remaining
        finally:
            session.close()


# 模块级单例：供路由与任务模块直接引用，避免每次调用重复实例化
electricity_service = ElectricityService()
