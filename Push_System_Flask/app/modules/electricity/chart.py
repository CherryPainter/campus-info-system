#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用电统计图表生成模块
生成周报/月报所需的 matplotlib 折线图与饼图
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.core.logger import get_logger
from app.utils.chinese_font import setup_chinese_font

logger = get_logger(__name__)


class ElectricityChartGenerator:
    """用电统计图表生成器"""

    def __init__(self, records_path: str, output_dir: str) -> None:
        """
        Args:
            records_path: 用电记录 JSON 文件路径
            output_dir: 图表输出目录
        """
        self.records_path = records_path
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self._daily_stats: Dict[str, float] = {}
        self._meter_stats: Dict[str, Dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """重新加载数据"""
        self._load()

    def generate_weekly_chart(self, week_start: datetime) -> Optional[str]:
        """
        生成指定周的用电折线图 + 电表占比饼图

        Args:
            week_start: 周一日期

        Returns:
            保存的图片路径，无数据时返回 None
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            setup_chinese_font()
        except ImportError:
            logger.error('matplotlib 未安装，无法生成图表')
            return None

        dates = []
        usages = []
        valid_days = []
        meter1_total = 0.0
        meter2_total = 0.0

        for i in range(7):
            day = week_start + timedelta(days=i)
            date_str = day.strftime('%Y-%m-%d')
            weekday_label = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][i]
            usage = self._daily_stats.get(date_str, 0.0)
            if usage > 0:
                dates.append(f'{weekday_label}\n{day.strftime("%m-%d")}')
                usages.append(usage)
                valid_days.append(i)
            for meter, stats in self._meter_stats.items():
                if date_str in stats.get('daily', {}) and stats['daily'][date_str] > 0:
                    if '310512' in meter:
                        meter1_total += stats['daily'][date_str]
                    else:
                        meter2_total += stats['daily'][date_str]

        if not usages:
            logger.warning(f'generate_weekly_chart: {week_start.strftime("%Y-%m-%d")} 周无数据')
            return None

        total_usage = sum(usages)
        first_day = week_start + timedelta(days=valid_days[0])
        last_day = week_start + timedelta(days=valid_days[-1])

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # 左图：每日折线
        x = range(len(dates))
        ax1.plot(x, usages, marker='o', color='#2196F3', linewidth=2, markersize=8)
        ax1.fill_between(x, usages, color='#2196F3', alpha=0.2)
        for i, v in enumerate(usages):
            ax1.text(i, v + 0.05, f'{v:.1f}', ha='center', va='bottom', fontsize=10)
        ax1.set_title(
            f'每日用电量 ({first_day.strftime("%m-%d")} ~ {last_day.strftime("%m-%d")})\n'
            f'总用电量: {total_usage:.1f} 度',
            fontsize=13, pad=15
        )
        ax1.set_xlabel('日期', fontsize=11)
        ax1.set_ylabel('用电量 (度)', fontsize=11)
        ax1.set_xticks(x)
        ax1.set_xticklabels(dates, fontsize=10)
        ax1.grid(True, linestyle='--', alpha=0.6, axis='y')
        ax1.set_ylim(bottom=0)

        # 右图：电表占比饼图
        if meter1_total > 0 or meter2_total > 0:
            sizes = [meter1_total, meter2_total]
            labels = ['310512', '31栋512照明']
            colors = ['#2196F3', '#FF9800']
            wedges, texts, autotexts = ax2.pie(
                sizes, explode=(0.05, 0.05), labels=labels, colors=colors,
                autopct='%1.1f%%', shadow=True, startangle=90
            )
            for at in autotexts:
                at.set_fontweight('bold')
        ax2.set_title(f'电表用电占比\n总用电: {total_usage:.1f} 度', fontsize=13, pad=15)

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, f'weekly_{week_start.strftime("%Y%m%d")}.png')
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        logger.info(f'生成周报图表: {filepath}')
        return filepath

    def generate_monthly_chart(self, year: int, month: int) -> Optional[str]:
        """
        生成指定月份的用电柱状图 + 电表占比饼图

        Returns:
            保存的图片路径，无数据时返回 None
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            setup_chinese_font()
        except ImportError:
            logger.error('matplotlib 未安装，无法生成图表')
            return None

        daily_usage: Dict[int, float] = {}
        meter1_total = 0.0
        meter2_total = 0.0

        for date_str, usage in self._daily_stats.items():
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                if dt.year == year and dt.month == month:
                    daily_usage[dt.day] = usage
                    for meter, stats in self._meter_stats.items():
                        if date_str in stats.get('daily', {}):
                            if '310512' in meter:
                                meter1_total += stats['daily'][date_str]
                            else:
                                meter2_total += stats['daily'][date_str]
            except Exception:
                continue

        if not daily_usage:
            logger.warning(f'generate_monthly_chart: {year}-{month:02d} 无数据')
            return None

        days = sorted(daily_usage.keys())
        usages = [daily_usage[d] for d in days]
        total_usage = sum(usages)
        avg_usage = total_usage / len(usages) if usages else 0.0

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # 左图：柱状图
        ax1.bar(days, usages, color='#FF9800', alpha=0.7, edgecolor='white', linewidth=1)
        ax1.axhline(
            y=avg_usage, color='#E91E63', linestyle='--', linewidth=2,
            label=f'日均: {avg_usage:.2f} 度'
        )
        ax1.set_title(f'{year}年{month}月每日用电量', fontsize=14, pad=15)
        ax1.set_xlabel('日期', fontsize=11)
        ax1.set_ylabel('用电量 (度)', fontsize=11)
        ax1.legend()
        ax1.grid(True, linestyle='--', alpha=0.6, axis='y')

        # 右图：饼图
        if meter1_total > 0 or meter2_total > 0:
            sizes = [meter1_total, meter2_total]
            labels = ['310512', '31栋512照明']
            colors = ['#2196F3', '#FF9800']
            _, _, autotexts = ax2.pie(
                sizes, explode=(0.05, 0.05), labels=labels, colors=colors,
                autopct='%1.1f%%', shadow=True, startangle=90
            )
            for at in autotexts:
                at.set_color('white')
                at.set_fontweight('bold')
        ax2.set_title(f'电表用电占比\n总用电: {total_usage:.2f} 度', fontsize=14, pad=15)

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, f'monthly_{year}{month:02d}.png')
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        logger.info(f'生成月报图表: {filepath}')
        return filepath

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._daily_stats = {}
        self._meter_stats = {}
        try:
            if not os.path.exists(self.records_path):
                return
            with open(self.records_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 兼容嵌套列表
            records: List[Dict] = []
            if isinstance(data, list) and data and isinstance(data[0], list):
                for sub in data:
                    records.extend(sub if isinstance(sub, list) else [sub])
            else:
                records = data if isinstance(data, list) else []

            for rec in records:
                try:
                    date_str = rec['time'].split()[0]
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                    actual = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
                    usage = float(rec['usage'])
                    meter = rec['meter']

                    self._daily_stats[actual] = self._daily_stats.get(actual, 0.0) + usage
                    if meter not in self._meter_stats:
                        self._meter_stats[meter] = {'total': 0.0, 'daily': {}}
                    self._meter_stats[meter]['total'] += usage
                    self._meter_stats[meter]['daily'][actual] = (
                        self._meter_stats[meter]['daily'].get(actual, 0.0) + usage
                    )
                except Exception:
                    continue
            logger.debug(f'ElectricityChartGenerator: 加载 {len(records)} 条记录')
        except Exception as exc:
            logger.error(f'ElectricityChartGenerator: 加载数据失败 {exc}')
