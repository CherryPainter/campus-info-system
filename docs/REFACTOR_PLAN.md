# 重构方案 Plan：统一任务模型

> 版本：v1.0 ｜ 创建：2026-07-13 ｜ 更新：2026-07-13 ｜ 状态：**阶段 2 + 阶段 3 均已完成（后端）**
> 适用范围：Push_System_Flask（后端） + admin-frontend（前端）
> 触发背景：课程管理全量爬取任务结束后前端状态不更新（已修复 `4da5941`），根因为任务轮询/状态管理各自为政、特制模块分散。

---

## 一、背景与目标

系统存在 4+ 套分散、特制的任务轮询/状态管理机制，同一类 Bug（轮询提前终止）会跨页面重复出现。本方案目标：

- 把「课表爬虫 / 全量爬取 / 定时爬取 / 推送任务」四类后台作业，统一成 **一套状态机 + 一个查询接口 + 一个前端 Hook 供给所有页面**。
- 消除重复代码与历史 Bug 根因；新增任务类型（如天气全量刷新）零轮询代码即可接入。

---

## 二、系统「各自为政」模块全景（审计结果）

### 后端（高严重度）
| # | 模块 | 现状 | 统一目标 |
|---|---|---|---|
| 1 | 任务状态机 | 内存 `_spider_status` + `TaskProcess`/`ScheduledCrawlTask`/`PushTask` 三张表各一套状态枚举 | 统一 `TaskStatus` 枚举 + `BaseTask` 基类 |
| 2 | 爬虫调用入口 | `scheduler.run_spider` 与 `crawl_task_service._crawl_one_semester` 两处 subprocess 调 main.py，env/超时/重试各自实现 | 统一 `SpiderRunner` 封装 |
| 3 | 进程记录写入 | `process_routes.create_task_process` + `delivery_service._create/_update_push_process` 三处分散 | 统一 `TaskService` 唯一写入入口 |
| 4 | API 响应格式 | 无统一封装，各路由内联 `{status,data,message}`，形态各异 | `api_response` 工具（后续阶段 2） |
| 5 | 服务层目录 | `app/service/`（单数）与 `app/services/`（复数）并存 | 合并为单一 service 层（阶段 2） |
| 6 | 日志与配置 | 爬虫自带 `logger.py`/`config.py` 平行副本，与 app 的 `get_logger`/`core/config` 分叉 | 复用 app 统一 logger/config（阶段 3） |
| 7 | 鉴权与环境 | JWT + DynamicToken + ADMIN_TOKEN 三套 token；`get_client_ip` 三处；`security_before_request` 与 `@path_security_check` 重复 | 收敛 JWT + 统一工具（阶段 3） |

### 前端（高严重度）
| # | 模块 | 现状 | 统一目标 |
|---|---|---|---|
| 1 | 任务轮询 | 9 处 `setInterval` 各自实现，含 3 处「按 ID 轮询」近乎逐字复制、2 处「爬虫状态」间隔不一致（2s vs 30s） | 三个统一 Hook（见第三节） |
| 2 | ApiResponse 类型 | 在 6 个 api 文件各定义一遍 | 单一 `src/types/api.ts`（阶段 2） |
| 3 | 用户类型 | `UserInfo`（auth）与 `User`（admin）双份，`id` 类型不同 | 单一 `User`（阶段 2） |
| 4 | 分页结构 | `processApi`/`pushApi`/`ipBlacklist` 三种嵌套形态 | 统一 `Paginated<T>` + 适配层（阶段 2） |
| 5 | 状态映射 | `statusMap`/`crawlStatusMap`/`TASK_STATUS_MAP` 三份拷贝 | 共享 `statusMaps.ts`（阶段 2） |
| 6 | 消息提示 | 新页面 `App.useApp()` vs Blacklist 20 处静态 `message` | 统一 `useMessage` + `showApiError`（阶段 2） |
| 7 | 共享与工具 | 当前学期 Course/CrawlScheduler 各自拉取未共享；日期格式化散落 30+ 处 | `useSemesters` Hook + `formatDateTime`（阶段 2） |

### 本次执行范围
**阶段 1 + 阶段 2 + 阶段 3 均已完成**（阶段 1：统一任务模型；阶段 2：服务层合并 + API 响应封装 + 前端类型/分页/状态映射/消息/共享工具统一；阶段 3：鉴权/security 收敛 + 爬虫 config 安全化）。

---

## 三、核心重构：统一任务模型（阶段 1 详细设计）

### 3.1 后端设计

**A. `app/core/task_state.py`（新增，无破坏性）**
- 定义枚举 `TaskStatus = PENDING / RUNNING / COMPLETED / COMPLETED_EMPTY / FAILED / CANCELLED`（注意：用 `COMPLETED` 而非 `SUCCESS`，与前端 Hook 约定 `completed` 一致）
- 定义 `TaskType = SPIDER / COURSE_FULL_CRAWL / COURSE / WEATHER / ELECTRICITY / CRAWL / CUSTOM / SYSTEM`
- 提供 `is_terminal(status)`、`is_running(status)`、`is_success(status)` 工具函数
- 三张表（TaskProcess / ScheduledCrawlTask）的 `status` 字段 `default=` 统一引用本枚举常量；PushTask 队列子系统状态词（pending/processing/success/...）属独立体系，保持不动
- 所有写入点（scheduler / crawl_task_service / process_routes / delivery_service）硬编码状态字符串改为引用 `TaskStatus.*`

**B. `SpiderRunner`（新增，替代 2 处 subprocess）**
- `app/services/spider_runner.py`：封装 `subprocess.run([python, 'main.py', *args], env=..., timeout=...)`，env 注入 `JWXT_HEADLESS`/`TESSERACT_CMD`
- `scheduler.run_spider` 与 `crawl_task_service._crawl_one_semester` 改为调用 `SpiderRunner.run_spider_process(...)`；删除 `crawl_task_service._spider_env` 重复实现

**C. `UnifiedTaskService`（新增，唯一写入入口）**
- `app/services/unified_task_service.py`（文件名区别于既有 push 队列 `task_service.py`）：提供 `create_process` / `update_progress` / `complete_process` / `get_running` / `get_by_id`
- `process_routes.create_task_process` / `complete_task_process` / `update_task_progress` 与 `delivery_service._create_push_process` / `_update_push_process` 均委托至此
- 注意：既有 `app/services/task_service.py` 是推送队列（push_task_queue）的落库+重试子系统，与 TaskProcess 写入无关，保持独立不合并

**D. 统一查询接口 `GET /api/tasks/:id`**
- 新增 `app/api/task_routes.py`：返回 `{status, data: {...}, message}` 统一结构
- 按 `task_type` 路由到对应表读取（spider→task_processes，crawl→scheduled_crawl_tasks，push→push_task_queue）
- `get_spider_status` 改造：优先查 `task_processes` 表（type=spider）最新记录，内存 `_spider_status` 作为兜底/缓存，消除内存态竞态

**E. `UnifiedTask` 模型（务实路径）**
- **不新建物理表、不做数据迁移**（避免生产环境风险）。
- 采用「`task_processes` 扩展承载统一任务类型」的务实路径：所有任务类型的状态读写经 `TaskService` 落现有表，状态词统一引用 `TaskStatus` 枚举。
- 物理表合并为后续可选优化，不在本阶段。

### 3.2 前端设计

**A. `src/hooks/useTaskPolling.ts`（新增）**
```ts
useTaskPolling(taskId, { getStatus, interval?, onSuccess?, onFailed? })
// 按 ID 轮询终态，统一清理定时器；内部含 pending→running→success/failed 全周期
```

**B. `src/hooks/useRunningTasksPolling.ts`（新增）**
```ts
useRunningTasksPolling({ taskType?, getRunning, onIdle? })
// 轮询运行中任务列表，空则回调刷新（合并 Course/Weather/Electricity 三处同质逻辑）
```

**C. `src/hooks/useIntervalPolling.ts`（新增）**
```ts
useIntervalPolling(fetcher, interval, enabled?)
// 页面周期刷新 / 时钟（Dashboard/Processes/ServerStatus 共用）
```

**D. 统一间隔常量 `src/hooks/pollIntervals.ts`**
```ts
export const POLL_FAST = 2000; export const POLL_NORMAL = 5000; export const POLL_SLOW = 30000;
```
替换散落的 2s/3s/5s/30s。

**E. 页面接入（删除原 9 处散落轮询）**
- `Course.tsx`：`startSpiderPolling`→`useTaskPolling`；`fetchRunningTasks`/`checkRunningTasks`→`useRunningTasksPolling`；`startCrawlTaskPolling`→`useTaskPolling`
- `Weather.tsx` / `Electricity.tsx`：`checkRunningTasks`+`setInterval`→`useRunningTasksPolling`；`startPollingWithTaskId`→`useTaskPolling`
- `Tasks.tsx`：`fetchSpiderStatus` 30s→统一间隔 + 经 `useIntervalPolling`
- `Processes.tsx`：爬取/进程/定时任务轮询→对应 Hook
- `CrawlScheduler.tsx`：自身 `startPolling(taskId)`→复用 `useTaskPolling`
- `ServerStatusProvider.tsx`：存活探测→`useIntervalPolling`

### 3.3 迁移步骤与风险

| 子阶段 | 内容 | 风险 | 回滚 |
|---|---|---|---|
| 1.1 | 前端抽三个 Hook + 统一间隔常量，接进现有轮询（不改后端） | 低 | 旧逻辑删除前保留 `.bak` |
| 1.2 | 后端加 `task_state`/`SpiderRunner`/`TaskService`/统一接口；`get_spider_status` 先并行双读（DB+内存），灰度后切 DB | 中 | 旧路由保留兼容期 |
| 1.3 | 三张表 `status` 字段对齐枚举常量；业务写入点分批改经 `TaskService` | 中 | 枚举为纯常量别名，零 Schema 变更 |

---

## 四、整体重构路线图（阶段 2/3 另排期）

| 阶段 | 范围 | 价值 | 风险 |
|---|---|---|---|
| 阶段 1（本次） | 统一任务模型 | 修掉轮询类 Bug 根因；新增任务零轮询代码 | 中 |
| 阶段 2 | 服务层统一 + 业务分层 + API 响应封装 + 前端类型/分页/状态映射统一 | 消除重复、降低新增功能成本 | 中高 |
| 阶段 3 | 日志/配置副本合并、token 收敛到 JWT、`get_client_ip`/`security` 统一 | 安全面收敛、排障统一 | 低-中 |

---

## 五、执行状态追踪

- [x] 2026-07-13 方案 Plan 定稿（REFACTOR_PLAN.md）
- [x] 1.1 前端：三个 Hook + 间隔常量（提交 `6c3473f`）
- [x] 1.1 前端：各页面接入 Hook，删除散落轮询（提交 `6c3473f`，tsc + build 通过）
- [x] 1.2 后端：task_state.py 统一枚举（TaskStatus/TaskType + 三表 default 引用）
- [x] 1.2 后端：SpiderRunner 统一爬虫入口（替代 scheduler + crawl_task_service 两处 subprocess）
- [x] 1.2 后端：UnifiedTaskService 唯一写入入口（process_routes + delivery_service 委托）
- [x] 1.2 后端：GET /api/tasks/:id 统一接口 + get_spider_status DB 兜底
- [x] 1.3 三张表 status 对齐枚举 + 业务写入点改经 UnifiedTaskService
- [x] 联调验证：py_compile 全量通过；import 冒烟（task_state/spider_runner/unified_task_service/process_routes/delivery_service/crawl_task_service/scheduler 无循环依赖）；SpiderRunner 功能测试（临时脚本验证参数+JWXT_HEADLESS 注入）通过

- [x] 2.0 后端 #5：合并 `app/service` 与 `app/services` 为单一服务层（提交 `fcf09bc`）
- [x] 2.1 后端 #4：新增 `app/core/api_response.py`（api_success/api_error/api_paginate）+ 迁移 `app/api` 全部 28 个路由文件（提交 `7d74b6b`）
- [x] 2.2 前端 #2：抽取 `src/types/api.ts`（ApiResponse/Paginated），6 个 api 文件改引用（提交 `3a775c3`）
- [x] 2.3 前端 #4：各 api 加适配层归一为 `Paginated<T>`，消费页面统一读 `res.data` + `res.pagination`（提交 `0ffe888`）
- [x] 2.4 前端 #3：合并 UserInfo/User 为单一 `src/types/user.ts` 的 User（id:number），UserContext/Login/Profile/UserManagement 同步（提交 `3f687a4`）
- [x] 2.5 前端 #7：新增 `src/utils/datetime.ts` + `src/hooks/useSemester.ts` + `src/utils/semester.ts`，Course/CrawlScheduler 共用（提交 `cdcd519`）
- [x] 2.6 前端 #5：新增 `src/constants/statusMaps.ts`（7 个共享映射），Push/Processes/Dashboard/Webhooks/Blacklist/ipBlacklist 接入（提交 `e49f813`）
- [x] 2.7 前端 #6：新增 `src/utils/message.ts`（useMessage/showApiError），Blacklist/CrawlScheduler/Webhooks 静态 `message` 转 `App.useApp()`（提交 `b21bc21`）
- [x] 联调验证（阶段 2）：后端 py_compile 全量通过 + api_response import 冒烟通过 + 无残留单数 `app.service` 导入；前端 `tsc --noEmit` 通过（build 通过）

- [x] 3.1 后端 #7：删除 `app/utils/token.py` DynamicToken 死代码（全仓零调用，无业务引用）（提交 `a0ab501`）
- [x] 3.2 后端 #7：auth_routes.py 三处内联 IP 提取（登录限流/登录/MFA）统一为 `app.utils.security.get_client_ip()`，修复登录限流可被 `X-Real-IP` 伪造绕过（提交 `a0ab501`）
- [x] 3.3 后端 #7：删除 `security.py` 中与 `_run_security_checks` 100% 重复的 `path_security_check` 装饰器及 `security_check` 别名；移除 `routes.py:30` 的 `@path_security_check`（index 已在 `/api/*` 被 `global_security_check` 覆盖，属重复校验）（提交 `a0ab501`）
- [x] 3.4 后端 #6：安全化爬虫 `config.py`——移除将教务系统用户名明文打印到 stdout 的泄露隐患、移除 `.env` 多路径探测噪音；保留 `from app.core.config import Config` 复用统一配置，CONFIG 字典形态与配置值不变（提交 `320a7db`）
- [x] 3.5 后端 #6：说明 `logger.py` 为爬虫子进程专属日志器（每轮时间戳独立文件 + 历史备份），因 subprocess 不启动 Flask、`setup_logger` 永不调用，强行统一到 app root-logger 会导致 INFO/DEBUG 静默丢失，故保留；完整收敛为后续可选项
- [x] 联调验证（阶段 3）：后端全量 py_compile 通过；security 模块 import 冒烟通过（`get_client_ip` 可用、`path_security_check` 已移除、`security_before_request` 保留）；爬虫 `config`/`logger` 子进程导入冒烟通过（CONFIG 七键齐全、每轮日志文件正常生成、行为不变）；无残留 `path_security_check`/`token_manager`/`DynamicToken` 引用

> 注：阶段 1+2+3 全部完成。后端阶段 3 提交 `a0ab501`（#7）+ `320a7db`（#6）；阶段 1/2 提交见上。
> 后续动作：重启后端使新代码生效；前端重新 `npm run build` 部署 dist（阶段 2 产出）；可选验证 `GET /api/tasks/:id`；logger.py 完整收敛为后续可选项（需评估改变日志落盘行为的影响）。
> 关于"三套 token"的澄清：经审计仅 JWT 为真实在用的请求鉴权机制；DynamicToken 为死代码（已删）；ADMIN_TOKEN 实为初始管理员密码环境变量（非请求头令牌），属误归类，无需改动。
