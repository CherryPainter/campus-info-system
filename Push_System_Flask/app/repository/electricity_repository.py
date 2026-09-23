#!/usr/bin/env python3
"""
电量数据仓库

职责：
- 封装电量相关的数据库操作
- 提供类型安全的 CRUD 接口
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

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
        user_id: int | None = None,
    ) -> ElectricityRecord:
        """
        创建用电记录

        Args:
            session: 数据库会话
            record_time: 记录时间
            usage: 用电量
            meter: 电表名称
            user_id: 归属用户ID（每宿舍独立电表，学生各自的数据归各自）

        Returns:
            ElectricityRecord: 创建的记录对象
        """
        record = ElectricityRecord(
            record_time=record_time,
            usage=usage,
            meter=meter,
            user_id=user_id,
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def normalize_meter(raw: Any) -> str:
        """
        把电表写法归一化为唯一标识（去噪，用于去重时的比对）

        同一个宿舍在库里会出现多种写法（历史脏数据 + 不同解析路径）：
          - "电表: 31栋512照明"  →  "31栋512"
          - "31栋512照明"        →  "31栋512"
          - "31栋512"            →  "31栋512"
          - "电表: 310512"       →  "310512"
          - "310512"             →  "310512"

        注意：一个宿舍通常有**多块分表**（如照明 / 空调），它们归一化后仍然是
        不同的标识（"31栋512" 与 "310512" 是两块不同的表，用电量各不相同，
        当天真实用量 = 各分表之和）。因此去重绝不能只按「用户+日期」，
        必须带上归一化后的电表，否则会把另一块分表当成重复数据误删。
        """
        import re

        if raw is None:
            return "default"
        s = str(raw).strip()
        if not s or s == "default":
            return "default"
        s = re.sub(r"^电表[:：]\s*", "", s)
        s = re.sub(r"照明\s*$", "", s)
        s = s.strip()
        return s if s else "default"

    @staticmethod
    def create_records_batch(
        session: Session,
        records: list[tuple[datetime, float, str]],
        user_id: int | None = None,
    ) -> int:
        """
        批量创建用电记录（按「用户 + 用电日期 + 归一化电表」去重）

        去重逻辑变更说明（重要）：
            旧逻辑按 (record_time 精确到秒, meter 原始字符串) 精确匹配。但同一个
            电表在库里存在多种写法——老数据是未清洗的 "电表: 31栋512照明"，
            新数据经 clean_meter 清洗后变成 "31栋512"——两次爬取的写法对不上，
            精确匹配永远命中不了，于是同一块表同一天被反复插入多条。
            趋势图按日求和时被成倍累加：实际每天约 7 度，图上却显示 22 度
            （7.37 × 3 份重复）；列表总条数也随之虚高到单用户 2000+。

            修正：先用电表写法归一化（normalize_meter）去掉 "电表:" 前缀与
            "照明" 后缀，再按 (user_id, DATE(record_time), 归一化电表) 去重。

        特别强调：
            一个宿舍有**多块分表**（如照明 / 空调），归一化后仍是不同标识
            （"31栋512" 与 "310512" 是两块表，同一天用电量分别是 1.8 和 5.57）。
            因此去重必须带上电表维度，绝不能只按「用户 + 日期」，
            否则会把另一块分表当成重复数据误删，日用量直接少算一大截。

        Args:
            session: 数据库会话
            records: [(record_time, usage, meter), ...]
            user_id: 归属用户ID，None 表示历史全局数据

        Returns:
            int: 实际创建的记录数（已存在被更新、重复被删除的不计入）
        """
        created_count = 0
        for record_time, usage, meter in records:
            if record_time is None:
                continue

            norm_meter = ElectricityRepository.normalize_meter(meter)
            day_start = record_time.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            q = session.query(ElectricityRecord).filter(
                and_(
                    ElectricityRecord.record_time >= day_start,
                    ElectricityRecord.record_time < day_end,
                )
            )
            if user_id is not None:
                q = q.filter(ElectricityRecord.user_id == user_id)
            else:
                q = q.filter(ElectricityRecord.user_id.is_(None))

            # 在当天记录里找出「归一化后是同一块表」的那些
            same_meter = [
                r
                for r in q.order_by(ElectricityRecord.id).all()
                if ElectricityRepository.normalize_meter(r.meter) == norm_meter
            ]

            if same_meter:
                # 保留第一条，更新用电量并把电表写法统一为归一化后的值
                keep = same_meter[0]
                keep.usage = usage
                keep.meter = norm_meter
                for dup in same_meter[1:]:
                    session.delete(dup)
                continue

            record = ElectricityRecord(
                record_time=record_time,
                usage=usage,
                meter=norm_meter,
                user_id=user_id,
            )
            session.add(record)
            created_count += 1
        session.flush()
        return created_count

    @staticmethod
    def deduplicate_records(
        session: Session,
        user_id: int | None = None,
    ) -> dict:
        """
        清理历史重复用电记录：同一用户 + 同一日期 + 同一块电表 只保留一条

        用于修复「按 (record_time, meter) 精确字符串去重」时期已经写进库的脏数据
        （同一块表被写成 "电表: 31栋512照明" 和 "31栋512" 等多种写法，
        精确匹配不上，导致同一块表同一天被插入多条，趋势图数值成倍放大）。

        分组维度必须是「用户 + 日期 + 归一化电表」：
            一个宿舍有多块分表（"31栋512" 和 "310512" 是两块不同的表，
            同一天用电量分别是 1.8 和 5.57），只按「用户+日期」分组会把
            另一块分表误判为重复而删除，导致日用量少算。

        保留策略（同一分组内）：保留 created_at 最新的一条
        （学校每日结算值可能随采集时间略有更新），并把电表写法统一为归一化值。

        Args:
            session: 数据库会话
            user_id: 指定用户ID；None 表示清理全部用户（含 NULL 的历史全局数据）

        Returns:
            dict: {"groups": 重复的分组数, "deleted": 删除条数, "kept": 保留条数}
        """
        from collections import defaultdict

        q = session.query(ElectricityRecord)
        if user_id is not None:
            q = q.filter(ElectricityRecord.user_id == user_id)
        all_records = q.all()

        # 按 (user_id, 日期, 归一化电表) 分组
        groups: dict[tuple, list] = defaultdict(list)
        for r in all_records:
            if r.record_time is None:
                continue
            key = (
                r.user_id,
                r.record_time.date(),
                ElectricityRepository.normalize_meter(r.meter),
            )
            groups[key].append(r)

        deleted = 0
        kept = 0
        dup_groups = 0

        for _key, items in groups.items():
            if len(items) <= 1:
                kept += len(items)
                # 单条也顺手统一电表写法，便于后续展示与去重
                if items:
                    items[0].meter = ElectricityRepository.normalize_meter(items[0].meter)
                continue

            dup_groups += 1
            items_sorted = sorted(
                items, key=lambda rec: (rec.created_at or datetime.min, rec.id), reverse=True
            )
            keep = items_sorted[0]
            keep.meter = ElectricityRepository.normalize_meter(keep.meter)
            for dup in items_sorted[1:]:
                session.delete(dup)
                deleted += 1
            kept += 1

        session.flush()
        return {"groups": dup_groups, "deleted": deleted, "kept": kept}

    @staticmethod
    def get_records(
        session: Session,
        meter: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 1000,
        offset: int = 0,
        user_id: int | None = None,
    ) -> list[ElectricityRecord]:
        """
        查询用电记录

        Args:
            session: 数据库会话
            meter: 电表名称筛选
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回条数限制
            offset: 跳过的条数（用于分页）
            user_id: 归属用户ID，None 表示全部（管理员视图）

        Returns:
            List[ElectricityRecord]: 用电记录列表
        """
        query = session.query(ElectricityRecord)

        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        if meter:
            query = query.filter(ElectricityRecord.meter == meter)
        if start_time:
            query = query.filter(ElectricityRecord.record_time >= start_time)
        if end_time:
            query = query.filter(ElectricityRecord.record_time <= end_time)

        return (
            query.order_by(desc(ElectricityRecord.record_time))
            .offset(offset)
            .limit(limit)
            .all()
        )

    @staticmethod
    def count_records(
        session: Session,
        meter: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: int | None = None,
    ) -> int:
        """
        统计用电记录总数（与 get_records 相同的过滤条件，用于分页 total）

        Returns:
            int: 记录总数
        """
        query = session.query(func.count(ElectricityRecord.id))

        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        if meter:
            query = query.filter(ElectricityRecord.meter == meter)
        if start_time:
            query = query.filter(ElectricityRecord.record_time >= start_time)
        if end_time:
            query = query.filter(ElectricityRecord.record_time <= end_time)

        return query.scalar() or 0

    # ==================== 按「用电日」聚合 ====================
    #
    # 关键语义（全项目统一，勿改）：electricity_records.record_time 是**结算时刻**，
    # 即「实际用电日 + 1 天的 00:0x」。依据：
    #   - 爬虫在用电日次日 00 点后结算前一天，同一次爬取抓到的多块分表时刻完全相同；
    #   - tasks._build_weekly_stats / _build_monthly_stats 均按 record_time - 1 天
    #     还原用电日；_build_daily_stats 亦按 record_time 落在 target_date + 1 天取值；
    #   - 小程序电量页自身提示「每日 00 点后结算前一天的用电」。
    # 因此按下表分组后，展示给用户的「用电日」= 结算日 - 1 天。

    @staticmethod
    def _settle_date_expr():
        """结算日表达式：DATE(record_time)，MySQL / SQLite 均支持"""
        return func.date(ElectricityRecord.record_time)

    @staticmethod
    def _to_date_str(value: Any) -> str:
        """把 func.date() 的返回值统一成 'YYYY-MM-DD'（MySQL 返回 date，SQLite 返回 str）"""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    @staticmethod
    def get_daily_aggregates(
        session: Session,
        user_id: int | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        按结算日分组、分页返回每日合计用电（一天一条，已合并该日全部电表）

        这是「一个宿舍多块分表 → 一天多条原始记录」的聚合层：
        同一个宿舍的两块分表当天各有一条记录，此处按天 SUM 后一天只剩一条。

        Returns:
            List[Dict]: 按结算日倒序，每项
                {
                  "settle_date": "2026-09-18",      # 结算日（= 用电日 + 1 天）
                  "total_usage": 2.46,
                  "record_count": 2,                # 该日涉及的分表条数
                  "settle_time": "2026-09-18 00:09:51",
                }
        """
        day = ElectricityRepository._settle_date_expr()
        query = session.query(
            day.label("settle_date"),
            func.sum(ElectricityRecord.usage).label("total_usage"),
            func.count(ElectricityRecord.id).label("record_count"),
            func.max(ElectricityRecord.record_time).label("settle_time"),
        ).filter(ElectricityRecord.record_time.isnot(None))

        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)

        rows = (
            query.group_by(day)
            .order_by(desc(day))
            .limit(max(1, int(limit)))
            .offset(max(0, int(offset)))
            .all()
        )

        result: list[dict[str, Any]] = []
        for settle_date, total, count, settle_time in rows:
            result.append(
                {
                    "settle_date": ElectricityRepository._to_date_str(settle_date),
                    "total_usage": round(float(total or 0), 2),
                    "record_count": int(count or 0),
                    "settle_time": settle_time.strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(settle_time, datetime)
                    else None,
                }
            )
        return result

    @staticmethod
    def count_daily_aggregates(session: Session, user_id: int | None = None) -> int:
        """统计有记录的「结算日」天数（用于按天分页的 total）"""
        day = ElectricityRepository._settle_date_expr()
        query = session.query(func.count(func.distinct(day))).filter(
            ElectricityRecord.record_time.isnot(None)
        )
        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        return int(query.scalar() or 0)

    @staticmethod
    def get_records_of_usage_day(
        session: Session,
        usage_date: str,
        user_id: int | None = None,
    ) -> list[ElectricityRecord]:
        """
        取某个**用电日**的全部原始记录（该日各分表各一条）

        用电日 D 的结算记录落在 [D+1 00:00, D+2 00:00)。

        Args:
            usage_date: 用电日 'YYYY-MM-DD'
        """
        start = datetime.strptime(usage_date, "%Y-%m-%d") + timedelta(days=1)
        end = start + timedelta(days=1)

        query = session.query(ElectricityRecord).filter(
            and_(
                ElectricityRecord.record_time >= start,
                ElectricityRecord.record_time < end,
            )
        )
        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        return query.order_by(ElectricityRecord.meter).all()

    @staticmethod
    def get_daily_totals_between(
        session: Session,
        start_time: datetime,
        end_time: datetime,
        user_id: int | None = None,
    ) -> list[tuple[str, float]]:
        """
        取时间范围内按结算日的每日合计，返回 [(结算日 'YYYY-MM-DD', 合计), ...] 升序

        用于「较前一日」「近 7 日均值」等对比口径，避免为每个对比项单独查一次库。
        """
        day = ElectricityRepository._settle_date_expr()
        query = session.query(
            day.label("settle_date"),
            func.sum(ElectricityRecord.usage).label("total_usage"),
        ).filter(
            and_(
                ElectricityRecord.record_time.isnot(None),
                ElectricityRecord.record_time >= start_time,
                ElectricityRecord.record_time < end_time,
            )
        )
        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)

        rows = query.group_by(day).order_by(day).all()
        return [
            (ElectricityRepository._to_date_str(d), round(float(u or 0), 2))
            for d, u in rows
        ]

    @staticmethod
    def get_remaining_at_or_before(
        session: Session,
        cutoff: datetime,
        meter: str = "default",
        user_id: int | None = None,
    ) -> ElectricityRemaining | None:
        """
        取 cutoff 时刻（含）之前最近一条剩余电量记录

        用于给「某个历史用电日」还原当时的剩余电量；无记录返回 None。
        """
        query = session.query(ElectricityRemaining).filter(
            and_(
                ElectricityRemaining.meter == meter,
                ElectricityRemaining.recorded_at <= cutoff,
            )
        )
        if user_id is not None:
            query = query.filter(ElectricityRemaining.user_id == user_id)
        return query.order_by(desc(ElectricityRemaining.recorded_at)).first()

    @staticmethod
    def get_daily_statistics(
        session: Session,
        target_date: datetime,
        meter: str | None = None,
        user_id: int | None = None,
    ) -> tuple[float, int]:
        """
        获取某日用电统计

        Args:
            session: 数据库会话
            target_date: 目标日期
            meter: 电表名称筛选
            user_id: 归属用户ID，None 表示全部

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

        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
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
        user_id: int | None = None,
    ) -> list[tuple[str, float]]:
        """
        按电表统计用电量

        Args:
            session: 数据库会话
            days: 统计最近多少天
            user_id: 归属用户ID，None 表示全部

        Returns:
            List[Tuple[str, float]]: [(meter, total_usage), ...]
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        query = (
            session.query(
                ElectricityRecord.meter,
                func.sum(ElectricityRecord.usage),
            ).filter(ElectricityRecord.record_time >= cutoff_time)
        )
        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        results = (
            query.group_by(ElectricityRecord.meter)
            .order_by(desc(func.sum(ElectricityRecord.usage)))
            .all()
        )

        return [(meter, float(usage or 0)) for meter, usage in results]

    @staticmethod
    def get_usage_by_meter_and_range(
        session: Session,
        start_time: datetime,
        end_time: datetime,
        meter: str | None = None,
        user_id: int | None = None,
    ) -> list[tuple[str, float]]:
        """
        按电表统计指定时间范围的用电量

        Args:
            session: 数据库会话
            start_time: 开始时间
            end_time: 结束时间
            meter: 电表名称筛选（可选）
            user_id: 归属用户ID，None 表示全部

        Returns:
            List[Tuple[str, float]]: [(meter, total_usage), ...]
        """
        query = session.query(
            ElectricityRecord.meter,
            func.sum(ElectricityRecord.usage),
        ).filter(
            and_(
                ElectricityRecord.record_time >= start_time,
                ElectricityRecord.record_time < end_time,
            )
        )

        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        if meter:
            query = query.filter(ElectricityRecord.meter == meter)

        results = (
            query.group_by(ElectricityRecord.meter)
            .order_by(desc(func.sum(ElectricityRecord.usage)))
            .all()
        )

        return [(m, float(usage or 0)) for m, usage in results]

    @staticmethod
    def sum_usage_since(
        session: Session,
        start_time: datetime,
        user_id: int | None = None,
    ) -> float:
        """
        统计某个时间点之后的累计用电量（不按电表分组，直接求和）

        用于「本月已用」等自然月累计口径：前端此前各自拉取若干条记录在本地累加，
        不同页面取的条数不同（我的页取 1000 条、详情页只取首屏 20 条），
        导致同一个月在两个页面显示成 162.93 / 74.04 两个不同数字。
        统一由后端聚合后，各页面口径一致。

        Args:
            session: 数据库会话
            start_time: 起始时间（含），通常传本月 1 号 00:00
            user_id: 归属用户ID，None 表示全部

        Returns:
            float: 累计用电量（度），无记录时返回 0.0
        """
        query = session.query(func.sum(ElectricityRecord.usage)).filter(
            ElectricityRecord.record_time >= start_time
        )
        if user_id is not None:
            query = query.filter(ElectricityRecord.user_id == user_id)
        total = query.scalar()
        return float(total or 0.0)

    # ==================== 剩余电量相关 ====================

    @staticmethod
    def create_remaining(
        session: Session,
        remaining: float,
        meter: str = "default",
        user_id: int | None = None,
    ) -> ElectricityRemaining:
        """
        创建剩余电量记录

        Args:
            session: 数据库会话
            remaining: 剩余电量
            meter: 电表名称
            user_id: 归属用户ID

        Returns:
            ElectricityRemaining: 创建的记录对象
        """
        record = ElectricityRemaining(
            meter=meter,
            remaining=remaining,
            recorded_at=datetime.utcnow(),
            user_id=user_id,
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def get_latest_remaining(
        session: Session,
        meter: str = "default",
        user_id: int | None = None,
    ) -> ElectricityRemaining | None:
        """
        获取最新剩余电量

        Args:
            session: 数据库会话
            meter: 电表名称
            user_id: 归属用户ID，None 表示全部

        Returns:
            Optional[ElectricityRemaining]: 最新记录或 None
        """
        query = session.query(ElectricityRemaining).filter(ElectricityRemaining.meter == meter)
        if user_id is not None:
            query = query.filter(ElectricityRemaining.user_id == user_id)
        return query.order_by(desc(ElectricityRemaining.recorded_at)).first()

    @staticmethod
    def get_previous_remaining(
        session: Session,
        meter: str = "default",
        user_id: int | None = None,
    ) -> ElectricityRemaining | None:
        """
        获取上一条剩余电量（跳过最新条，用于容量充值对比）

        因为最新条通常是本次爬取刚插入的，用次新条来对比才能发现"昨天 < 今天"的充值场景。
        """
        query = session.query(ElectricityRemaining).filter(ElectricityRemaining.meter == meter)
        if user_id is not None:
            query = query.filter(ElectricityRemaining.user_id == user_id)
        return query.order_by(desc(ElectricityRemaining.recorded_at)).offset(1).limit(1).first()

    @staticmethod
    def get_remaining_history(
        session: Session,
        meter: str = "default",
        days: int = 30,
        user_id: int | None = None,
    ) -> list[ElectricityRemaining]:
        """
        获取剩余电量历史

        Args:
            session: 数据库会话
            meter: 电表名称
            days: 查询最近多少天
            user_id: 归属用户ID，None 表示全部

        Returns:
            List[ElectricityRemaining]: 剩余电量记录列表
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        query = session.query(ElectricityRemaining).filter(
            and_(
                ElectricityRemaining.meter == meter,
                ElectricityRemaining.recorded_at >= cutoff_time,
            )
        )
        if user_id is not None:
            query = query.filter(ElectricityRemaining.user_id == user_id)

        return query.order_by(ElectricityRemaining.recorded_at).all()

    # ==================== 电量容量相关 ====================

    @staticmethod
    def create_capacity_record(
        session: Session,
        total_capacity: float,
        remaining_at_record: float,
        meter: str = "default",
        reason: str = "auto_detect",
        user_id: int | None = None,
    ) -> ElectricityTotalCapacity:
        """
        创建电量容量记录

        Args:
            session: 数据库会话
            total_capacity: 总量（度）
            remaining_at_record: 记录时的剩余电量（度）
            meter: 电表名称
            reason: 记录原因
            user_id: 归属用户ID

        Returns:
            ElectricityTotalCapacity: 创建的记录对象
        """
        record = ElectricityTotalCapacity(
            meter=meter,
            total_capacity=total_capacity,
            remaining_at_record=remaining_at_record,
            record_reason=reason,
            recorded_at=datetime.utcnow(),
            user_id=user_id,
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def get_latest_capacity_record(
        session: Session,
        meter: str = "default",
        user_id: int | None = None,
    ) -> ElectricityTotalCapacity | None:
        """
        获取最新容量记录

        Args:
            session: 数据库会话
            meter: 电表名称
            user_id: 归属用户ID，None 表示全部

        Returns:
            Optional[ElectricityTotalCapacity]: 最新记录或 None
        """
        query = session.query(ElectricityTotalCapacity).filter(
            ElectricityTotalCapacity.meter == meter
        )
        if user_id is not None:
            query = query.filter(ElectricityTotalCapacity.user_id == user_id)
        return query.order_by(desc(ElectricityTotalCapacity.recorded_at)).first()

    @staticmethod
    def get_capacity_history(
        session: Session,
        meter: str = "default",
        days: int = 30,
        user_id: int | None = None,
    ) -> list[ElectricityTotalCapacity]:
        """
        获取容量历史记录

        Args:
            session: 数据库会话
            meter: 电表名称
            days: 查询最近多少天
            user_id: 归属用户ID，None 表示全部

        Returns:
            List[ElectricityTotalCapacity]: 容量记录列表
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)

        query = session.query(ElectricityTotalCapacity).filter(
            and_(
                ElectricityTotalCapacity.meter == meter,
                ElectricityTotalCapacity.recorded_at >= cutoff_time,
            )
        )
        if user_id is not None:
            query = query.filter(ElectricityTotalCapacity.user_id == user_id)

        return query.order_by(desc(ElectricityTotalCapacity.recorded_at)).all()
