# 课程表爬虫与处理系统

自动化教务系统课程表获取、处理与图片生成工具。

---

## 📖 目录

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
d:\Learn\data\tool\
├── course_processing/          # 课程处理模块
│   ├── process_course_data.py   # 课程数据处理核心
│   ├── csv_to_image.py          # CSV 转图片
│   ├── first.json               # 第一套时间配置
│   └── second.json              # 第二套时间配置
├── static/                     # 静态资源
│   └── background.png           # 课程表背景图
├── output/                     # 输出目录（运行时自动创建）
│   ├── course-data/             # 课程数据
│   │   ├── raw/                 # 原始数据
│   │   ├── processed/           # 处理后数据
│   │   ├── images/              # 生成图片
│   │   └── history/             # 历史备份
│   └── logs/                    # 日志文件
├── main.py                     # ⭐ 整合版入口（推荐使用）
├── pipeline.py                 # 处理/入库模块（被 crawl_task_service 调用）
├── config.py                   # 配置文件
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

### 2. 配置账号密码

编辑 `config.py`，填写教务系统的用户名和密码：

```python
CONFIG = {
    'spider': {
        'login': {
            'username': '你的学号',
            'password': '你的密码'
        },
        # ... 其他配置
    }
}
```

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
| `spider.login.username` | 教务系统用户名 | - |
| `spider.login.password` | 教务系统密码 | - |
| `spider.headless` | 是否无界面浏览器 | `True` |
| `processing.raw_data_dir` | 原始数据目录 | `'output/course-data/raw'` |
| `processing.processed_data_dir` | 处理后数据目录 | `'output/course-data/processed'` |
| `processing.images_dir` | 图片目录 | `'output/course-data/images'` |
| `processing.time_config` | 使用哪套时间配置 | `'first'` |
| `images.class_name` | 班级名称 | `'ZK2401'` |
| `images.width` | 图片宽度 | `1080` |
| `images.height` | 图片高度 | `1920` |

---

## 输出文件

运行后会在 `output/course-data/` 目录下生成以下文件：

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 原始 HTML | `raw/course_table.html` | 从教务系统获取的原始 HTML |
| 原始 JSON | `raw/course_table.json` | 解析后的原始课程数据 |
| 处理后 JSON | `processed/processed_course_table_week{周数}.json` | 包含周数标注和完整课程信息 |
| 处理后 CSV | `processed/processed_course_table_week{周数}.csv` | 用于生成图片的 CSV |
| 课程表图片 | `images/{班级} 第{周数}周 课程表.png` | 最终生成的图片 |
| 日志文件 | `logs/course_spider_*.log` | 运行日志 |
| 历史备份 | `history/` | 所有历史版本的自动备份 |

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

A: 在 `config.py` 中修改 `images.width` 和 `images.height` 来调整图片尺寸。

### Q: 如何使用第二套时间配置？

A: 在 `config.py` 中将 `processing.time_config` 改为 `'second'`。

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

## 更新日志

### v1.1.0 (2026-05-30)

- ✅ 修复：正确处理 HTML 表格 rowspan 跨节课程
- ✅ 修复：过滤打印预览行导致的乱码数据
- ✅ 优化：大课合并逻辑，固定按 2 节小课合并为 1 节大课
- ✅ 修复：爬虫路径使用 Config.BASE_DIR 统一管理

### v1.0.0 (2026-05-29)

- ✅ 完成核心功能开发
- ✅ 添加10分钟超时保护机制
- ✅ 添加账号密码错误检测
- ✅ 添加验证码错误检测
- ✅ 添加资源自动清理
- ✅ 使用相对路径，支持任意目录部署
- ✅ 自动创建所需目录
- ✅ 完善错误处理和日志记录
