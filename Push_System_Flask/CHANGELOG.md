# 校园信息聚合与智能推送系统 · 更新日志

> 版本号规则：后端 `.env` / `app/core/config.py` 的 `APP_VERSION`、前端 `package.json` 的 `version`、前端 `src/version.ts` 的 `APP_VERSION` 以及各部署/配置文档须保持一致。

---

## v6.8.4 (2026-07-18)

> 发版类型：**功能优化（patch）**。Webhook 管理页「测试」列新增「须测试」标识。

### 🎨 前端改进

#### Webhook 管理页「测试」列增强
- 新增「须测试」标识：当某个 webhook 的配置（`名称 / URL / 模块 / 描述 / 状态`）在**上次测试之后**被修改过，或**从未测试过**，其「测试」列显示橙色 `⚠ 须测试` 标签（带 tooltip 提示「配置已更新，建议重新发送测试以确认可用性」）。
- 判断依据为后端已持久化的 `updated_at` 与 `last_test_time` 字段对比，刷新页面后依然有效，**无需改动后端或迁移数据库**。
- 点击「测试」按钮且测试完成（成功或失败）后，`last_test_time` 刷新，「须测试」标识自动消失，恢复正常状态徽标（成功/失败/测试中）。
- 正在测试中的行优先显示「测试中」状态，不受「须测试」覆盖。

---

## v6.8.3 (2026-07-18)

> 发版类型：**安全增强（patch）**。新增登录密码爆破分层封禁 + 黑名单管理 UI 升级 + 安全事件推送通知。

### ✨ 新功能

#### 登录密码爆破分层封禁（Redis 滑动窗口计数）
- **L1（3次失败/5分钟）**：锁定 5 分钟，返回 429 + Retry-After，推送"疑似暴力破解"预警（不写黑名单）。
- **L2（4次失败）**：临时封禁 30 分钟（source=`login_brute_tier2`），写入黑名单 + 推送告警。
- **L3（5次失败）**：永久封禁（source=`login_brute_tier3`），写入黑名单 + 推送严重告警。
- **覆盖范围**：密码错误、用户名不存在、空参数——三种失败场景均计入爆破检测。
- **正确登录自动重置**计数器，防误伤正常用户。
- **存储**：优先 Redis（滑动窗口有序集合）；不可用时降级为内存字典（进程重启丢失可接受）。
- **配置**：`.env` 新增 `REDIS_URL`；分层阈值在 `ip_blacklist_service.py` 的 `LOGIN_BRUTE_TIERS` 常量中可调。

#### 安全事件推送通知增强
- `_send_block_alert` 支持传入 `tier_info` 参数，推送文案按层级差异化（含 emoji 级别标识、累计失败次数、处置状态）。
- 新增 `send_brute_force_alert` 方法：L1 限流级别专用推送（未封禁但需管理员关注）。
- 所有告警走 **system 适配器通道**（企业微信 webhook），不再悄无声息。

#### 黑名单管理 API 扩展
- 新增 `PUT /api/admin/ip-blacklist/<ip>/update` 接口：支持修改已有记录的封禁期限(`duration_hours`)、原因(`reason`)、备注(`note`)、状态(`is_active`)。

### 🎨 前端改进

#### 黑名单列表 UI 升级
- **来源区分**：系统自动（安全违规/DDoS）vs 手动 vs 爆破封禁——用颜色标签 + "🔴 爆破"高亮标记一目了然。
- **操作列增强**：
  - 「解封」按钮（显式 unblock，区别于 toggle 禁用）
  - 「编辑」按钮 → 打开 Drawer 抽屉修改期限/原因/备注/状态
  - 启停 Switch + 彻底删除保留
- **编辑抽屉**（Drawer）：展示当前记录信息（IP/来源/封禁时间），可修改所有字段；期限修改从当前时间重新计算过期时间。
- **移动端卡片同步增强**：来源色标置顶、增加解封/编辑按钮、爆破标记高亮。

### 🔧 配置变更
- `.env` 新增 `REDIS_URL=redis://localhost:6379/0`（不配则降级内存字典）。
- `app/core/config.py` 新增 `Config.REDIS_URL` 加载项。

---

## v6.8.2 (2026-07-18)

> 发版类型：**安全修复（patch）**。修复 IP 黑名单对已封禁 IP 的登录暴力破解无效的问题。

### 🐛 修复

- **登录环节 IP 黑名单失效**：`/api/auth/login` 原被 `security_before_request` 列入白名单，导致 IP 黑名单检查在登录入口被整体跳过——已封禁（含永久 `auto_security_violation`）的 IP 仍能持续打登录接口、走 bcrypt 校验失败并写入"密码错误"日志，封禁形同虚设。
  - 在 `app/api/auth_routes.py` 的 `login()` 内新增显式 IP 封禁拦截：被封禁 IP 直接返回 `403 拒绝访问`，不再产生"密码错误"登录日志，杜绝暴力破解与日志污染。
  - 保留"持有正确凭据的管理员"自助解封通道：被误封的管理员凭正确账号密码仍可登录，随后在后台解封自己，避免自锁。
  - 新增 `_ip_is_blocked` / `_verify_password` 辅助函数。

### ⚠️ 部署提醒

- 重新上传后端 `app/api/auth_routes.py` 与 `app/core/config.py`、前端 `dist/`，并将服务器 `.env` 的 `APP_VERSION` 改为 `6.8.2`。
- 已在 `ip_blacklist` 表中的封禁记录部署后立即生效，无需额外操作。

---

## v6.8.1 (2026-07-15)

> 发版类型：**修复版本（patch）**。本期聚焦两处误推送/误弹框回归修复，以及部署整洁度与运行稳定性。

### 🐛 修复

- **「今天没课却推送」误推送（严重）**：根因为 `CourseRepository.get_week_number` 用 `MAX(week_number)` 冒充当前教学周次，学期推进超过数据中最大周次后必然误判。改为**基于学期第 1 周起始日（`course_weeks.week_number=1.start_date`）推算真实当前周次**，兜底才用 `MAX`。修复后今天（2026-07-15）被正确判定为第 20 周，而 `courses` 表无第 20 周课程 → 不误推。
- **会话失效弹框重复弹出两次**：旧逻辑当前页 `notifySessionExpired` 弹一次 + 登录页挂载时读 `sessionStorage` 又弹一次（因整页跳转使模块变量清零挡不住）。改为只保留当前页弹框，`Login.tsx` 移除重复弹框逻辑，`request.ts` 删除死代码 `redirectToLogin`，`sessionExpiry.ts` 不再写桥接 key。
- **爬虫无头模式默认开启**：`.env` 的 `JWXT_HEADLESS` 由 `false` 改回 `true`（日常爬虫路径唯一真源，受 `load_dotenv(override=True)` 覆盖注入值影响，须改此变量）。
- **登录页新增「记住我」并修复会话过期不弹框**：此前登录接口 `remember_me` 默认 `True`（永远 30 天），普通会话几乎不会自然过期、过期弹框难以触发。现登录页增加「记住我」复选框（默认**不勾选**）：不勾 = 短会话（服务端 24h + JWT 闲置 2h / 绝对 1d），勾选 = 长会话（服务端 30d + JWT 闲置 7d / 绝对 30d）；`remember_me` 现在**同时驱动服务端 Session 与 JWT 闲置/绝对上限**（此前只影响服务端 Session，JWT 仍写死 3d/30d，导致勾选也挡不住 3 天闲置踢人）。

### 🔒 安全

- **头像上传安全加固（中危 → 已修复）**：原 `PUT /api/admin/user/profile` 与 `PUT /api/admin/user/<id>` 直接 `user.avatar = data['avatar']` 无任何校验，存在存储型 XSS（SVG 内嵌脚本）与超大 payload（DoS）风险。新增 `validate_avatar_data_uri`：仅允许 JPG/PNG/GIF/WEBP（**显式拒绝 SVG**）、校验文件头 Magic Bytes 防伪造、限制解码后 2MB；并新增「**一年仅可修改 3 次头像**」频率限制（基于 `users.avatar_change_log` 时间戳记录，超频返回 429 及下次可改时间）。前端同步加类型/大小前端校验（仅作体验拦截，后端为权威）。

### 🧹 工程

- 后端根目录结构整理：部署/安全文档归档 `docs/deploy/`；运行日志 `run.log`/`runtime.log` 归位 `logs/`；`.gitignore` 停止跟踪运行期数据（`course_table.json`、`data/electricity/*.json`、`data/weather/.cooldown_state`）。
- 版本号同步至 6.8.1（前端 `version.ts`/`package.json`、后端 `config.py` 默认值、`.env`）。

### 🗄️ 数据库

- **`users` 表新增 `avatar_change_log` 列**（TEXT，存头像修改时间戳 JSON 列表）。`init_db.py` 基于模型 `create_all` 自动同步；若老库已有 `users` 表缺此列，启动后端会在 `app/__init__.py` 调 `ensure_user_columns()` 幂等 `ALTER TABLE` 补齐（与 `ensure_session_columns` 同理），**无需手动改初始化工具代码**。
- `server_sessions` 的 `revoked_at`/`revoked_reason`/`revoked_by_ip` 三列已在 v6.8.0 随模型加入，启动期 `ensure_session_columns()` 自动补列。

---

## v6.8.0 (2026-07-14)

> 发版类型：**次要版本（minor）**。本期聚焦统一任务模型重构收尾、爬虫稳定性修复，以及会话与权限模块强化（单会话策略、实时轮询、心跳检测、被踢结构化提示）。

### ✨ 新增功能

- **统一任务模型重构（阶段 1-3 全量落地）**：
  - 后端：`TaskStatus` 枚举 + `UnifiedTaskService` 唯一写入入口；`SpiderRunner` 统一爬虫 subprocess 入口；新增 `GET /api/tasks/:id` 统一任务查询；服务层合并为单一 `app/services/`；API 响应统一 `api_success/api_error/api_paginate` 封装。
  - 前端：新增 `useTaskPolling` / `useRunningTasksPolling` / `useIntervalPolling` 三个轮询 Hook；统一 `ApiResponse`/`Paginated` 类型、`User` 单一类型、`statusMaps` 状态映射、`useMessage` 提示、`datetime`/`useSemester` 共享工具。
- **会话心跳检测**：新增 `GET /api/auth/session/status` 心跳端点（常驻 200），前端 `AuthGuard` 每 5s 探测，空闲也能及时感知被踢。
- **会话失效结构化提示**：被踢/过期时弹框告知原因，被踢场景显示「踢人设备 IP」；`server_sessions` 新增 `revoked_at` / `revoked_reason` / `revoked_by_ip` 三列。

### 🐛 修复

- **前端全量/指定学期爬取轮询**：修复「不等程序跑完就刷新」（残留轮询 effect 抵消修复）与「任务卡不亮」（启动按 id 轮询、查询同时含 pending+running）。
- **爬虫「过快点击被掐」**：登录成功后增加 3-7s 缓冲；新增 `_goto_course_table` 进课程页指数退避重试（最多 4 次）。
- **爬虫「解析全部课表串味」**：整学期主数据源由渲染表格切换为页面 JS `TaskActivity` 周次位图重建，稳健性大幅提升。
- **课程管理「任务运行中」横幅卡死**：根因为数据库僵尸 running 任务，后端新增 `reap_stale_crawl_tasks` 30 分钟超时自愈。
- **会话不灭绝/无限叠加**：改为单会话策略（新登录挤掉旧登录），不同用户仍可并行；修复「被踢 → 401 → refresh 又成功 → 无限刷新」死循环。
- **用户与权限模块无实时刷新**：`UserManagement` / `SessionManager` 改为 `useIntervalPolling` 实时轮询。

### 🛠 基础设施与配置

- 爬虫点击改造：登录按钮改原生 Playwright 点击、导出表单点真实提交按钮，规避合成点击触发过快点击。
- 版本号同步至 **6.8.0**（前端 `version.ts` / `package.json`、后端 `config.py` 默认值 / `.env`）。
- `.gitignore` 新增 `*.bak*` 规则，避免改动前备份文件误入库。

### 🔒 安全

- 修复登录限流可被 `X-Real-IP` 伪造绕过（统一 `get_client_ip`，仅内网后信任 `X-Forwarded-For`）。
- 删除 `DynamicToken` 死代码、`security.py` 重复 `path_security_check` 装饰器；安全化爬虫 `config`（移除用户名明文打印与 `.env` 探测噪音）。

---

## v6.7.0 (2026-07-07)

> 发版类型：**次要版本（minor）**。本期聚焦移动端适配、安全事件处置能力、学期切换全链路打通，以及多项体验与稳定性修复。

### ✨ 新增功能

- **学期切换全链路打通**：前端学期选择器 + 后端按学期过滤 + 上学期数据入库，切换学期后课程/爬取范围联动正确。
- **课程爬取预约任务**：支持范围/预约爬取，配套进程管理（增删改查、状态追踪）。
- **IP 安全事件快捷处置**：
  - 后端新增 `ip_security_events.is_ignored` 字段，及 `/admin/ip-blacklist/events/<id>/ignore`、`/ban` 两个接口（`ignore_event` / `ban_event_ip` 服务）。
  - 前端安全事件页新增「忽略」「封禁」操作（桌面表格操作列 / 移动卡片按钮），并支持「仅未处理」过滤。
- **天气 24h 预报竖向时间轴**：由表格改为轴线 + emoji 节点 + 当前时刻高亮的时间轴展示，支持纵向滚动、无横向滑动。

### 📱 移动端适配（手机端专用卡片 / 布局）

- **课程表**：禁横向滚动、等宽可挤压完全显示；无课的周六/周日整列自动隐藏让位给其他有课日；「课程表/列表」切换按钮移至标题「第 X 周课表」旁。
- **个人设置 - 登录日志**：由 7 列宽表改为简洁时间线（Timeline）展示。
- **用户与权限**：手机端改用专用卡片（桌面端表格不变）。
- **我的会话 / IP 黑名单**：手机端改用专用卡片（桌面端表格不变）。
- **黑名单工具栏**：「添加黑名单」按钮右对齐独占一行；列表/事件工具栏强制单行显示（控件缩小、紧凑间距、不换行）。
- **会话状态**：「活跃」标签改为绿色背景，与「当前设备」区分但仍醒目。

### 🐛 修复

- 课程表「正在上课」仅按当前真实教学周判定，抑制历史学期误高亮。
- 非本学期默认跳到第一个有课的周，避免空白课表。
- 移动端侧边栏滚动到底部后遮罩消失的问题。
- 课程爬取 0 条静默成功 → 新增 `completed_empty` 状态 + 橙色提醒。
- 全量爬取无「运行中」状态 → 课程页接管轮询。
- 推送任务队列落库持久化（`push_task_queue`），重启不丢任务。
- 课程重复（原 `hash()` 随机）→ 改用 `hashlib.md5` 定点修复 + 清库。
- 设置项审计：删除 8 个空壳配置项、修正 3 处映射。

### 🛠 基础设施与配置

- 数据库初始化工具（`init_db.py`）补全 20 张表并修复 `COLLATE` 误报；`user.avatar` 类型对齐。
- **版本号单一真源**：前端新增 `src/version.ts` 导出 `APP_VERSION`，`Footer` / `About` / `Login` 统一引用，不再各自写死（修复 Login 页长期停留在 v6.6.0 的问题）。
- 版本号全面统一：后端 `.env` 与 `config.py`、前端 `package.json`、README、安全配置指南、部署检查清单、Linux 部署指南均更新为 **6.7.0**。

### 🔒 安全（持续有效）

- JWT 双 Token（access 1h / refresh 7d，httpOnly Cookie）、TOTP MFA、IP 黑名单、server_sessions 会话管理、路径/SQL/XSS 检测 + Flask-Limiter 限流。

---

## v6.6.0 (2026-06-25)

**安全与权限：**

- 修复主管理员密码可被非主管理员重置的严重权限漏洞。
- 非主管理员只能查看/创建普通用户，不能查看或提升管理员，不能重置其他管理员密码。

**公开页面鉴权修复：**

- 修复 footer 链接页面（用户协议、网站介绍、联系我们、隐私政策、法律声明、Cookies 政策）在未登录时被错误重定向到登录页的问题。

**进程管理修复：**

- 修复定时任务下次执行时间格式导致前端倒计时不准的问题（改用 ISO 8601）。
- 修复任务执行后状态卡在「即将执行」不更新的问题。

**用户名唯一性：**

- 改进用户名重复时的错误提示，明确指出被占用的用户名。

**版本号：**

- 后端 `.env` APP_VERSION 更新为 6.6.0。
- 前端 `package.json` 版本更新为 6.6.0。
- Footer / Login / About 页面版本号更新为 v6.6.0。

---

## v6.5.0 (2026-06-22)

- 课程模块学期过滤与周次计算优化。
- 爬虫调度稳定性提升。
- 设置项审计与映射修正。
- 版本号更新为 6.5.0。
