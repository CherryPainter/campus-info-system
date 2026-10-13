#!/usr/bin/env python3
"""
天气业务服务

职责：
- 天气数据获取与存储业务逻辑
- 天气分析与推送业务逻辑
- 协调 Repository 完成数据操作
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import OperationalError

from app.core.database import get_db
from app.modules.weather.fetcher import WeatherFetcher
from app.repository.weather_repository import WeatherRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# 数据库瞬时错误重试（单点收口）
#
# weather_records 的写者有多个：定时任务（master 进程，实时天气/逐小时预报）
# 与读路径补写（worker 进程 + 后台线程）。多个写者并发做「DELETE 旧行 + INSERT 新行」
# 时会互锁，MySQL 侧表现为 OperationalError：
#   1213 Deadlock found            —— 死锁，InnoDB 毫秒级检测并回滚改动行数少的一方
#   1205 Lock wait timeout         —— 锁等待超时
#   2013 Lost connection           —— 查询中途连接断开
#   2006 MySQL server has gone away —— 连接已被关闭
#   2014 Command Out of Sync       —— 协议乱序（跨进程共用连接的残指纹）
# 这些都是瞬时错误，退避重试即可恢复，不属于业务失败。
# ---------------------------------------------------------------------
_RETRYABLE_MYSQL_CODES = {1213, 1205, 2013, 2006, 2014}
_DB_MAX_ATTEMPTS = 3


def _is_retryable_db_error(exc: Exception) -> bool:
    """判断是否为可重试的 MySQL 瞬时错误（依据 pymysql 错误码）。"""
    if not isinstance(exc, OperationalError):
        return False
    orig = getattr(exc, "orig", None)
    orig_args = getattr(orig, "args", None) or ()
    return bool(orig_args) and orig_args[0] in _RETRYABLE_MYSQL_CODES


def _run_db_op(op):
    """执行一次完整的 DB 操作（op 内部自含 session 生命周期），遇瞬时错误退避重试。

    op 必须是「从 get_db() 到 commit/close」的完整单元，保证每次重试都拿到
    全新的 session 与连接，不会复用已进入错误状态的事务。

    Raises:
        Exception: 重试耗尽或非瞬时错误时原样抛出，由调用方决定降级方式。
    """
    last_exc: Exception | None = None
    for attempt in range(1, _DB_MAX_ATTEMPTS + 1):
        try:
            return op()
        except Exception as exc:
            if attempt >= _DB_MAX_ATTEMPTS or not _is_retryable_db_error(exc):
                raise
            last_exc = exc
            logger.warning(
                f"[WeatherService] 数据库瞬时错误，第 {attempt}/{_DB_MAX_ATTEMPTS} 次重试: {exc}"
            )
            time.sleep(0.5 * attempt)
    raise last_exc  # 理论不可达，防御性兜底


class WeatherService:
    """
    天气业务服务类

    封装所有天气相关的业务逻辑
    """

    def __init__(self, fetcher: WeatherFetcher | None = None) -> None:
        """
        初始化服务

        Args:
            fetcher: 天气数据获取器，为 None 时自动创建
        """
        self._fetcher = fetcher

    def _get_fetcher(self) -> WeatherFetcher:
        """获取或创建 fetcher"""
        if self._fetcher is None:
            from app.modules.weather.tasks import _make_fetcher

            self._fetcher = _make_fetcher()
        return self._fetcher

    def fetch_and_save_now(self, city_name: str = "重庆") -> dict[str, Any] | None:
        """
        获取并保存实时天气

        Args:
            city_name: 城市名称

        Returns:
            Optional[Dict]: 保存的天气数据；上游（和风 API）无数据时返回 None

        Raises:
            Exception: 数据库写入失败时抛出（含重试耗尽），由调用方决定降级方式。
                定时任务调用方据此标记 failed，读路径调用方据此返回旧数据/空，
                不再出现「DB 写失败却返回 None 与『无数据』混淆」的情况。
        """
        fetcher = self._get_fetcher()
        data = fetcher.fetch_now()

        if not data:
            logger.warning("[WeatherService] 获取实时天气失败")
            return None

        city = data.get("city_name", city_name)

        def _op() -> dict[str, Any]:
            session = get_db()
            try:
                # 清理所有旧数据
                deleted = WeatherRepository.delete_all_now_records(
                    session=session,
                    city_name=city,
                )
                logger.debug(f"[WeatherService] 清理 {deleted} 条旧实时天气")

                # 保存新数据
                record = WeatherRepository.create_weather_record(
                    session=session,
                    record_type="now",
                    city_name=city,
                    temp=float(data.get("temp")) if data.get("temp") else None,
                    feels_like=float(data.get("feels_like")) if data.get("feels_like") else None,
                    text=data.get("text"),
                    humidity=int(data.get("humidity")) if data.get("humidity") else None,
                    wind_dir=data.get("wind_dir"),
                    wind_scale=data.get("wind_scale"),
                    pressure=int(data.get("pressure")) if data.get("pressure") else None,
                    vis=float(data.get("vis")) if data.get("vis") else None,
                    cloud=int(data.get("cloud")) if data.get("cloud") else None,
                )
                session.commit()
                logger.info(f"[WeatherService] 实时天气已保存: {record.id}")
                return record.to_dict()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        return _run_db_op(_op)

    def fetch_and_save_hourly(self, city_name: str = "重庆") -> list[dict[str, Any]]:
        """
        获取并保存24小时预报

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 保存的天气数据列表；上游（和风 API）无数据时返回空列表

        Raises:
            Exception: 数据库写入失败时抛出（含重试耗尽），由调用方决定降级方式。
        """
        fetcher = self._get_fetcher()
        data_list = fetcher.fetch_hourly()

        if not data_list:
            logger.warning("[WeatherService] 获取24h预报失败")
            return []

        def _op() -> list[dict[str, Any]]:
            session = get_db()
            try:
                # 清理所有旧数据
                deleted = WeatherRepository.delete_all_hourly_records(
                    session=session,
                    city_name=city_name,
                )
                logger.debug(f"[WeatherService] 清理 {deleted} 条旧预报")

                # 保存新数据
                saved = []
                for data in data_list:
                    fx_time = None
                    if data.get("time"):
                        try:
                            fx_time = datetime.fromisoformat(data["time"].replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass

                    record = WeatherRepository.create_weather_record(
                        session=session,
                        record_type="hourly",
                        city_name=city_name,
                        temp=float(data.get("temp")) if data.get("temp") else None,
                        text=data.get("text"),
                        humidity=int(data.get("humidity")) if data.get("humidity") else None,
                        wind_dir=data.get("wind_dir"),
                        wind_scale=data.get("wind_scale"),
                        precip=float(data.get("precip")) if data.get("precip") else None,
                        pop=int(data.get("pop")) if data.get("pop") else None,
                        fx_time=fx_time,
                    )
                    saved.append(record.to_dict())

                session.commit()
                logger.info(f"[WeatherService] 24h预报已保存: {len(saved)} 条")
                return saved

            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        return _run_db_op(_op)

    def get_now_weather(self, city_name: str = "重庆") -> dict[str, Any] | None:
        """
        获取最新实时天气（优先从数据库读取）

        Args:
            city_name: 城市名称

        Returns:
            Optional[Dict]: 天气数据或 None
        """
        session = get_db()
        try:
            record = WeatherRepository.get_latest_now_record(session, city_name)
            if record:
                # 检查数据是否过期（超过30分钟）
                # 注意：created_at 由 datetime.now()（本地时间）写入，必须同口径比较；
                # 早期误用 utcnow 与之比较，相差约 8 小时导致「数据永不过期」，
                # 定时任务写库失败时读路径也不会补写（2026-10-13 修复）
                if record.created_at and datetime.now() - record.created_at < timedelta(
                    minutes=30
                ):
                    return record.to_dict()
                else:
                    # 数据已过期，先返回旧数据，然后异步刷新
                    old_data = record.to_dict()
                    # 在后台线程中刷新数据，不阻塞当前请求
                    import threading

                    def _bg_refresh() -> None:
                        # 后台刷新失败不能让异常逃出线程（否则 traceback 直接刷 gunicorn 日志）
                        try:
                            self.fetch_and_save_now(city_name)
                        except Exception as exc:
                            logger.warning(f"[WeatherService] 后台刷新实时天气失败: {exc}")

                    thread = threading.Thread(target=_bg_refresh, daemon=True)
                    thread.start()
                    logger.info("[WeatherService] 实时天气数据已过期，返回旧数据并在后台刷新")
                    return old_data

            # 数据库无数据，重新获取；刷新失败时降级返回 None（读路径不 500）
            try:
                return self.fetch_and_save_now(city_name)
            except Exception as exc:
                logger.warning(f"[WeatherService] 读取时刷新实时天气失败，降级返回空: {exc}")
                return None
        finally:
            session.close()

    def get_hourly_forecast(self, city_name: str = "重庆") -> list[dict[str, Any]]:
        """
        获取24小时预报（优先从数据库读取）

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 预报数据列表
        """
        session = get_db()
        try:
            records = WeatherRepository.get_hourly_records(session, city_name, limit=24)
            if records:
                # 检查数据是否过期（超过60分钟）
                latest_record = max(records, key=lambda r: r.created_at)
                # 跨天判定：缓存数据是「昨天或更早」写入的，说明还停留在跨零点之前的旧批次，
                # 必须刷新（否则 00:05 仍返回「昨天→今天00:00」的倒序脏数据）
                latest_date = (latest_record.created_at or datetime.min).date()
                # created_at 以本地时间写入，过期判定必须同口径用 datetime.now()（勿改回 utcnow）
                is_stale = (
                    latest_record.created_at is None
                    or datetime.now() - latest_record.created_at >= timedelta(minutes=60)
                )
                is_cross_day = latest_date < datetime.now().date()
                if is_stale or is_cross_day:
                    # 过期或跨天：同步刷新（跨天时刻必须拿到「今天」的数据，不能返回旧批次）
                    logger.info(
                        "[WeatherService] 24h预报%s，同步刷新",
                        "已过期" if is_stale else "跨天需更新",
                    )
                    try:
                        hourly = self.fetch_and_save_hourly(city_name)
                    except Exception as exc:
                        # 刷新失败降级返回旧数据（旧数据好过空列表）
                        logger.warning(f"[WeatherService] 读取时刷新24h预报失败，降级返回旧数据: {exc}")
                        hourly = [r.to_dict() for r in records]
                else:
                    hourly = [r.to_dict() for r in records]
            else:
                # 数据库无数据，重新获取；刷新失败时降级返回空列表（读路径不 500）
                try:
                    hourly = self.fetch_and_save_hourly(city_name)
                except Exception as exc:
                    logger.warning(f"[WeatherService] 读取时刷新24h预报失败，降级返回空列表: {exc}")
                    hourly = []
        finally:
            session.close()

        # 以实时为主：把折线里「当前小时」那条记录的温度覆盖为实况温度（仅改返回，不落库）
        return self._overlay_realtime_temp(hourly, city_name)

    def _overlay_realtime_temp(
        self, hourly: list[dict[str, Any]], city_name: str = "重庆"
    ) -> list[dict[str, Any]]:
        """将 24h 折线中「当前小时」那条记录的温度覆盖为实况温度（实时为主）。

        仅修改返回给前端的数据，不写入数据库，避免污染历史 hourly 记录。
        """
        try:
            now_weather = self.get_now_weather(city_name)
            if not now_weather or now_weather.get("temp") is None:
                return hourly
            live_temp = now_weather["temp"]
            now = datetime.now()
            # 找时间最接近当前时刻的那条 hourly 记录
            target_idx = -1
            min_diff: float | None = None
            for i, item in enumerate(hourly):
                t = item.get("time") or item.get("fx_time")
                if not t:
                    continue
                try:
                    ts = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                    if ts.tzinfo is not None:
                        ts = ts.replace(tzinfo=None)
                except (ValueError, TypeError):
                    continue
                diff = abs((ts - now).total_seconds())
                if min_diff is None or diff < min_diff:
                    min_diff = diff
                    target_idx = i
            if target_idx >= 0:
                hourly[target_idx] = {**hourly[target_idx], "temp": live_temp}
                logger.info(
                    "[WeatherService] 24h折线当前小时温度已覆盖为实况: idx=%s temp=%s",
                    target_idx,
                    live_temp,
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[WeatherService] 覆盖当前小时温度失败: {e}")
        return hourly

    def fetch_and_save_alerts(self, city_name: str = "重庆") -> list[dict[str, Any]]:
        """
        获取并保存天气预警

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 保存的预警数据列表
        """
        try:
            fetcher = self._get_fetcher()
            alerts = fetcher.fetch_alert()

            if not alerts:
                return []

            session = get_db()
            try:
                saved = []
                for alert in alerts:
                    alert_id = alert.get("id")
                    if not alert_id:
                        continue

                    # 检查是否已存在
                    if WeatherRepository.alert_exists(session, alert_id):
                        continue

                    record = WeatherRepository.create_alert(
                        session=session,
                        alert_id=alert_id,
                        city_name=city_name,
                        headline=alert.get("headline", ""),
                        event_type=alert.get("event_type", ""),
                        severity=alert.get("severity", ""),
                        color_code=alert.get("color_code", ""),
                        description=alert.get("description"),
                    )
                    saved.append(record.to_dict())

                session.commit()
                logger.info(f"[WeatherService] 新增预警: {len(saved)} 条")
                return saved

            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        except Exception as e:
            logger.error(f"[WeatherService] 获取并保存预警失败: {e}")
            return []

    def get_active_alerts(self, city_name: str = "重庆") -> list[dict[str, Any]]:
        """
        获取生效中的预警

        Args:
            city_name: 城市名称

        Returns:
            List[Dict]: 预警数据列表
        """
        session = get_db()
        try:
            records = WeatherRepository.get_active_alerts(session, city_name)
            return [r.to_dict() for r in records]
        finally:
            session.close()


# 模块级单例：供路由与任务模块直接引用，避免每次调用重复实例化
weather_service = WeatherService()
