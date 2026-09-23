"""
课程手动课保护单元测试

契约（v6.19.x，与 app/repository/course_repository.create_batch 保持一致）：
课程稳定身份 = course_key = md5(课程名|星期|排序节次|教室|教师)，**与周次无关**；
批次去重只按 (semester_id, course_key)（course_key 为 NULL 的老行按同一身份兜底补 key）。

手动课保护：爬虫来源（full/daily）下，爬虫行的 course_key 命中 data_source='admin'
行 → 整条跳过（既不覆盖也不新建）。

注意（相对 v6.11.2 旧契约的变化）：
- 去重键不再含 course_code（爬虫侧常缺失/由 generate_course_code 生成，不稳定）；
- 旧「同时间槽 (week_day, period_idx, week_number) 被手动课占据则不插入」保护已废弃
  —— week_number 是爬取周、随每次爬取漂移，该判据不可靠。因此 course_key 不同的课
  即便落在手动课同槽位，也会正常新建；漂移产生的旧行由全量重爬 reconcile 对账软删收敛。
- 改名/改教师/改教室会改变 course_key，视作另一门课（预期行为）。
- v6.20.1 补充：**某次爬取缺教师**（教务源返回空教师，daily 常见）不视作「另一门课」——
  会先按弱身份（课名/星期/节次/教室，不含教师）从库中回填已知教师，故仍命中既有行
  upsert，既不新增重复行，手动课保护也不因此失效（见 test_missing_teacher_* 用例）。
"""

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Course 模型使用了 MySQL 专有类型（TINYINT / mysql.JSON），SQLite 无法渲染。
# 测试仅在内存库下将其替换为通用类型，不影响生产库（生产用 MySQL）。
import sqlalchemy as _sa

from app.model.course import Course, JSONEncodedList
from app.repository.course_repository import CourseRepository

Course.__table__.c.term.type = _sa.Integer()
_orig_load = JSONEncodedList.load_dialect_impl


def _json_load(self, dialect):
    if dialect.name == "mysql":
        return _orig_load(self, dialect)
    return dialect.type_descriptor(_sa.String())


JSONEncodedList.load_dialect_impl = _json_load


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Course.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _admin_course(s, **kwargs):
    """构造一门手动课。默认身份 = 手动课|周一|第1节|A101|老师"""
    defaults = {
        "course_code": "ADMIN-1",
        "course_name": "手动课",
        "semester_id": 20251,
        "semester_name": "2025-2026-1",
        "academic_year": "2025-2026",
        "term": 1,
        "week_day": 1,
        "period_idx": 1,
        "periods": [1],
        "teacher": "老师",
        "classroom": "A101",
        "building": "教一",
        "start_time": "08:00",
        "end_time": "08:45",
        "weeks": [1, 2, 3],
        "week_number": 1,
        "data_source": "admin",
    }
    defaults.update(kwargs)
    c = Course(**defaults)
    s.add(c)
    s.commit()
    return c


def test_crawler_does_not_overwrite_admin_course(session):
    # 手动课身份：手动英语 / 周一 / 第1节 / A101 / 老师
    _admin_course(session, course_code="ADMIN-11111", course_name="手动英语")
    # 爬虫爬到同一 course_key（课名/星期/节次/教室/教师全同）→ 整条跳过
    created, updated = CourseRepository.create_batch(
        session,
        [
            {
                "course_code": "CRAWL-11111",  # course_code 不参与身份，不同也无妨
                "semester_id": 20251,  # 必须与手动课同学期，保护/匹配才按该学期生效
                "course_name": "手动英语",
                "week_day": 1,
                "period_idx": 1,
                "periods": [1],
                "teacher": "老师",
                "classroom": "A101",
                "building": "教一",
                "start_time": "08:00",
                "end_time": "08:45",
                "weeks": [1, 2, 3, 4, 5],  # 周次不同也不得覆盖手动课
                "week_number": 2,
            }
        ],
        data_source="full",
    )
    assert created == 0  # 没新建
    assert updated == 0  # 被保护整条跳过，连更新也没有
    assert session.query(Course).count() == 1
    kept = session.query(Course).one()
    assert kept.data_source == "admin"
    assert kept.course_name == "手动英语"  # 人工修正未被覆盖
    assert kept.weeks == [1, 2, 3]  # 周次未被爬虫改写


def test_crawler_inserts_when_key_differs_in_admin_slot(session):
    """v6.19.x 契约：同槽位不再拦截——course_key 不同的爬虫课正常新建。

    旧契约「同 (week_day, period_idx, week_number) 槽位被手动课占据则不插入」已废弃
    （判据含随爬取漂移的 week_number，不可靠）。这里明确固化新行为：身份不同即新建，
    手动课本身不被触碰。
    """
    _admin_course(
        session, course_code="ADMIN-X", course_name="手动课2", week_day=2, period_idx=1, periods=[1]
    )
    created, updated = CourseRepository.create_batch(
        session,
        [
            {
                "course_code": "CRAWL-99999",
                "semester_id": 20251,
                "course_name": "爬虫课A",  # course_key 与手动课不同
                "week_day": 2,
                "period_idx": 1,
                "periods": [1],
                "teacher": "t",
                "classroom": "B202",
                "building": "教二",
                "start_time": "10:00",
                "end_time": "10:45",
                "weeks": [1],
                "week_number": 1,
            }
        ],
        data_source="daily",
    )
    assert created == 1  # 身份不同 → 新建（不再因同槽位被拦截）
    assert session.query(Course).count() == 2
    # 手动课原样保留、未被覆盖
    admin_row = session.query(Course).filter(Course.data_source == "admin").one()
    assert admin_row.course_name == "手动课2"


def test_crawler_updates_non_admin_course(session):
    # 同一 course_key（课名/星期/节次/教室/教师都不变）再次爬取 → 更新既有行（回归：保护不影响正常 upsert）
    first = {
        "course_code": "CRAWL-55555",
        "semester_id": 20251,
        "course_name": "数学",
        "week_day": 3,
        "period_idx": 2,
        "periods": [2],
        "teacher": "甲",
        "classroom": "C303",
        "building": "教三",
        "start_time": "14:00",
        "end_time": "14:45",
        "weeks": [1, 2],
        "week_number": 1,
    }
    created1, updated1 = CourseRepository.create_batch(session, [dict(first)], data_source="full")
    assert created1 == 1
    assert updated1 == 0

    # 只改「非身份字段」：course_code / building / weeks 均不参与 course_key
    second = {
        **first,
        "course_code": "CRAWL-55555B",
        "building": "教三-新",
        "weeks": [1, 2, 3, 4],
        "week_number": 2,
    }
    created2, updated2 = CourseRepository.create_batch(session, [second], data_source="daily")
    assert created2 == 0  # 命中既有 course_key，不新建
    assert updated2 == 1
    upd = session.query(Course).one()
    assert upd.weeks == [1, 2, 3, 4]
    assert upd.building == "教三-新"
    assert upd.data_source == "daily"


def test_admin_source_can_manage_admin(session):
    # 手动来源（admin）不受爬虫保护限制，按 course_key 正常 upsert 自己的手动课
    _admin_course(
        session, course_code="ADMIN-Y", course_name="课A", week_day=4, period_idx=1, periods=[1]
    )
    created, updated = CourseRepository.create_batch(
        session,
        [
            {
                "course_code": "ADMIN-Y",
                "semester_id": 20251,
                "course_name": "课A",  # 身份字段（名/星期/节次/教室/教师）保持不变
                "week_day": 4,
                "period_idx": 1,
                "periods": [1],
                "teacher": "老师",
                "classroom": "A101",
                "building": "教四",  # 非身份字段 → 会被更新
                "start_time": "08:00",
                "end_time": "08:45",
                "weeks": [1, 2],
                "week_number": 1,
            }
        ],
        data_source="admin",
    )
    assert created == 0  # 命中已存在，更新不新建
    assert updated == 1
    row = session.query(Course).one()
    assert row.building == "教四"
    assert row.weeks == [1, 2]


def test_missing_teacher_does_not_duplicate(session):
    """v6.20.1 契约：某次爬取缺教师时，不因 course_key 漂移而重复插入。

    场景：full 爬取入库「英语 / 周三 / 第1-2节 / C303 / 甲」；随后 daily 爬取同一门课，
    但教务源返回空教师。旧行为：空教师算出「无教师版」course_key，匹配不到既有行，
    于是新增一条重复记录（既不纠错，反增冗余——正是「越同步越乱」的根因之一）。
    新行为：按弱身份（课名/星期/节次/教室，不含教师）回填已知教师「甲」，
    命中既有行 upsert，不新增，且不覆盖既有非空教师。
    """
    base = {
        "course_code": "CRAWL-77777",
        "semester_id": 20251,
        "course_name": "英语",
        "week_day": 3,
        "period_idx": 1,
        "periods": [1, 2],
        "teacher": "甲",
        "classroom": "C303",
        "building": "教三",
        "start_time": "08:00",
        "end_time": "09:40",
        "weeks": [1, 2, 3, 4],
        "week_number": 1,
    }
    created1, _ = CourseRepository.create_batch(session, [dict(base)], data_source="full")
    assert created1 == 1

    # daily 缺教师：期望命中既有行（不新增），纠错 weeks，既有教师不被清空
    no_teacher = {**base, "teacher": "", "weeks": [1, 2, 3, 4, 5], "week_number": 5}
    created2, updated2 = CourseRepository.create_batch(session, [no_teacher], data_source="daily")
    assert created2 == 0  # 回填教师后 key 命中既有行 → 不新增
    assert updated2 == 1
    assert session.query(Course).count() == 1
    row = session.query(Course).one()
    assert row.teacher == "甲"  # 既有非空教师未被空值覆盖
    assert row.weeks == [1, 2, 3, 4, 5]  # 周次被纠正（每日纠错生效）
    assert row.data_source == "daily"


def test_missing_teacher_still_protects_admin_course(session):
    """v6.20.1：daily 缺教师时，手动课保护依然生效。

    管理员课身份「手动课T / 周五 / 第1节 / A101 / 老师」；爬虫行字段全同但教师为空。
    回填教师后 course_key 命中 admin 行 → 仍整条跳过，不覆盖人工课。
    （若不做回填，空教师 key 与 admin key 不同，保护会失效——本用例固化该回归。）
    """
    _admin_course(
        session, course_code="ADMIN-T", course_name="手动课T", week_day=5, period_idx=1, periods=[1]
    )
    created, updated = CourseRepository.create_batch(
        session,
        [
            {
                "course_code": "CRAWL-T",
                "semester_id": 20251,
                "course_name": "手动课T",
                "week_day": 5,
                "period_idx": 1,
                "periods": [1],
                "teacher": "",  # 缺教师
                "classroom": "A101",
                "building": "教一",
                "start_time": "08:00",
                "end_time": "08:45",
                "weeks": [1, 2, 3, 4, 5],
                "week_number": 2,
            }
        ],
        data_source="daily",
    )
    assert created == 0
    assert updated == 0  # 被保护整条跳过
    assert session.query(Course).count() == 1
    row = session.query(Course).one()
    assert row.data_source == "admin"
    assert row.weeks == [1, 2, 3]  # 人工课周次未被爬虫改写
