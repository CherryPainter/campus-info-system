#!/usr/bin/env python3
"""调度器共享状态（模块级全局变量）。

start_scheduler 写入 _scheduler / _spider_cron_hours；各执行函数读写
_spider_running / _spider_status / _spider_success_dates / _daily_push_pending。
集中到本模块，供 scheduler.py（生命周期）与 executors.py（执行逻辑）共享，
避免「生命周期 ↔ 执行」相互 import 造成的循环依赖。
"""

# 调度器实例（APScheduler BackgroundScheduler）
_scheduler = None

# 爬虫并发执行锁
_spider_running = False

# 爬虫执行状态记录
_spider_status = {
    "last_run": None,  # 上次执行时间 (ISO 格式)
    "last_result": None,  # 上次执行结果: 'success' / 'failed' / 'running'
    "last_error": None,  # 上次错误信息
    "last_exit_code": None,  # 上次退出码
}

# 爬虫与每日课表推送的协调机制
_spider_success_dates = {}  # {date_str: True} - 爬虫成功执行的日期
_daily_push_pending = {}  # {date_str: True} - 因爬虫未完成而延迟的每日课表推送
_spider_cron_hours = set()  # 爬虫 cron 触发的小时集合（如 {7, 13}）
