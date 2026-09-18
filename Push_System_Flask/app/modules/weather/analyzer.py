#!/usr/bin/env python3
"""
天气分析引擎
包含规则引擎、提示生成、冷却机制
"""

import json
import os
import time
from datetime import datetime
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)

# 冷却时间常量（秒）——用于高温/降温/预警等「按时间冷却」的事件
# 降雨提醒已改为「分时段 + 每天每段仅一次」，不再使用时间冷却
_COOLDOWN_SECONDS = {
    "heat": 6 * 3600,  # 高温提醒 6 小时
    "cold": 6 * 3600,  # 降温提醒 6 小时
    "alert": 1 * 3600,  # 预警提醒 1 小时
}

# ── 降雨提醒分时段配置 ──
# 排除夜间后把白天等分为若干时段；每个时段仅在高概率时提醒，且当天每段只播报一次。
RAIN_DAY_START_HOUR = 6  # 白天起始（含），早于此视为夜间
RAIN_DAY_END_HOUR = 22  # 白天结束（不含），22:00 起视为夜间
RAIN_SEGMENT_COUNT = 4  # 白天等分块数（(22-6)/4 = 每段 4 小时）
RAIN_SEGMENT_LABELS = ["上午", "中午", "下午", "傍晚"]  # 与块数一一对应
RAIN_POP_THRESHOLD = 70  # 高概率阈值：达到才提醒
RAIN_HEAVY_POP_THRESHOLD = 80  # 大雨阈值（连续 ≥2 小时达标视为大雨）


class WeatherAnalyzer:
    """天气分析引擎

    分析实时天气 + 24h 预报 + 预警数据，输出分析结果与提示。
    内置冷却机制，避免相同类型消息频繁推送。
    冷却状态持久化到磁盘文件。
    """

    def __init__(self, state_dir: str = None) -> None:
        """初始化分析器

        Args:
            state_dir: 状态文件存储目录，默认使用 Config.BASE_DIR/data/weather
        """
        self._state_dir = state_dir
        self._cooldown_state: dict[str, float] = {}
        self._load_cooldown_state()

    # ------------------------------------------------------------------
    # 核心分析方法
    # ------------------------------------------------------------------

    def analyze(
        self,
        now_data: dict | None,
        hourly_data: list[dict] | None,
        alerts_data: list[dict] | None,
    ) -> list[dict[str, Any]]:
        """分析天气数据，返回需要推送的事件列表

        Args:
            now_data: 实时天气字典（来自 fetcher.fetch_now）
            hourly_data: 24h 预报列表（来自 fetcher.fetch_hourly）
            alerts_data: 预警列表（来自 fetcher.fetch_alert）

        Returns:
            事件列表，每个事件包含 type, title, description 等字段
        """
        import logging

        logger = logging.getLogger(__name__)

        events = []
        hourly = hourly_data or []
        alerts = alerts_data or []

        logger.info(f"[天气分析器] 开始分析: 逐小时预报={len(hourly)}条, 预警={len(alerts)}条")

        # ── 降雨检测（分时段）──
        # 规则：排除夜间，白天等分为若干时段；仅当「当前所处时段」降雨概率达到高概率阈值时提醒，
        # 且每个时段当天只播报一次。不再把全天/次日的高概率小时一次性罗列（此前提醒范围过广）。
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        seg_len = (RAIN_DAY_END_HOUR - RAIN_DAY_START_HOUR) / RAIN_SEGMENT_COUNT
        rain_events: list[dict[str, Any]] = []
        rain_hours: list[dict] = []

        # 1) 仅归档「当前时刻之后、当天白天」的逐小时预报（夜间与次日一律排除）
        segment_hours: dict[int, list[dict]] = {i: [] for i in range(RAIN_SEGMENT_COUNT)}
        for item in hourly:
            item_time_str = item.get("time", "")
            # 时间无法解析的条目直接跳过：此前「保守保留」会把次日/异常时段混入提醒范围
            item_dt = self._parse_item_dt(item_time_str)
            if item_dt is None:
                continue
            # 只统计「当天、且在当前时刻之后」的时段
            if item_dt.date() != now.date() or item_dt <= now:
                continue
            hour = item_dt.hour
            # 排除夜间
            if hour < RAIN_DAY_START_HOUR or hour >= RAIN_DAY_END_HOUR:
                continue
            seg_idx = int((hour - RAIN_DAY_START_HOUR) // seg_len)
            if 0 <= seg_idx < RAIN_SEGMENT_COUNT:
                segment_hours[seg_idx].append(
                    {
                        "time": item_time_str,
                        "pop": self._safe_int(item.get("pop", "0")),
                        "text": item.get("text", ""),
                    }
                )

        # 2) 只处理「当前所处时段」：高概率且当天未播报过 → 播报一次
        if RAIN_DAY_START_HOUR <= now.hour < RAIN_DAY_END_HOUR:
            cur_seg = int((now.hour - RAIN_DAY_START_HOUR) // seg_len)
            cur_seg = min(max(cur_seg, 0), RAIN_SEGMENT_COUNT - 1)
            seg_items = [
                x
                for x in segment_hours.get(cur_seg, [])
                if x["pop"] is not None and x["pop"] >= RAIN_POP_THRESHOLD
            ]
            seg_key = f"rain_seg:{today_str}:{cur_seg}"
            if seg_items and not self._segment_pushed(seg_key):
                # 段内连续 ≥2 小时概率 ≥ 大雨阈值 → 视为大雨
                has_heavy = False
                run = 0
                for x in sorted(seg_items, key=lambda y: y["time"]):
                    if (x["pop"] or 0) >= RAIN_HEAVY_POP_THRESHOLD:
                        run += 1
                        if run >= 2:
                            has_heavy = True
                    else:
                        run = 0

                seg_label = (
                    RAIN_SEGMENT_LABELS[cur_seg]
                    if cur_seg < len(RAIN_SEGMENT_LABELS)
                    else f"第{cur_seg + 1}时段"
                )
                seg_start = RAIN_DAY_START_HOUR + int(cur_seg * seg_len)
                seg_end = seg_start + int(seg_len)
                seg_range = f"{seg_start:02d}:00-{seg_end:02d}:00"
                rain_hours = sorted(seg_items, key=lambda y: y["time"])
                max_pop = max((x["pop"] or 0) for x in seg_items)
                rain_events.append(
                    {
                        "type": "rain",
                        "title": "大雨提醒" if has_heavy else "降雨提醒",
                        "description": (
                            f"{seg_label}（{seg_range}）有大雨，请注意防涝，减少外出"
                            if has_heavy
                            else f"{seg_label}（{seg_range}）可能有雨，记得带伞"
                        ),
                        "rain_hours": rain_hours,
                        "severity": "high" if has_heavy else "normal",
                        "has_heavy_rain": has_heavy,
                        "segment_label": seg_label,
                        "segment_range": seg_range,
                        "max_pop": max_pop,
                    }
                )
                self._mark_segment_pushed(seg_key)
                logger.info(
                    f"[天气分析器] 降雨提醒: {seg_label}({seg_range}) 最高概率={max_pop}% "
                    f"小时数={len(rain_hours)} 大雨={has_heavy}"
                )
            elif seg_items:
                logger.info(f"[天气分析器] 当前时段({seg_key})已提醒过，跳过")
        else:
            logger.info("[天气分析器] 非白天时段，跳过降雨提醒")

        logger.info(
            f"[天气分析器] 降雨检测: 事件数={len(rain_events)}, 当前时段高概率小时数={len(rain_hours)}"
        )

        # 温度分析
        has_heat = False
        has_cold_wave = False
        max_temp = None
        min_temp = None
        current_temp = None

        if now_data:
            feels_like = self._safe_int(now_data.get("feels_like", ""))
            if feels_like is not None and feels_like >= 35:
                has_heat = True
            current_temp = self._safe_int(now_data.get("temp", ""))

        # 从 24h 预报中提取最高/最低温
        temp_list = []
        for item in hourly:
            t = self._safe_int(item.get("temp", ""))
            if t is not None:
                temp_list.append(t)

        if temp_list:
            max_temp = max(temp_list)
            min_temp = min(temp_list)
            # 降温检测：当前温度比 24h 最高温低 6 度以上
            if current_temp is not None and max_temp is not None:
                if (max_temp - current_temp) >= 6:
                    has_cold_wave = True

        logger.info(
            f"[天气分析器] 温度分析: current_temp={current_temp}, max_temp={max_temp}, min_temp={min_temp}, has_heat={has_heat}, has_cold_wave={has_cold_wave}"
        )

        # 生成事件列表
        # 1. 降雨事件（分时段，已在检测阶段完成阈值判定与「当天每段仅一次」去重）
        events.extend(rain_events)

        # 2. 高温事件
        if has_heat and not self._check_cooldown("heat"):
            logger.info("[天气分析器] 添加高温提醒事件")
            events.append(
                {
                    "type": "heat",
                    "title": "高温提醒",
                    "description": "注意防暑降温，减少户外活动",
                    "temp": current_temp,
                    "severity": "high",
                }
            )
            self._update_cooldown("heat")
        elif has_heat:
            logger.info(f'[天气分析器] 有高温但处于冷却期: {self._check_cooldown("heat")}')

        # 3. 降温事件
        if has_cold_wave and not self._check_cooldown("cold"):
            logger.info("[天气分析器] 添加降温提醒事件")
            events.append(
                {
                    "type": "cold",
                    "title": "降温提醒",
                    "description": "气温下降明显，注意保暖",
                    "temp_drop": max_temp - current_temp if max_temp and current_temp else None,
                    "severity": "normal",
                }
            )
            self._update_cooldown("cold")
        elif has_cold_wave:
            logger.info(f'[天气分析器] 有降温但处于冷却期: {self._check_cooldown("cold")}')

        # 4. 预警事件（检查所有预警，推送优先级最高的未冷却预警）
        if alerts and not self._check_cooldown("alert"):
            # 按严重程度排序，优先处理高优先级预警
            sorted_alerts = self._sort_alerts_by_priority(alerts)
            for alert in sorted_alerts:
                event = self._analyze_alert(alert)
                if event:
                    events.append(event)
                    self._update_cooldown("alert")
                    break  # 一次只推送一条预警

        return events

    def _sort_alerts_by_priority(self, alerts: list[dict]) -> list[dict]:
        """按优先级排序预警列表（高优先级在前）

        Args:
            alerts: 预警列表

        Returns:
            排序后的预警列表
        """
        # 优先级映射：数值越大优先级越高
        severity_priority = {
            "red": 4,  # 红色预警
            "orange": 3,  # 橙色预警
            "yellow": 2,  # 黄色预警
            "blue": 1,  # 蓝色预警
        }

        def get_priority(alert: dict) -> int:
            color = alert.get("color_code", "").lower()
            severity = alert.get("severity", "").lower()
            # 优先使用 color_code，其次使用 severity
            return severity_priority.get(color, severity_priority.get(severity, 0))

        return sorted(alerts, key=get_priority, reverse=True)

    def _analyze_alert(self, alert: dict) -> dict[str, Any] | None:
        """分析单条预警信息，转换为事件格式

        Args:
            alert: 预警原始数据

        Returns:
            事件字典，如果不需要推送则返回 None
        """
        headline = alert.get("headline", "")
        event_type = alert.get("event_type", "")
        severity = alert.get("severity", "")
        description = alert.get("description", "")
        color_code = alert.get("color_code", "")

        if not headline and not event_type:
            return None

        return {
            "type": "alert",
            "title": headline or f"{severity}{event_type}预警",
            "description": description or f"气象台发布{event_type}预警",
            "event_type": event_type,
            "severity": severity,
            "color_code": color_code,
            "headline": headline,
        }

    def _check_cooldown(self, alert_type: str) -> bool:
        """检查是否在冷却期内

        Args:
            alert_type: 告警类型

        Returns:
            True 表示在冷却期内，False 表示可以推送
        """
        last_push = self._cooldown_state.get(alert_type, 0)
        cooldown = _COOLDOWN_SECONDS.get(alert_type, 3600)
        now = time.time()
        if now - last_push > cooldown:
            return False
        logger.debug(
            f"[天气] {alert_type} 类型在冷却期内，跳过推送 "
            f"(距上次 {(now - last_push):.0f}s < {cooldown}s)"
        )
        return True

    def _update_cooldown(self, alert_type: str) -> None:
        """更新冷却时间

        Args:
            alert_type: 告警类型
        """
        self._cooldown_state[alert_type] = time.time()
        self._save_cooldown_state()

    # ------------------------------------------------------------------
    # 降雨分时段去重（当天每段仅播报一次，状态持久化到冷却状态文件）
    # ------------------------------------------------------------------

    _RAIN_SEG_PREFIX = "rain_seg:"

    def _segment_pushed(self, seg_key: str) -> bool:
        """该时段当天是否已播报过降雨提醒"""
        return seg_key in self._cooldown_state

    def _mark_segment_pushed(self, seg_key: str) -> None:
        """标记该时段当天已播报，并清理历史日期的时段键避免状态文件无限增长"""
        self._cooldown_state[seg_key] = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        keep_prefix = f"{self._RAIN_SEG_PREFIX}{today}:"
        stale = [
            k
            for k in self._cooldown_state
            if k.startswith(self._RAIN_SEG_PREFIX) and not k.startswith(keep_prefix)
        ]
        for k in stale:
            self._cooldown_state.pop(k, None)
        self._save_cooldown_state()

    def get_daily_summary(
        self,
        now_data: dict | None,
        hourly_data: list[dict] | None,
    ) -> dict[str, Any]:
        """生成每日天气摘要

        Args:
            now_data: 实时天气数据
            hourly_data: 逐小时预报数据

        Returns:
            每日摘要字典，包含当前天气、今日温度范围、降雨概率等信息
        """
        summary = {
            "city_name": now_data.get("city_name", "") if now_data else "",
            "current_temp": now_data.get("temp", "") if now_data else "",
            "current_text": now_data.get("text", "") if now_data else "",
            "feels_like": now_data.get("feels_like", "") if now_data else "",
            "humidity": now_data.get("humidity", "") if now_data else "",
            "wind_dir": now_data.get("wind_dir", "") if now_data else "",
            "wind_scale": now_data.get("wind_scale", "") if now_data else "",
            "max_temp": None,
            "min_temp": None,
            "rain_probability": 0,
            "tips": [],
        }

        # 从逐小时预报中提取最高/最低温；降雨概率仅统计「当天白天」。
        # 与降雨提醒时段口径保持一致（排除夜间与次日），避免晨报用次日/夜间高概率误报「今日有雨」。
        if hourly_data:
            temps = []
            day_pop = 0
            today = datetime.now().date()
            for item in hourly_data:
                temp = self._safe_int(item.get("temp", ""))
                if temp is not None:
                    temps.append(temp)
                item_dt = self._parse_item_dt(item.get("time", ""))
                if item_dt is None or item_dt.date() != today:
                    continue
                if item_dt.hour < RAIN_DAY_START_HOUR or item_dt.hour >= RAIN_DAY_END_HOUR:
                    continue
                pop = self._safe_int(item.get("pop", "0"))
                if pop is not None and pop > day_pop:
                    day_pop = pop

            if temps:
                summary["max_temp"] = max(temps)
                summary["min_temp"] = min(temps)
            summary["rain_probability"] = day_pop

            # 生成提示
            tips = []
            if day_pop >= RAIN_POP_THRESHOLD:
                tips.append(f"今日白天有降雨可能（最高概率 {day_pop}%），记得带伞")
            if summary["max_temp"] is not None and summary["max_temp"] >= 35:
                tips.append("今日高温，注意防暑")
            if summary["min_temp"] is not None and summary["min_temp"] <= 5:
                tips.append("今日低温，注意保暖")
            if not tips:
                tips.append("今日天气平稳，适宜出行")
            summary["tips"] = tips

        return summary

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_item_dt(value: Any) -> datetime | None:
        """解析逐小时预报的 time 字段为本地 naive datetime，失败返回 None。

        预报表项时间可能带时区（如 +08:00），统一去除时区信息以便与本地
        `datetime.now()` 做同口径比较；无法解析时返回 None，由调用方决定跳过
        （避免把次日/异常时段混入当天范围）。
        """
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        """安全地将值转为 int，失败返回 None"""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _load_cooldown_state(self) -> None:
        """从磁盘加载冷却状态"""
        state_file = self._state_file_path()
        try:
            if os.path.exists(state_file):
                with open(state_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cooldown_state = data
                    logger.debug(f"[天气] 冷却状态已加载: {list(data.keys())}")
        except Exception as exc:
            logger.warning(f"[天气] 加载冷却状态失败: {exc}")
            self._cooldown_state = {}

    def _save_cooldown_state(self) -> None:
        """持久化冷却状态到磁盘"""
        state_file = self._state_file_path()
        try:
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(self._cooldown_state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"[天气] 保存冷却状态失败: {exc}")

    def _state_file_path(self) -> str:
        """获取冷却状态文件路径（延迟读取 Config）"""
        if self._state_dir:
            return os.path.join(self._state_dir, ".cooldown_state")
        from app.core.config import Config

        return os.path.join(Config.BASE_DIR, "data", "weather", ".cooldown_state")
