#!/usr/bin/env python3
"""统一状态告警服务（系统侧权威）。

替代原先散落在爬虫 pipeline.py 的 _send_status_alert，便于后续替换学校爬虫时
告警逻辑不丢失。失败静默，不依赖 Flask 请求上下文（仅读取 Config 中的
WECOM_STATUS_WEBHOOK 环境变量）。

设计原则（v6.14 爬虫越权收回阶段2）：
- 告警是「系统职责」，不应由可替换的爬虫模块自带。
- 任何异常都被吞掉，绝不影响主流程（落库/爬取/推送）。
"""

import logging

logger = logging.getLogger(__name__)


def send_status_alert(content: str):
    """通过状态 Webhook 发送运维告警（env-only，失败静默）。

    复用后端配置的 WECOM_STATUS_WEBHOOK（Config.get_status_webhooks），
    用于课程数据空结果护栏等运维告警。任何异常都被吞掉，绝不影响主流程。

    Args:
        content: 企微 markdown 格式告警文本。
    """
    try:
        import requests

        from app.core.config import Config

        webhooks = Config.get_status_webhooks()
        if not webhooks:
            return
        for url in webhooks:
            try:
                requests.post(
                    url,
                    json={"msgtype": "markdown", "markdown": {"content": content}},
                    timeout=10,
                )
            except Exception:
                pass
    except Exception:
        pass
