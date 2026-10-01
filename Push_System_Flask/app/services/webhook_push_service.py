#!/usr/bin/env python3
"""
Webhook 多用户定向推送服务（scope-aware）

背景：电量从「全局单 Cookie」改为「多用户各自配 Cookie」后，原企业微信电量推送被整体移除，
只保留小程序站内通知，导致管理端/班级群看不到汇总电量。本服务恢复 webhook 推送，但改为
按 webhook 的 scope 定向聚合发送，避免全员报告刷屏：

- scope=student：仅 scope_target 中的 user_id 子集
- scope=dorm：仅 scope_target 中的宿舍（同宿舍=一组）内的已绑定学生
- scope=global（或受众无法解析）：**拒绝投递**。报告含各人私有数据，汇总进同一个群属隐私
  泄露，故记录告警后跳过该 webhook（管理端已不提供「全局」选项，此处兜住 API 直调 /
  历史遗留数据等绕过前端的情况）。详见 send_module_report 内的「隐私护栏」。

调用方（电量任务）负责收集每条学生报告的结构化 entry（user_id / display_name /
markdown_block），本服务按每个 webhook 的 scope 过滤后聚合为单条 Markdown 发送。

设计原则：失败静默、绝不影响主推送流程（与站内通知通道相互独立）。
"""

from app.core.database import get_db
from app.core.logger import get_logger

logger = get_logger(__name__)

# 企业微信 Markdown 单条消息长度上限（字节），预留安全余量
_WECOM_MARKDOWN_LIMIT = 3800


def _resolve_scope_user_ids(scope: str, scope_target) -> set[int] | None:
    """
    解析某 webhook 覆盖的 user_id 集合

    Returns:
        None 表示「全部」（global）；否则为命中的 user_id 集合。
        集合可能为空（如该宿舍暂无已绑定学生）。
    """
    from app.model.webhook import WEBHOOK_SCOPE_GLOBAL, WEBHOOK_SCOPE_DORM, WEBHOOK_SCOPE_STUDENT

    if scope == WEBHOOK_SCOPE_GLOBAL:
        return None

    if scope == WEBHOOK_SCOPE_STUDENT:
        try:
            ids = [int(x) for x in (scope_target or []) if x is not None]
        except (TypeError, ValueError):
            ids = []
        return set(ids)

    if scope == WEBHOOK_SCOPE_DORM:
        return _expand_dorm_user_ids(scope_target or [])

    # 未知 scope 视为全局，避免漏发
    logger.warning(f"[webhook_push] 未知 scope={scope}，按 global 处理")
    return None


def _expand_dorm_user_ids(dorms) -> set[int]:
    """
    按宿舍值展开已绑定学生的 user_id

    同宿舍（dorm 字段值相同）的学生构成一个组；返回这些宿舍内已绑定账号的 user_id 集合。
    以**学生名单 student_rosters 的宿舍字段为准**（管理员维护的源头），join 到已绑定的
    student_profiles（按 学校+学号 对应）取 user_id —— 名单里新增/改宿舍立即生效，
    不依赖「绑定那一刻」写入 profile.dorm 的快照（否则绑定后补填的宿舍会查不到人）。
    """
    try:
        dorms = [str(x).strip() for x in (dorms or []) if x is not None and str(x).strip()]
    except (TypeError, ValueError):
        return set()

    if not dorms:
        return set()

    from sqlalchemy import and_

    from app.model.student_profile import StudentProfile
    from app.model.student_roster import StudentRoster

    session = get_db()
    try:
        rows = (
            session.query(StudentProfile.user_id)
            .join(
                StudentRoster,
                and_(
                    StudentRoster.school == StudentProfile.school,
                    StudentRoster.student_number == StudentProfile.student_number,
                ),
            )
            .filter(
                StudentRoster.dorm.in_(dorms),
                StudentProfile.user_id.isnot(None),
            )
            .all()
        )
        return {r[0] for r in rows if r[0]}
    except Exception as exc:
        logger.error(f"[webhook_push] 展开宿舍用户失败: {exc}")
        return set()
    finally:
        session.close()


def _aggregate_markdown(header: str | None, blocks: list[str]) -> str:
    """将多名学生报告聚合成一条 Markdown，超长截断并提示。"""
    parts: list[str] = []
    if header:
        parts.append(header)
        parts.append("")

    total_len = sum(len(p) for p in parts)
    truncated = False
    for block in blocks:
        block_len = len(block) + 2  # 分隔行
        if total_len + block_len > _WECOM_MARKDOWN_LIMIT:
            truncated = True
            break
        parts.append(block)
        parts.append("---")
        total_len += block_len

    if truncated:
        parts.append("...（内容过长已省略，请在小程序查看完整报告）")
    return "\n".join(parts).strip()


def _send_one(url: str, content: str) -> bool:
    """向单个 webhook 发送 Markdown 消息（失败静默）。"""
    try:
        from app.services.adapter_service import WeComAdapter

        adapter = WeComAdapter({"webhook_url": url, "name": "scope_push"})
        result = adapter.send({"msgtype": "markdown", "markdown": {"content": content}})
        return bool(result.get("success"))
    except Exception as exc:
        logger.error(f"[webhook_push] 发送失败 url={url[:40]}...: {exc}")
        return False


def send_module_report(module: str, entries: list[dict], header: str | None = None) -> int:
    """
    按 webhook 的 scope 定向聚合发送某模块的报告

    Args:
        module: 模块名（course/weather/electricity/system）
        entries: 报告条目列表，每项 {user_id:int, display_name:str, markdown_block:str}
        header: 聚合消息头部（如「每日用电报告汇总」）

    Returns:
        成功发送的 webhook 数量
    """
    if not entries:
        return 0

    from app.model.webhook import Webhook

    session = get_db()
    try:
        webhooks = Webhook.get_enabled_webhooks(session)
    finally:
        session.close()

    if not webhooks:
        logger.info(f"[webhook_push] 模块 {module} 无启用 webhook，跳过")
        return 0

    sent = 0
    for wh in webhooks:
        module_list = wh.get_module_list()
        if "all" not in module_list and module not in module_list:
            continue

        target_ids = _resolve_scope_user_ids(wh.scope, wh.scope_target)

        # 隐私护栏（2026-10-01）：电量报告含各人用电数据，`scope=global`（或受众无法解析）
        # 会把多个人的数据汇总成一条发进同一个群，属隐私泄露，故**拒绝投递**并告警。
        # 管理端已不提供「全局」选项，这里兜住绕过前端的情况（API 直调 / 历史遗留数据）。
        if target_ids is None:
            logger.warning(
                f"[webhook_push] 拒绝向 scope={wh.scope or 'global'} 的 webhook「{wh.name}」"
                f"投递 {module} 报告（会把多人数据汇总进同一个群）。"
                f"请为其指定宿舍或学生；本条已跳过，未发送。"
            )
            continue

        scoped = [e for e in entries if e.get("user_id") in target_ids]

        if not scoped:
            logger.info(f"[webhook_push] webhook {wh.name} scope={wh.scope} 无命中学生，跳过")
            continue

        blocks = [e.get("markdown_block", "") for e in scoped if e.get("markdown_block")]
        content = _aggregate_markdown(header, blocks)
        if not content:
            continue

        if _send_one(wh.url, content):
            sent += 1
            logger.info(
                f"[webhook_push] webhook {wh.name} 发送成功，覆盖 {len(scoped)} 名学生"
            )
        else:
            logger.warning(f"[webhook_push] webhook {wh.name} 发送失败")

    return sent


def fanout_broadcast_webhooks(module: str, content: str) -> int:
    """
    广播型模块（course/weather）内容补发给「非全局」定向 webhook

    全局 webhook 已由 adapter_service 的广播适配器覆盖，此处只补发
    scope=student / scope=dorm 的 webhook，避免重复投递。适用于学生/宿舍
    自建的「第三方消息通知」等定向场景：它们同样需要收到课程等广播副本。

    注意 system 刻意**不在此列**（调用方 delivery_service 仅对 course/weather 调用）：
    爬虫失败、系统异常属运维告警，不适合补发到宿舍群/学生自建 webhook；
    订阅 system 的 webhook 一律按全局处理，由 adapter 广播覆盖。

    Args:
        module: 模块名
        content: 已渲染的 Markdown 文本（与全局广播同内容）

    Returns:
        成功发送的 webhook 数量
    """
    if not content:
        return 0

    from app.model.webhook import WEBHOOK_SCOPE_GLOBAL, Webhook

    session = get_db()
    try:
        webhooks = Webhook.get_enabled_webhooks(session)
    finally:
        session.close()

    if not webhooks:
        return 0

    sent = 0
    for wh in webhooks:
        module_list = wh.get_module_list()
        if "all" not in module_list and module not in module_list:
            continue
        # 全局已由 adapter 广播覆盖，跳过避免重复
        if (wh.scope or WEBHOOK_SCOPE_GLOBAL) == WEBHOOK_SCOPE_GLOBAL:
            continue
        if _send_one(wh.url, content):
            sent += 1
            logger.info(
                f"[webhook_push] 定向广播 {module} -> webhook {wh.name} (scope={wh.scope})"
            )
        else:
            logger.warning(f"[webhook_push] 定向广播 {module} -> webhook {wh.name} 发送失败")
    return sent
