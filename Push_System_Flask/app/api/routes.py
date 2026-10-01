#!/usr/bin/env python3
"""API 路由蓝图

所有端点统一使用 JWT Bearer Token 认证：
- @jwt_required: 需要登录即可访问
- @admin_required: 需要管理员权限
- 无装饰器: 公开端点（如健康检查）
"""

import os
from datetime import datetime

from flask import Blueprint, current_app, g, request, send_from_directory

from app.core.api_response import api_error, api_success
from app.core.config import Config
from app.core.logger import get_logger
from app.services.adapter_service import adapter_service
from app.services.rule_service import rule_service
from app.services.schedule_service import schedule_service
from app.services.task_service import task_service
from app.services.template_service import template_service
from app.tasks.scheduler import get_spider_status, run_spider
from app.utils.auth_middleware import admin_required, jwt_required
from app.utils.security import get_client_ip

logger = get_logger(__name__)

api_bp = Blueprint("api", __name__)


@api_bp.route("/")
def index():
    """服务信息（公开）。

    刻意**不再返回端点清单**：那是一份攻击面自述（7 条管理端路径），而两端前端都没有
    消费方，属纯粹的指纹暴露面（原样保留在 B 级加固项 B11 里）。

    保留 `version` 与 `your_ip` 是经过权衡的：`version` 是部署后核对版本的实际手段，
    `your_ip` 是配置 `REGION_BLOCK_EXCEPTIONS` 管理员白名单时的自助查询入口（返回的
    也只是请求方自己的 IP），删掉会打断既有运维流程。若需彻底移除版本号，请连同
    `/api/health` 一并决定。
    """
    return api_success(
        message="Course Push System API",
        your_ip=get_client_ip(),
        version=current_app.config["APP_VERSION"],
    )


@api_bp.route("/health")
def health():
    """健康检查（无限制）"""
    return api_success(
        status="healthy",
        service="course-push-system",
        timestamp=int(datetime.now().timestamp()),
        version=current_app.config["APP_VERSION"],
    )


@api_bp.route("/status")
@jwt_required
def status():
    """系统状态（需 JWT 认证）"""
    return api_success(
        service="Course Push System",
        version=current_app.config["APP_VERSION"],
        auth_enabled=current_app.config["AUTH_ENABLED"],
        data_ready=schedule_service.is_data_ready,
        schedule_stats=schedule_service.get_statistics(),
        task_stats=task_service.get_statistics(),
        adapter_status=adapter_service.get_all_status(),
    )


@api_bp.route("/trigger", methods=["POST"])
@admin_required
def trigger():
    """手动触发推送（需管理员权限）

    修复：原为 @jwt_required（任意登录用户，含学生 role='student'）即可调用，
    可 force=true 强制触发面向全校的推送广播。推送是管理端运营操作，
    学生端角色不应能触发，收紧为 @admin_required（2026-09-06）。

    查询参数:
        force: bool - 为 true 时忽略时间窗口检查，强制触发所有适用规则（默认 false）
        type: str - 指定规则类型（before_class/daily_schedule/before_end_class/after_class）
    """
    force = request.args.get("force", "false").lower() == "true"
    rule_type = request.args.get("type", "")

    schedules = schedule_service.get_schedules()
    if not schedules and not schedule_service.is_data_ready:
        return api_error(
            message="Schedule data not ready yet, please wait for spider to run",
            tasks_created=0,
            http_status=503,
        )

    if force:
        tasks = rule_service.check_conditions_force(datetime.now(), schedules, rule_type=rule_type)
    else:
        tasks = rule_service.check_conditions(datetime.now(), schedules)

    if not tasks:
        return api_success(message="No trigger conditions met", tasks_created=0)

    created = task_service.create_tasks(tasks)
    user = g.get("current_user", {})
    logger.info(
        f'Manual trigger by {user.get("username")} (force={force}, type={rule_type}): {len(created)} task(s) created'
    )

    return api_success(
        message=f"Trigger executed, {len(created)} task(s) created", tasks_created=len(created)
    )


@api_bp.route("/schedules")
@jwt_required
def get_schedules():
    """获取课表（需 JWT 认证）"""
    force = request.args.get("force", "false").lower() == "true"
    schedules = schedule_service.get_schedules(force_reload=force)
    return api_success(
        count=len(schedules), data_ready=schedule_service.is_data_ready, schedules=schedules
    )


@api_bp.route("/schedules/today")
@jwt_required
def get_today_schedules():
    """获取今日课表（需 JWT 认证）"""
    schedules = schedule_service.get_today_schedules()
    return api_success(
        count=len(schedules), data_ready=schedule_service.is_data_ready, schedules=schedules
    )


@api_bp.route("/schedules/statistics")
@jwt_required
def get_statistics():
    """获取课表统计（需 JWT 认证）"""
    stats = schedule_service.get_statistics()
    return api_success(**stats)


@api_bp.route("/rules")
@jwt_required
def get_rules():
    """获取推送规则（需 JWT 认证）"""
    return api_success(rules=rule_service.get_rules())


# ==================== 公告正文图片（公开访问）====================
# 富文本编辑器上传的正文图片存于 output/announcement-images/，
# 学生端 RichText 渲染正文时也需无鉴权加载，故放公共蓝图。
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@api_bp.route("/announcement-images/<path:name>")
def announcement_image(name):
    """公告正文图片（公开）

    安全：扩展名白名单 + send_from_directory 自带路径穿越防护。
    """
    ext = os.path.splitext(name)[1].lower()
    if ext not in _IMAGE_EXTS:
        return api_error(message="非法图片路径", http_status=400)
    root = os.path.abspath(os.path.join(Config.OUTPUT_DIR, "announcement-images"))
    return send_from_directory(root, name)


# ==================== 反馈截图（需签名）====================
@api_bp.route("/feedback-images/<path:name>")
def feedback_image(name):
    """反馈截图（需签名访问）

    安全（B1）：反馈截图属于「仅提交者与管理员应可见」的内容，此前是完全公开的
    无鉴权路由 —— URL 一经泄漏（转发、浏览器历史、代理日志、Referer）即可被任何人在
    任何时间取走，且服务端无法撤销。现要求 `?exp=&sig=`（HMAC 签名，见
    app/utils/signed_url.py），过期或签名不符一律 403。

    为什么用签名而不是鉴权：`<img>` 标签无法携带 Authorization 头，改鉴权需要两端都换成
    blob 拉取，且小程序 `<Image>` 的 cookie 行为本地无法验证。签名 URL 是图片类资源在
    「不可携带凭证」约束下的标准解法。

    扩展名白名单 + send_from_directory 的路径穿越防护保持原样。
    """
    from app.utils.signed_url import verify_signature

    ext = os.path.splitext(name)[1].lower()
    if ext not in _IMAGE_EXTS:
        return api_error(message="非法图片路径", http_status=400)

    # 签名基准 = 不带 query 的规范路径，避免把签名参数本身卷进验签字符串
    canonical = f"/api/feedback-images/{name}"
    ok, reason = verify_signature(
        canonical, request.args.get("exp"), request.args.get("sig")
    )
    if not ok:
        logger.warning(f"反馈截图签名校验失败（{reason}）: name={name}")
        return api_error(message="图片链接无效或已过期，请刷新页面重试", http_status=403)

    root = os.path.abspath(os.path.join(Config.OUTPUT_DIR, "feedback-images"))
    return send_from_directory(root, name)


# ==================== 公告封面（公开访问）====================
@api_bp.route("/announcement-covers/<path:name>")
def announcement_cover(name):
    """公告封面图（公开，学生端消息卡片 / 详情页加载）

    安全：扩展名白名单 + send_from_directory 自带路径穿越防护。
    """
    ext = os.path.splitext(name)[1].lower()
    if ext not in _IMAGE_EXTS:
        return api_error(message="非法图片路径", http_status=400)
    root = os.path.abspath(os.path.join(Config.OUTPUT_DIR, "announcement-covers"))
    return send_from_directory(root, name)


@api_bp.route("/tasks")
@jwt_required
def get_tasks():
    """获取任务统计（需 JWT 认证）"""
    return api_success(**task_service.get_statistics())


@api_bp.route("/templates")
@jwt_required
def get_templates():
    """获取消息模板（需 JWT 认证）"""
    return api_success(templates=template_service.get_all_templates())


@api_bp.route("/templates/reload", methods=["POST"])
@admin_required
def reload_templates():
    """重新加载模板配置文件（需管理员权限）"""
    count = template_service.reload_templates()
    return api_success(message=f"Reloaded {count} templates")


@api_bp.route("/spider/run", methods=["POST"])
@admin_required
def run_spider_api():
    """手动触发爬虫（需管理员权限）"""
    spider_status = get_spider_status()
    if spider_status.get("running"):
        return api_error(message="Spider is already running", http_status=409)

    import threading

    thread = threading.Thread(target=run_spider, kwargs={"trigger_source": "manual"}, daemon=True)
    thread.start()

    return api_success(message="Spider execution started")


@api_bp.route("/spider/status")
@jwt_required
def spider_status():
    """查询爬虫执行状态（需 JWT 认证）"""
    status = get_spider_status()
    return api_success(spider=status)
