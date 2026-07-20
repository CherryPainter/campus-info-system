#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""假期模式服务

提供「寒暑假假期模式」的核心判断与区间管理：
- is_active()：总开关开启 且 今天命中某 enabled 区间 → (True, period)，否则 (False, None)
- get_status()：供前端横幅展示当前状态
- list/create/update/delete/set_enabled：假期区间 CRUD
- set_master(enabled)：切换总开关（写入 module_configs）

安全原则（fail-open）：任何异常都回退为「不静音」，避免配置读取异常导致永久失声。
"""

from datetime import date, datetime
import os
from typing import Optional, Tuple

from app.core.logger import get_logger
from app.core.database import get_db
from app.core.task_state import TaskStatus
from app.model.holiday_period import HolidayPeriod
from app.model.module_config import ModuleConfig

logger = get_logger(__name__)

_HOLIDAY_TYPE_VALUES = ('winter', 'summer', 'custom')

# 高频静默按天汇总的进程名称（与 skip_if_active record=False 分支配套）
_HOLIDAY_SUMMARY_NAME = '假期高频静默汇总'
# task_type -> 前端友好标签（用于汇总记录的文案）
_TASK_TYPE_LABELS = {
    'weather': '天气',
    'electricity': '电量',
    'course': '课表',
    'spider': '课表爬虫',
    'system': '系统',
}


class HolidayService:
    """假期模式服务（单例）"""

    # ------------------------------------------------------------------
    # 核心判断
    # ------------------------------------------------------------------
    def is_active(self) -> Tuple[bool, Optional[HolidayPeriod]]:
        """当前是否处于假期静默中。

        Returns:
            (True, period) —— 总开关开启且今天命中某启用区间，应当静默
            (False, None)  —— 不静默（开关关 / 无命中 / 异常）
        """
        try:
            from app.services.config_service import get_config_service
            enabled = get_config_service().get('system', 'holiday_mode_enabled', False)
            if not enabled:
                return False, None

            today = date.today()
            session = get_db()
            try:
                period = session.query(HolidayPeriod).filter(
                    HolidayPeriod.enabled.is_(True),
                    HolidayPeriod.start_date <= today,
                    HolidayPeriod.end_date >= today,
                ).first()
                return (period is not None, period)
            finally:
                session.close()
        except Exception as e:
            logger.warning(f'[假期模式] 状态判断异常，回退为不静音: {e}')
            return False, None

    def skip_if_active(self, name: str, task_type: str = 'generic', record: bool = True) -> bool:
        """假期模式静默时，建 skipped 进程记录并跳过；否则返回 False（不跳过）。

        供各定时 job 入口调用：
            if holiday_service.skip_if_active('每日天气晨报', 'weather'):
                return
        - record=True（默认）：创建单条 skipped 进程记录，进程管理可见
          （适合低频面向用户的推送，如每日/每周/每月报告）。
        - record=False：仅静默早退，不打独立记录，而是按天聚合进一条
          「假期高频静默汇总」记录（适合高频缓存刷新类 job，避免刷屏进程表，
          同时保留历史可见性）。
        fail-open：任何异常仍按静音处理（返回 True），避免误发。
        """
        try:
            active, period = self.is_active()
            if not active:
                return False
            reason = f'假期模式静默（{period.name}）' if period else '假期模式静默'
            if record:
                try:
                    from app.api.process_routes import create_task_process, complete_task_process
                    pid = create_task_process(name, task_type, total_items=1)
                    complete_task_process(pid, TaskStatus.SKIPPED, reason)
                except Exception as e:
                    logger.warning(f'[假期模式] 跳过进程记录创建失败（仍静音）: {e}')
            else:
                # 高频 job：按天合并为一条汇总记录，历史可见且不刷屏
                try:
                    self._record_daily_summary(task_type, reason)
                except Exception as e:
                    logger.warning(f'[假期模式] 高频静默汇总记录失败（仍静音）: {e}')
            logger.info(f'[假期模式] {name} 静默跳过')
            return True
        except Exception as e:
            logger.warning(f'[假期模式] 状态判断异常，回退为静音: {e}')
            return True

    def _record_daily_summary(self, task_type: str, reason: str):
        """假期高频静默按天汇总成 1 条 skipped 记录。

        同一天、同一 task_type 的多次高频静默合并为一条记录，累计次数体现在
        total_items 与 message 中；跨天自动新建一条。跨 worker 安全：
        每次先按「今天 + task_type」查重，已存在则累加，不存在则新建。
        """
        from sqlalchemy import func
        from app.model.task_process import TaskProcess

        label = _TASK_TYPE_LABELS.get(task_type, task_type)
        today = date.today()
        session = get_db()
        try:
            existing = session.query(TaskProcess).filter(
                TaskProcess.name == _HOLIDAY_SUMMARY_NAME,
                TaskProcess.task_type == task_type,
                func.date(TaskProcess.started_at) == today.isoformat(),
            ).first()
            if existing:
                existing.total_items += 1
                existing.processed_items = existing.total_items
                existing.message = f'{reason}·{label}高频任务已静音 {existing.total_items} 次'
                existing.completed_at = datetime.now()
                session.commit()
                return
            process = TaskProcess(
                name=_HOLIDAY_SUMMARY_NAME,
                task_type=task_type,
                status=TaskStatus.SKIPPED,
                pid=os.getpid(),
                progress=100,
                total_items=1,
                processed_items=1,
                message=f'{reason}·{label}高频任务已静音 1 次',
                created_by='system',
            )
            process.completed_at = datetime.now()
            session.add(process)
            session.commit()
        finally:
            session.close()

    def get_status(self) -> dict:
        """返回当前假期模式状态，供前端横幅展示。"""
        active, period = self.is_active()
        try:
            from app.services.config_service import get_config_service
            enabled = bool(get_config_service().get('system', 'holiday_mode_enabled', False))
        except Exception:
            enabled = False
        return {
            'enabled': enabled,
            'active': active,
            'period': period.to_dict() if period else None,
            'now': date.today().isoformat(),
        }

    # ------------------------------------------------------------------
    # 区间 CRUD
    # ------------------------------------------------------------------
    def list_periods(self) -> list:
        session = get_db()
        try:
            periods = session.query(HolidayPeriod).order_by(
                HolidayPeriod.start_date.asc()
            ).all()
            return [p.to_dict() for p in periods]
        finally:
            session.close()

    def create_period(self, data: dict) -> HolidayPeriod:
        self._validate(data)
        session = get_db()
        try:
            period = HolidayPeriod(
                name=data['name'].strip(),
                holiday_type=data.get('holiday_type', 'custom'),
                start_date=self._parse_date(data['start_date']),
                end_date=self._parse_date(data['end_date']),
                enabled=bool(data.get('enabled', True)),
                note=(data.get('note') or '').strip() or None,
            )
            session.add(period)
            session.commit()
            session.refresh(period)
            logger.info(f'[假期模式] 新建区间: {period.name} ({period.start_date}~{period.end_date})')
            return period
        finally:
            session.close()

    def update_period(self, period_id: int, data: dict) -> Optional[HolidayPeriod]:
        session = get_db()
        try:
            period = session.query(HolidayPeriod).filter(HolidayPeriod.id == period_id).first()
            if not period:
                return None
            if 'name' in data and data['name'] is not None:
                period.name = data['name'].strip()
            if 'holiday_type' in data and data['holiday_type'] is not None:
                if data['holiday_type'] not in _HOLIDAY_TYPE_VALUES:
                    raise ValueError(f'非法假期类型: {data["holiday_type"]}')
                period.holiday_type = data['holiday_type']
            if 'start_date' in data and data['start_date'] is not None:
                period.start_date = self._parse_date(data['start_date'])
            if 'end_date' in data and data['end_date'] is not None:
                period.end_date = self._parse_date(data['end_date'])
            if 'enabled' in data and data['enabled'] is not None:
                period.enabled = bool(data['enabled'])
            if 'note' in data:
                period.note = (data['note'] or '').strip() or None
            if period.start_date > period.end_date:
                raise ValueError('开始日期不能晚于结束日期')
            session.commit()
            session.refresh(period)
            logger.info(f'[假期模式] 更新区间: {period.name} ({period.start_date}~{period.end_date})')
            return period
        finally:
            session.close()

    def delete_period(self, period_id: int) -> bool:
        session = get_db()
        try:
            period = session.query(HolidayPeriod).filter(HolidayPeriod.id == period_id).first()
            if not period:
                return False
            session.delete(period)
            session.commit()
            logger.info(f'[假期模式] 删除区间: id={period_id} ({period.name})')
            return True
        finally:
            session.close()

    def set_enabled(self, period_id: int, enabled: bool) -> Optional[HolidayPeriod]:
        return self.update_period(period_id, {'enabled': enabled})

    # ------------------------------------------------------------------
    # 总开关
    # ------------------------------------------------------------------
    def set_master(self, enabled: bool) -> bool:
        """切换假期模式总开关，写入 module_configs。"""
        session = get_db()
        try:
            cfg = session.query(ModuleConfig).filter(
                ModuleConfig.module == 'system',
                ModuleConfig.key == 'holiday_mode_enabled',
            ).first()
            if not cfg:
                cfg = ModuleConfig(
                    module='system',
                    key='holiday_mode_enabled',
                    value_type='boolean',
                    description='假期模式总开关',
                )
                session.add(cfg)
            cfg.value = 'true' if enabled else 'false'
            session.commit()
            logger.info(f'[假期模式] 总开关已切换为: {enabled}')
            return True
        finally:
            session.close()

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _validate(data: dict):
        if not data.get('name') or not str(data['name']).strip():
            raise ValueError('假期名称不能为空')
        if not data.get('start_date') or not data.get('end_date'):
            raise ValueError('开始日期与结束日期均必填')
        start = HolidayService._parse_date(data['start_date'])
        end = HolidayService._parse_date(data['end_date'])
        if start > end:
            raise ValueError('开始日期不能晚于结束日期')
        if data.get('holiday_type') and data['holiday_type'] not in _HOLIDAY_TYPE_VALUES:
            raise ValueError(f'非法假期类型: {data["holiday_type"]}')

    @staticmethod
    def _parse_date(value) -> date:
        if isinstance(value, date):
            return value
        from datetime import datetime
        return datetime.strptime(str(value), '%Y-%m-%d').date()


# 全局单例
holiday_service = HolidayService()
