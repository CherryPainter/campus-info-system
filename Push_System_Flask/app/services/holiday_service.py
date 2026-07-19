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

from datetime import date
from typing import Optional, Tuple

from app.core.logger import get_logger
from app.core.database import get_db
from app.model.holiday_period import HolidayPeriod
from app.model.module_config import ModuleConfig

logger = get_logger(__name__)

_HOLIDAY_TYPE_VALUES = ('winter', 'summer', 'custom')


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
