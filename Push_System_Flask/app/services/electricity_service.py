#!/usr/bin/env python3
"""
电量业务服务

职责：
- 电量数据获取与存储业务逻辑
- 电量统计分析与推送业务逻辑
- 协调 Repository 完成数据操作
- 集成容量管理器，提供百分比计算

用户化说明（2026-09-01）：
- 每宿舍独立电表，数据按 user_id 隔离（NULL=历史全局数据/管理员视图）。
- 爬虫 Cookie 由学生在小程序自行配置，存 student_profiles.electricity_cookie；
  本服务构造 crawler 时使用用户 Cookie，不再读全局 Config.ELECTRICITY_CRAWLER_COOKIE。
"""

import logging
import time
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

    def __init__(
        self,
        crawler: ElectricityCrawler | None = None,
        meter: str = "default",
        user_id: int | None = None,
        cookie: str = "",
    ) -> None:
        """
        初始化服务

        Args:
            crawler: 电量爬虫，为 None 时自动创建
            meter: 电表名称，默认为'default'（用户维度下每宿舍一个电表）
            user_id: 归属用户ID（None=历史全局/管理员视图）
            cookie: 用户自行配置的电表爬虫 Cookie（留空则爬虫无 Cookie，仅可读历史库）
        """
        self._crawler = crawler
        self._meter = meter
        self._user_id = user_id
        self._cookie = cookie
        self._capacity_manager = get_capacity_manager(meter, user_id=user_id)
        # 轻量刷新冷却状态（秒）：防频繁爬取被反爬
        self._last_remaining_refresh: float | None = None
        self._remaining_refresh_cooldown: float = 60.0

    def set_cookie(self, cookie: str) -> None:
        """
        运行时更新用户 Cookie，crawler 立即生效

        学生在小程序修改电表配置后调用，无需重建实例。
        """
        self._cookie = cookie or ""
        if self._crawler is not None:
            self._crawler.set_cookie(self._cookie)

    def _get_crawler(self) -> ElectricityCrawler:
        """获取或创建 crawler（使用用户自配 Cookie）"""
        if self._crawler is None:
            from app.core.config import Config

            self._crawler = ElectricityCrawler(
                base_url=getattr(Config, "ELECTRICITY_CRAWLER_BASE_URL", "http://dk.cqie.cn"),
                cookie=self._cookie,
                max_pages=getattr(Config, "ELECTRICITY_CRAWLER_MAX_PAGES", 50),
            )
        return self._crawler

    @staticmethod
    def clean_meter(raw: Any) -> str:
        """
        清洗电表名：去掉爬虫可能附加的 "电表:" 前缀和 "照明" 后缀等噪声，
        统一为楼栋+寝室号（如 "31栋512"）。空值兜底 "default"。

        实现委托给 ElectricityRepository.normalize_meter（单一真相源），
        入库去重与展示清洗共用同一套归一化规则，避免两处规则不一致
        导致「清洗后的值」与「库里历史值」对不上而重复插入。

        历史脏数据格式（爬虫 _parse_json 拼前缀 / _parse_html 原文本）：
          - "电表: 31栋512照明" → "31栋512"
          - "电表: 310512" → "310512"
          - "31栋512照明" → "31栋512"
          - "310512" → "310512"

        注意：一个宿舍可能有多块分表（如 "31栋512" 与 "310512"），
        归一化后仍是不同标识，各自保留，不能互相合并。
        """
        return ElectricityRepository.normalize_meter(raw)

    @staticmethod
    def _utc_to_local(ts: Any) -> Any:
        """
        把 electricity_remaining.recorded_at（UTC 存储）转成本地时间（Asia/Shanghai, UTC+8）。
        输入为 to_dict 输出的 "%Y-%m-%d %H:%M:%S" 字符串或 datetime；解析失败原样返回。
        """
        if not ts:
            return ts
        try:
            if isinstance(ts, datetime):
                dt = ts
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                # 移除时区信息后按 UTC 处理（库内为 naive UTC）
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
            return (dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return ts

    @staticmethod
    def parse_statistics_range(
        range_type: str,
        start_date_str: str | None = None,
        end_date_str: str | None = None,
    ) -> tuple[datetime, datetime, datetime, datetime]:
        """
        解析统计时间范围（本地时间 + 对应 UTC 时间）

        供路由层（electricity_routes / admin_routes）共用，避免两端重复实现。

        Args:
            range_type: 时间范围类型
                (week-本周, last_week-上周, month-本月, last_month-上月, custom-自定义)
            start_date_str: 自定义开始日期 (YYYY-MM-DD)，range_type=custom 时必填
            end_date_str: 自定义结束日期 (YYYY-MM-DD)，range_type=custom 时必填

        Returns:
            (start_time_utc, end_time_utc, local_start_time, local_end_time)
            前两个为 UTC 时间（数据库查询用），后两个为本地时间（展示用）

        Raises:
            ValueError: 自定义日期格式错误
        """
        # 计算日期范围（使用本地时间，中国时区 UTC+8）
        now = datetime.utcnow()
        local_now = now + timedelta(hours=8)
        today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

        if range_type == "week":
            # 本周（周一到今天）
            weekday = today.weekday()  # 0=周一, 6=周日
            start_time = today - timedelta(days=weekday)
            end_time = today + timedelta(days=1)
        elif range_type == "last_week":
            # 上周（上周一到上周日）
            weekday = today.weekday()
            end_time = today - timedelta(days=weekday)  # 本周一
            start_time = end_time - timedelta(days=7)  # 上周一
        elif range_type == "month":
            # 本月（1号到今天）
            start_time = today.replace(day=1)
            end_time = today + timedelta(days=1)
        elif range_type == "last_month":
            # 上月（1号到月底）
            end_time = today.replace(day=1)  # 本月1号
            last_month_end = end_time - timedelta(days=1)  # 上月最后一天
            start_time = last_month_end.replace(day=1)  # 上月1号
        elif range_type == "custom" and start_date_str and end_date_str:
            # 自定义日期范围
            try:
                start_time = datetime.strptime(start_date_str, "%Y-%m-%d")
                end_time = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
            except ValueError as exc:
                raise ValueError("日期格式错误，请使用 YYYY-MM-DD") from exc
        else:
            # 默认本月
            start_time = today.replace(day=1)
            end_time = today + timedelta(days=1)

        # 将本地时间转换回 UTC 时间用于数据库查询
        start_time_utc = start_time - timedelta(hours=8)
        end_time_utc = end_time - timedelta(hours=8)
        return start_time_utc, end_time_utc, start_time, end_time

    def fetch_and_save_data(self, max_pages: int | None = None) -> tuple[bool, str]:
        """
        获取并保存电量数据（按当前用户隔离落库）

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
                    user_id=self._user_id,
                )

                # 更新容量管理器，检测充值和低电量
                session.commit()  # 先提交剩余电量记录
                self._capacity_manager.update_remaining(
                    current_remaining=remaining_float,
                    low_power_threshold=10.0,
                )

                # 批量保存用电记录（meter 经 clean_meter 统一清洗写入，避免污染）
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
                            self.clean_meter(r.get("meter", "")),
                        )
                    )

                ElectricityRepository.create_records_batch(
                    session, record_tuples, user_id=self._user_id
                )

                session.commit()
                logger.info(
                    f"[ElectricityService] 电量数据已保存(user_id={self._user_id}): "
                    f"{len(records)} 条记录，剩余 {remaining} 度"
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

    def refresh_remaining_power(self, force: bool = False) -> dict[str, Any] | None:
        """
        轻量刷新剩余电量：只爬一次 remaining（1 个请求，快），不爬全量用电记录。

        带冷却保护（默认 60s）：冷却期内重复调用直接返回最新缓存，避免用户频繁
        打开电量页/我的页导致对学校接口的频繁请求被反爬。

        Args:
            force: 为 True 时跳过冷却，强制爬取一次

        Returns:
            最新剩余电量数据（同 get_remaining_power 结构），失败返回缓存或 None
        """
        now = time.time()
        if (
            not force
            and self._last_remaining_refresh
            and now - self._last_remaining_refresh < self._remaining_refresh_cooldown
        ):
            return self.get_remaining_power()

        crawler = self._get_crawler()
        remaining = crawler.fetch_remaining_power()
        if remaining:
            remaining_value = remaining.get("default", 0) if isinstance(remaining, dict) else remaining
            try:
                remaining_float = float(remaining_value) if remaining_value else 0.0
            except (TypeError, ValueError):
                remaining_float = 0.0
            session = get_db()
            try:
                ElectricityRepository.create_remaining(
                    session=session,
                    remaining=remaining_float,
                    meter=self._meter,
                    user_id=self._user_id,
                )
                session.commit()
                self._capacity_manager.update_remaining(
                    current_remaining=remaining_float,
                    low_power_threshold=10.0,
                )
                self._last_remaining_refresh = now
                logger.info(
                    f"[ElectricityService] 轻量刷新剩余电量成功(user_id={self._user_id}): "
                    f"{remaining_float} 度"
                )
            except Exception as exc:
                session.rollback()
                logger.error(f"[ElectricityService] 轻量刷新剩余电量保存失败: {exc}")
            finally:
                session.close()
        else:
            logger.warning("[ElectricityService] 轻量刷新剩余电量失败（爬取为空），返回缓存")

        return self.get_remaining_power()

    def get_remaining_power(self, meter: str = None) -> dict[str, Any] | None:
        """
        获取最新剩余电量（包含百分比信息，按用户隔离）

        Args:
            meter: 电表名称，为None时使用初始化时的meter

        Returns:
            Optional[Dict]: 剩余电量数据或 None，包含百分比和总量信息
        """
        target_meter = meter or self._meter
        session = get_db()
        try:
            record = ElectricityRepository.get_latest_remaining(
                session, target_meter, user_id=self._user_id
            )
            if record:
                data = record.to_dict()
                # recorded_at 以 UTC 存储（create_remaining 用 datetime.utcnow），
                # 转成本地时间（Asia/Shanghai, UTC+8）再返回，避免前端显示比本地慢 8 小时
                data["recorded_at"] = self._utc_to_local(data.get("recorded_at"))
                # 获取容量管理器的状态信息
                capacity_status = self._capacity_manager.get_current_status()
                # 合并容量信息到返回数据
                data["total_capacity"] = capacity_status.get("total_capacity", 100.0)
                data["percentage"] = capacity_status.get("percentage", 0.0)
                data["is_low_power"] = capacity_status.get("is_low_power", False)
                # 写入真实楼栋名（remaining 表 meter 恒为 default，楼栋需从历史记录解析）
                building = self.get_building_meter()
                if building:
                    data["meter"] = building
                return data
            return None
        finally:
            session.close()

    def get_usage_records(
        self,
        meter: str | None = None,
        days: int | None = 30,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        获取用电记录（按用户隔离）

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
                offset=offset,
                user_id=self._user_id,
            )
            return [r.to_dict() for r in records]
        finally:
            session.close()

    def count_usage_records(
        self,
        meter: str | None = None,
        days: int | None = 30,
    ) -> int:
        """
        统计用电记录总数（与 get_usage_records 一致的过滤条件，用于列表分页 total）

        Args:
            meter: 电表名称筛选
            days: 最近多少天；为 None 时不做时间过滤

        Returns:
            int: 记录总数
        """
        session = get_db()
        try:
            start_time = None
            end_time = None
            if days is not None:
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(days=days)
            return ElectricityRepository.count_records(
                session=session,
                meter=meter,
                start_time=start_time,
                end_time=end_time,
                user_id=self._user_id,
            )
        finally:
            session.close()

    def get_usage_trend(self, days: int = 30) -> list[dict[str, Any]]:
        """
        获取最近 days 天每日用电量聚合（含用电为 0 的日期，按天补齐，按用户隔离）

        返回列表按日期升序（旧 -> 新），每项 {"date": "YYYY-MM-DD", "usage": float}。
        用于小程序用电趋势折线图，仅传输聚合后的少量点，避免一次性拉取全部明细。

        时区说明：入库 record_time 为北京本地时间（naive），此处用服务器本地时间
        now 作为"今天"近似（服务与设备均在中国时区），并以 days+1 的窗口兜底，
        避免 UTC/北京约 8 小时偏差造成边界日漏统计。
        """
        from collections import defaultdict

        session = get_db()
        try:
            now = datetime.now()
            start_pad = now - timedelta(days=days + 1)
            end_pad = now + timedelta(days=1)
            records = ElectricityRepository.get_records(
                session=session,
                start_time=start_pad,
                end_time=end_pad,
                limit=100000,
                user_id=self._user_id,
            )
            daily = defaultdict(float)
            for r in records:
                d = r.record_time.strftime("%Y-%m-%d") if r.record_time else None
                if d:
                    daily[d] += float(r.usage or 0)

            points: list[dict[str, Any]] = []
            for i in range(days - 1, -1, -1):
                d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                points.append({"date": d, "usage": round(daily.get(d, 0.0), 2)})
            return points
        finally:
            session.close()

    def get_building_meter(self) -> str | None:
        """
        获取该用户宿舍真实楼栋名（优先可读的「照明」变体，如「31栋512照明」）

        用电记录的 meter 字段即为楼栋寝室信息（如「31栋512照明」或原始「310512」），
        两者交替出现。优先返回带「照明」后缀的可读名称，供前端直接展示。
        """
        session = get_db()
        try:
            recent = ElectricityRepository.get_records(
                session=session, limit=50, user_id=self._user_id
            )
            # 优先：含「照明」或「栋」的可读楼栋名
            for r in recent:
                m = (r.meter or "").strip()
                if m and m != "default" and (m.endswith("照明") or "栋" in m):
                    return m
            # 兜底：任意非默认 meter
            for r in recent:
                m = (r.meter or "").strip()
                if m and m != "default":
                    return m
            return None
        finally:
            session.close()

    def get_statistics(self, days: int = 30) -> dict[str, Any]:
        """
        获取用电统计（按用户隔离）

        Args:
            days: 统计最近多少天

        Returns:
            Dict: 统计数据
        """
        session = get_db()
        try:
            # 按电表统计
            by_meter = ElectricityRepository.get_usage_by_meter(
                session, days, user_id=self._user_id
            )

            # 计算汇总
            total_usage = sum(usage for _, usage in by_meter)
            meter_count = len(by_meter)

            # 获取每日统计（简化版，取最近7天）
            daily = []
            for i in range(min(days, 7)):
                target_date = datetime.utcnow() - timedelta(days=i)
                total, count = ElectricityRepository.get_daily_statistics(
                    session, target_date, user_id=self._user_id
                )
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
        获取指定时间范围的用电统计（按用户隔离）

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
                user_id=self._user_id,
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
                    user_id=self._user_id,
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

    def get_monthly_usage(self) -> dict[str, Any]:
        """
        获取本月（自然月 1 号起）累计用电量（按用户隔离，后端统一聚合）

        背景：此前「本月已用」由前端各自拉取记录在本地累加——我的页拉 1000 条、
        详情页只拉首屏 20 条，同一月份算出 162.93 / 74.04 两个不同值。
        改由后端按 user_id + 自然月聚合，保证各页面口径一致。

        Returns:
            Dict: {"month_used": 本月累计(度), "month_start": "YYYY-MM-DD", "days": 已统计天数}
        """
        session = get_db()
        try:
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # 学校系统每日 00 点后结算前一天，记录时间会比用电日多约 1 天，
            # 上界留到明天，避免当天结算记录被漏掉
            total = ElectricityRepository.sum_usage_since(
                session=session, start_time=month_start, user_id=self._user_id
            )
            return {
                "month_used": round(total, 2),
                "month_start": month_start.strftime("%Y-%m-%d"),
                "days": max(1, (now - month_start).days + 1),
            }
        finally:
            session.close()

    def deduplicate_records(self) -> dict[str, Any]:
        """
        清理本用户（user_id=None 时为全库）的历史重复用电记录

        同一用户同一日期只保留一条，删除因电表写法不一致（"31栋512"/"310512"）
        产生的重复行。用于修复此前已经写进库的脏数据。

        Returns:
            Dict: {"groups": 重复天数, "deleted": 删除条数, "kept": 保留条数}
        """
        session = get_db()
        try:
            result = ElectricityRepository.deduplicate_records(
                session=session, user_id=self._user_id
            )
            session.commit()
            logger.info(
                f"[ElectricityService] 重复用电记录清理完成(user_id={self._user_id}): {result}"
            )
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def check_low_power(
        self, threshold: float = 10.0, meter: str = "default"
    ) -> tuple[bool, float]:
        """
        检查是否低电量（按用户隔离）

        Args:
            threshold: 低电量阈值
            meter: 电表名称

        Returns:
            Tuple[bool, float]: (是否低电量, 当前剩余电量)
        """
        session = get_db()
        try:
            record = ElectricityRepository.get_latest_remaining(
                session, meter, user_id=self._user_id
            )
            if not record:
                return False, 0.0

            remaining = record.remaining
            is_low = remaining < threshold
            return is_low, remaining
        finally:
            session.close()


# 模块级单例：供路由与任务模块直接引用（user_id=None=全局/管理员视图）
electricity_service = ElectricityService()

# 按 (user_id, meter) 缓存的服务实例：避免每次请求重复实例化，且冷却状态按用户独立
_service_cache: dict[tuple[int | None, str], ElectricityService] = {}


def get_electricity_service(
    user_id: int | None = None, meter: str = "default", cookie: str = ""
) -> ElectricityService:
    """
    按用户+电表获取服务实例（缓存复用）

    Args:
        user_id: 归属用户ID（None=全局/管理员视图）
        meter: 电表名称
        cookie: 用户自配 Cookie；提供时同步到实例（crawler 立即生效）

    Returns:
        ElectricityService: 电量服务实例
    """
    global _service_cache
    key = (user_id, meter)
    svc = _service_cache.get(key)
    if svc is None:
        svc = ElectricityService(meter=meter, user_id=user_id, cookie=cookie)
        _service_cache[key] = svc
    elif cookie:
        svc.set_cookie(cookie)
    return svc
