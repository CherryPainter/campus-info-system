# -*- coding: utf-8 -*-
"""
中文字体解析工具（健壮版）

课程图片（cqie-course-timetable/course_processing/csv_to_image）与
电量图片（modules/electricity/chart）共用同一套字体解析策略，
保证两类图片中文字体一致。

健壮性要点（修复 Runtime Error: Can not load face (unknown file format)）：
- findSystemFonts() 可能返回损坏/格式不符/坏符号链接的字体文件，
  直接用 addfont 注册并在 rcParams 里按族名解析，渲染时 freetype
  加载该文件会抛出 FT2Font 错误导致整个爬虫子进程退出（code=1）。
- 因此选用字体前先用 ft2font 实测“文件是否真的可加载”，并校验
  “族名 -> 文件”解析结果也可加载；否则放弃该族名，回退到
  一定可加载的 DejaVu Sans（中文可能显示为方块，但绝不会崩溃）。
"""
import logging
import os

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

logger = logging.getLogger(__name__)

try:  # ft2font 是 matplotlib 自带的编译扩展，正常情况下必然可用
    from matplotlib import ft2font
except Exception:  # pragma: no cover
    ft2font = None

# Windows / Linux 常见中文字体关键词（按优先级排序）
_FONT_KEYWORDS = [
    'msyh', 'microsoft yahei',          # Windows 微软雅黑
    'simhei',                           # Windows 黑体
    'simsun', 'nsimsun',                # Windows 宋体
    'wqy-microhei', 'wqy-zenhei',       # Linux 文泉驿字体
    'noto sans cjk sc', 'noto sans cjk tc',  # Noto CJK 简体/繁体
    'noto sans cjk', 'notocjk', 'noto',      # Noto CJK 通用
    'source han sans sc', 'sourcehansanssc', # Source Han Sans SC
    'source han sans', 'sourcehansans',      # Source Han Sans
    'fangsong', 'kaiti',                # Windows 仿宋、楷体
]


def _is_font_loadable(path):
    """用 freetype 实测字体文件是否可加载，过滤掉损坏/格式不符/坏链接。"""
    if not path or not os.path.isfile(path):
        return False
    if ft2font is None:
        return True
    try:
        ft2font.FT2Font(path)
        return True
    except Exception:
        return False


def _rebuild_font_cache():
    """matplotlib 字体缓存可能过期（指向已删除/损坏文件），强制重建一次。"""
    try:
        fm._load_fontmanager(try_read_cache=False)
        logger.info('matplotlib 字体缓存已重建')
    except Exception as e:  # 不同版本签名差异，尽力而为
        logger.warning(f'重建字体缓存失败（不影响主流程）: {e}')


def _verify_dejavu():
    """校验 DejaVu Sans 是否可正常解析并加载（作为兜底字体）。"""
    try:
        path = fm.findfont(
            fm.FontProperties(family='DejaVu Sans'), fallback_to_default=False
        )
        return _is_font_loadable(path)
    except Exception:
        return False


def _find_loadable_chinese_font():
    """在所有系统字体里，返回第一个“可真实加载”的中文字体文件路径。"""
    for font in fm.findSystemFonts():
        if not _is_font_loadable(font):
            continue
        low = font.lower()
        for kw in _FONT_KEYWORDS:
            if kw in low:
                return font
    return None


def setup_chinese_font(force_rebuild_cache=False):
    """解析系统中文字体并配置 matplotlib rcParams，返回 FontProperties。

    与课程爬虫图片使用完全相同的字体优先级策略，确保两类图片中文字体一致。
    任何异常都会安全回退到 DejaVu Sans，绝不让字体问题导致调用方崩溃。

    Args:
        force_rebuild_cache: 是否先强制重建 matplotlib 字体缓存
            （仅在怀疑缓存过期导致解析到失效文件时传 True）。
    """
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['mathtext.fontset'] = 'dejavusans'

    if force_rebuild_cache:
        _rebuild_font_cache()

    font_prop = None
    try:
        path = _find_loadable_chinese_font()
        if path:
            try:
                fm.fontManager.addfont(path)
                name = fm.FontProperties(fname=path).get_name()
                # 族名解析也必须指向“可加载”的文件，否则放弃族名方案
                resolved = None
                try:
                    resolved = fm.findfont(
                        fm.FontProperties(family=name), fallback_to_default=False
                    )
                except Exception:
                    resolved = None
                if _is_font_loadable(resolved):
                    plt.rcParams['font.sans-serif'] = [name, 'DejaVu Sans']
                    plt.rcParams['font.family'] = 'sans-serif'
                    font_prop = fm.FontProperties(fname=path)
                    logger.info(f'使用中文字体: {path} (族名: {name})')
                    return font_prop
                logger.warning(
                    f'中文字体 {name} 族名解析到不可加载文件({resolved})，'
                    f'放弃族名方案，改用显式路径回退'
                )
            except Exception as e:
                logger.warning(f'注册中文字体失败: {e}')

        # 兜底：DejaVu Sans（始终随 matplotlib 打包且可加载）
        if not _verify_dejavu():
            _rebuild_font_cache()
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'
        font_prop = fm.FontProperties(family='DejaVu Sans')
        if path:
            logger.warning(
                '找到中文字体但无法安全使用，已回退 DejaVu Sans（中文可能显示为方块）'
            )
        else:
            logger.warning(
                '未找到可加载的中文字体，使用 DejaVu Sans（中文可能显示为方块）'
            )
    except Exception as e:
        logger.error(f'设置字体失败: {e}')
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'
        font_prop = fm.FontProperties(family='DejaVu Sans')

    return font_prop
