#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一爬虫子进程执行入口（SpiderRunner）

封装 subprocess 调用 app/cqie-course-timetable/main.py 的全部细节：
- Python 解释器解析（PlatformUtils，兼容 PYTHON_PATH 覆盖）
- 环境变量注入（JWXT_HEADLESS / TESSERACT_CMD）
- cwd / 超时 / 编码

替代 scheduler.run_spider 与 crawl_task_service._crawl_one_semester 中各自重复、
易漂移的 subprocess 调用，成为系统调用课程爬虫的唯一入口。
"""
import os
import subprocess
import logging

from app.core.config import Config
from app.utils.platform_utils import PlatformUtils

logger = logging.getLogger(__name__)


def spider_dir() -> str:
    """返回爬虫脚本所在目录。"""
    return os.path.join(Config.BASE_DIR, 'app', 'cqie-course-timetable')


def build_spider_env(extra: dict = None) -> dict:
    """构造爬虫子进程环境变量（内存态 + 配置项注入）。"""
    env = os.environ.copy()
    env['JWXT_HEADLESS'] = str(getattr(Config, 'SPIDER_HEADLESS', True)).lower()
    tess = getattr(Config, 'TESSERACT_CMD', None)
    if tess:
        env['TESSERACT_CMD'] = tess
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def run_spider_process(args=None, *, timeout: int = 600, headless=None) -> subprocess.CompletedProcess:
    """运行爬虫 main.py，返回 subprocess.CompletedProcess。

    Args:
        args: 传给 main.py 的命令行参数列表（如 ['--semester-id', '251']）
        timeout: 单学期/单次爬虫超时（秒），默认 600
        headless: 覆盖无头模式（True/False），不传则使用 Config.SPIDER_HEADLESS

    Returns:
        subprocess.CompletedProcess（含 returncode / stdout / stderr）

    Raises:
        FileNotFoundError: 爬虫脚本不存在
        subprocess.TimeoutExpired: 超时（由调用方决定是否重试）
    """
    script = os.path.join(spider_dir(), 'main.py')
    if not os.path.exists(script):
        raise FileNotFoundError(f'爬虫脚本不存在: {script}')

    python_path = os.environ.get('PYTHON_PATH', '') or PlatformUtils.get_python_command()
    cmd = [python_path, script]
    if args:
        cmd.extend(str(a) for a in args)

    env = build_spider_env()
    if headless is not None:
        env['JWXT_HEADLESS'] = str(headless).lower()

    logger.info(f'[SpiderRunner] 执行: {" ".join(cmd)} (timeout={timeout}s)')
    return subprocess.run(
        cmd,
        cwd=spider_dir(),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        encoding='utf-8',
        errors='replace',
    )
