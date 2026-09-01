#!/usr/bin/env python3
"""
电量监控 API 路由
提供电量数据查询、手动触发推送、Cookie 更新等接口

职责：
- 仅处理 HTTP 请求/响应
- 业务逻辑委托给 Service 层
- 数据访问委托给 Repository 层

认证方式：统一使用 JWT Bearer Token
- @jwt_required: 需要登录即可访问（查询数据、触发任务）
- @admin_required: 需要管理员权限（模块状态、Cookie 更新、配置管理）
- 无装饰器: 公开端点（健康检查）
"""

import threading

from flask import Blueprint, current_app, g, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.utils.auth_middleware import admin_required, jwt_required

logger = get_logger(__name__)

electricity_bp = Blueprint("electricity", __name__)


@electricity_bp.route("/health")
def health():
    """电量模块健康检查（无需认证）"""
    import time

    return api_success(status="healthy", module="electricity", timestamp=int(time.time()))


@electricity_bp.route("/status")
@admin_required
def status():
    """电量模块状态（需管理员权限）"""
    from app.services.electricity_service import get_electricity_service

    from app.modules.electricity.tasks import _iter_students_with_cookie

    configured_students = len(_iter_students_with_cookie())
    svc = get_electricity_service()
    remaining = svc.get_remaining_power()
    records = svc.get_usage_records(days=1, limit=1)

    return api_success(
        module="electricity",
        cookie_configured=configured_students > 0,
        configured_students=configured_students,
        data={"records_exists": len(records) > 0, "remaining_exists": remaining is not None},
        config={
            "low_power_threshold": current_app.config.get("ELECTRICITY_LOW_POWER_THRESHOLD", 10.0),
            "daily_push_time": current_app.config.get("ELECTRICITY_SCHEDULE_DAILY", "00:30"),
            "weekly_push_day": current_app.config.get("ELECTRICITY_SCHEDULE_WEEKLY_DAY", "mon"),
        },
    )


@electricity_bp.route("/remaining")
@jwt_required
def get_remaining():
    """
    获取最新剩余电量（从数据库读取）

    返回数据包含：
    - remaining: 剩余电量（度）
    - total_capacity: 总量（度）
    - percentage: 百分比（0-100）
    - is_low_power: 是否低电量
    """
    from app.services.electricity_service import electricity_service

    svc = electricity_service
    data = svc.get_remaining_power()
    if data is None:
        return api_success(data=None, message="暂无数据，请先触发数据采集")

    # 格式化返回数据，便于前端使用
    response_data = {
        "default": data.get("remaining", 0),
        "total_capacity": data.get("total_capacity", 100.0),
        "percentage": data.get("percentage", 0.0),
        "is_low_power": data.get("is_low_power", False),
        "recorded_at": data.get("recorded_at"),
    }
    return api_success(data=response_data)


@electricity_bp.route("/records")
@jwt_required
def get_records():
    """获取用电记录（从数据库读取）

    展示全部记录列表，不做时间窗口过滤，仅按 limit 返回最新记录，
    避免入库本地时间与 UTC 上界错配导致最近记录被截断。
    """
    from app.services.electricity_service import electricity_service

    svc = electricity_service
    records = svc.get_usage_records(days=None, limit=1000)
    return api_success(data=records)


@electricity_bp.route("/statistics")
@jwt_required
def get_statistics():
    """
    获取用电统计数据（按日聚合 + 按电表聚合）

    查询参数：
    - range_type: 时间范围类型 (week-本周, last_week-上周, month-本月, last_month-上月, custom-自定义)
    - start_date: 自定义开始日期 (YYYY-MM-DD)，range_type=custom 时必填
    - end_date: 自定义结束日期 (YYYY-MM-DD)，range_type=custom 时必填
    """
    from datetime import datetime, timedelta

    from app.services.electricity_service import electricity_service

    # 获取查询参数
    range_type = request.args.get("range_type", "month")  # 默认本月
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    # 计算日期范围（使用本地时间，中国时区 UTC+8）
    now = datetime.utcnow()
    # UTC+8 转换：本地时间 = UTC时间 + 8小时
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
        end_time = end_time  # 本周一作为结束（不包含）
    elif range_type == "month":
        # 本月（1号到今天）
        start_time = today.replace(day=1)
        end_time = today + timedelta(days=1)
    elif range_type == "last_month":
        # 上月（1号到月底）
        end_time = today.replace(day=1)  # 本月1号
        last_month_end = end_time - timedelta(days=1)  # 上月最后一天
        start_time = last_month_end.replace(day=1)  # 上月1号
        end_time = end_time  # 本月1号作为结束
    elif range_type == "custom" and start_date_str and end_date_str:
        # 自定义日期范围
        try:
            start_time = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_time = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            return api_error(message="日期格式错误，请使用 YYYY-MM-DD", http_status=400)
    else:
        # 默认本月
        start_time = today.replace(day=1)
        end_time = today + timedelta(days=1)

    # 将本地时间转换回UTC时间用于数据库查询
    start_time_utc = start_time - timedelta(hours=8)
    end_time_utc = end_time - timedelta(hours=8)

    svc = electricity_service
    stats = svc.get_statistics_by_range(start_time_utc, end_time_utc, start_time, end_time)

    # 过滤测试电表数据
    by_meter = [m for m in stats.get("by_meter", []) if "测试" not in m.get("meter", "")]

    # 补充前端需要的 summary 字段
    daily = stats.get("daily", [])
    total_usage = sum(m.get("usage", 0) for m in by_meter)

    summary = {
        "total_records": sum(d.get("count", 0) for d in daily),
        "total_usage": round(total_usage, 2),
        "avg_daily": round(total_usage / max(len(daily), 1), 2),
        "max_daily": round(max((d.get("usage", 0) for d in daily), default=0), 2),
        "min_daily": round(min((d.get("usage", 0) for d in daily), default=0), 2),
        "meter_count": len(by_meter),
    }

    return api_success(
        data={
            "daily": daily,
            "by_meter": by_meter,
            "summary": summary,
            "range": {
                "type": range_type,
                "start_date": start_time.strftime("%Y-%m-%d"),
                "end_date": (end_time - timedelta(days=1)).strftime("%Y-%m-%d"),
            },
        }
    )


@electricity_bp.route("/trigger/daily", methods=["POST"])
@admin_required
def trigger_daily():
    """手动触发每日用电报告推送（仅管理员）"""
    return _trigger_task("push_electricity_daily", "每日用电报告")


@electricity_bp.route("/trigger/weekly", methods=["POST"])
@admin_required
def trigger_weekly():
    """手动触发每周用电报告推送（仅管理员）"""
    return _trigger_task("push_electricity_weekly", "每周用电报告")


@electricity_bp.route("/trigger/monthly", methods=["POST"])
@admin_required
def trigger_monthly():
    """手动触发每月用电报告推送（仅管理员）"""
    return _trigger_task("push_electricity_monthly", "每月用电报告")


@electricity_bp.route("/trigger/cookie_check", methods=["POST"])
@admin_required
def trigger_cookie_check():
    """手动触发 Cookie 有效性检测（仅管理员）"""
    return _trigger_task("check_cookie_validity", "Cookie 检测")


@electricity_bp.route("/trigger/fetch_all", methods=["POST"])
@admin_required
def trigger_fetch_all():
    """
    手动触发全量爬取（需管理员权限）

    遍历所有已配置电表 Cookie 的学生，为每人强制全量爬取历史数据。
    适用场景：数据丢失后重新采集、学生更换电表/重新配置 Cookie 后重新导入等。
    """
    try:
        from app.modules.electricity.tasks import push_electricity_full_crawl

        def _do_fetch_all():
            push_electricity_full_crawl()

        thread = threading.Thread(target=_do_fetch_all, daemon=True)
        thread.start()

        user = g.get("current_user", {})
        logger.info(f'[电量] {user.get("username")} 手动触发全量爬取')
        return api_success(message="全量爬取任务已触发，正在后台执行")
    except Exception as exc:
        logger.error(f"[电量] 全量爬取触发失败: {exc}")
        return api_error(message=f"触发失败: {exc}", http_status=500)


@electricity_bp.route("/records", methods=["DELETE"])
@admin_required
def delete_all_records():
    """
    删除全部用电记录（需管理员权限）

    会清空以下表的数据：
    - electricity_records（用电记录）
    - electricity_remaining（剩余电量）
    - electricity_total_capacity（容量记录）

    适用场景：数据重置、重新全量爬取前清理旧数据
    """
    from app.core.database import get_db
    from app.model.electricity import (
        ElectricityRecord,
        ElectricityRemaining,
        ElectricityTotalCapacity,
    )

    session = get_db()
    try:
        records_count = session.query(ElectricityRecord).count()
        remaining_count = session.query(ElectricityRemaining).count()
        capacity_count = session.query(ElectricityTotalCapacity).count()

        session.query(ElectricityRecord).delete()
        session.query(ElectricityRemaining).delete()
        session.query(ElectricityTotalCapacity).delete()
        session.commit()

        user = g.get("current_user", {})
        logger.info(
            f'[电量] {user.get("username")} 删除了全部用电记录: '
            f'用电记录 {records_count} 条, 剩余电量 {remaining_count} 条, 容量记录 {capacity_count} 条'
        )

        return api_success(
            message="已清空全部数据",
            data={
                "deleted_records": records_count,
                "deleted_remaining": remaining_count,
                "deleted_capacity": capacity_count,
            },
        )
    except Exception as exc:
        session.rollback()
        logger.error(f"[电量] 删除用电记录失败: {exc}")
        return api_error(message=f"删除失败: {exc}", http_status=500)
    finally:
        session.close()


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------


def _trigger_task(func_name: str, label: str):
    """通用手动触发逻辑（JWT 认证由装饰器保证）"""
    try:
        import app.modules.electricity.tasks as elec_tasks

        task_func = getattr(elec_tasks, func_name)
        thread = threading.Thread(target=task_func, daemon=True)
        thread.start()
        user = g.get("current_user", {})
        logger.info(f'[电量] {user.get("username")} 手动触发 {label}')
        return api_success(message=f"{label} 任务已触发")
    except Exception as exc:
        logger.error(f"[电量] 触发 {label} 失败: {exc}")
        return api_error(message=f"触发失败: {exc}", http_status=500)
