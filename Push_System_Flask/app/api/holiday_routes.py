#!/usr/bin/env python3
"""
假期模式管理 API 蓝图

端点（全部 @admin_required）：
- GET   /api/holiday/status       — 当前假期模式状态（总开关 / 是否静默中 / 命中区间）
- PUT   /api/holiday/master       — 切换总开关 { enabled: bool }
- GET   /api/holiday/periods      — 假期区间列表
- POST  /api/holiday/periods      — 新建区间 { name, holiday_type, start_date, end_date, enabled, note }
- PUT   /api/holiday/periods/<id> — 修改区间
- DELETE /api/holiday/periods/<id>— 删除区间
"""

from flask import Blueprint, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.services.holiday_service import holiday_service
from app.utils.auth_middleware import admin_required

logger = get_logger(__name__)

holiday_bp = Blueprint("holiday", __name__)


@holiday_bp.route("/status", methods=["GET"])
@admin_required
def status():
    """当前假期模式状态。"""
    return api_success(data=holiday_service.get_status())


@holiday_bp.route("/master", methods=["PUT"])
@admin_required
def set_master():
    """切换假期模式总开关。"""
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        return api_error(message="enabled 必须为布尔值")
    holiday_service.set_master(enabled)
    return api_success(message="总开关已更新", data={"enabled": enabled})


@holiday_bp.route("/periods", methods=["GET"])
@admin_required
def list_periods():
    """假期区间列表。"""
    return api_success(data=holiday_service.list_periods())


@holiday_bp.route("/periods", methods=["POST"])
@admin_required
def create_period():
    """新建假期区间。"""
    data = request.get_json(silent=True) or {}
    try:
        period = holiday_service.create_period(data)
    except ValueError as e:
        return api_error(message=str(e), http_status=400)
    return api_success(message="假期区间已创建", data=period.to_dict())


@holiday_bp.route("/periods/<int:period_id>", methods=["PUT"])
@admin_required
def update_period(period_id: int):
    """修改假期区间。"""
    data = request.get_json(silent=True) or {}
    try:
        period = holiday_service.update_period(period_id, data)
    except ValueError as e:
        return api_error(message=str(e), http_status=400)
    if not period:
        return api_error(message="假期区间不存在", http_status=404)
    return api_success(message="假期区间已更新", data=period.to_dict())


@holiday_bp.route("/periods/<int:period_id>", methods=["DELETE"])
@admin_required
def delete_period(period_id: int):
    """删除假期区间。"""
    ok = holiday_service.delete_period(period_id)
    if not ok:
        return api_error(message="假期区间不存在", http_status=404)
    return api_success(message="假期区间已删除")
