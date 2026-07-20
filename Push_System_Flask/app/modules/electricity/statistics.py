#!/usr/bin/env python3
"""
用电量统计模块
按日、周、月维度聚合用电记录
"""

import json
import os
from datetime import datetime, timedelta

from app.core.logger import get_logger

logger = get_logger(__name__)


class UsageStatistics:
    """用电量统计器"""

    def __init__(self, records_path: str, remaining_power_path: str) -> None:
        self.records_path = records_path
        self.remaining_power_path = remaining_power_path
        self._records: list[dict] = []
        self._remaining: dict = {}
        self._load()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """重新从磁盘加载数据"""
        self._load()

    def get_remaining_power(self) -> dict:
        """返回剩余电量字典，文件不存在时返回 {}"""
        return dict(self._remaining)

    def get_daily_statistics(self, target_date: datetime | None = None) -> dict | None:
        """
        返回指定日期的用电统计

        Args:
            target_date: 目标日期，默认昨天

        Returns:
            {'date': str, 'total_usage': float, 'meter_usage': {meter: float}} 或 None
        """
        if target_date is None:
            target_date = datetime.now() - timedelta(days=1)
        target_str = target_date.strftime("%Y-%m-%d")

        total = 0.0
        meter_usage: dict[str, float] = {}

        for rec in self._records:
            try:
                actual_date = self._actual_date(rec["time"])
                if actual_date != target_str:
                    continue
                usage = float(rec["usage"])
                total += usage
                meter = rec["meter"]
                meter_usage[meter] = meter_usage.get(meter, 0.0) + usage
            except Exception:
                continue

        if total > 0 or meter_usage:
            return {"date": target_str, "total_usage": total, "meter_usage": meter_usage}
        return None

    def get_weekly_statistics(self, target_date: datetime | None = None) -> dict | None:
        """
        返回指定日期所在周（周一至周日）的用电统计

        Returns:
            含 year / week_num / start_date / end_date / total_usage /
            days_count / meter_usage / daily_usage 的字典，或 None
        """
        if target_date is None:
            target_date = datetime.now()
        weekday = target_date.weekday()
        week_start = target_date - timedelta(days=weekday)
        week_end = week_start + timedelta(days=6)

        total = 0.0
        meter_usage: dict[str, float] = {}
        daily_usage: dict[str, float] = {}

        for rec in self._records:
            try:
                actual_str = self._actual_date(rec["time"])
                actual_dt = datetime.strptime(actual_str, "%Y-%m-%d")
                if not (week_start.date() <= actual_dt.date() <= week_end.date()):
                    continue
                usage = float(rec["usage"])
                total += usage
                meter = rec["meter"]
                meter_usage[meter] = meter_usage.get(meter, 0.0) + usage
                daily_usage[actual_str] = daily_usage.get(actual_str, 0.0) + usage
            except Exception:
                continue

        if total > 0 or meter_usage:
            iso = week_start.isocalendar()
            return {
                "year": iso[0],
                "week_num": iso[1],
                "start_date": week_start.strftime("%Y-%m-%d"),
                "end_date": week_end.strftime("%Y-%m-%d"),
                "total_usage": total,
                "meter_usage": meter_usage,
                "daily_usage": daily_usage,
                "days_count": len(daily_usage),
            }
        return None

    def get_monthly_statistics(self, target_date: datetime | None = None) -> dict | None:
        """
        返回指定月份的用电统计

        Returns:
            含 year / month / total_usage / days_count / meter_usage / daily_usage 的字典，或 None
        """
        if target_date is None:
            target_date = datetime.now()
        year = target_date.year
        month = target_date.month

        total = 0.0
        meter_usage: dict[str, float] = {}
        daily_usage: dict[str, float] = {}

        for rec in self._records:
            try:
                actual_str = self._actual_date(rec["time"])
                actual_dt = datetime.strptime(actual_str, "%Y-%m-%d")
                if actual_dt.year != year or actual_dt.month != month:
                    continue
                usage = float(rec["usage"])
                total += usage
                meter = rec["meter"]
                meter_usage[meter] = meter_usage.get(meter, 0.0) + usage
                daily_usage[actual_str] = daily_usage.get(actual_str, 0.0) + usage
            except Exception:
                continue

        if total > 0 or meter_usage:
            return {
                "year": year,
                "month": month,
                "total_usage": total,
                "meter_usage": meter_usage,
                "daily_usage": daily_usage,
                "days_count": len(daily_usage),
            }
        return None

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._load_records()
        self._load_remaining()

    def _load_records(self) -> None:
        try:
            if not os.path.exists(self.records_path):
                self._records = []
                return
            with open(self.records_path, encoding="utf-8") as f:
                data = json.load(f)
            # 兼容嵌套列表结构 [[{...}], [{...}], ...]
            if isinstance(data, list) and data and isinstance(data[0], list):
                flat: list[dict] = []
                for sub in data:
                    if isinstance(sub, list):
                        flat.extend(sub)
                    else:
                        flat.append(sub)
                self._records = flat
            else:
                self._records = data if isinstance(data, list) else []
            logger.info(f"UsageStatistics: 加载 {len(self._records)} 条用电记录")
        except Exception as exc:
            logger.error(f"UsageStatistics: 加载用电记录失败 {exc}")
            self._records = []

    def _load_remaining(self) -> None:
        try:
            if not os.path.exists(self.remaining_power_path):
                self._remaining = {}
                return
            with open(self.remaining_power_path, encoding="utf-8") as f:
                self._remaining = json.load(f)
            logger.debug(f"UsageStatistics: 剩余电量 {self._remaining}")
        except Exception as exc:
            logger.error(f"UsageStatistics: 加载剩余电量失败 {exc}")
            self._remaining = {}

    @staticmethod
    def _actual_date(time_str: str) -> str:
        """
        将记录时间字符串转为实际用电日期字符串
        原始时间为次日（记录时间 - 1 天 = 实际用电日）
        """
        date_str = time_str.split()[0]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        actual = dt - timedelta(days=1)
        return actual.strftime("%Y-%m-%d")
