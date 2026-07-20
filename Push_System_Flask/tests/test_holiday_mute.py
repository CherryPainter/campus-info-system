# -*- coding: utf-8 -*-
"""
假期模式静音逻辑单元测试（v6.14.0）

覆盖假期模式「静音闸口」的底层决策逻辑，免去逐个手动验证：
1) HolidayService.is_active() 决策单元
   - 总开关关闭 → (False, None)
   - 开关开 + 今天命中 enabled 区间 → (True, period)
   - 开关开但无命中 / 命中区间被禁用 → (False, None)
   - 配置读取异常 → fail-open 回退 (False, None)（不静音、避免永久失声）
2) HolidayService.skip_if_active() 统一跳过助手
   - 不活跃 → 返回 False，不建记录
   - 活跃 + record=True（面向用户推送）→ 返回 True，建 skipped 进程记录，reason 含假期名
   - 活跃 + record=False（高频数据更新 job）→ 返回 True，按天聚合为 1 条 skipped 汇总记录（历史可见、不刷屏）
   - is_active 抛异常 → fail-open 回退 True（仍静音）
   - 建记录时进程表异常 → 仍静音、不抛出
3) 各定时 job 入口闸口契约
   - 运行时：skip_if_active 返回 True 时，job 在真正工作前早退（不调用 create_task_process）
   - 结构：闸口是每个 gated 函数的首个 if；check_cookie_validity 刻意不静音（系统运维检测）

设计原则：fail-open。任何配置 / DB / 进程写入异常都回退为「不静音」，
但 skip_if_active 在其自身 try 内对 is_active 抛异常与建记录异常均回退为「静音」，
两层 fail-open 方向相反，分别保护「别误静音」与「别误发送」。
"""
import os
import sys
import ast
import inspect

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.model.holiday_period import HolidayPeriod
from app.model.task_process import TaskProcess
from app.services.holiday_service import (
    HolidayService,
    _HOLIDAY_SUMMARY_NAME,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def db_engine():
    """内存 SQLite（StaticPool，保证每次 get_db 拿到同一连接，数据可跨 session 持久）"""
    eng = create_engine(
        'sqlite:///:memory:',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    HolidayPeriod.__table__.create(eng)
    TaskProcess.__table__.create(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine)


@pytest.fixture
def fake_config():
    """配置存储：key 形如 (module, key) -> value。与真实 config_service 的 .get 同形。"""
    return {}


@pytest.fixture
def holiday(monkeypatch, db_engine, session_factory, fake_config):
    """构造一个隔离了 config_service 与 DB 的 HolidayService 实例。"""
    from app.services import config_service as cfg_mod
    from app.services import holiday_service as hs_mod

    class FakeConfigService:
        def get(self, module, key, default=None):
            return fake_config.get((module, key), default)

    # 注意：holiday_service 在模块顶层 `from app.core.database import get_db`，
    # is_active 用的是这个模块级绑定名，必须 patch app.services.holiday_service.get_db，
    # 而非 app.core.database.get_db（否则会落到真实 MySQL）。
    monkeypatch.setattr(cfg_mod, 'get_config_service', lambda: FakeConfigService())
    monkeypatch.setattr(hs_mod, 'get_db', lambda: session_factory())

    svc = HolidayService()
    svc._set_config = lambda v: fake_config.__setitem__(('system', 'holiday_mode_enabled'), v)
    svc._add_period = lambda **kw: _seed_period(session_factory, **kw)
    return svc


def _seed_period(session_factory, name='2026年暑假', holiday_type='summer',
                 start_offset=-5, end_offset=5, enabled=True):
    """插入一个假期区间（默认覆盖今天），返回模型对象。"""
    s = session_factory()
    try:
        today = date.today()
        p = HolidayPeriod(
            name=name,
            holiday_type=holiday_type,
            start_date=today + timedelta(days=start_offset),
            end_date=today + timedelta(days=end_offset),
            enabled=enabled,
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        return p
    finally:
        s.close()


def _process_routes():
    """返回 app.api.process_routes 模块（供 monkeypatch 进程记录函数）。"""
    return __import__('app.api.process_routes', fromlist=['x'])


# ----------------------------------------------------------------------
# 1) is_active 决策单元
# ----------------------------------------------------------------------
class TestHolidayServiceIsActive:

    def test_master_off_blocks_even_with_matching_period(self, holiday):
        holiday._set_config(False)
        holiday._add_period()
        active, period = holiday.is_active()
        assert active is False
        assert period is None

    def test_enabled_and_matching_period_returns_active(self, holiday):
        holiday._set_config(True)
        p = holiday._add_period()
        active, period = holiday.is_active()
        assert active is True
        assert period is not None
        assert period.id == p.id
        assert period.name == '2026年暑假'

    def test_enabled_but_no_matching_period(self, holiday):
        holiday._set_config(True)
        # 区间在未来，今天不命中
        holiday._add_period(start_offset=10, end_offset=20)
        active, period = holiday.is_active()
        assert active is False
        assert period is None

    def test_enabled_but_period_disabled(self, holiday):
        holiday._set_config(True)
        holiday._add_period(enabled=False)
        active, period = holiday.is_active()
        assert active is False
        assert period is None

    def test_fail_open_on_config_exception(self, holiday, monkeypatch):
        """配置读取异常应回退为不静音（fail-open），而非误静音。"""
        from app.services import config_service as cfg_mod

        def boom():
            raise RuntimeError('config db down')

        monkeypatch.setattr(cfg_mod, 'get_config_service', boom)
        holiday._add_period()  # 即便有命中区间，异常也应被捕获
        active, period = holiday.is_active()
        assert active is False
        assert period is None


# ----------------------------------------------------------------------
# 2) skip_if_active 统一跳过助手
# ----------------------------------------------------------------------
class TestHolidayServiceSkipIfActive:

    def test_inactive_returns_false_no_record(self, holiday, monkeypatch):
        holiday._set_config(False)
        calls = []
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process', lambda *a, **k: calls.append(a))
        assert holiday.skip_if_active('每日天气晨报', 'weather') is False
        assert calls == []

    def test_active_record_true_creates_skipped(self, holiday, monkeypatch):
        """面向用户推送：假期激活时建 skipped 进程记录，reason 含假期名。"""
        holiday._set_config(True)
        period = holiday._add_period(name='2026年暑假')
        created = []
        completed = []
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process',
                            lambda name, tt, total_items=1: (created.append((name, tt)) or 1))
        monkeypatch.setattr(pr, 'complete_task_process',
                            lambda pid, status, message=None, error=None: completed.append((pid, status, message)))

        result = holiday.skip_if_active('每日天气晨报', 'weather', record=True)

        assert result is True
        assert created == [('每日天气晨报', 'weather')]
        assert completed, '应写入 skipped 完成记录'
        assert completed[0][1] == 'skipped'
        assert '2026年暑假' in (completed[0][2] or '')

    def test_active_record_false_aggregates_to_summary(self, holiday, monkeypatch, session_factory):
        """高频数据更新 job：假期激活时静默早退、不调 create_task_process，
        而是按天聚合写入 1 条 skipped 汇总进程记录（历史可见、不刷屏）。"""
        holiday._set_config(True)
        holiday._add_period(name='2026年暑假')
        created = []
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process', lambda *a, **k: created.append(a))

        result = holiday.skip_if_active('更新天气预警', 'weather', record=False)

        assert result is True
        # 高频 job 不走 create_task_process，而是直接写汇总记录
        assert created == []
        s = session_factory()
        try:
            rows = s.query(TaskProcess).filter(
                TaskProcess.name == _HOLIDAY_SUMMARY_NAME,
                TaskProcess.task_type == 'weather',
            ).all()
            assert len(rows) == 1
            assert rows[0].status == 'skipped'
            assert '2026年暑假' in (rows[0].message or '')
            assert '已静音 1 次' in (rows[0].message or '')
        finally:
            s.close()

    def test_fail_open_when_is_active_raises(self, holiday, monkeypatch):
        """is_active 抛异常时，skip_if_active 仍回退为静音（返回 True）。"""
        def boom():
            raise RuntimeError('db down')

        monkeypatch.setattr(holiday, 'is_active', boom)
        assert holiday.skip_if_active('每日天气晨报', 'weather') is True

    def test_record_creation_failure_still_silent(self, holiday, monkeypatch):
        """建 skipped 记录时进程表异常，不应抛出，仍按静音处理。"""
        holiday._set_config(True)
        holiday._add_period()
        pr = _process_routes()

        def create_raises(*a, **k):
            raise RuntimeError('process table down')

        monkeypatch.setattr(pr, 'create_task_process', create_raises)

        assert holiday.skip_if_active('每日天气晨报', 'weather', record=True) is True


# ----------------------------------------------------------------------
# 2.5) 高频静默按天汇总（record=False 分支）
# ----------------------------------------------------------------------
class _ShiftedDate(date):
    """测试用可控时钟：today() 返回真实今天 + _offset 天。"""
    _offset = 0

    @classmethod
    def today(cls):
        return date.today() + timedelta(days=cls._offset)


class TestHolidayDailySummary:

    def test_same_day_same_type_increments(self, holiday, monkeypatch, session_factory):
        """同一天、同一 task_type 的多次高频静默合并为 1 条记录，次数累加。"""
        holiday._set_config(True)
        holiday._add_period(name='2026年暑假')
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process', lambda *a, **k: None)

        holiday.skip_if_active('更新实时天气', 'weather', record=False)
        holiday.skip_if_active('更新逐小时预报', 'weather', record=False)
        holiday.skip_if_active('更新天气预警', 'weather', record=False)

        s = session_factory()
        try:
            rows = s.query(TaskProcess).filter(
                TaskProcess.name == _HOLIDAY_SUMMARY_NAME,
                TaskProcess.task_type == 'weather',
            ).all()
            assert len(rows) == 1
            assert rows[0].total_items == 3
            assert '已静音 3 次' in (rows[0].message or '')
        finally:
            s.close()

    def test_different_type_separate_summary(self, holiday, monkeypatch, session_factory):
        """不同 task_type 的高频静默各保留一条独立汇总记录。"""
        holiday._set_config(True)
        holiday._add_period()
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process', lambda *a, **k: None)

        holiday.skip_if_active('更新实时天气', 'weather', record=False)
        holiday.skip_if_active('低电量检测', 'electricity', record=False)

        s = session_factory()
        try:
            assert s.query(TaskProcess).filter_by(
                name=_HOLIDAY_SUMMARY_NAME, task_type='weather').count() == 1
            assert s.query(TaskProcess).filter_by(
                name=_HOLIDAY_SUMMARY_NAME, task_type='electricity').count() == 1
        finally:
            s.close()

    def test_record_true_not_in_summary(self, holiday, monkeypatch, session_factory):
        """面向用户推送（record=True）只建自己的 skipped 记录，不写汇总记录。"""
        holiday._set_config(True)
        holiday._add_period()
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process',
                            lambda *a, **k: 1)
        monkeypatch.setattr(pr, 'complete_task_process', lambda *a, **k: None)

        holiday.skip_if_active('每日天气晨报', 'weather', record=True)

        s = session_factory()
        try:
            assert s.query(TaskProcess).filter_by(
                name=_HOLIDAY_SUMMARY_NAME).count() == 0
        finally:
            s.close()

    def test_cross_day_new_record(self, holiday, monkeypatch, session_factory):
        """跨天后高频静默应新建一条汇总记录（避免把昨天的静默次数累计到今天）。"""
        from app.services import holiday_service as hs_mod

        holiday._set_config(True)
        holiday._add_period()
        pr = _process_routes()
        monkeypatch.setattr(pr, 'create_task_process', lambda *a, **k: None)
        monkeypatch.setattr(hs_mod, 'date', _ShiftedDate)

        _ShiftedDate._offset = 0
        holiday.skip_if_active('更新实时天气', 'weather', record=False)
        _ShiftedDate._offset = 1
        holiday.skip_if_active('更新实时天气', 'weather', record=False)

        s = session_factory()
        try:
            rows = s.query(TaskProcess).filter(
                TaskProcess.name == _HOLIDAY_SUMMARY_NAME,
                TaskProcess.task_type == 'weather',
            ).all()
            assert len(rows) == 2, '跨天应新建汇总记录'
        finally:
            s.close()


# ----------------------------------------------------------------------
# 3) 各定时 job 入口闸口契约
# ----------------------------------------------------------------------
# 10 个已加闸口的定时 job（天气 5 + 电量 5）。check_cookie_validity 刻意不静音，不入此列表。
GATED_JOBS = [
    ('app.modules.weather.tasks', 'update_weather_now'),
    ('app.modules.weather.tasks', 'update_weather_hourly'),
    ('app.modules.weather.tasks', 'update_weather_alert'),
    ('app.modules.weather.tasks', 'push_weather_daily'),
    ('app.modules.weather.tasks', 'push_weather_analysis'),
    ('app.modules.electricity.tasks', 'push_electricity_daily'),
    ('app.modules.electricity.tasks', 'push_electricity_weekly'),
    ('app.modules.electricity.tasks', 'push_electricity_monthly'),
    ('app.modules.electricity.tasks', 'push_electricity_full_crawl'),
    ('app.modules.electricity.tasks', 'check_low_power'),
]


class TestTaskEntryGates:

    @pytest.mark.parametrize('module_path,func_name', GATED_JOBS)
    def test_entry_gate_short_circuits_when_holiday_active(self, monkeypatch, module_path, func_name):
        """假期激活时，job 在真正工作（create_task_process）前早退，不抛错即证明闸口生效。"""
        from app.services.holiday_service import holiday_service as HS

        # 桩：假期激活，任何 SkipIfActive 调用都返回 True（且不建真实 skipped 记录）
        monkeypatch.setattr(HS, 'skip_if_active',
                            lambda name, task_type='generic', record=True: True)

        # 桩：真实工作第一步 create_task_process / complete_task_process 一旦被调用即记录并抛错
        called = []
        pr = _process_routes()

        def _should_not_run(*a, **k):
            called.append((func_name, a, k))
            raise AssertionError(f'假期激活时仍执行了推送/抓取工作: {func_name}')

        monkeypatch.setattr(pr, 'create_task_process', _should_not_run)
        monkeypatch.setattr(pr, 'complete_task_process', _should_not_run)

        mod = __import__(module_path, fromlist=['x'])
        func = getattr(mod, func_name)
        func()  # 若闸口缺失/错位，会触发 _should_not_run 抛错

        assert called == [], f'{func_name} 在假期激活时不应执行任何工作'

    @pytest.mark.parametrize('module_path,func_name', GATED_JOBS)
    def test_gate_is_first_if_in_function(self, module_path, func_name):
        """结构性契约：闸口必须是函数体中的首个 if（保证位于真正工作之前）。"""
        mod = __import__(module_path, fromlist=['x'])
        node = _get_function_ast(mod, func_name)
        first_if = _first_if_in(node)
        assert first_if is not None, f'{func_name} 缺少假期闸口 if'
        assert _contains_skip_if_active(first_if), f'{func_name} 首个 if 不是假期闸口'

    def test_check_cookie_validity_not_gated(self):
        """check_cookie_validity 是系统运维检测，刻意不静音——结构上断言其无假期闸口。"""
        mod = __import__('app.modules.electricity.tasks', fromlist=['x'])
        node = _get_function_ast(mod, 'check_cookie_validity')
        assert _first_if_in(node) is None, 'check_cookie_validity 不应包含假期闸口'
        assert not _contains_skip_if_active(node), 'check_cookie_validity 不应调用 skip_if_active'


# ----------------------------------------------------------------------
# AST 辅助
# ----------------------------------------------------------------------
def _get_function_ast(module_obj, func_name):
    mod_file = inspect.getsourcefile(module_obj)
    with open(mod_file, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    raise AssertionError(f'未找到函数 {func_name}')


def _first_if_in(node):
    for stmt in node.body:
        if isinstance(stmt, ast.If):
            return stmt
    return None


def _contains_skip_if_active(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == 'skip_if_active':
                return True
            if isinstance(f, ast.Name) and f.id == 'skip_if_active':
                return True
    return False
