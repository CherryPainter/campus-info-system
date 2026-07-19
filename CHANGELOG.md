# 校园信息聚合与智能推送系统 · 更新日志

> 版本号规则：后端 `.env` / `app/core/config.py` 的 `APP_VERSION`、前端 `package.json` 的 `version`、前端 `src/version.ts` 的 `APP_VERSION` 以及各部署/配置文档须保持一致。

---

## v6.11.6 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。修复学期切换的两处隐患（提交 `6d21ee9`）。

### 隐患1：课表推送跨学期串扰（schedule_service.py / course_repository.py）
- **问题**：`ScheduleService.load_schedules` 经 `CourseRepository.get_all` 加载课程时**不过滤学期**，会把库里所有学期的课程按 `week_number` 排到本周日期推送。新学期开始后，新旧学期 `week_number` 均 1..20、共用同一全局锚点，锚点重置后两学期同周次课程被排到同一天、一起推送，用户每天收到重复课表。
- **修复**：`get_all` 新增可选 `semester_id` 参数（默认不过滤，兼容旧调用方）；`load_schedules` 仅加载 `derive_current_semester()` 的当前学期，与前端默认学期一致。

### 隐患2：重爬旧学期污染第1周锚点（pipeline.py）
- **问题**：`CourseWeek.week_number` 全局唯一，而爬虫 `_calculate_date` 把每门课日期盖成"本周"，不反映真实学期日历；`get_week_number` 只能正确表示单一学期时间线。重爬旧学期会据此覆盖 `CourseWeek.week_number==1` 起始日，破坏正在用的当前学期周次。v6.11.5 的 Fix B 把此隐患波及面从"重爬 N=1"扩大到"重爬任意 N≥1"。
- **修复**：`pipeline.save_to_database` 增加 `_is_current_semester` 闸门——仅当 `semester_id` 命中当前学期（或每日爬虫未指定学期、即当前周）才写/维护 `CourseWeek` 锚点，旧学期爬取整段跳过，避免污染全局 week1 锚点。当前学期的锚点维护行为不变（Fix B 仍生效）。

### 日志口径修正：消除重爬假警报（crawl_task_service.py / pipeline.py / scheduler.py）
- **问题**：`pipeline.save_to_database` 之前仅返回"新建数"。重爬已存在课程时新建数为 0，但数据已刷新（命中更新分支）；`crawl_task_service` 却据此打印 `WARNING 学期 X 未导入任何课程（可能无排课数据）`，且任务状态被置为 `COMPLETED_EMPTY`、消息"未获取到任何课程数据"——属典型的"狼来了"假警报，正常重爬也会每天刷 warning、误导排查。
- **修复**：`save_to_database` 返回值由 `int` 改为 `(新建数, 更新数)` 元组（空结果护栏 / 异常分别返回 `(0, 0)` / `(-1, 0)`，契约兼容）；`crawl_task_service` 据此精确分级——
  - 新建 0 **且**更新 0 → 仍 `WARNING`（确无排课 / 爬虫解析退化，空结果护栏已另告警）；
  - 新建 0 但更新 > 0 → 降级为 `INFO`「重爬刷新完成（新增 0 条 / 更新 N 条），属正常」，**不再告警**；
  - 新建 > 0 → `INFO` 正常导入日志。
  - 单次/指定学期爬取的任务消息同步修正：有更新时状态为 `COMPLETED`、消息「重爬刷新 N 门课程（新增 0 条），属正常」，不再误报空。
- 同步更新 `scheduler.py` 每日爬虫入库日志（新增/更新分列）与 README 文档中 `return 0` 的旧描述。

---

## v6.11.5 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。课程全量爬取入库日志口径修正 + 课表错周锚点修复（Fix A + Fix B，均来自生产日志排查，提交 `e31b5dd`）。

### Fix A：课程入库日志区分"新增 / 更新"（course_repository.py / pipeline.py / course_routes.py / reimport_with_teacher.py）
- **问题**：`CourseRepository.create_batch` 仅返回"新建数"。库内已有课程时全部命中 update 分支、新建数为 0，日志显示"成功保存 0 条"，与"实际入库条数"严重不符，排查时易被误读为丢数据。
- **修复**：`create_batch` 改返回 `(新建数, 更新数)` 元组，命中既有记录计为更新；`pipeline.save_to_database` 日志与任务进程消息改为"新增 X / 更新 Y"；`course_routes.py`、`reimport_with_teacher.py` 及测试同步解包。`save_to_database` 对外仍返回新建数，`crawl_task_service` 的 `<0`/`==0` 判断行为不变。

### Fix B：补全第 1 周锚点，修复课表错周（pipeline.py）
- **问题**：`save_to_database` 仅 upsert `CourseWeek(week_number=top-level)`。当爬取数据最早周次 > 1（如本批数据从第 2 周开始、无第 1 周课程）时，`CourseWeek.week_number==1` 不存在，`get_week_number` 回退 `MAX(week_number)` 导致课表加载错周、报"0 条课表数据"。
- **修复**：入库时按日历反推并 upsert 第 1 周锚点：`week1_start = 当前周周一 − 7×(N−1)`、`week1_end = week1_start + 6 天`。恢复后 `get_week_number` 周日前返 1、周一（2026-07-20）起正确返 2；当 top-level `week_number==1` 时推导值与原逻辑完全一致（幂等，无 schema 改动）。
- **验证**：改动文件 `py_compile` 全过；`pytest tests/test_course_admin_protection.py` 4 例全绿（sqlite 内存库，新建/更新计数断言正确）。

---

## v6.11.4 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。Redis 写入探针的动态冷却恢复 + 边缘兜底，并完成一次后端安全代码审查，修复若干中低风险隐患。

### Redis 冷却期自动恢复 + 边缘兜底（ip_blacklist_service.py）
- **非阻塞探针**：为 Redis 连接设置 `socket_family=AF_INET`、`socket_connect_timeout=2`、`socket_timeout=2`，避免连接卡死拖垮请求。
- **冷却自动恢复**：新增 `REDIS_UNAVAILABLE_COOLDOWN=60` 秒冷却窗口；Redis 探测失败后进入冷却，期间复用上次结果，冷却结束自动重试，无需重启服务即可恢复。
- **边缘兜底**：`is_account_high_risk` 等判断在 Redis 异常时走 try/except 兜底分支（退化为宽松/保守默认），杜绝因缓存层抖动导致的请求级崩溃。

### 安全代码审查修复（详见 `docs/安全代码审查报告_v6.11.4.md`）
- **F1 配置注入防护**：`config_routes.update_config` 拒绝含 `\r`/`\n` 的配置值，并将 `SECRET_KEY`、数据库口令、Redis 地址等安全关键项列入写入黑名单（403），杜绝通过接口篡改 `.env`  poisoning。
- **F2 日志注入防护**：`security.py` 新增 `_strip_crlf()`，在记录客户端 IP / User-Agent 前剥离回车换行，防止伪造日志行。
- **F3 路径穿越防护**：`push_routes` 新增 `_resolve_safe_image_path()`，自定义推送图片路径强制限定在 `BASE_DIR` 内，拒绝绝对路径与 `..`，消除后台可达的路径遍历。
- **F4 调试日志清理**：移除 `login_mfa` 中两处打印 Cookie 的 `[DEBUG]` 日志，避免凭证痕迹落盘。
- **结论**：未发现可直接利用的高危漏洞；鉴权（JWT 签名 + admin_required 分层）、SQL 注入（全参数化/ORM）、命令注入（列表式 subprocess、无 shell）、反序列化（无 pickle/yaml.load）、密钥管理（v6.11.0 已强制 env 必填）均确认安全。

---

## v6.11.3 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。限流器 Redis 不可用时的可用性兜底 + 启动期基础设施探针 + 启动自动增量迁移补列；后台权限页文案重命名。

### 限流器 Redis 不可用内存降级（extensions.py）
- `Flask-Limiter` 启用 `in_memory_fallback_enabled`：Redis 不可用时自动回退到进程内存限流，不再因缓存层缺失直接 500，同时消除生产环境 Redis 抖动拖垮登录的隐患。

### 启动期 Redis 状态探针（ip_blacklist_service.py）
- 新增 `log_redis_status()`，启动期明确打印 Redis 连接状态（已连接 / 用内存 / 连接失败降级内存），便于部署时快速确认限流与黑名单缓存后端。

### 启动自动增量迁移补列（app/__init__.py + init_db.py）
- 启动流程在 `init_database()` 后调用 `init_db.cmd_migrate()`，自动比对模型字段、补建缺失表/列/索引（阶段 A/B/C），根治字段漂移；幂等可重复，带异常兜底不影响启动。

### 后台权限页文案（前端）
- 用户与权限页「黑名单」Tab 更名为「访问控制」（纯展示文案调整，无行为变化）。

---

## v6.11.2 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。补 6.11.1 课程数据来源标记的缺口：手动课（`admin`）此前无任何保护，会被每日/全量爬虫覆盖或挤占。

### 手动课保护（data_source='admin'）
- **后台建/改课打标**：`course_routes.py` 的创建、多节次更新、单条更新三处落库均显式写入 `data_source='admin'`（此前缺失，自建课会落为模型默认 `full`，系统不知其为手动课，进而被爬虫当普通课覆盖）。
- **爬虫不可覆盖手动课**：`CourseRepository.create_batch` 在来源为爬虫（`full`/`daily`）时：
  - 命中已有记录且为 `admin` → 跳过，保留人工修正；
  - 同时间槽（`week_day` + `period_idx` + `week_number`）已被 `admin` 占据 → 不插入第二条，避免同一格子出现两门课；
  - 手动来源（`admin`）调用 `create_batch` 不受影响，仍可正常 upsert 自身。
- 单元测试 `tests/test_course_admin_protection.py`：4 例覆盖"爬虫不覆盖手动课 / 爬虫不挤占手动课槽位 / 爬虫正常更新爬虫课（回归）/ 手动来源管理手动课"，全量 33 例通过。

---

## v6.11.1 (2026-07-19)

> 发版类型：**功能增强（minor）**。课程数据来源标记 + 每日爬虫入库当前周 + 空结果护栏，缓解"解析非 100% 时数据可信度"问题。

### 数据来源标记（data_source / last_verified_at）
- `courses` 表新增两列：`data_source`（`full`=全量/指定学期爬虫写入、`daily`=每日爬虫写入当前周、`admin`=后台手动新增/编辑）、`last_verified_at`（最后被爬虫写入/校验的时间）。`init_db.py migrate` 阶段 B 自动补列（无需手写迁移）。
- `CourseRepository.create_batch`：命中已有记录时刷新 `data_source` 与 `last_verified_at`；新建记录写入来源标记。前端 `to_dict` 输出这两字段（供后续"来源标签/最后校验时间"展示使用）。

### 每日爬虫入库当前周（实现每日校验）
- `scheduler.run_spider` 每日爬虫成功后，额外调用 `pipeline.save_to_database(..., data_source='daily', create_task_process=False)`，把"当前周"数据 upsert 入库。
- 用每日爬取的当前周正确数据修正全量爬取的当前周错误，达成"每日校验"。因 `create_batch` 是 upsert 且只更新不删除，**非当前周的历史数据仍只由全量爬取维护**（每日爬虫按设计只爬当前周，碰不到历史周）。
- `create_task_process=False`：每日爬虫已有自己的 `spider` 进程记录，避免再生成冗余的 `course_full_crawl` 进程记录污染执行历史。

### 空结果护栏
- `save_to_database` 在 `courses` 为空时**拒绝入库**（`return 0`，不会清空库——upsert 本就不删除），并区分：
  - 数据库该周已有历史课程 → 判定"疑似解析退化"，`logger.error` 升级告警 + 经 `WECOM_STATUS_WEBHOOK` 发送企业微信告警；
  - 否则 `logger.warning` 提示。
- 顺带修复潜在 `NameError`：原成功日志引用 `week_start/week_end`，但二者仅在课程含 `date` 字段时才定义；现已初始化并在无日期时降级为不带日期范围的日志。

### 重要边界
- 历史周（非当前周）若全量爬取写入了错误数据，仍需一次正确的"全量/指定学期爬取"覆盖；每日爬虫只覆盖当前周。

---

## v6.11.0 (2026-07-19)

> 发版类型：**安全加固（minor）**。五项生产级安全配置加固，对应安全审计中标注的高风险项。

### 安全加固
- **① SECRET_KEY 改为环境变量必填（最高优先级）**：`config.py` 改为 `os.getenv('SECRET_KEY')`；生产环境（`DEBUG=false`）缺失时启动即 `RuntimeError` 失败，杜绝"每次重启所有 JWT/Session 失效 / 多实例密钥不一致"。开发环境允许不安全默认并告警。`.env` 已写入强随机值（gitignored，不入库）。
- **② Flask-Limiter 存储改为 Redis**：`extensions.py` 的 `storage_uri` 改为 `os.getenv("REDIS_URL") or "memory://"`。多 worker 与重启后限流状态不丢失，与已有的 IP 封禁 / 登录限流 / 安全事件体系一致；`REDIS_URL` 为空时回退内存（兼容测试与单机开发）。
- **③ 强制管理员 MFA（含首次引导）**：`auth_routes.py` 登录逻辑在密码校验通过后判断——`role=='admin'` 且未启用 MFA 时，若系统内已有其他 MFA 用户则**拒绝登录并要求先完成 MFA 设置**（423 + 明确提示）；若系统内尚无任何 MFA 用户（首次部署），放行但响应 `mfa_setup_required=true` 引导去个人中心绑定，避免永久锁死。文档可写"管理员账户强制启用多因素认证"。
- **④ 登录风险策略：多 IP 围攻改为账号风险升级（不再封攻击源 IP）**：维度五"账号遭多 IP 围攻"处置由"临时封攻击源 IP"改为"提升账号风险等级 HIGH"（`account_risk`，不封 IP），避免 NAT / 公司出口 / 校园网等共享出口被误封。若账号已启用 MFA，则密码正确时照常强制 MFA 挑战（攻击者无 TOTP 被拦，正常用户不受影响）；未启用 MFA 的账号依赖其他维度限流。新增 `IPBlacklistService.is_account_high_risk()` 读取风险标记。前端标签由"账号遭多IP围攻(临时封禁)"改为"账号遭多IP围攻(风险升级)"。
- **⑤ CORS 生产配置**：跨域来源变量由写死 `CORS_ORIGINS` 改为 `ALLOWED_ORIGINS`（逗号分隔，支持多个真实域名），兼容旧名 `CORS_ORIGINS`；开发默认含 localhost 端口便于联调，生产由 env 收口。

### 测试 / 文档
- 单元测试更新：维度五用例改为断言 `account_risk` + `risk_level='HIGH'` + `is_account_high_risk` 行为（不再有 `target_ips` / `temp_block`）；新增 `test_is_account_high_risk_false_by_default`。总计 29 例全绿。
- README「环境变量配置」补充 SECRET_KEY 不硬编码说明、新增 `FORCE_ADMIN_MFA`、CORS 改为 `ALLOWED_ORIGINS`。
- `.env.example` 同步：版本号、SECRET_KEY 说明、CORS 改名、新增 `FORCE_ADMIN_MFA`。

---

## v6.10.2 (2026-07-18)

> 发版类型：**缺陷修复（patch）**。修复安全事件自动封禁「配置了封禁时长却没生效、一律永久」的隐患。

### 修复
- `AUTO_BLOCK_THRESHOLDS` 里早已为各类自动封禁定义了 `block_duration_hours`（DDoS 探测 24h、安全违规 72h 等），但 `record_event` 触发自动封禁时**没有把该时长传给 `block_ip`**，导致 `duration_hours` 取默认 `None` = **永久封禁**——配置形同虚设。
- 现 `_check_auto_block` 返回值新增 `duration_hours`（四元组），`record_event` 据此按配置**限时封禁**，到期自动解除。红线：**自动封禁一律限时、可自愈**；只有管理员手动封禁才可永久，避免正常 IP 被误判后永久拉黑、需人工解封。
- 单元测试增强：`test_record_event_auto_block` 断言自动封禁记录 `expires_at` 非空（限时），而非永久。

---

## v6.10.1 (2026-07-18)

> 发版类型：**缺陷修复（patch）**。修复 v6.9.0 引入的"账号级失败锁账号"自 DoS 隐患。

### 修复
- 账号级登录失败计数的 key 由"仅用户名"改为"(IP,账号)"，达阈值只限流该 IP（429），**不再锁账号、不影响其他来源**——攻击者无法靠试错把 admin 自己锁在门外。
- 新增维度五"账号遭多 IP 围攻"：同一账号窗口内被 ≥5 个不同来源 IP 试密，自动临时封禁这些攻击源 IP（非永久）并告警，但**账号本身永不锁**，可扛分布式爆破 admin。
- `_login_failure_response` 移除 423 锁账号分支，temp_block 改为按 `target_ips` 封禁全部攻击源；`reset_login_counters` 同步清理新维度计数。
- 前端黑名单来源/事件标签补充 `login_account_target`（账号遭多IP围攻），"登录风险"高亮覆盖该来源。
- 单元测试同步更新（信号感知用例改为 per-(IP,账号) 限流 + 新增多IP围攻用例）。
- 修复 `reset_login_counters`（登录成功后清计数）清错 key 的 bug：原按"仅用户名"清，与维度一写入的"(IP,账号)" key 不匹配，导致 per-(IP,账号) 计数无法清零；现按 `ip:username` 清除（并兼容旧版 username-only key）。同步修正多IP围攻用例：第 6 个新攻击 IP 在窗口内仍应被临时封禁（即"多IP围攻"持续生效，账号本身不锁）。

---

## v6.10.0 (2026-07-18)

> 发版类型：**新功能（minor）**。真实推送失败时自动标记 Webhook 为失效。

### 新功能

#### 真实推送失败自动标记 Webhook 失效
- 以往 Webhook 的 `last_test_status` 只在管理页手动点"测试"时更新；真正发通知时失败，管理页看不出来。
- 现在 `WeComAdapter.send` 在每次真实推送后，把成败写回数据库里**匹配该 URL 的 Webhook 记录**：
  - 推送失败（HTTP 非 200 / 企业微信 `errcode != 0` / 异常）→ 标记 `failed`（管理页"测试"列显示红色"失败"徽标）；
  - 推送成功且此前为 `failed` → 自动恢复为 `success`（瞬时故障恢复后自动清除红标）。
- 仅在与当前状态不同（发生状态迁移）时才写库，避免正常轮询频繁写库；写库异常被吞掉，绝不影响主推送流程。
- 覆盖路径：课程 / 天气 / 电费 / 系统通知经 `adapter_service` 发送的全部 Webhook（即管理页列出的 DB 记录），含多 Webhook 群发与图片发送。

### 说明 / 边界
- 企业微信对"已移除机器人"的 key 仍可能返回 `errcode:0`（平台行为），这类"假活"仍无法自动识别——与 v6.9.1 测试接口的边界一致。
- 调度器里基于环境变量 `WECOM_STATUS_WEBHOOK` 的状态通知为 env-only 单 URL、不在管理页，故未纳入标记（无 UI 可展示）。

---

## v6.9.1 (2026-07-18)

> 发版类型：**修复 / 规范（patch）**。Webhook 测试健壮性加固 + 全项目源码禁用 emoji。

### 修复与加固

#### Webhook 测试检测更准确
- 测试逻辑加固：HTTP 非 200、或企业微信返回 `errcode != 0`（如 `93000 无效 key`）均判为失败并回传原始响应；非 JSON 响应安全降级；无 `errcode` 字段的通用 webhook 仅以 HTTP 状态码判断。
- 说明：企业微信 `send` 接口对"已移除机器人"的 key 仍可能返回 `errcode:0`（平台行为，无查询机器人存续的 API），此类情况无法仅靠测试接口检出；真正失效的 key（errcode 非 0）现可被正确识别。

### 规范
- 项目源码与推送给用户的消息（企业微信通知、webhook 测试消息等）一律禁用 emoji，严重程度/状态改用纯文字（警告 / 严重 / 提示）。已清理 webhook 测试消息、登录安全告警、IP 封禁告警中的 emoji。

---

## v6.9.0 (2026-07-18)

> 发版类型：**安全重构（minor）**。登录失败处置从"一刀切密码爆破封禁"重构为**信号感知**分层判定，降低共享 IP / NAT 误封风险。

### 🔒 安全重构：登录失败「信号感知」

此前 v6.8.3 将"5 分钟内登录失败 N 次"统一判定为密码爆破并封 IP，存在两类问题：
1. **信号歧义**——真人忘密码、校园网 NAT 下多人各自输错叠加，都会触发"爆破"判定；
2. **误封共享 IP**——对 NAT / 办公网出口 IP 永久封禁会连坐大量正常用户。

v6.9.0 改为按**四个独立信号维度**分别滑动窗口计数（Redis ZSET，内存字典兜底），按严重程度取最高优先级处置，并**不再对任何 IP 自动永久封禁**：

- **维度一 · 账号级**（同一账号失败次数，仅密码错计入）→ 临时锁定**该账号**（返回 423，不碰 IP，避免误伤共享 IP）。
- **维度二 · IP 跨账号**（同一 IP 窗口内失败涉及的**不同账号**数）→ 疑似撞库/枚举：3 个不同账号限流（429，不封禁）；5 个不同账号临时封禁 1 小时（`source=login_brute_tier2`，非永久）。
- **维度三 · IP 枚举**（同一 IP 窗口内"用户名不存在"涉及的**不同用户名**数）→ 8 个不同用户名限流（429，`source=login_enum`）。
- **维度四 · IP 总量**（同一 IP 窗口内登录失败总次数，含空参数/异常客户端）→ 30 次/5分钟限流（429，`source=login_rate_limit`）。

各级处置均推送分级告警（区分账号锁定 / 限流 / 临时封禁），安全事件类型新增 `login_security`。

### 🎨 前端改进

#### 黑名单管理页标签更准确
- 来源映射更新：`login_brute_tier2` →「撞库/枚举(临时封禁)」；新增「用户名枚举探测」「登录限流」；事件类型新增「登录安全信号」。
- 原硬编码的"爆破"高亮标签改为更准确的"登录风险"，tooltip 从"登录密码爆破自动封禁"改为"登录安全自动处置"，与信号感知语义一致。

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

---

## v6.4.0 (2026-06-22)

**用户管理**：用户列表按角色优先级排序（主管理员 → 管理员 → 普通用户）；超级管理员可删除自己创建的管理员/用户、重置非根管理员 MFA；用户列表新增 MFA 状态标识。

**课程管理**：`periods`/`weeks` 字段由逗号分隔字符串改为 JSON 数组；修复创建/编辑课程类型不匹配报错；修复 `get_all` 未过滤已删除课程；编辑弹窗新增独立删除按钮。

**天气管理**：预警历史记录展示；降雨时段按时间顺序排序。

**其他修复**：普通用户登录后跳转首页而非天气页；日志角色动态显示；删除废弃 IP 地理限制配置；支持中文数字节次解析（"第一、二节"）；修复推送今日课表排版与通知样式不一致；修复 `UserMFA` 导入路径；修复天气配置 API 认证显示。

---

## v6.3.0 (2026-06-21)

**安全增强**：删除 IP 地域限制（支持全球访问）；SQL 注入检测 30+ 规则；XSS 检测 30+ 规则；请求大小限制 10MB；HTTP 方法验证；`sanitize_input()` 输入清理；请求审计日志；安全响应头（X-Content-Type-Options / X-Frame-Options / CSP / HSTS 等）；标准化错误响应；智能速率限制（身份感知）；预定义 strict/moderate/lenient/burst 限流级别；登录/MFA 用 strict 级别。

**配置清理**：删除 `IP_GEO_ENABLED` / `IP_GEO_ALLOWED_REGIONS`。

---

## v6.2.0 (2026-06-03)

**新增**：进程管理任务类型筛选；天气分析推送任务；普通用户欢迎页；进程自动清理（每天凌晨 2 点清 1 个月前记录）。

**优化**：按钮 hover 效果；天气时间改本地时区；任务卡片美化；Ant Design 废弃属性警告修复；React Router v7 兼容；统计基于全量数据。

---

## v6.1.0 (2026-06-03)

**优化**：项目更名「校园信息聚合与智能推送系统」；前端请求拦截器冷却机制防无限刷新；登录页不再触发多余认证请求。

---

## v6.0.0 (2026-06-02)

**重大更新**：数据库从 SQLite 全面迁移到 MySQL（课表/电量/天气/用户数据全量迁移）；新增 `webhooks` 表支持多 Webhook 配置。

**新增**：配置动态重载（改配置免重启、重注册定时任务）；模块配置后台管理实时生效；电量/天气/课程任务状态轮询；"同步课表"与"导入"功能区分。

**修复**：`config_routes.py` 缺 `os` 导入导致写 `.env` 失败；配置/任务时间修改不生效；Webhook 表缺失报错；MFA 二维码识别。

---

## v5.0.0 (2026-05)

**新增**：天气监控模块（和风天气 API）；电量监控模块（宿舍电表爬虫）；管理后台前端（React 19 + TypeScript + Ant Design Pro）；JWT 双 Token 认证；管理后台 API；天气分析规则引擎；Token 自动刷新；路由守卫；密码 bcrypt 哈希；Token 撤销黑名单。

**重构**：认证从动态 Token 全面迁移到 JWT Bearer Token。

---

## v4.1.3

- 课表爬虫稳定性优化；验证码识别准确率提升。

---

## v4.0.0

- 初始版本发布；课表推送核心功能；企业微信集成；推送规则引擎。
