#!/usr/bin/env python3
"""
天气消息格式化器
生成企业微信 Markdown 格式的推送消息，不使用 emoji
"""

from datetime import datetime


class WeatherFormatter:
    """天气消息格式化器（全静态方法）"""

    @staticmethod
    def format_daily_report(now_data: dict, analysis: dict) -> str:
        """格式化每日天气晨报 Markdown

        Args:
            now_data: 实时天气字典
            analysis: 分析结果字典

        Returns:
            Markdown 格式字符串
        """
        city_name = now_data.get("city_name", "未知")
        text = now_data.get("text", "未知")
        temp = now_data.get("temp", "--")
        feels_like = now_data.get("feels_like", "--")
        humidity = now_data.get("humidity", "--")
        wind_dir = now_data.get("wind_dir", "未知")
        wind_scale = now_data.get("wind_scale", "--")
        vis = now_data.get("vis", "--")

        max_temp = analysis.get("max_temp")
        min_temp = analysis.get("min_temp")
        tips = analysis.get("tips", [])

        lines = [
            "**今日天气**",
            "",
            f"**城市**: {city_name}",
            f"**天气**: {text}",
            f"**温度**: {temp}°C（体感 {feels_like}°C）",
            f"**湿度**: {humidity}%",
            f"**风向**: {wind_dir} {wind_scale}级",
            f"**能见度**: {vis}km",
            "",
            "**24小时趋势**",
        ]

        if max_temp is not None and min_temp is not None:
            lines.append(f"最高 {max_temp}°C / 最低 {min_temp}°C")
        else:
            lines.append("暂无数据")

        if tips:
            lines.extend(["", "**提醒**"])
            for tip in tips:
                lines.append(f"- {tip}")

        lines.extend(["", f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
        return "\n".join(lines)

    @staticmethod
    def format_rain_alert(analysis: dict) -> str:
        """格式化降雨提醒 Markdown

        Args:
            analysis: 分析结果字典

        Returns:
            Markdown 格式字符串
        """
        rain_hours = analysis.get("rain_hours", [])
        has_heavy_rain = analysis.get("has_heavy_rain", False)

        if has_heavy_rain:
            level = "[紧急]"
            desc = "未来几小时有大雨，请注意防涝，减少外出"
        else:
            level = "[提醒]"
            desc = "未来几小时可能有降雨"

        lines = [
            f"{level} **降雨提醒**",
            "",
            desc,
            "",
        ]

        if rain_hours:
            lines.append("**降雨时段**:")
            for rh in rain_hours:
                t = rh.get("time", "")
                if t:
                    # ISO 时间取 HH:mm 部分
                    try:
                        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                        t_display = dt.strftime("%H:%M")
                    except (ValueError, TypeError):
                        t_display = t[-8:-3] if len(t) >= 8 else t
                else:
                    t_display = "未知"
                pop = rh.get("pop", 0)
                text = rh.get("text", "")
                lines.append(f"- {t_display} 降雨概率 {pop}%  {text}")

        lines.extend(["", f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
        return "\n".join(lines)

    @staticmethod
    def format_heat_alert(now_data: dict, analysis: dict) -> str:
        """格式化高温提醒 Markdown

        Args:
            now_data: 实时天气字典
            analysis: 分析结果字典

        Returns:
            Markdown 格式字符串
        """
        temp = now_data.get("temp", "--")
        feels_like = now_data.get("feels_like", "--")

        feels_int = None
        try:
            feels_int = int(feels_like)
        except (ValueError, TypeError):
            pass

        if feels_int is not None and feels_int >= 40:
            level = "[紧急]"
        else:
            level = "[提醒]"

        lines = [
            f"{level} **高温提醒**",
            "",
            f"**当前温度**: {temp}°C",
            f"**体感温度**: {feels_like}°C",
            "",
            "注意防暑降温，减少户外活动，多补充水分",
            "",
            f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        ]
        return "\n".join(lines)

    @staticmethod
    def format_cold_alert(now_data: dict, analysis: dict) -> str:
        """格式化降温提醒 Markdown

        Args:
            now_data: 实时天气字典
            analysis: 分析结果字典

        Returns:
            Markdown 格式字符串
        """
        temp = now_data.get("temp", "--")
        max_temp = analysis.get("max_temp", "--")
        min_temp = analysis.get("min_temp", "--")

        lines = [
            "**降温提醒**",
            "",
            f"**当前温度**: {temp}°C",
            f"**24小时最高温**: {max_temp}°C",
            f"**24小时最低温**: {min_temp}°C",
            "",
            "气温下降明显，注意保暖，适当增加衣物",
            "",
            f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        ]
        return "\n".join(lines)

    @staticmethod
    def format_weather_alert(alert_data: dict) -> str:
        """格式化天气预警 Markdown

        Args:
            alert_data: 单条预警数据字典

        Returns:
            Markdown 格式字符串
        """
        headline = alert_data.get("headline", "未知预警")
        event_type = alert_data.get("event_type", "")
        severity = alert_data.get("severity", "")
        description = alert_data.get("description", "")
        effective_time = alert_data.get("effective_time", "")
        expire_time = alert_data.get("expire_time", "")

        lines = [
            "**天气预警**",
            "",
            f"**预警标题**: {headline}",
            f"**预警类型**: {event_type}",
            f"**严重程度**: {severity}",
        ]

        if description:
            # 截断过长的描述
            display_desc = description[:500] if len(description) > 500 else description
            lines.extend(["", f"**详情**: {display_desc}"])

        if effective_time:
            lines.append(f"**生效时间**: {effective_time}")
        if expire_time:
            lines.append(f"**过期时间**: {expire_time}")

        lines.extend(["", f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
        return "\n".join(lines)

    @staticmethod
    def format_fetch_error(report_type: str, reason: str) -> str:
        """格式化数据采集失败通知

        Args:
            report_type: 报告类型描述
            reason: 失败原因

        Returns:
            Markdown 格式字符串
        """
        return "\n".join(
            [
                f"**{report_type}推送失败**",
                "",
                f"**原因**: {reason}",
                "",
                "请检查 API Key 是否有效，或网络连接是否正常。",
                "",
                f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            ]
        )
