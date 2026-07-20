"""数据库初始化与迁移的共享常量/工具（Style / 表清单 / 引擎获取）。"""
import sys


class Style:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'

    @staticmethod
    def ok(text: str) -> str:   return f'{Style.GREEN}{text}{Style.RESET}'
    @staticmethod
    def warn(text: str) -> str: return f'{Style.YELLOW}{text}{Style.RESET}'
    @staticmethod
    def err(text: str) -> str:  return f'{Style.RED}{text}{Style.RESET}'
    @staticmethod
    def info(text: str) -> str: return f'{Style.CYAN}{text}{Style.RESET}'
    @staticmethod
    def dim(text: str) -> str:  return f'{Style.DIM}{text}{Style.RESET}'
    @staticmethod
    def bold(text: str) -> str: return f'{Style.BOLD}{text}{Style.RESET}'


# ── 所有表的定义（名称 + 描述 + 模型类名） ─────────────────

ALL_TABLES = [
    ('users',                        '用户表',                  'User'),
    ('token_blacklist',              'Token 黑名单',            'TokenBlacklist'),
    ('user_mfa',                     '用户 MFA 配置',           'UserMFA'),
    ('login_logs',                   '登录日志',                'LoginLog'),
    ('module_configs',               '模块配置',                'ModuleConfig'),
    ('courses',                      '课程表',                  'Course'),
    ('custom_pushes',                '自定义推送',              'CustomPush'),
    ('task_processes',               '任务进程',                'TaskProcess'),
    ('scheduled_crawl_tasks',        '爬取预约任务',            'ScheduledCrawlTask'),
    ('push_task_queue',              '推送任务队列',            'PushTask'),
    ('weather_records',              '天气记录',                'WeatherRecord'),
    ('weather_alerts',               '天气预警',                'WeatherAlert'),
    ('electricity_records',          '电量使用记录',            'ElectricityRecord'),
    ('electricity_remaining',        '剩余电量',                'ElectricityRemaining'),
    ('electricity_total_capacity',   '电量总量记录',            'ElectricityTotalCapacity'),
    ('webhooks',                     'Webhook 配置',            'Webhook'),
    ('server_sessions',              '服务端会话',              'ServerSession'),
    ('ip_blacklist',                 'IP 黑名单',               'IPBlacklist'),
    ('ip_security_events',           'IP 安全事件',             'IPSecurityEvent'),
]

def _ensure_db():
    """确保数据库引擎已初始化，返回 db_manager 实例"""
    from app.core.database import db_manager
    return db_manager



def _import_all_models():
    """导入所有模型，确保 Base.metadata 包含全部表"""
    from app.core.database import Base
    return Base


# ══════════════════════════════════════════════════════════════
#  status - 数据库状态总览
# ══════════════════════════════════════════════════════════════


def _parse_yes_flag() -> bool:
    """检测命令行是否含 --yes 或 -y 标志。"""
    return any(a in ('--yes', '-y') for a in sys.argv)


