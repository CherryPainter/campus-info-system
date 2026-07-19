#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程推送系统配置文件
安全设计原则：
1. 敏感信息（密码、Token）必须从环境变量读取
2. 非敏感配置（时间、阈值、路径）直接写在代码中
3. 启动时验证必要配置是否存在
4. 提供清晰的错误提示
"""
import os
import sys
import platform
import shutil
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))


def _detect_tesseract_path() -> str:
    """
    自动检测 Tesseract OCR 路径（跨平台）

    Returns:
        Tesseract 可执行文件路径，未找到则返回空字符串
    """
    # 优先使用环境变量
    env_path = os.getenv('TESSERACT_CMD', '').strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    # 常见路径列表
    common_paths = []

    if platform.system() == 'Windows':
        # Windows 常见安装路径
        common_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe',
        ]
    elif platform.system() == 'Linux':
        # Linux 常见路径
        common_paths = [
            '/usr/bin/tesseract',
            '/usr/local/bin/tesseract',
        ]
    elif platform.system() == 'Darwin':
        # macOS 常见路径（Homebrew）
        common_paths = [
            '/usr/local/bin/tesseract',
            '/opt/homebrew/bin/tesseract',
        ]

    # 检查常见路径
    for path in common_paths:
        if os.path.isfile(path):
            return path

    # 尝试从 PATH 中查找
    tesseract_name = 'tesseract.exe' if platform.system() == 'Windows' else 'tesseract'
    found = shutil.which(tesseract_name)
    if found:
        return found

    return ''


class ConfigError(Exception):
    """配置错误异常"""
    pass


def validate_required_config():
    """
    验证必要的配置是否存在
    启动时调用，缺少必要配置则抛出异常
    """
    errors = []
    
    # 检查管理员Token
    admin_token = os.getenv('ADMIN_TOKEN', '')
    if not admin_token:
        errors.append("ADMIN_TOKEN: 管理接口Token未设置")
    elif len(admin_token) < 16:
        errors.append("ADMIN_TOKEN: Token长度不足16位，安全性过低")
    
    # 注：SECRET_KEY 的强制校验已在 Config.reload() 中按「生产失败 / 开发告警」处理，此处不再重复

    if errors:
        print("=" * 60)
        print("配置错误：以下必要配置缺失或无效")
        print("=" * 60)
        for error in errors:
            print(f"  - {error}")
        print("=" * 60)
        print("请复制 .env.example 为 .env 并填入正确的配置值")
        print("=" * 60)
        raise ConfigError("配置验证失败")


class Config:
    """应用配置（支持动态重新加载）"""
    
    @classmethod
    def reload(cls):
        """重新从环境变量加载所有配置"""
        from dotenv import load_dotenv
        # 重新加载 .env 文件
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
        load_dotenv(env_path, override=True)
        
        # 应用
        cls.APP_NAME = os.getenv('APP_NAME', '校园信息聚合与智能推送系统')
        cls.APP_VERSION = os.getenv('APP_VERSION', '6.13.1')
        cls.DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
        cls.HOST = os.getenv('HOST', '0.0.0.0')
        cls.PORT = int(os.getenv('PORT', '29528'))
        
        # 安全：SECRET_KEY 必须来自环境变量（敏感配置不硬编码）
        # 生产环境缺失则直接启动失败（避免重启即全员下线 / 多实例密钥不一致）；
        # 开发环境允许不安全默认值并告警，便于本地联调。
        cls.SECRET_KEY = (os.getenv('SECRET_KEY') or '').strip()
        if not cls.SECRET_KEY or cls.SECRET_KEY == 'dev-secret-key':
            if cls.DEBUG:
                import warnings
                warnings.warn(
                    '[安全警告] SECRET_KEY 未配置，使用不安全的开发默认值；'
                    '生产环境必须在 .env 中设置固定强密钥（生成：python -c "import secrets;print(secrets.token_hex(48))"），'
                    '否则重启后所有 JWT/Session 失效且多实例密钥不一致'
                )
                cls.SECRET_KEY = 'dev-insecure-secret-key-change-me'
            else:
                raise RuntimeError(
                    '环境变量 SECRET_KEY 未配置：生产环境必须设置固定强随机值，'
                    '否则重启即全员下线且多实例密钥不一致。详见 .env.example'
                )
        cls.ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', '')
        cls.AUTH_ENABLED = os.getenv('AUTH_ENABLED', 'true').lower() == 'true'

        # CORS 允许的域名（生产务必用 ALLOWED_ORIGINS 环境变量指定真实域名，勿写死 localhost）
        _origins_raw = os.getenv('ALLOWED_ORIGINS') or os.getenv('CORS_ORIGINS') or f'http://localhost:{cls.PORT},http://localhost:5173,http://localhost:5174'
        cls.ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(',') if o.strip()]
        cls.CORS_ORIGINS = cls.ALLOWED_ORIGINS  # 兼容别名

        # 是否强制管理员启用 MFA（默认开启；设为 false 可关闭，便于特殊场景）
        cls.FORCE_ADMIN_MFA = os.getenv('FORCE_ADMIN_MFA', 'true').lower() == 'true'

        # 境外 IP 拦截（防火墙）：仅允许中国 IP 访问，其余请求在请求最前端直接 403 断开
        # 默认开启；REGION_BLOCK_EXCEPTIONS 为逗号分隔的例外 IP/CIDR（管理员白名单，防止误锁自己）
        cls.ENABLE_FOREIGN_IP_BLOCK = os.getenv('ENABLE_FOREIGN_IP_BLOCK', 'true').lower() in ('1', 'true', 'yes', 'on')
        cls.REGION_BLOCK_EXCEPTIONS = [x.strip() for x in os.getenv('REGION_BLOCK_EXCEPTIONS', '').split(',') if x.strip()]
        
        # 教务系统
        cls.JWXT_USERNAME = os.getenv('JWXT_USERNAME', '')
        cls.JWXT_PASSWORD = os.getenv('JWXT_PASSWORD', '')
        cls.JWXT_HEADLESS = os.getenv('JWXT_HEADLESS', 'true').lower() == 'true'
        cls.JWXT_TIMEOUT = int(os.getenv('JWXT_TIMEOUT', '180'))
        
        # 企业微信（支持多 webhook，用逗号分隔）
        cls.WECOM_WEBHOOK = os.getenv('WECOM_WEBHOOK', '')
        cls.WECOM_STATUS_WEBHOOK = os.getenv('WECOM_STATUS_WEBHOOK', '')
        
        # 班级
        cls.CLASS_NAME = os.getenv('CLASS_NAME', 'ZK2401')
        
        # 定时任务
        cls.CRON_EXPRESSION = os.getenv('CRON_EXPRESSION', '0 7,13 * * *')
        
        # 推送规则
        cls.DAILY_PUSH_TIME = os.getenv('DAILY_PUSH_TIME', '07:00')
        cls.BEFORE_CLASS_MINUTES = int(os.getenv('BEFORE_CLASS_MINUTES', '15'))
        cls.BEFORE_END_CLASS_MINUTES = int(os.getenv('BEFORE_END_CLASS_MINUTES', '10'))
        
        # 课程图片配置
        cls.COURSE_ENABLE_BACKGROUND = os.getenv('COURSE_ENABLE_BACKGROUND', 'true').lower() == 'true'
        
        # 课程推送开关（前端可修改）
        cls.COURSE_PUSH_ENABLED = os.getenv('COURSE_PUSH_ENABLED', 'true').lower() == 'true'
        cls.COURSE_DEFAULT_PUSH_ENABLED = os.getenv('COURSE_DEFAULT_PUSH_ENABLED', 'true').lower() == 'true'
        
        # 爬虫配置（前端可修改）
        cls.COURSE_SPIDER_ENABLED = os.getenv('COURSE_SPIDER_ENABLED', 'true').lower() == 'true'
        cls.COURSE_SPIDER_INTERVAL_HOURS = int(os.getenv('COURSE_SPIDER_INTERVAL_HOURS', '6'))
        
        # 爬虫配置
        cls.SPIDER_HEADLESS = os.getenv('SPIDER_HEADLESS', 'true').lower() == 'true'

        # Tesseract OCR（跨平台自动检测）
        cls.TESSERACT_CMD = _detect_tesseract_path()
        
        # 日志配置
        cls.LOGGER_CONFIG = {
            'log_dir': 'logs',
            'log_file': 'app.log',
            'max_bytes': 10 * 1024 * 1024,  # 10MB
            'backup_count': 5,
            'console_level': 'INFO',
            'file_level': 'DEBUG',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        }
        
        # 路径
        cls.BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cls.OUTPUT_DIR = os.path.join(cls.BASE_DIR, 'output')
        # 爬虫模块自己的输出目录
        cls.SPIDER_OUTPUT_DIR = os.path.join(cls.BASE_DIR, 'app', 'cqie-course-timetable', 'output')
        cls.RAW_DATA_DIR = os.path.join(cls.SPIDER_OUTPUT_DIR, 'course-data', 'raw')
        cls.PROCESSED_DATA_DIR = os.path.join(cls.SPIDER_OUTPUT_DIR, 'course-data', 'processed')
        cls.IMAGES_DIR = os.path.join(cls.SPIDER_OUTPUT_DIR, 'course-data', 'images')
        cls.LOGS_DIR = os.path.join(cls.BASE_DIR, 'logs')
        
        # 课程数据文件路径（课表服务读取处理后的数据）
        cls.COURSE_DATA_PATH = os.path.join(cls.PROCESSED_DATA_DIR, 'processed_course_table.json')

        # ============================================================
        # 电量监控模块配置
        # ============================================================

        # 爬虫目标
        cls.ELECTRICITY_CRAWLER_BASE_URL = os.getenv('ELECTRICITY_CRAWLER_BASE_URL', 'http://dk.cqie.cn')
        # 敏感：从环境变量读取
        cls.ELECTRICITY_CRAWLER_COOKIE = os.getenv('ELECTRICITY_CRAWLER_COOKIE', '')
        cls.ELECTRICITY_CRAWLER_USER_AGENT = os.getenv(
            'ELECTRICITY_CRAWLER_USER_AGENT',
            'Mozilla/5.0 (Linux; Android 11; V2123A Build/RP1A.200720.012; wv) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.177 '
            'Mobile Safari/537.36 XWEB/1460075 MMWEBSDK/20260101 MicroMessenger/8.0.69.3040 '
            'WeChat/arm64 Weixin NetType/4G Language/zh_CN ABI/arm64',
        )
        cls.ELECTRICITY_CRAWLER_MAX_PAGES = int(os.getenv('ELECTRICITY_CRAWLER_MAX_PAGES', '50'))

        # 低电量告警
        cls.ELECTRICITY_LOW_POWER_THRESHOLD = float(os.getenv('ELECTRICITY_LOW_POWER_THRESHOLD', '10.0'))
        cls.ELECTRICITY_LOW_POWER_INTERVAL_HOURS = float(
            os.getenv('ELECTRICITY_LOW_POWER_INTERVAL_HOURS', '4.0')
        )

        # 电量推送定时配置
        cls.ELECTRICITY_SCHEDULE_DAILY = os.getenv('ELECTRICITY_SCHEDULE_DAILY', '00:30')
        cls.ELECTRICITY_SCHEDULE_WEEKLY = os.getenv('ELECTRICITY_SCHEDULE_WEEKLY', '00:30')
        cls.ELECTRICITY_SCHEDULE_WEEKLY_DAY = os.getenv('ELECTRICITY_SCHEDULE_WEEKLY_DAY', 'mon')
        cls.ELECTRICITY_SCHEDULE_MONTHLY = os.getenv('ELECTRICITY_SCHEDULE_MONTHLY', '00:30')
        cls.ELECTRICITY_SCHEDULE_MONTHLY_DAY = int(os.getenv('ELECTRICITY_SCHEDULE_MONTHLY_DAY', '1'))
        cls.ELECTRICITY_COOKIE_CHECK_TIME = os.getenv('ELECTRICITY_COOKIE_CHECK_TIME', '20:00')

        # 电量数据存储目录
        cls.ELECTRICITY_DATA_DIR = os.path.join(cls.BASE_DIR, 'data', 'electricity')

        # ============================================================
        # 天气模块配置
        # ============================================================

        # 和风天气 API (Ed25519/EdDSA JWT 认证)
        cls.QWEATHER_API_KEY = os.getenv('QWEATHER_API_KEY', '')  # API KEY（兼容旧版）
        cls.QWEATHER_CREDENTIAL_ID = os.getenv('QWEATHER_CREDENTIAL_ID', '')  # JWT 凭据 ID (kid)
        cls.QWEATHER_PROJECT_ID = os.getenv('QWEATHER_PROJECT_ID', '')  # JWT 项目 ID (sub)
        cls.QWEATHER_PRIVATE_KEY_PATH = os.getenv('QWEATHER_PRIVATE_KEY_PATH', 'ed25519-private.pem')  # Ed25519 私钥路径
        cls.QWEATHER_SECRET = os.getenv('QWEATHER_SECRET', '')  # 旧版 SHA-256 密钥（已废弃）
        cls.QWEATHER_API_HOST = os.getenv('QWEATHER_API_HOST', 'https://devapi.qweatherapi.com')
        cls.QWEATHER_LOCATION = os.getenv('QWEATHER_LOCATION', '106.55,29.56')  # 默认重庆坐标
        cls.QWEATHER_CITY_NAME = os.getenv('QWEATHER_CITY_NAME', '重庆')

        # 天气推送定时配置
        cls.WEATHER_SCHEDULE_DAILY = os.getenv('WEATHER_SCHEDULE_DAILY', '07:00')

        # 天气数据存储目录
        cls.WEATHER_DATA_DIR = os.path.join(cls.BASE_DIR, 'data', 'weather')

        # 天气独立推送 Webhook（为空则使用默认 WECOM_WEBHOOK）
        cls.WEATHER_WEBHOOK = os.getenv('WEATHER_WEBHOOK', '')

        # ============================================================
        # 数据库配置 - MySQL
        # ============================================================
        cls.DATABASE_TYPE = 'mysql'  # 仅支持 MySQL
        cls.DATABASE_HOST = os.getenv('DATABASE_HOST', 'localhost')
        cls.DATABASE_PORT = int(os.getenv('DATABASE_PORT', '3306'))
        cls.DATABASE_USER = os.getenv('DATABASE_USER', 'root')
        cls.DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', '123456')
        cls.DATABASE_NAME = os.getenv('DATABASE_NAME', 'push_system')

        # Redis（登录爆破滑动窗口计数；不配则降级为内存字典）
        cls.REDIS_URL = os.getenv('REDIS_URL', '')

        # ============================================================
        # JWT 认证配置
        # ============================================================

        # JWT Access Token 有效期（秒），默认 1 小时
        cls.JWT_ACCESS_TOKEN_EXPIRE = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRE', '3600'))
        # JWT Refresh Token 有效期（秒），默认 7 天
        cls.JWT_REFRESH_TOKEN_EXPIRE = int(os.getenv('JWT_REFRESH_TOKEN_EXPIRE', '604800'))
        # JWT 管理员用户名（用于登录认证）
        cls.JWT_ADMIN_USERNAME = os.getenv('JWT_ADMIN_USERNAME', 'admin')
        # JWT 管理员密码（为空则使用 ADMIN_TOKEN 作为初始密码）
        cls.JWT_ADMIN_PASSWORD = os.getenv('JWT_ADMIN_PASSWORD', '')
        # JWT 认证数据存储目录
        cls.JWT_AUTH_DATA_DIR = os.path.join(cls.BASE_DIR, 'data', 'auth')
    
    @classmethod
    def get_wecom_webhooks(cls) -> list:
        """获取所有企业微信推送 webhook 地址列表"""
        webhooks = []
        if cls.WECOM_WEBHOOK:
            webhooks = [url.strip() for url in cls.WECOM_WEBHOOK.split(',') if url.strip()]
        return webhooks
    
    @classmethod
    def get_status_webhooks(cls) -> list:
        """获取所有状态告警 webhook 地址列表"""
        webhooks = []
        if cls.WECOM_STATUS_WEBHOOK:
            webhooks = [url.strip() for url in cls.WECOM_STATUS_WEBHOOK.split(',') if url.strip()]
        return webhooks

    # 动态生成数据库 URL
    @staticmethod
    def get_database_url():
        """获取 MySQL 数据库连接 URL"""
        from app.core.config import Config
        return f"mysql+pymysql://{Config.DATABASE_USER}:{Config.DATABASE_PASSWORD}@{Config.DATABASE_HOST}:{Config.DATABASE_PORT}/{Config.DATABASE_NAME}?charset=utf8mb4"

# 初始化配置
Config.reload()


# 便捷的配置实例
config = Config()

