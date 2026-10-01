#!/usr/bin/env python3
"""
Webhook 管理 API 路由

端点列表：
- GET    /api/admin/webhooks              — 获取所有 webhook
- POST   /api/admin/webhooks              — 创建 webhook
- GET    /api/admin/webhooks/<id>         — 获取单个 webhook
- PUT    /api/admin/webhooks/<id>         — 更新 webhook
- DELETE /api/admin/webhooks/<id>         — 删除 webhook
- POST   /api/admin/webhooks/<id>/test    — 测试 webhook
- POST   /api/admin/webhooks/reload       — 重载适配器配置
"""

import requests
from flask import Blueprint, request

from app.core.api_response import api_error, api_success
from app.core.database import get_db
from app.core.extensions import RATE_LIMITS, limiter
from app.core.logger import get_logger
from app.model.webhook import (
    WEBHOOK_SCOPE_DORM,
    WEBHOOK_SCOPE_GLOBAL,
    WEBHOOK_SCOPE_STUDENT,
    WEBHOOK_SCOPES,
    Webhook,
)
from app.services.adapter_service import adapter_service
from app.utils.auth_middleware import admin_required
from app.utils.url_guard import validate_outbound_url

logger = get_logger(__name__)

webhook_bp = Blueprint("webhook", __name__)

# scope_target 格式非法的哨兵值（用于与 scope=global 的 None 区分开，见 _normalize_scope_target）
_INVALID_SCOPE_TARGET = object()

_SCOPE_TARGET_FORMAT_ERROR = "scope_target 格式错误（student 应为整数 ID 列表，dorm 应为宿舍值列表）"


def _normalize_scope_target(raw, scope: str):
    """
    规范化 scope_target（按 scope 决定元素类型）

    - scope=global：忽略，返回 None（不限定受众）
    - scope=student：整数 user_id 列表（JSON 数组）
    - scope=dorm：宿舍值列表（字符串，如 ["A栋305"]）

    Returns:
        合法目标列表（global 为 None，其余为列表）；
        **格式非法**返回哨兵 `_INVALID_SCOPE_TARGET`。
        注意：`global` 与「格式非法」必须区分 —— 早期两者都返回 None，导致
        「全局 webhook（课表/天气/系统的默认范围）」被误判为格式错误而无法保存。
    """
    if scope == WEBHOOK_SCOPE_GLOBAL:
        return None

    if raw is None:
        return []

    if not isinstance(raw, (list, tuple, set)):
        return _INVALID_SCOPE_TARGET

    if scope == WEBHOOK_SCOPE_DORM:
        # 宿舍值：去空白后的非空字符串
        vals = [str(x).strip() for x in raw if x is not None and str(x).strip()]
        return vals

    # student：整数 user_id
    try:
        return [int(x) for x in raw if x is not None]
    except (TypeError, ValueError):
        return _INVALID_SCOPE_TARGET


# 电量报告是「逐人」数据（每人在小程序自配电表 Cookie，按 user_id 采集、按 user_id 落库）。
# 接收范围若为 global，会把多个人的用电数据汇总成同一条消息发进同一个群，属隐私泄露。
# 故在**写入层**就拒绝「含电量（或 all）+ global」的配置 —— 即使有人绕过前端直调 API
# 也存不进这种配置。这与投递层护栏（app/services/webhook_push_service.py 的
# send_module_report 会拒发 scope=global 的电量报告）构成双保险：
#   写入层拦住新配置，投递层兜住历史遗留数据。
_SCOPE_REQUIRED_MODULES = {"electricity"}


def _check_scope_conflict(modules, scope: str, scope_target):
    """
    写入层围栏：校验「模块 + 接收范围」组合是否合法

    Args:
        modules: 模块逗号串（或列表），如 "course,electricity"、"all"
        scope: global / student / dorm
        scope_target: 已规范化的范围目标（global 为 None，其余为列表）

    Returns:
        合法返回 None；否则返回可直接回给前端的错误文案。

    口径与前端 admin-frontend/src/pages/Webhooks.tsx 的 MODULE_SCOPE_KIND 一致：
    "all" 视为含电量，同样必须指定受众。
    """
    if isinstance(modules, (list, tuple, set)):
        module_list = [str(m).strip() for m in modules if str(m).strip()]
    else:
        module_list = [m.strip() for m in str(modules or "").split(",") if m.strip()]

    if "all" not in module_list and not (_SCOPE_REQUIRED_MODULES & set(module_list)):
        return None

    if scope == WEBHOOK_SCOPE_GLOBAL:
        return (
            "接收范围不能为「全局」：所选模块含电量，而电量是逐人数据，"
            "汇总成一条发进同一个群会造成隐私泄露。请改为指定宿舍或指定学生"
        )
    if not scope_target:
        return "范围目标不能为空：请至少指定一个宿舍或一名学生，否则本条不会发出任何电量报告"
    return None


def _validate_url(url: str):
    """
    Webhook URL 校验（SSRF 防护）

    早期只校验 `https://` 前缀，等于允许管理员（或被盗用的管理员令牌）把服务端
    当探针去打内网。现改走共享的出站 URL 校验（app/utils/url_guard.py）：
    协议 + 禁止内嵌凭据 + 拒绝本机/内网域名 + 拒绝非公网 IP + DNS 解析结果校验。

    合法但确实指向内网中转的场景，用环境变量 `WEBHOOK_URL_ALLOWED_HOSTS`
    显式放行（见 url_guard 模块 docstring），不做任何隐式放宽。

    Returns:
        合法返回 None；否则返回可直接回给前端的错误文案。
    """
    ok, err = validate_outbound_url(url, label="Webhook URL")
    return None if ok else err


def _find_missing_scope_members(scope: str, scope_target):
    """
    校验接收范围的成员是否真实存在

    背景：范围目标（学生 user_id / 宿舍值）若填错或对象已被删除、解绑、移出名单，
    保存会成功但**投递时静默不发**，管理员很难发现。这里在写入层就给出明确提示。

    判定口径与「下拉选项来源」保持一致：
    - student → `users.id` 是否存在
    - dorm    → `student_rosters.dorm` 是否有该值（与管理端宿舍下拉同源）

    Returns:
        (不存在的学生 ID 列表, 不存在的宿舍值列表)

    注意：这是「防拼错」的便利校验，不是隐私围栏，故**查询异常时 fail-open**
    （记 warning 后跳过校验），不让一次数据库抖动阻断管理员保存配置。
    """
    missing_students, missing_dorms = [], []

    if scope == WEBHOOK_SCOPE_STUDENT and scope_target:
        wanted = sorted({int(x) for x in scope_target})
        session = None
        try:
            from app.model.user import User

            session = get_db()
            rows = session.query(User.id).filter(User.id.in_(wanted)).all()
            found = {int(row[0]) for row in rows}
            missing_students = [i for i in wanted if i not in found]
        except Exception as exc:
            logger.warning(f"[Webhook] 学生受众存在性校验已跳过: {exc}")
        finally:
            if session:
                session.close()

    elif scope == WEBHOOK_SCOPE_DORM and scope_target:
        wanted = sorted({str(x) for x in scope_target})
        session = None
        try:
            from app.model.student_roster import StudentRoster

            session = get_db()
            rows = (
                session.query(StudentRoster.dorm)
                .filter(StudentRoster.dorm.in_(wanted))
                .distinct()
                .all()
            )
            found = {str(row[0]) for row in rows if row[0]}
            missing_dorms = [d for d in wanted if d not in found]
        except Exception as exc:
            logger.warning(f"[Webhook] 宿舍受众存在性校验已跳过: {exc}")
        finally:
            if session:
                session.close()

    return missing_students, missing_dorms


def _scope_member_error(scope: str, scope_target):
    """受众成员存在性校验：合法返回 None，否则返回错误文案。"""
    missing_students, missing_dorms = _find_missing_scope_members(scope, scope_target)
    if not missing_students and not missing_dorms:
        return None

    def _fmt(values):
        shown = "、".join(str(v) for v in values[:10])
        return f"{shown} 等 {len(values)} 项" if len(values) > 10 else shown

    parts = []
    if missing_students:
        parts.append(f"学生 ID {_fmt(missing_students)}")
    if missing_dorms:
        parts.append(f"宿舍 {_fmt(missing_dorms)}")
    return (
        "以下范围目标不存在，保存后将不会发出任何内容：" + "；".join(parts) + "。"
        "可能已被删除、解绑或移出名单，请重新选择"
    )


@webhook_bp.route("", methods=["GET"])
@admin_required
def get_webhooks():
    """
    获取所有 webhook 列表（支持分页）

    查询参数：
        enabled_only: true 只返回启用的
        page: 页码（从 1 开始，默认 1）
        page_size: 每页条数（默认 20，最大 100）
    """
    enabled_only = request.args.get("enabled_only", "false").lower() == "true"
    page = request.args.get("page", 1, type=int) or 1
    page_size = min(100, max(1, request.args.get("page_size", 20, type=int) or 20))

    session = get_db()
    try:
        if enabled_only:
            result = Webhook.get_enabled_webhooks(session, page=page, page_size=page_size)
        else:
            result = Webhook.get_all_webhooks(session, page=page, page_size=page_size)

        # 新分页接口返回 tuple；旧调用（无 page）返回 list 以保持兼容
        if isinstance(result, tuple):
            webhooks, total = result
        else:
            webhooks = result
            total = len(result)

        # 解析归属学生姓名（owner_user_id 非空时），供管理端「来源」徽标展示
        owner_ids = [w.owner_user_id for w in webhooks if w.owner_user_id]
        owner_names: dict = {}
        if owner_ids:
            from app.model.student_profile import StudentProfile

            rows = (
                session.query(
                    StudentProfile.user_id,
                    StudentProfile.real_name,
                    StudentProfile.nickname,
                )
                .filter(StudentProfile.user_id.in_(owner_ids))
                .all()
            )
            for r in rows:
                owner_names[r.user_id] = r.nickname or r.real_name or f"用户{r.user_id}"

        # 解析「指定学生」范围的目标姓名：列表页要展示范围受众，但前端不能再一次性
        # 拉全量名单（/admin/roster/students 的 page_size 上限 100，千人名单会被截断）。
        # 因此由服务端只按本条记录命中的 user_id 批量取名字回填。
        target_ids: set = set()
        for w in webhooks:
            if (w.scope or "") == "student":
                for x in w.scope_target or []:
                    try:
                        target_ids.add(int(x))
                    except (TypeError, ValueError):
                        continue
        target_names: dict = {}
        if target_ids:
            from app.model.student_profile import StudentProfile

            rows = (
                session.query(
                    StudentProfile.user_id,
                    StudentProfile.real_name,
                    StudentProfile.nickname,
                )
                .filter(StudentProfile.user_id.in_(list(target_ids)))
                .all()
            )
            for r in rows:
                target_names[r.user_id] = r.nickname or r.real_name or f"用户{r.user_id}"

        data = []
        for w in webhooks:
            d = w.to_dict()
            if w.owner_user_id:
                d["owner_name"] = owner_names.get(w.owner_user_id) or f"用户{w.owner_user_id}"
            else:
                d["owner_name"] = None
            # 仅 student 范围需要把 user_id 翻译成姓名；dorm 的 scope_target 本身就是宿舍名
            if (w.scope or "") == "student" and w.scope_target:
                names = []
                for x in w.scope_target:
                    try:
                        uid = int(x)
                    except (TypeError, ValueError):
                        names.append(str(x))
                        continue
                    names.append(target_names.get(uid) or f"用户{uid}")
                d["scope_target_names"] = names
            else:
                d["scope_target_names"] = None
            data.append(d)

        return api_success(
            data=data,
            total=total,
            page=page,
            page_size=page_size,
        )
    finally:
        session.close()


@webhook_bp.route("", methods=["POST"])
@admin_required
def create_webhook():
    """
    创建新 webhook

    请求体：
        {
            "name": "班级群",
            "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
            "modules": "electricity",           // course,weather,electricity,system,all
            "scope": "global",                  // global / student / dorm
            "scope_target": [3, 7],             // scope=student 时 user_id 列表；dorm 时宿舍值列表
            "description": "可选描述"
        }
    """
    data = request.get_json(silent=True) or {}

    # 验证必填字段
    name = data.get("name", "").strip()
    url = data.get("url", "").strip()

    if not name:
        return api_error(message="名称不能为空", http_status=400)
    if not url:
        return api_error(message="URL 不能为空", http_status=400)
    url_error = _validate_url(url)
    if url_error:
        return api_error(message=url_error, http_status=400)

    # 验证 modules
    modules = data.get("modules", "course")
    if not isinstance(modules, str):
        # 显式拒绝：早期直接 modules.split(",") 会在收到数组时抛 AttributeError → 500
        return api_error(message="modules 必须是逗号分隔的字符串，如 course,electricity", http_status=400)
    valid_modules = {"all", "course", "weather", "electricity", "system"}
    module_list = [m.strip() for m in modules.split(",") if m.strip()]
    invalid = set(module_list) - valid_modules
    if invalid:
        return api_error(message=f"无效的模块: {invalid}", http_status=400)

    # 验证 scope 与 scope_target
    scope = (data.get("scope") or "global").strip()
    if scope not in WEBHOOK_SCOPES:
        return api_error(message=f"无效的接收范围: {scope}", http_status=400)
    scope_target = _normalize_scope_target(data.get("scope_target"), scope)
    if scope_target is _INVALID_SCOPE_TARGET:
        return api_error(message=_SCOPE_TARGET_FORMAT_ERROR, http_status=400)

    # 写入层围栏：拒绝「电量（或 all）+ 全局」这类会泄露隐私的配置
    conflict = _check_scope_conflict(modules, scope, scope_target)
    if conflict:
        return api_error(message=conflict, http_status=400)

    # 受众成员存在性校验：填了不存在的学生/宿舍会「保存成功但静默不发」
    member_error = _scope_member_error(scope, scope_target)
    if member_error:
        return api_error(message=member_error, http_status=400)

    session = get_db()
    try:
        webhook = Webhook.create(
            session=session,
            name=name,
            url=url,
            modules=modules,
            scope=scope,
            scope_target=scope_target,
            description=data.get("description", "").strip() or None,
        )

        logger.info(f"[Webhook] 创建成功: {name} ({modules}) scope={scope}")

        return api_success(message="Webhook 创建成功", data=webhook.to_dict(), http_status=201)
    finally:
        session.close()


@webhook_bp.route("/<int:webhook_id>", methods=["GET"])
@admin_required
def get_webhook(webhook_id: int):
    """获取单个 webhook 详情"""
    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not webhook:
            return api_error(message="Webhook 不存在", http_status=404)

        return api_success(data=webhook.to_dict())
    finally:
        session.close()


@webhook_bp.route("/<int:webhook_id>", methods=["PUT"])
@admin_required
def update_webhook(webhook_id: int):
    """
    更新 webhook

    请求体（可选字段）：
        {
            "name": "新名称",
            "url": "新 URL",
            "modules": "course,weather",
            "scope": "student",               // global / student / dorm
            "scope_target": [3, 7],          // scope=student 时整数 ID 列表；dorm 时宿舍值列表
            "is_enabled": true/false,
            "description": "描述"
        }
    """
    data = request.get_json(silent=True) or {}

    # 验证 URL 格式
    if "url" in data:
        url = data["url"].strip()
        url_error = _validate_url(url)
        if url_error:
            return api_error(message=url_error, http_status=400)
        data["url"] = url

    # 验证 modules
    if "modules" in data:
        if not isinstance(data["modules"], str):
            # 显式拒绝：早期直接 .split(",") 会在收到数组时抛 AttributeError → 500
            return api_error(
                message="modules 必须是逗号分隔的字符串，如 course,electricity", http_status=400
            )
        valid_modules = {"all", "course", "weather", "electricity", "system"}
        module_list = [m.strip() for m in data["modules"].split(",") if m.strip()]
        invalid = set(module_list) - valid_modules
        if invalid:
            return api_error(message=f"无效的模块: {invalid}", http_status=400)

    # 验证 scope
    if "scope" in data:
        scope = (data.get("scope") or "global").strip()
        if scope not in WEBHOOK_SCOPES:
            return api_error(message=f"无效的接收范围: {scope}", http_status=400)

    session = get_db()
    try:
        # 写入层围栏必须按「与库内现值合并后的最终配置」判定：PUT 允许只传部分字段，
        # 否则可以只传 {"scope": "global"} 就把一条含电量的 webhook 改成隐私越界配置。
        existing = Webhook.get_by_id(session, webhook_id)
        if not existing:
            return api_error(message="Webhook 不存在", http_status=404)

        eff_scope = data["scope"] if "scope" in data else (existing.scope or WEBHOOK_SCOPE_GLOBAL)
        eff_modules = data["modules"] if "modules" in data else (existing.modules or "")

        # 最终受众（同样要合并库内现值）
        if eff_scope == WEBHOOK_SCOPE_GLOBAL:
            eff_target = None
            if "scope" in data:
                # 切回全局：清空残留受众，避免旧 ID 继续生效
                data["scope_target"] = None
        elif "scope_target" in data:
            eff_target = _normalize_scope_target(data.get("scope_target"), eff_scope)
            if eff_target is _INVALID_SCOPE_TARGET:
                return api_error(message=_SCOPE_TARGET_FORMAT_ERROR, http_status=400)
            data["scope_target"] = eff_target
        elif "scope" in data and eff_scope == (existing.scope or WEBHOOK_SCOPE_GLOBAL):
            # 只传了 scope 且与库内一致：沿用原有受众
            eff_target = existing.scope_target
        elif "scope" in data:
            # 换了 scope 类型但没给新受众：旧受众的元素类型不兼容（user_id ↔ 宿舍值），
            # 一律清空；含电量时会被下面的围栏拦下，要求重新指定。
            eff_target = None
            data["scope_target"] = None
        else:
            eff_target = existing.scope_target

        conflict = _check_scope_conflict(eff_modules, eff_scope, eff_target)
        if conflict:
            return api_error(message=conflict, http_status=400)

        # 受众成员存在性校验（同样按合并后的最终受众判定）
        member_error = _scope_member_error(eff_scope, eff_target)
        if member_error:
            return api_error(message=member_error, http_status=400)

        success = Webhook.update(session, webhook_id, **data)
        if not success:
            return api_error(message="Webhook 不存在", http_status=404)

        webhook = Webhook.get_by_id(session, webhook_id)
        logger.info(f"[Webhook] 更新成功: ID={webhook_id}")

        return api_success(message="Webhook 更新成功", data=webhook.to_dict())
    finally:
        session.close()


@webhook_bp.route("/<int:webhook_id>", methods=["DELETE"])
@admin_required
def delete_webhook(webhook_id: int):
    """删除 webhook"""
    session = get_db()
    try:
        success = Webhook.delete(session, webhook_id)
        if not success:
            return api_error(message="Webhook 不存在", http_status=404)

        logger.info(f"[Webhook] 删除成功: ID={webhook_id}")

        return api_success(message="Webhook 已删除")
    finally:
        session.close()


@webhook_bp.route("/<int:webhook_id>/test", methods=["POST"])
@admin_required
@limiter.limit(RATE_LIMITS["strict"])
def test_webhook(webhook_id: int):
    """
    测试 webhook

    发送一条测试消息到指定 webhook

    限流：该端点会向外部地址真实发起请求，单独设「strict」档（10 次/分钟），
    避免被反复调用刷出站流量或把目标机器人打到限流。
    """
    session = get_db()
    try:
        webhook = Webhook.get_by_id(session, webhook_id)
        if not webhook:
            return api_error(message="Webhook 不存在", http_status=404)

        # 更新测试状态为 pending
        webhook.update_test_status(session, "pending")

        # 测试端点会真的发起出站请求，故在此**再校验一次库里的 URL**：
        # 护栏加在写入层之前入库的历史数据（早期只校验 https 前缀）可能指向内网/本机，
        # 直接发送等于把服务端当 SSRF 探针。这里拦住并给出明确提示。
        url_error = _validate_url(webhook.url)
        if url_error:
            webhook.update_test_status(session, "failed")
            logger.warning(f"[Webhook] 测试已拦截（URL 不安全）: {webhook.name} - {url_error}")
            return api_error(message=f"测试已拦截：{url_error}", http_status=400)

        # 发送测试消息
        test_message = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"**测试消息**\n\nWebhook: {webhook.name}\n时间: 刚刚\n\n> 如果收到此消息，说明 webhook 配置正确"
            },
        }

        try:
            resp = requests.post(webhook.url, json=test_message, timeout=10)
            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text[:200]}

            # 企业微信返回 HTTP 200 + JSON {errcode, errmsg}；
            # 其他通用 webhook 仅以 HTTP 状态码判断。
            if resp.status_code != 200:
                error_msg = f"HTTP {resp.status_code}"
                webhook.update_test_status(session, "failed")
                logger.warning(f"[Webhook] 测试失败: {webhook.name} - {error_msg}")
                return api_error(
                    message=f"测试失败: {error_msg}",
                    data={"webhook_response": data},
                    http_status=400,
                )

            errcode = data.get("errcode")
            if errcode is not None and errcode != 0:
                error_msg = data.get("errmsg", "未知错误")
                webhook.update_test_status(session, "failed")
                logger.warning(f"[Webhook] 测试失败: {webhook.name} - {error_msg}")
                return api_error(
                    message=f"测试失败: {error_msg}",
                    data={"webhook_response": data},
                    http_status=400,
                )

            # 成功（errcode=0，或无 errcode 字段的通用 webhook）
            webhook.update_test_status(session, "success")
            logger.info(f"[Webhook] 测试成功: {webhook.name}")
            return api_success(
                message="测试消息发送成功",
                data={"webhook_response": data},
            )

        except Exception as e:
            webhook.update_test_status(session, "failed")
            logger.error(f"[Webhook] 测试异常: {webhook.name} - {e}")
            return api_error(message=f"测试异常: {str(e)}", http_status=500)

    finally:
        session.close()


@webhook_bp.route("/reload", methods=["POST"])
@admin_required
def reload_adapters():
    """
    重载适配器配置

    从数据库重新加载 webhook 配置到适配器服务
    """
    try:
        adapter_service.reload_webhooks()
        logger.info("[Webhook] 适配器配置已重载")

        return api_success(message="适配器配置已重载", data=adapter_service.get_all_status())
    except Exception as e:
        logger.error(f"[Webhook] 重载适配器失败: {e}")
        return api_error(message=f"重载失败: {str(e)}", http_status=500)
