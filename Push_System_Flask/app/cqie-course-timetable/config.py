# 全局配置文件
# 课程表爬虫与处理系统配置
import os
import sys

from dotenv import load_dotenv

# 获取当前文件所在的目录
current_file_dir = os.path.dirname(os.path.abspath(__file__))

# 尝试多个可能的 .env 文件位置
env_paths = [
    # 1. 项目根目录（上一级目录的上一级）
    os.path.join(current_file_dir, "..", "..", ".env"),
    # 2. 当前目录的父级
    os.path.join(current_file_dir, "..", ".env"),
    # 3. 环境变量指定的路径
    os.environ.get("ENV_FILE_PATH", ""),
]

# 加载 .env 文件（app.core.config 在导入时已统一加载，这里作为兜底确保爬虫子进程可用）
for env_path in env_paths:
    if env_path and os.path.exists(env_path):
        load_dotenv(env_path, override=True)
        break

# 获取当前目录（爬虫模块目录）
BASE_DIR = current_file_dir

# 添加项目根目录到 Python 路径，以便导入 Config 类
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 尝试从项目 Config 类读取配置（如果失败，则使用旧方式）
try:
    from app.core.config import Config

    # 使用 Config 类的配置
    CLASS_NAME = Config.CLASS_NAME
    ENABLE_BACKGROUND = Config.COURSE_ENABLE_BACKGROUND
except (ImportError, AttributeError):
    # 回退到旧方式
    CLASS_NAME = os.environ.get("CLASS_NAME", "ZK2401")
    ENABLE_BACKGROUND = os.environ.get("COURSE_ENABLE_BACKGROUND", "true").lower() == "true"

# 爬虫配置
SPIDER_CONFIG = {
    "timeout": int(os.environ.get("JWXT_TIMEOUT", "120")),  # 超时时间（秒）
    "headless": os.environ.get("JWXT_HEADLESS", "true").lower() == "true",  # 是否使用无头浏览器
    "output_dir": os.path.join(BASE_DIR, "output"),  # 输出目录
    "error_screenshot": True,  # 是否在错误时截图
    "max_retries": 3,  # 最大重试次数
    "retry_delay": 5,  # 重试延迟（秒）
    "course_table": {
        "initial_wait_time": 120,  # 初始等待时间（秒）
        "wait_increment": 60,  # 每次重试增加的等待时间（秒）
        "max_retries": 2,  # 最大重试次数
        "max_total_wait": 240,  # 最大总等待时间（秒）
    },
    "login": {
        "username": os.environ.get("JWXT_USERNAME", ""),  # 登录账号
        "password": os.environ.get("JWXT_PASSWORD", ""),  # 登录密码
    },
}

# 注：登录凭据不再打印到 stdout，避免信息泄露

# 课程处理配置
PROCESSING_CONFIG = {
    "first_schedule_path": os.path.join(
        BASE_DIR, "course_processing/first.json"
    ),  # 第一套时间安排文件
    "second_schedule_path": os.path.join(
        BASE_DIR, "course_processing/second.json"
    ),  # 第二套时间安排文件
    "raw_data_dir": os.path.join(BASE_DIR, "output/course-data/raw"),  # 原始数据目录
    "processed_data_dir": os.path.join(BASE_DIR, "output/course-data/processed"),  # 处理后数据目录
    "history_dir": os.path.join(BASE_DIR, "output/course-data/history"),  # 历史数据目录
}

# 图片生成配置
IMAGE_CONFIG = {
    "output_dir": os.path.join(BASE_DIR, "output/course-data/images"),  # 图片输出目录
    "dpi": 250,  # 图片DPI
    "fig_width": 18,  # 图片宽度（英寸）
    "fig_height_per_row": 0.5,  # 每行高度（英寸）
    "font_size": 10,  # 字体大小
    "title_font_size": 24,  # 标题字体大小
    "table_scale_x": 1.2,  # 表格X轴缩放
    "table_scale_y": 1.5,  # 表格Y轴缩放
    "header_bg_color": "#4CAF50",  # 表头背景色
    "even_row_color": "#f0f8ff",  # 偶数行背景色
    "odd_row_color": "#ffffff",  # 奇数行背景色
    "border_color": "#cccccc",  # 边框颜色
    "title_format": "{class_name} 第 {week_number} 周 课程表",  # 标题格式
    "filename_format": "course_week{week_number}.jpg",  # 文件名格式（英文，无空格，JPEG格式）
    "enable_background": ENABLE_BACKGROUND,  # 是否启用背景图片（从 Config 读取）
    "background_path": os.path.join(BASE_DIR, "static/background.png"),  # 背景图片路径
    "color_mode": "weekday",  # 着色模式: 'row'（按行交替）或 'weekday'（按星期）
    "weekday_colors": {  # 星期对应的颜色
        "星期一": "#FFE4E1",  # 浅红色
        "星期二": "#E8F4F8",  # 浅蓝色
        "星期三": "#E8F5E8",  # 浅绿色
        "星期四": "#FFF8E1",  # 浅黄色
        "星期五": "#F3E5F5",  # 浅紫色
        "星期六": "#E0F7FA",  # 浅蓝色
        "星期日": "#FFECB3",  # 浅黄色
    },
}

# 教务系统配置（兼容旧脚本）
JWXT_CONFIG = {
    "headless": SPIDER_CONFIG["headless"],
    "timeout": SPIDER_CONFIG["timeout"],
    "username": SPIDER_CONFIG["login"]["username"],
    "password": SPIDER_CONFIG["login"]["password"],
    "captcha_mode": "auto",  # 验证码模式: 'auto' 或 'manual'
    "base_url": "http://jwxt.cqie.edu.cn",  # 教务系统基础URL
    "output_dir": SPIDER_CONFIG["output_dir"],
}

# 验证码配置（兼容旧脚本）
CAPTCHA_CONFIG = {
    "tesseract_path": "",  # Tesseract OCR路径
    "min_confidence": 60,  # 最小识别置信度
    "max_attempts": 3,  # 最大尝试次数
}

# 日志配置（兼容旧脚本）
LOG_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(levelname)s - %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S",
}

# 其他配置
CONFIG = {
    "class_name": CLASS_NAME,
    "spider": SPIDER_CONFIG,
    "processing": PROCESSING_CONFIG,
    "image": IMAGE_CONFIG,
    "jwxt": JWXT_CONFIG,
    "captcha": CAPTCHA_CONFIG,
    "log": LOG_CONFIG,
}
