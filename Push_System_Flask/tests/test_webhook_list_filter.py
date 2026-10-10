"""
Webhook 列表筛选回归测试（keyword / module / scope）

背景（2026-10-10）：管理端 Webhook 列表原只支持 enabled_only，没有关键字与
模块/范围筛选，千条名单下找不到目标。本次在模型层 get_all_webhooks /
get_enabled_webhooks 增加 keyword（名称/URL 模糊）、module、scope 三个过滤，
路由透传；前端加防抖搜索 + 模块/范围下拉。

覆盖：
- keyword 同时匹配 name 与 url；module 按 modules 逗号串包含匹配；scope 精确匹配。
- 组合筛选（keyword + scope）取交集。
- 反向：构造一条 name/url 都不含关键字的记录，断言被过滤掉。

运行：
    cd Push_System_Flask && python -m pytest tests/test_webhook_list_filter.py -v
"""

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.model.webhook import Webhook


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Webhook.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _seed(session):
    rows = [
        Webhook(name="班级群", url="https://qyapi.weixin.qq.com/send?key=aaa",
                modules="course,weather", scope="global", is_enabled=True),
        Webhook(name="电量告警群", url="https://qyapi.weixin.qq.com/send?key=bbb",
                modules="electricity", scope="dorm", is_enabled=True,
                scope_target=["31栋512"]),
        Webhook(name="张三专属", url="https://qyapi.weixin.qq.com/send?key=ccc",
                modules="all", scope="student", is_enabled=False,
                scope_target=[3]),
        Webhook(name="系统告警", url="https://qyapi.weixin.qq.com/send?key=ddd",
                modules="system", scope="global", is_enabled=True),
    ]
    for r in rows:
        session.add(r)
    session.commit()


def _names(result):
    return {w.name for w in result}


def test_keyword_matches_name(session):
    _seed(session)
    items, _ = Webhook.get_all_webhooks(session, keyword="电量", page=1, page_size=20)
    assert _names(items) == {"电量告警群"}


def test_keyword_matches_url(session):
    _seed(session)
    items, _ = Webhook.get_all_webhooks(session, keyword="key=ccc", page=1, page_size=20)
    assert _names(items) == {"张三专属"}


def test_module_filter(session):
    _seed(session)
    items, _ = Webhook.get_all_webhooks(session, module="electricity", page=1, page_size=20)
    assert _names(items) == {"电量告警群"}


def test_scope_filter(session):
    _seed(session)
    items, _ = Webhook.get_all_webhooks(session, scope="student", page=1, page_size=20)
    assert _names(items) == {"张三专属"}


def test_combined_keyword_and_scope(session):
    _seed(session)
    # keyword="群" 命中 name 含「群」的 {班级群, 电量告警群}；
    # scope="global" 命中 {班级群, 系统告警}；二者取交集应为 {班级群}
    # （"电量告警群" 的 scope 是 dorm；"系统告警" 的 name 不含「群」）。
    items, _ = Webhook.get_all_webhooks(
        session, keyword="群", scope="global", page=1, page_size=20
    )
    assert _names(items) == {"班级群"}, "keyword 与 scope 应取交集"


def test_enabled_only_with_filters(session):
    _seed(session)
    # 张三专属 是禁用，keyword=专属 + enabled_only 应排除它
    items, _ = Webhook.get_enabled_webhooks(
        session, keyword="专属", page=1, page_size=20
    )
    assert items == [], "禁用的应被 enabled_only 过滤掉"


def test_keyword_excludes_non_match(session):
    _seed(session)
    items, _ = Webhook.get_all_webhooks(session, keyword="不存在的关键字xyz", page=1, page_size=20)
    assert items == [], "反向验证：无关关键字必须过滤为空"
