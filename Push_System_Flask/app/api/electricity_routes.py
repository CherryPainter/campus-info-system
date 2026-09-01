#!/usr/bin/env python3
"""
电量监控 API 路由
提供电量数据查询、手动触发推送、Cookie 更新等接口

职责：
- 仅处理 HTTP 请求/响应
- 业务逻辑委托给 Service 层
- 数据访问委托给 Repository 层

认证方式：统一使用 JWT Bearer Token
- @admin_required: 需要管理员权限（模块状态、全量爬取、清空数据）
- 无装饰器: 公开端点（健康检查）

用户化说明（2026-09-01）：
- 电量数据按用户隔离后，原全局视图查询接口（/remaining、/records、/statistics）
  已随管理端改版删除；学生维度查询统一走 /api/admin/electricity/students/<id>/...。
- 手动触发推送（daily/weekly/monthly/cookie_check）已无前端引用，一并删除；
  管理端触发统一走 /api/admin/electricity/trigger。
"""

import threading

from flask import Blueprint, current_app, g, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.utils.auth_middleware import admin_required

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
