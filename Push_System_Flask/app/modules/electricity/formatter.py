#!/usr/bin/env python3
"""
用电消息格式化模块
生成企业微信 Markdown 格式的推送消息，不使用 emoji
"""

from datetime import datetime


class ElectricityFormatter:
    """用电消息格式化器"""

    @staticmethod
    def format_daily(stats: dict, remaining_power: dict) -> str:
        """
        格式化每日用电报告

        Args:
            stats: get_daily_statistics() 返回值
            remaining_power: get_remaining_power() 返回值

        Returns:
            Markdown 格式字符串
        """
        date_str = stats.get("date", "未知")
        total = stats.get("total_usage", 0.0)
        meter_usage = stats.get("meter_usage", {})

        lines = [
            "## 每日用电报告",
            "",
            f"**统计日期**: {date_str}",
            "",
            "### 用电概况",
            f"- **总用电量**: {total:.2f} 度",
        ]
        remaining_val = remaining_power.get("default")
        if remaining_val is not None:
            lines.append(f"- **剩余电量**: {remaining_val:.2f} 度")

        lines.extend(["", "### 各电表用电详情"])
        for meter, usage in meter_usage.items():
            meter_name = meter.replace("电表: ", "")
            lines.append(f"- {meter_name}: {usage:.2f} 度")

        lines.extend(["", f'**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        return "\n".join(lines)

    @staticmethod
    def format_weekly(stats: dict, remaining_power: dict) -> str:
        """格式化每周用电报告"""
        stats.get("year", "")
        week_num = stats.get("week_num", "")
        start_date = stats.get("start_date", "")
        end_date = stats.get("end_date", "")
        total = stats.get("total_usage", 0.0)
        days_count = stats.get("days_count", 0)
        meter_usage = stats.get("meter_usage", {})
        daily_usage = stats.get("daily_usage", {})
        avg_daily = total / days_count if days_count > 0 else 0.0

        lines = [
            "## 每周用电报告",
            "",
            f"**统计周期**: 第 {week_num} 周 ({start_date} ~ {end_date})",
            "",
            "### 用电概况",
            f"- **总用电量**: {total:.2f} 度",
            f"- **用电天数**: {days_count} 天",
            f"- **日均用电**: {avg_daily:.2f} 度",
        ]
        remaining_val = remaining_power.get("default")
        if remaining_val is not None:
            lines.append(f"- **剩余电量**: {remaining_val:.2f} 度")

        lines.extend(["", "### 各电表用电详情"])
        for meter, usage in meter_usage.items():
            meter_name = meter.replace("电表: ", "")
            lines.append(f"- {meter_name}: {usage:.2f} 度")

        lines.extend(["", "### 每日用电详情"])
        for date, usage in sorted(daily_usage.items()):
            lines.append(f"- {date}: {usage:.2f} 度")

        lines.extend(["", f'**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        return "\n".join(lines)

    @staticmethod
    def format_monthly(stats: dict, remaining_power: dict) -> str:
        """格式化每月用电报告"""
        year = stats.get("year", "")
        month = stats.get("month", "")
        total = stats.get("total_usage", 0.0)
        days_count = stats.get("days_count", 0)
        meter_usage = stats.get("meter_usage", {})
        daily_usage = stats.get("daily_usage", {})
        avg_daily = total / days_count if days_count > 0 else 0.0

        lines = [
            "## 每月用电报告",
            "",
            f"**统计周期**: {year}年{month}月",
            "",
            "### 用电概况",
            f"- **总用电量**: {total:.2f} 度",
            f"- **用电天数**: {days_count} 天",
            f"- **日均用电**: {avg_daily:.2f} 度",
        ]
        remaining_val = remaining_power.get("default")
        if remaining_val is not None:
            lines.append(f"- **剩余电量**: {remaining_val:.2f} 度")

        lines.extend(["", "### 各电表用电详情"])
        for meter, usage in meter_usage.items():
            meter_name = meter.replace("电表: ", "")
            lines.append(f"- {meter_name}: {usage:.2f} 度")

        lines.extend(["", "### 每日用电详情"])
        for date, usage in sorted(daily_usage.items()):
            lines.append(f"- {date}: {usage:.2f} 度")

        lines.extend(["", f'**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        return "\n".join(lines)

    @staticmethod
    def format_low_power_alert(power_value: float) -> str:
        """
        格式化低电量告警消息

        Args:
            power_value: 剩余电量（度）
        """
        if power_value <= 5:
            level = "[紧急]"
            suggestion = "请**立即充值**，电量即将耗尽！"
        elif power_value <= 8:
            level = "[警告]"
            suggestion = "请**尽快充值**，预计可用 1~2 天"
        else:
            level = "[提醒]"
            suggestion = "建议**尽快充值**，预计可用 2~3 天"

        return "\n".join(
            [
                f"{level} **低电量提醒**",
                "",
                f"**当前剩余电量**: {power_value:.2f} 度",
                "",
                suggestion,
                "",
                "**充值方式**:",
                '1. 关注"重庆工程学院"公众号',
                '2. 进入"智慧校园" - "电费缴纳"',
                "3. 选择宿舍号进行充值",
                "",
                "---",
                f'提醒时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            ]
        )

    @staticmethod
    def format_cookie_invalid(reason: str) -> str:
        """格式化 Cookie 失效通知消息"""
        return "\n".join(
            [
                "**Cookie 失效提醒**",
                "",
                "**状态**: Cookie 已失效",
                "",
                f"**原因**: {reason}",
                "",
                "**请尽快更新 Cookie**，否则定时推送任务将无法正常执行。",
                "",
                "**更新方式**:",
                "1. 用静态 Token 申请动态 Token：",
                "   ```",
                "   POST /api/electricity/request_token",
                "   Header: X-Admin-Token: <your_token>",
                "   ```",
                "2. 用动态 Token 更新 Cookie：",
                "   ```",
                "   POST /api/electricity/update_cookie",
                "   Header: X-Dynamic-Token: <dynamic_token>",
                '   Body: {"cookie": "新的Cookie"}',
                "   ```",
                "",
                "---",
                f'检测时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            ]
        )

    @staticmethod
    def format_fetch_error(report_type: str, reason: str) -> str:
        """格式化数据采集失败通知"""
        return "\n".join(
            [
                f"**{report_type}推送失败**",
                "",
                f"**原因**: {reason}",
                "",
                "请检查 Cookie 是否有效，或网络连接是否正常。",
                "",
                f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            ]
        )
