#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电量监控 API 路由
提供电量数据查询、手动触发推送、Cookie 更新等接口

职责：
- 仅处理 HTTP 请求/响应
- 业务逻辑委托给 Service 层
- 数据访问委托给 Repository 层

认证方式：统一使用 JWT Bearer Token
- @jwt_required: 需要登录即可访问（查询数据、触发任务）
- @admin_required: 需要管理员权限（模块状态、Cookie 更新、配置管理）
- 无装饰器: 公开端点（健康检查）
"""

import threading
from flask import Blueprint, request, jsonify, current_app, g
from app.core.api_response import api_success, api_error, api_paginate

from app.utils.auth_middleware import jwt_required, admin_required
from app.core.logger import get_logger

logger = get_logger(__name__)

electricity_bp = Blueprint('electricity', __name__)


@electricity_bp.route('/health')
def health():
    """电量模块健康检查（无需认证）"""
    import time
    return api_success(status='healthy', module='electricity', timestamp=int(time.time()))


@electricity_bp.route('/status')
@admin_required
def status():
    """电量模块状态（需管理员权限）"""
    from app.services.electricity_service import electricity_service

    svc = electricity_service
    remaining = svc.get_remaining_power()
    records = svc.get_usage_records(days=1, limit=1)

    return api_success(module='electricity', cookie_configured=bool(current_app.config.get('ELECTRICITY_CRAWLER_COOKIE')), data={'records_exists': len(records) > 0, 'remaining_exists': remaining is not None}, config={'low_power_threshold': current_app.config.get('ELECTRICITY_LOW_POWER_THRESHOLD', 10.0), 'daily_push_time': current_app.config.get('ELECTRICITY_SCHEDULE_DAILY', '00:30'), 'weekly_push_day': current_app.config.get('ELECTRICITY_SCHEDULE_WEEKLY_DAY', 'mon')})


@electricity_bp.route('/remaining')
@jwt_required
def get_remaining():
    """
    获取最新剩余电量（从数据库读取）

    返回数据包含：
    - remaining: 剩余电量（度）
    - total_capacity: 总量（度）
    - percentage: 百分比（0-100）
    - is_low_power: 是否低电量
    """
    from app.services.electricity_service import electricity_service

    svc = electricity_service
    data = svc.get_remaining_power()
    if data is None:
        return api_success(data=None, message='暂无数据，请先触发数据采集')

    # 格式化返回数据，便于前端使用
    response_data = {
        'default': data.get('remaining', 0),
        'total_capacity': data.get('total_capacity', 100.0),
        'percentage': data.get('percentage', 0.0),
        'is_low_power': data.get('is_low_power', False),
        'recorded_at': data.get('recorded_at'),
    }
    return api_success(data=response_data)


@electricity_bp.route('/records')
@jwt_required
def get_records():
    """获取用电记录（从数据库读取）

    展示全部记录列表，不做时间窗口过滤，仅按 limit 返回最新记录，
    避免入库本地时间与 UTC 上界错配导致最近记录被截断。
    """
    from app.services.electricity_service import electricity_service

    svc = electricity_service
    records = svc.get_usage_records(days=None, limit=1000)
    return api_success(data=records)


@electricity_bp.route('/statistics')
@jwt_required
def get_statistics():
    """
    获取用电统计数据（按日聚合 + 按电表聚合）

    查询参数：
    - range_type: 时间范围类型 (week-本周, last_week-上周, month-本月, last_month-上月, custom-自定义)
    - start_date: 自定义开始日期 (YYYY-MM-DD)，range_type=custom 时必填
    - end_date: 自定义结束日期 (YYYY-MM-DD)，range_type=custom 时必填
    """
    from app.services.electricity_service import electricity_service
    from datetime import datetime, timedelta

    # 获取查询参数
    range_type = request.args.get('range_type', 'month')  # 默认本月
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    # 计算日期范围（使用本地时间，中国时区 UTC+8）
    now = datetime.utcnow()
    # UTC+8 转换：本地时间 = UTC时间 + 8小时
    local_now = now + timedelta(hours=8)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

    if range_type == 'week':
        # 本周（周一到今天）
        weekday = today.weekday()  # 0=周一, 6=周日
        start_time = today - timedelta(days=weekday)
        end_time = today + timedelta(days=1)
    elif range_type == 'last_week':
        # 上周（上周一到上周日）
        weekday = today.weekday()
        end_time = today - timedelta(days=weekday)  # 本周一
        start_time = end_time - timedelta(days=7)   # 上周一
        end_time = end_time  # 本周一作为结束（不包含）
    elif range_type == 'month':
        # 本月（1号到今天）
        start_time = today.replace(day=1)
        end_time = today + timedelta(days=1)
    elif range_type == 'last_month':
        # 上月（1号到月底）
        end_time = today.replace(day=1)  # 本月1号
        last_month_end = end_time - timedelta(days=1)  # 上月最后一天
        start_time = last_month_end.replace(day=1)  # 上月1号
        end_time = end_time  # 本月1号作为结束
    elif range_type == 'custom' and start_date_str and end_date_str:
        # 自定义日期范围
        try:
            start_time = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_time = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            return api_error(message='日期格式错误，请使用 YYYY-MM-DD', http_status=400)
    else:
        # 默认本月
        start_time = today.replace(day=1)
        end_time = today + timedelta(days=1)

    # 将本地时间转换回UTC时间用于数据库查询
    start_time_utc = start_time - timedelta(hours=8)
    end_time_utc = end_time - timedelta(hours=8)

    svc = electricity_service
    stats = svc.get_statistics_by_range(start_time_utc, end_time_utc, start_time, end_time)

    # 过滤测试电表数据
    by_meter = [m for m in stats.get('by_meter', []) if '测试' not in m.get('meter', '')]

    # 补充前端需要的 summary 字段
    daily = stats.get('daily', [])
    total_usage = sum(m.get('usage', 0) for m in by_meter)

    summary = {
        'total_records': sum(d.get('count', 0) for d in daily),
        'total_usage': round(total_usage, 2),
        'avg_daily': round(total_usage / max(len(daily), 1), 2),
        'max_daily': round(max((d.get('usage', 0) for d in daily), default=0), 2),
        'min_daily': round(min((d.get('usage', 0) for d in daily), default=0), 2),
        'meter_count': len(by_meter),
    }

    return api_success(data={'daily': daily, 'by_meter': by_meter, 'summary': summary, 'range': {'type': range_type, 'start_date': start_time.strftime('%Y-%m-%d'), 'end_date': (end_time - timedelta(days=1)).strftime('%Y-%m-%d')}})


@electricity_bp.route('/update_cookie', methods=['POST'])
@admin_required
def update_cookie():
    """
    更新电量爬虫 Cookie（需管理员权限）

    Body JSON: {"cookie": "JSESSIONID=xxx; leech_k=xxx"}
    """
    data = request.get_json(silent=True) or {}
    new_cookie = data.get('cookie', '').strip()

    if not new_cookie:
        return api_error(message='请提供 cookie 字段', http_status=400)

    if len(new_cookie) < 10 or len(new_cookie) > 4096:
        return api_error(message='Cookie 长度不合法', http_status=400)

    import re
    if re.search(r'[\'\"<>;]', new_cookie):
        return api_error(message='Cookie 包含非法字符', http_status=400)

    try:
        from app.modules.electricity.tasks import update_cookie_in_memory
        success = update_cookie_in_memory(new_cookie)
        if success:
            user = g.get('current_user', {})
            logger.info(f'[电量] {user.get("username")} 更新了 Cookie')
            return api_success(message='Cookie 已更新，爬虫将立即使用新 Cookie')
        return api_error(message='Cookie 更新失败', http_status=500)
    except Exception as exc:
        logger.error(f'[电量] update_cookie 接口异常: {exc}')
        return api_error(message='服务器异常', http_status=500)


@electricity_bp.route('/trigger/daily', methods=['POST'])
@admin_required
def trigger_daily():
    """手动触发每日用电报告推送（仅管理员）"""
    return _trigger_task('push_electricity_daily', '每日用电报告')


@electricity_bp.route('/trigger/weekly', methods=['POST'])
@admin_required
def trigger_weekly():
    """手动触发每周用电报告推送（仅管理员）"""
    return _trigger_task('push_electricity_weekly', '每周用电报告')


@electricity_bp.route('/trigger/monthly', methods=['POST'])
@admin_required
def trigger_monthly():
    """手动触发每月用电报告推送（仅管理员）"""
    return _trigger_task('push_electricity_monthly', '每月用电报告')


@electricity_bp.route('/trigger/cookie_check', methods=['POST'])
@admin_required
def trigger_cookie_check():
    """手动触发 Cookie 有效性检测（仅管理员）"""
    return _trigger_task('check_cookie_validity', 'Cookie 检测')


@electricity_bp.route('/trigger/fetch_all', methods=['POST'])
@admin_required
def trigger_fetch_all():
    """
    手动触发全量爬取（需管理员权限）
    
    忽略首次/非首次判断，强制全量爬取所有历史数据。
    适用场景：数据丢失后重新采集、更换电表后重新导入等。
    """
    try:
        from app.modules.electricity.tasks import _fetch_and_save
        from app.modules.electricity.crawler import ElectricityCrawler
        from app.core.config import Config
        from app.api.process_routes import create_task_process

        # 创建任务进程记录
        pid = create_task_process('电量全量爬取', 'electricity', total_items=1)
        
        # 创建爬虫，强制全量爬取
        crawler = ElectricityCrawler(
            base_url=getattr(Config, 'ELECTRICITY_CRAWLER_BASE_URL', 'http://dk.cqie.cn'),
            cookie=getattr(Config, 'ELECTRICITY_CRAWLER_COOKIE', ''),
            max_pages=getattr(Config, 'ELECTRICITY_CRAWLER_MAX_PAGES', 50),
        )

        def _do_fetch_all():
            from app.api.process_routes import complete_task_process
            
            # 爬取数据
            try:
                remaining = crawler.fetch_remaining_power()
                records = crawler.fetch_usage_records(max_pages=50)  # 全量爬取，最多50页
            except Exception as crawl_exc:
                logger.error(f'[电量] 爬取数据失败: {crawl_exc}')
                complete_task_process(pid, 'failed', error=str(crawl_exc))
                return

            # 保存到数据库
            from app.core.database import get_db
            from app.repository.electricity_repository import ElectricityRepository
            from app.modules.electricity.capacity_manager import get_capacity_manager
            from datetime import datetime

            session = get_db()
            try:
                # 保存剩余电量
                remaining_value = remaining
                if isinstance(remaining, dict):
                    remaining_value = remaining.get('default', 0)
                remaining_float = float(remaining_value) if remaining_value else 0.0

                ElectricityRepository.create_remaining(
                    session=session,
                    remaining=remaining_float,
                    meter='default',
                )
                session.commit()

                # 更新容量管理器
                capacity_manager = get_capacity_manager()
                capacity_manager.update_remaining(
                    current_remaining=remaining_float,
                    low_power_threshold=10.0,
                )

                # 批量保存用电记录
                record_tuples = []
                for r in records:
                    record_time = None
                    if r.get('time'):
                        time_str = r['time']
                        # 尝试多种时间格式解析
                        try:
                            # ISO 格式: 2026-06-29T11:00:00
                            if 'T' in time_str:
                                record_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                            # 空格分隔格式: 2026-06-29 11:00:00
                            else:
                                record_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                        except Exception as time_exc:
                            logger.warning(f'[电量] 时间解析失败: {time_str}, 错误: {time_exc}')
                            record_time = datetime.utcnow()
                    else:
                        record_time = datetime.utcnow()
                    
                    record_tuples.append((
                        record_time,
                        float(r.get('usage', 0)) if r.get('usage') else 0.0,
                        r.get('meter', 'default'),
                    ))

                created = ElectricityRepository.create_records_batch(session, record_tuples)
                session.commit()
                logger.info(f'[电量] 全量爬取完成: {created} 条记录，剩余 {remaining}')
                complete_task_process(pid, 'completed', f'全量爬取完成，{created} 条记录')
            except Exception as inner_exc:
                logger.error(f'[电量] 全量爬取执行失败: {inner_exc}')
                try:
                    complete_task_process(pid, 'failed', error=str(inner_exc))
                except Exception:
                    pass
            finally:
                session.close()

        thread = threading.Thread(target=_do_fetch_all, daemon=True)
        thread.start()

        user = g.get('current_user', {})
        logger.info(f'[电量] {user.get("username")} 手动触发全量爬取')
        return api_success(message='全量爬取任务已触发，正在后台执行', data={'task_id': pid})
    except Exception as exc:
        logger.error(f'[电量] 全量爬取触发失败: {exc}')
        return api_error(message=f'触发失败: {exc}', http_status=500)


@electricity_bp.route('/records', methods=['DELETE'])
@admin_required
def delete_all_records():
    """
    删除全部用电记录（需管理员权限）

    会清空以下表的数据：
    - electricity_records（用电记录）
    - electricity_remaining（剩余电量）
    - electricity_total_capacity（容量记录）

    适用场景：数据重置、重新全量爬取前清理旧数据
    """
    from app.core.database import get_db
    from app.model.electricity import ElectricityRecord, ElectricityRemaining, ElectricityTotalCapacity

    session = get_db()
    try:
        records_count = session.query(ElectricityRecord).count()
        remaining_count = session.query(ElectricityRemaining).count()
        capacity_count = session.query(ElectricityTotalCapacity).count()

        session.query(ElectricityRecord).delete()
        session.query(ElectricityRemaining).delete()
        session.query(ElectricityTotalCapacity).delete()
        session.commit()

        user = g.get('current_user', {})
        logger.info(f'[电量] {user.get("username")} 删除了全部用电记录: '
                    f'用电记录 {records_count} 条, 剩余电量 {remaining_count} 条, 容量记录 {capacity_count} 条')

        return api_success(message=f'已清空全部数据', data={'deleted_records': records_count, 'deleted_remaining': remaining_count, 'deleted_capacity': capacity_count})
    except Exception as exc:
        session.rollback()
        logger.error(f'[电量] 删除用电记录失败: {exc}')
        return api_error(message=f'删除失败: {exc}', http_status=500)
    finally:
        session.close()


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------

def _trigger_task(func_name: str, label: str):
    """通用手动触发逻辑（JWT 认证由装饰器保证）"""
    try:
        import app.modules.electricity.tasks as elec_tasks
        task_func = getattr(elec_tasks, func_name)
        thread = threading.Thread(target=task_func, daemon=True)
        thread.start()
        user = g.get('current_user', {})
        logger.info(f'[电量] {user.get("username")} 手动触发 {label}')
        return api_success(message=f'{label} 任务已触发')
    except Exception as exc:
        logger.error(f'[电量] 触发 {label} 失败: {exc}')
        return api_error(message=f'触发失败: {exc}', http_status=500)
