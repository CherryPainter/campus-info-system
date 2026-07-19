# -*- coding: utf-8 -*-
"""
课程手动课保护单元测试（v6.11.2）

验证：data_source='admin' 的手动课在爬虫来源（full/daily）的 create_batch 下
1) 不被覆盖（命中同去重键时跳过、保留人工修正）
2) 不被挤占（同时间槽已被手动课占据时，爬虫不插入第二条造成重复展示）
同时验证正常 upsert（爬虫更新爬虫课、手动来源管理手动课）不受影响。
"""
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.model.course import Course, JSONEncodedList
from app.repository.course_repository import CourseRepository


# Course 模型使用了 MySQL 专有类型（TINYINT / mysql.JSON），SQLite 无法渲染。
# 测试仅在内存库下将其替换为通用类型，不影响生产库（生产用 MySQL）。
import sqlalchemy as _sa
Course.__table__.c.term.type = _sa.Integer()
_orig_load = JSONEncodedList.load_dialect_impl


def _json_load(self, dialect):
    if dialect.name == 'mysql':
        return _orig_load(self, dialect)
    return dialect.type_descriptor(_sa.String())


JSONEncodedList.load_dialect_impl = _json_load


@pytest.fixture
def session():
    engine = create_engine('sqlite:///:memory:')
    Course.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _admin_course(s, **kwargs):
    defaults = dict(
        course_code='ADMIN-1',
        course_name='手动课',
        semester_id=20251, semester_name='2025-2026-1',
        academic_year='2025-2026', term=1,
        week_day=1, period_idx=1, periods=[1],
        teacher='老师', classroom='A101', building='教一',
        start_time='08:00', end_time='08:45',
        weeks=[1, 2, 3], week_number=1,
        data_source='admin',
    )
    defaults.update(kwargs)
    c = Course(**defaults)
    s.add(c)
    s.commit()
    return c


def test_crawler_does_not_overwrite_admin_course(session):
    # 已存在一门手动课（爬虫也会产出相同的去重键）
    _admin_course(session, course_code='CRAWL-11111', course_name='手动英语')
    # 全量爬虫爬到同去重键的课程，应跳过、不覆盖
    created, updated = CourseRepository.create_batch(session, [{
        'course_code': 'CRAWL-11111',
        'course_name': '英语(爬虫)',
        'week_day': 1, 'period_idx': 1, 'periods': [1],
        'teacher': '爬虫老师', 'classroom': 'A101', 'building': '教一',
        'start_time': '08:00', 'end_time': '08:45',
        'weeks': [1, 2, 3], 'week_number': 1,
    }], data_source='full')
    assert created == 0  # 没新建
    kept = session.query(Course).filter(Course.course_code == 'CRAWL-11111').one()
    assert kept.data_source == 'admin'
    assert kept.course_name == '手动英语'  # 人工修正未被覆盖


def test_crawler_does_not_dup_into_admin_slot(session):
    # 手动课占据 (wd=2, pidx=1, wn=1)，但爬虫给的 course_code 不同
    _admin_course(session, course_code='ADMIN-X', course_name='手动课2',
                  week_day=2, period_idx=1, periods=[1])
    created, updated = CourseRepository.create_batch(session, [{
        'course_code': 'CRAWL-99999',
        'course_name': '爬虫撞槽课',
        'week_day': 2, 'period_idx': 1, 'periods': [1],
        'teacher': 't', 'classroom': 'B202', 'building': '教二',
        'start_time': '10:00', 'end_time': '10:45',
        'weeks': [1], 'week_number': 1,
    }], data_source='daily')
    assert created == 0
    # 库里只有那门手动课，没有爬虫插入的第二条
    assert session.query(Course).count() == 1
    assert session.query(Course).one().data_source == 'admin'


def test_crawler_updates_non_admin_course(session):
    # 全量爬虫写入的课，后续爬虫可正常更新（回归：保护不影响正常 upsert）
    created1, updated1 = CourseRepository.create_batch(session, [{
        'course_code': 'CRAWL-55555',
        'course_name': '数学',
        'week_day': 3, 'period_idx': 2, 'periods': [2],
        'teacher': '甲', 'classroom': 'C303', 'building': '教三',
        'start_time': '14:00', 'end_time': '14:45',
        'weeks': [1, 2], 'week_number': 1,
    }], data_source='full')
    assert created1 == 1
    created2, updated2 = CourseRepository.create_batch(session, [{
        'course_code': 'CRAWL-55555',
        'course_name': '数学',
        'week_day': 3, 'period_idx': 2, 'periods': [2],
        'teacher': '乙(更正)', 'classroom': 'C303', 'building': '教三',
        'start_time': '14:00', 'end_time': '14:45',
        'weeks': [1, 2], 'week_number': 1,
    }], data_source='daily')
    assert created2 == 0  # 命中已存在，更新不新建
    upd = session.query(Course).one()
    assert upd.teacher == '乙(更正)'
    assert upd.data_source == 'daily'


def test_admin_source_can_manage_admin(session):
    # 手动来源（admin）调用 create_batch 时不受保护限制，可正常 upsert 手动课
    _admin_course(session, course_code='ADMIN-Y', course_name='课A',
                  week_day=4, period_idx=1, periods=[1])
    created, updated = CourseRepository.create_batch(session, [{
        'course_code': 'ADMIN-Y',
        'course_name': '课A(改)',
        'week_day': 4, 'period_idx': 1, 'periods': [1],
        'teacher': 't', 'classroom': 'D404', 'building': '教四',
        'start_time': '08:00', 'end_time': '08:45',
        'weeks': [1], 'week_number': 1,
    }], data_source='admin')
    assert created == 0  # 命中已存在，更新不新建
    assert session.query(Course).one().course_name == '课A(改)'
