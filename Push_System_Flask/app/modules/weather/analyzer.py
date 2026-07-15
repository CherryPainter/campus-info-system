#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天气分析引擎
包含规则引擎、提示生成、冷却机制
"""

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.logger import get_logger

logger = get_logger(__name__)

# 冷却时间常量（秒）
_COOLDOWN_SECONDS = {
    'rain': 3 * 3600,        # 普通降雨提醒 3 小时
    'rain_heavy': 4 * 3600,  # 大雨提醒 4 小时（优先级更高，冷却稍长）
    'heat': 6 * 3600,        # 高温提醒 6 小时
    'cold': 6 * 3600,        # 降温提醒 6 小时
    'alert': 1 * 3600,       # 预警提醒 1 小时
}


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
        self._cooldown_state: Dict[str, float] = {}
        self._load_cooldown_state()

    # ------------------------------------------------------------------
    # 核心分析方法
    # ------------------------------------------------------------------

    def analyze(
        self,
        now_data: Optional[Dict],
        hourly_data: Optional[List[Dict]],
        alerts_data: Optional[List[Dict]],
    ) -> List[Dict[str, Any]]:
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
        
        logger.info(f'[天气分析器] 开始分析: 逐小时预报={len(hourly)}条, 预警={len(alerts)}条')

        # 降雨检测
        # 只关注当前时间之后、当日之内的降雨时段
        rain_hours = []
        has_rain = False
        has_heavy_rain = False
        consecutive_heavy = 0
        now = datetime.now()
        today_end = now.replace(hour=23, minute=59, second=59)

        for item in hourly:
            # 过滤已过去或非今日的时段
            item_time_str = item.get('time', '')
            if item_time_str:
                try:
                    item_dt = datetime.fromisoformat(item_time_str)
                    # 去除时区信息，统一用本地时间比较
                    if item_dt.tzinfo is not None:
                        item_dt = item_dt.replace(tzinfo=None)
                    if item_dt <= now or item_dt > today_end:
                        continue
                except (ValueError, TypeError):
                    pass  # 时间解析失败不跳过，保守处理
            
            pop_val = self._safe_int(item.get('pop', '0'))
            if pop_val is not None and pop_val >= 70:
                has_rain = True
                rain_hours.append({
                    'time': item.get('time', ''),
                    'pop': pop_val,
                    'text': item.get('text', ''),
                })
                if pop_val >= 80:
                    consecutive_heavy += 1
                    if consecutive_heavy >= 2:
                        has_heavy_rain = True
                else:
                    consecutive_heavy = 0
            else:
                consecutive_heavy = 0
        
        # 按时间排序，确保降雨时段按时间顺序显示
        rain_hours.sort(key=lambda x: x['time'])
        
        logger.info(f'[天气分析器] 降雨检测: has_rain={has_rain}, has_heavy_rain={has_heavy_rain}, 降雨小时数={len(rain_hours)}')

        # 温度分析
        has_heat = False
        has_cold_wave = False
        max_temp = None
        min_temp = None
        current_temp = None

        if now_data:
            feels_like = self._safe_int(now_data.get('feels_like', ''))
            if feels_like is not None and feels_like >= 35:
                has_heat = True
            current_temp = self._safe_int(now_data.get('temp', ''))

        # 从 24h 预报中提取最高/最低温
        temp_list = []
        for item in hourly:
            t = self._safe_int(item.get('temp', ''))
            if t is not None:
                temp_list.append(t)

        if temp_list:
            max_temp = max(temp_list)
            min_temp = min(temp_list)
            # 降温检测：当前温度比 24h 最高温低 6 度以上
            if current_temp is not None and max_temp is not None:
                if (max_temp - current_temp) >= 6:
                    has_cold_wave = True
        
        logger.info(f'[天气分析器] 温度分析: current_temp={current_temp}, max_temp={max_temp}, min_temp={min_temp}, has_heat={has_heat}, has_cold_wave={has_cold_wave}')

        # 生成事件列表
        # 1. 降雨事件（大雨使用独立的冷却键，优先级更高）
        if has_heavy_rain and not self._check_cooldown('rain_heavy'):
            logger.info('[天气分析器] 添加大雨提醒事件')
            events.append({
                'type': 'rain',
                'title': '大雨提醒',
                'description': '未来几小时有大雨，请注意防涝，减少外出',
                'rain_hours': rain_hours,
                'severity': 'high',
            })
            # 更新大雨和普通降雨的冷却，避免短时间内重复提醒
            self._update_cooldown('rain_heavy')
            self._update_cooldown('rain')
        elif has_rain and not self._check_cooldown('rain'):
            logger.info('[天气分析器] 添加普通降雨提醒事件')
            events.append({
                'type': 'rain',
                'title': '降雨提醒',
                'description': '下午可能下雨，记得带伞',
                'rain_hours': rain_hours,
                'severity': 'normal',
            })
            self._update_cooldown('rain')
        else:
            if has_rain:
                cd_rain = self._check_cooldown('rain')
                cd_heavy = self._check_cooldown('rain_heavy')
                logger.info(f'[天气分析器] 有降雨但处于冷却期: rain={cd_rain}, heavy={cd_heavy}')

        # 2. 高温事件
        if has_heat and not self._check_cooldown('heat'):
            logger.info('[天气分析器] 添加高温提醒事件')
            events.append({
                'type': 'heat',
                'title': '高温提醒',
                'description': '注意防暑降温，减少户外活动',
                'temp': current_temp,
                'severity': 'high',
            })
            self._update_cooldown('heat')
        elif has_heat:
            logger.info(f'[天气分析器] 有高温但处于冷却期: {self._check_cooldown("heat")}')

        # 3. 降温事件
        if has_cold_wave and not self._check_cooldown('cold'):
            logger.info('[天气分析器] 添加降温提醒事件')
            events.append({
                'type': 'cold',
                'title': '降温提醒',
                'description': '气温下降明显，注意保暖',
                'temp_drop': max_temp - current_temp if max_temp and current_temp else None,
                'severity': 'normal',
            })
            self._update_cooldown('cold')
        elif has_cold_wave:
            logger.info(f'[天气分析器] 有降温但处于冷却期: {self._check_cooldown("cold")}')

        # 4. 预警事件（检查所有预警，推送优先级最高的未冷却预警）
        if alerts and not self._check_cooldown('alert'):
            # 按严重程度排序，优先处理高优先级预警
            sorted_alerts = self._sort_alerts_by_priority(alerts)
            for alert in sorted_alerts:
                event = self._analyze_alert(alert)
                if event:
                    events.append(event)
                    self._update_cooldown('alert')
                    break  # 一次只推送一条预警

        return events

    def _sort_alerts_by_priority(self, alerts: List[Dict]) -> List[Dict]:
        """按优先级排序预警列表（高优先级在前）

        Args:
            alerts: 预警列表

        Returns:
            排序后的预警列表
        """
        # 优先级映射：数值越大优先级越高
        severity_priority = {
            'red': 4,      # 红色预警
            'orange': 3,   # 橙色预警
            'yellow': 2,   # 黄色预警
            'blue': 1,     # 蓝色预警
        }

        def get_priority(alert: Dict) -> int:
            color = alert.get('color_code', '').lower()
            severity = alert.get('severity', '').lower()
            # 优先使用 color_code，其次使用 severity
            return severity_priority.get(color, severity_priority.get(severity, 0))

        return sorted(alerts, key=get_priority, reverse=True)

    def _analyze_alert(self, alert: Dict) -> Optional[Dict[str, Any]]:
        """分析单条预警信息，转换为事件格式

        Args:
            alert: 预警原始数据

        Returns:
            事件字典，如果不需要推送则返回 None
        """
        headline = alert.get('headline', '')
        event_type = alert.get('event_type', '')
        severity = alert.get('severity', '')
        description = alert.get('description', '')
        color_code = alert.get('color_code', '')

        if not headline and not event_type:
            return None

        return {
            'type': 'alert',
            'title': headline or f'{severity}{event_type}预警',
            'description': description or f'气象台发布{event_type}预警',
            'event_type': event_type,
            'severity': severity,
            'color_code': color_code,
            'headline': headline,
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
            f'[天气] {alert_type} 类型在冷却期内，跳过推送 '
            f'(距上次 {(now - last_push):.0f}s < {cooldown}s)'
        )
        return True

    def _update_cooldown(self, alert_type: str) -> None:
        """更新冷却时间

        Args:
            alert_type: 告警类型
        """
        self._cooldown_state[alert_type] = time.time()
        self._save_cooldown_state()

    def get_daily_summary(
        self,
        now_data: Optional[Dict],
        hourly_data: Optional[List[Dict]],
    ) -> Dict[str, Any]:
        """生成每日天气摘要

        Args:
            now_data: 实时天气数据
            hourly_data: 逐小时预报数据

        Returns:
            每日摘要字典，包含当前天气、今日温度范围、降雨概率等信息
        """
        summary = {
            'city_name': now_data.get('city_name', '') if now_data else '',
            'current_temp': now_data.get('temp', '') if now_data else '',
            'current_text': now_data.get('text', '') if now_data else '',
            'feels_like': now_data.get('feels_like', '') if now_data else '',
            'humidity': now_data.get('humidity', '') if now_data else '',
            'wind_dir': now_data.get('wind_dir', '') if now_data else '',
            'wind_scale': now_data.get('wind_scale', '') if now_data else '',
            'max_temp': None,
            'min_temp': None,
            'rain_probability': 0,
            'tips': [],
        }

        # 从逐小时预报中提取最高/最低温和降雨概率
        if hourly_data:
            temps = []
            max_pop = 0
            for item in hourly_data:
                temp = self._safe_int(item.get('temp', ''))
                if temp is not None:
                    temps.append(temp)
                pop = self._safe_int(item.get('pop', '0'))
                if pop is not None and pop > max_pop:
                    max_pop = pop

            if temps:
                summary['max_temp'] = max(temps)
                summary['min_temp'] = min(temps)
            summary['rain_probability'] = max_pop

            # 生成提示
            tips = []
            if max_pop >= 70:
                tips.append('今日有降雨可能，记得带伞')
            if summary['max_temp'] is not None and summary['max_temp'] >= 35:
                tips.append('今日高温，注意防暑')
            if summary['min_temp'] is not None and summary['min_temp'] <= 5:
                tips.append('今日低温，注意保暖')
            if not tips:
                tips.append('今日天气平稳，适宜出行')
            summary['tips'] = tips

        return summary

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """安全地将值转为 int，失败返回 None"""
        if value is None or value == '':
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
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cooldown_state = data
                    logger.debug(f'[天气] 冷却状态已加载: {list(data.keys())}')
        except Exception as exc:
            logger.warning(f'[天气] 加载冷却状态失败: {exc}')
            self._cooldown_state = {}

    def _save_cooldown_state(self) -> None:
        """持久化冷却状态到磁盘"""
        state_file = self._state_file_path()
        try:
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(self._cooldown_state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f'[天气] 保存冷却状态失败: {exc}')

    def _state_file_path(self) -> str:
        """获取冷却状态文件路径（延迟读取 Config）"""
        if self._state_dir:
            return os.path.join(self._state_dir, '.cooldown_state')
        from app.core.config import Config
        return os.path.join(Config.BASE_DIR, 'data', 'weather', '.cooldown_state')
