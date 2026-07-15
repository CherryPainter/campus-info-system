# 校园信息聚合与智能推送系统

> 一套「采集 → 聚合 → 主动推送」的校园信息中台：自动获取课表、天气、宿舍电量，并通过企业微信机器人主动推送到群，配套 React 管理后台统一展示与配置。
>
> 毕业设计项目 · 当前版本 `v6.8.1` · 已部署上线

---

## 这是什么

学生每天要在多个系统间查课表、看天气、盯宿舍电量，信息分散、还得手动查。本项目把这些信息**自动采集、集中展示、主动推送**，让「上课前提醒」「天气预警」「低电量提醒」自动送达群里。

**核心功能**
- 📅 **课程自动获取** — 爬虫定时抓取教务系统课表，按周次推算，课前自动提醒
- 🌤️ **天气查询** — 对接和风天气，实时/逐时天气 + 气象预警推送
- 🔌 **宿舍电量** — 电量采集、余额查询、低电量提醒
- 📢 **企业微信推送** — 课程/天气/电量/自定义通知统一经群机器人推送
- 🖥️ **信息聚合后台** — React 管理台一站式查看与配置，内置 MFA、IP 黑名单、会话管理等安全能力

---

## 技术栈

| 分层 | 技术 |
|---|---|
| 前端 | React 19 + TypeScript + Vite + Ant Design 5 |
| 后端 | Python + **Flask 3.1** + SQLAlchemy 2.0 + 自研 JWT 认证 |
| 数据库 | MySQL 8（utf8mb4） |
| 采集 | Playwright（Chromium 无头）+ 和风天气 API |
| 调度 | APScheduler |
| 部署 | Ubuntu + Nginx + Gunicorn |

> 说明：后端实际框架为 **Flask**（非 FastAPI）。

---

## 快速开始

### 环境要求
- Python 3.12+ · Node.js 22.x · MySQL 8.0+

### 后端
```bash
cd Push_System_Flask
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # 爬虫用无头浏览器

cp .env.example .env                 # 编辑数据库、密钥等（见下）
python init_db.py                    # 初始化数据库（自动建表）
python run.py                        # 启动，默认 http://127.0.0.1:29528
```

### 前端
```bash
cd admin-frontend
npm install
npm run dev                          # 本地开发
# 或 npm run build 产出 dist/ 交给 Nginx 托管
```

### 最少要配的几项（.env）
```ini
SECRET_KEY=<强随机字符串>            # JWT 签名，必须设置
DATABASE_HOST=localhost
DATABASE_USER=root
DATABASE_PASSWORD=<你的密码>
DATABASE_NAME=push_system
JWT_ADMIN_USERNAME=admin
JWT_ADMIN_PASSWORD=<初始管理员密码>
QWEATHER_*=<和风天气凭证>            # 需在和风天气官网申请
```
> ⚠️ `.env` 已在 `.gitignore` 中，切勿提交；生产环境务必更换默认密码与密钥。

---

## 项目结构

```
push_system/
├── admin-frontend/      前端（React 19 + Vite）
├── Push_System_Flask/   后端（Flask + 爬虫子系统）
│   ├── app/api/         接口路由（按蓝图划分）
│   ├── app/model/       数据模型（约 20 张表）
│   ├── app/services/    业务逻辑
│   └── app/cqie-course-timetable/  课表爬虫
├── docs/                项目文档（见下）
└── README.md            本文件
```

---

## 更多文档

想深入了解系统架构、数据库设计、API 全量清单、部署细节？请看：

📖 **[项目技术文档 → docs/技术文档.md](docs/技术文档.md)**

内容包含：系统架构设计、功能模块设计、数据库设计（表结构+索引）、核心业务流程（含时序图）、约 110 个 API 接口说明、完整部署说明、已知问题与后续规划。

其他文档：
- [服务运维命令速查指南](docs/服务运维命令速查指南.md)
- [变更记录 CHANGELOG](Push_System_Flask/CHANGELOG.md)

---

## 授权与联系

毕业设计项目，仅供学习交流。联系邮箱见管理后台「关于」页面。
