# 课程表爬虫与处理系统

自动化教务系统课程表获取、处理与图片生成工具。

---

## 目录

- [项目功能](#项目功能)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
- [配置说明](#配置说明)
- [输出文件](#输出文件)
- [常见问题](#常见问题)
- [技术栈](#技术栈)

---

## 项目功能

| 功能 | 说明 |
|------|------|
| 自动登录 | 使用 Playwright 自动化登录教务系统 |
| 验证码识别 | 自动识别登录验证码，只接受纯数字 |
| 错误检测 | 检测账号密码错误、验证码错误并及时退出 |
| 超时保护 | 10分钟超时机制，防止程序卡死 |
| 课程表解析 | 智能解析课程表 HTML 数据 |
| 连续课程合并 | 自动合并连续的相同课程 |
| 时间处理 | 白天课结束时间减 10 分钟，第9-12节晚上课保持原时间 |
| 楼栋转译 | 自动将楼栋代码（J06）转换为中文（理工楼） |
| 周数标注 | JSON 输出明确标注当前周数（周日显示下一周） |
| 图片生成 | 生成美观的课程表图片 |
| 历史备份 | 自动备份历史数据和图片 |
| 资源清理 | 程序结束时自动清理浏览器资源 |

---

## 项目结构

```
app/cqie-course-timetable/          # 本子系统根目录（BASE_DIR 由 config.py 依文件位置推导）
├── course_processing/          # 课程处理模块
│   ├── process_course_data.py   # 课程数据处理核心
│   ├── csv_to_image.py          # CSV 转图片
│   ├── first.json               # 第一套时间配置
│   └── second.json              # 第二套时间配置
├── static/                     # 静态资源
│   └── background.png           # 课程表背景图（可用同名文件替换）
├── output/                     # 输出目录（运行时自动创建）
│   ├── course-data/             # 课程数据
│   │   ├── raw/                 # 原始数据
│   │   ├── processed/           # 处理后数据
│   │   ├── images/              # 生成图片
│   │   └── history/             # 历史备份
│   └── logs/                    # 日志文件
├── main.py                     # 整合版入口（推荐使用）
├── pipeline.py                 # 处理/入库模块（被 crawl_task_service 调用）
├── parser_utils.py             # 课表解析工具（节次/时间等）
├── rebuild_course_meta.py      # 重建 course_meta.json
├── reimport_with_teacher.py    # 带教师信息重新导入
├── xlsx_import.py              # 从 Excel 导入课程
├── config.py                   # 配置（**账号密码等敏感项从环境变量读取**，见「快速开始」）
├── logger.py                   # 日志模块
├── captcha.py                  # 验证码识别（备用）
└── requirements.txt            # 依赖清单
```

---

## 快速开始

### 1. 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

### 2. 配置账号密码（走环境变量，不要改进 config.py 的取值）

`config.py` 中的账号密码是**从环境变量读取**的，不是写死在文件里的字面量：

```python
# app/cqie-course-timetable/config.py
SPIDER_CONFIG = {
    "login": {
        "username": os.environ.get("JWXT_USERNAME", ""),   # 登录账号
        "password": os.environ.get("JWXT_PASSWORD", ""),   # 登录密码
    },
    "headless": os.environ.get("JWXT_HEADLESS", "true").lower() == "true",
    "timeout": int(os.environ.get("JWXT_TIMEOUT", "120")),
}
CLASS_NAME = os.environ.get("CLASS_NAME", "ZK2401")
```

在本子系统目录放一个 `.env`（或由调用方通过环境变量传入；`config.py` 会额外加载
`ENV_FILE_PATH` 指向的文件），至少写上：

```ini
JWXT_USERNAME=<学号>
JWXT_PASSWORD=<密码>
# 可选
JWXT_HEADLESS=true
JWXT_TIMEOUT=120
CLASS_NAME=ZK2401
COURSE_ENABLE_BACKGROUND=true
```

> 后端集成运行时，这些变量由 `Push_System_Flask/.env` 经子进程传入，**无需**在此重复配置。

### 3. 运行程序

```bash
python main.py
```

---

## 使用方式

### 方式一：一键运行（推荐）

使用整合版 `main.py`，一键完成所有操作：

```bash
python main.py
```

### 方式二：分步运行

如果你想更灵活地控制流程，可以分步运行：

```bash
# 1. 获取课程表（爬取 + 解析 + 入库，已整合在 main.py）
python main.py

# 注：pipeline.py 的入库逻辑由 crawl_task_service 在爬取流程中自动调用，无需单独运行
```

---

## 配置说明

在 `config.py` 中可以配置以下选项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `spider.login.username` / `.password` | 教务系统账号密码（**取自环境变量** `JWXT_USERNAME` / `JWXT_PASSWORD`） | `''` |
| `spider.headless` | 是否无界面浏览器（环境变量 `JWXT_HEADLESS`） | `True` |
| `spider.timeout` | 单次超时（秒，环境变量 `JWXT_TIMEOUT`） | `120` |
| `class_name`（顶层 `CONFIG['class_name']`） | 班级名称（环境变量 `CLASS_NAME`） | `'ZK2401'` |
| `processing.raw_data_dir` | 原始数据目录 | `<BASE_DIR>/output/course-data/raw` |
| `processing.processed_data_dir` | 处理后数据目录 | `<BASE_DIR>/output/course-data/processed` |
| `processing.history_dir` | 历史备份目录 | `<BASE_DIR>/output/course-data/history` |
| `processing.first_schedule_path` / `.second_schedule_path` | 两套时间安排文件**路径**（`course_processing/first.json` / `second.json`） | 见 `config.py` |
| `image.output_dir` | 图片输出目录（注意是 `image` 单数，不是 `processing.images_dir`） | `<BASE_DIR>/output/course-data/images` |
| `image.fig_width` | 图片宽度（**英寸**） | `18` |
| `image.fig_height_per_row` | 表格每行高度（**英寸**） | `0.5` |
| `image.dpi` | 图片 DPI | `250` |
| `image.enable_background` | 是否启用背景图（来自 `COURSE_ENABLE_BACKGROUND`） | `true` |
| `image.filename_format` | 图片文件名格式 | `course_week{week_number}.jpg` |

> 旧版本此表里的 `processing.time_config`、`processing.images_dir`、`images.width`、`images.height`、`images.class_name` 等键在代码中**并不存在**（已订正）。两套时间表是按**文件路径**加载并在解析时按教学楼匹配，没有「切换 time_config」这样的开关。

---

## 输出文件

运行后会在 `output/course-data/` 目录下生成以下文件：

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 原始 HTML | `course-data/raw/course_table.html` | 从教务系统获取的原始 HTML |
| 原始 JSON | `course-data/raw/course_table.json` | 解析后的原始课程数据 |
| 全学期原始 JSON | `course-data/raw/course_table_all_weeks.json` | `--all-weeks` 全学期爬取的原始数据（供后端整学期入库） |
| 课程元信息 | `course-data/raw/course_meta.json` | 课程元信息（可由 `rebuild_course_meta.py` 重建） |
| 处理后 JSON | `course-data/processed/processed_course_table_week{周数}.json` | 包含周数标注和完整课程信息 |
| 处理后 CSV | `course-data/processed/processed_course_table_week{周数}.csv` | 用于生成图片的 CSV |
| 课程表图片 | `course-data/images/course_week{周数}.jpg` | 最终生成的图片（文件名取自 `image.filename_format`，JPEG） |
| 日志文件 | `logs/course_spider_*.log` | 运行日志 |
| 历史备份 | `course-data/history/`（另有 `logs/history/`） | 所有历史版本的自动备份 |

> 上述路径均相对 `output/`。图片文件名由 `IMAGE_CONFIG['filename_format']` 决定，默认
> `course_week{week_number}.jpg`（**不是**中文名 + `.png`）。

### JSON 数据格式

```json
{
  "week_number": 13,
  "week_str": "第13周",
  "total_courses": 13,
  "courses": [
    {
      "week_day": "星期一",
      "period_name": "第一、二节",
      "period_idx": 1,
      "course_name": "Python人工智能应用开发",
      "teacher": "田永平,刘夕炎",
      "building": "理工楼",
      "classroom": "406语音识别技术实训室",
      "weeks": "13",
      "week_number": 13,
      "start_time": "08:10",
      "end_time": "09:40",
      "date": "2026-05-25"
    }
  ]
}
```

---

## 常见问题

### Q: 验证码识别失败怎么办？

A: 程序会在识别失败时退出，你可以重新运行程序。验证码只接受纯数字，如果识别到非数字字符会自动失败。

### Q: 账号或密码错误怎么办？

A: 程序会检测到错误提示并立即退出，请检查 `config.py` 中的账号密码是否正确。

### Q: 程序运行超时怎么办？

A: 程序设置了10分钟超时保护，如果超过10分钟未完成会自动退出。请检查网络连接或重新运行程序。

### Q: 如何修改课程表背景图？

A: 将新的背景图命名为 `background.png` 并替换 `static/` 目录下的文件即可。

### Q: 生成的图片尺寸不对？

A: 在 `config.py` 的 `IMAGE_CONFIG` 中改 `fig_width`（宽度，英寸）与 `fig_height_per_row`（表格每行高度，英寸）；也可调 `dpi`。注意这两个值是**英寸**而不是像素，最终像素 = 英寸 × dpi。

### Q: 如何使用第二套时间配置？

A: **没有 `time_config` 这样的开关**（该键在代码中不存在）。两套时间表以路径形式配置在 `PROCESSING_CONFIG` 的 `first_schedule_path` / `second_schedule_path`，解析时按教学楼匹配，二者都在用；要调整时间请直接改 `course_processing/first.json` / `second.json` 的内容。

### Q: 周日显示的是下一周的课表？

A: 这是教务系统的原生机制，程序会正确识别并标注周数。

---

## 技术栈

| 技术 | 用途 | 版本 |
|------|------|------|
| **Playwright** | 浏览器自动化 | >= 1.40.0 |
| **BeautifulSoup** | HTML 解析 | >= 4.12.0 |
| **Pillow** | 图片处理 | >= 10.0.0 |
| **Matplotlib** | 图表生成 | >= 3.7.0 |
| **Pandas** | 数据处理 | >= 2.0.0 |
| **Pytesseract** | OCR 验证码识别（可选） | >= 0.3.10 |
| **OpenCV** | 图像预处理（可选） | >= 4.8.0 |

---

## 许可证

本项目仅供学习交流使用。

---

## 更新日志（本子系统早期记录）

> 本节只记录本子系统独立开发期（2026-05）的早期迭代，**此后不再更新**。本子系统后续已并入主仓库持续演进（如全学期爬取 `--all-weeks`、解析周次护栏等），完整变更请查看仓库根 `CHANGELOG.md`。

### v1.1.0 (2026-05-30)

- 修复：正确处理 HTML 表格 rowspan 跨节课程
- 修复：过滤打印预览行导致的乱码数据
- 优化：大课合并逻辑，固定按 2 节小课合并为 1 节大课
- 修复：爬虫路径使用 Config.BASE_DIR 统一管理

### v1.0.0 (2026-05-29)

- 完成核心功能开发
- 添加10分钟超时保护机制
- 添加账号密码错误检测
- 添加验证码错误检测
- 添加资源自动清理
- 使用相对路径，支持任意目录部署
- 自动创建所需目录
- 完善错误处理和日志记录
