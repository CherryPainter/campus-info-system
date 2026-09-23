# 校园信息聚合与智能推送系统 · 更新日志

> 版本号规则：后端 `.env` / `app/core/config.py` 的 `APP_VERSION`、前端 `package.json` 的 `version`、前端 `src/version.ts` 的 `APP_VERSION`（**管理端 `admin-frontend/src/version.ts` 与小程序端 `miniapp-frontend/src/version.ts` 各一份**）以及各部署/配置文档须保持一致。

---

## Unreleased

### 修复：课表爬虫把"风控/未渲染完"的空壳页当有效课表保存（后端，2026-09-23）
- **现象**：用户反馈当天（周三）应 1-8 节都有课，应用只显示上午。
- **根因**：教务系统 EAMS 在被"过快点击"限流或课表尚未渲染完成时，返回的是只含导航链接的**空壳页**（`swal2` 弹窗、`startWeek` 仍在、`TaskActivity` 为 0）。爬虫"是否进入课表页"的判据含 `startWeek`，空壳页同样命中 → 误判成功；随后 `TaskActivity` 解析为空，回退 `_extract_schedule` 解析 HTML 表，得到形如 `[["[返回前页]"]]` 的**非空垃圾行**，又通过 `if merged_data.get("rows")` 校验 → 被当作有效整学期课表保存（`raw/course_table.json` 被覆盖成垃圾），`processed_course_table.json` 产出 0 门课。
- **后果**：`pipeline.save_to_database` 的"空结果护栏"（0 门课拒绝入库）保护了数据库不被清空，但也意味着**数据永远刷不新**——当前学期 20261 长期停在旧快照（`full` 7 门停在 2026-09-06、`daily` 6 门 weeks 恒为 `[3]`，均系残缺爬取的产物），今天只剩上午第 1 节。
- **改动**（仅 `app/cqie-course-timetable/main.py`，单点护栏；不改动作者已明确不做的"见弹窗即退避"逻辑）：
  - 新增模块函数 `_grid_has_real_courses(grid)`：排除表头（节次/周次）、星期名、节次名（第X节）、纯方括号导航文本后，仍存在任意非空单元格才判为"含真实课程"；
  - `_save_raw_data` 入口加**单点护栏**：解析结果不含真实课程时**拒绝落盘并返回 `False`**（覆盖全部调用方），保留上次成功数据；
  - 两处爬取出口（单周 `_get_course_table` 与整学期 `_get_all_weeks_auto`）据 `_save_raw_data` 的返回值判失败：返回 `None` 并记录明确错误（"疑似被过快点击限流或课表未渲染完成"），不再把空壳当成功。
- **验证**：`py_compile` 通过；用真实函数断言——`[["[返回前页]"]]` / 仅表头 / 空 rows / None / 空壳周期行 均判 `False`，含课程格的网格判 `True`（6/6 通过）。
- **待跟进（本次未做）**：① 本修复只防"残缺被当成功"，**真正补齐 20261 仍需一次成功的全量重爬**（可能需等风控冷却 / 有头模式人工等待）；② 派生开学日为 2026-09-01（`system.semester_start_date` 为空时按 term 推算），而 school 端渲染疑似慢一周，建议核对开学日配置以免"当前教学周"整体偏移；③ 失败那次已把 `output/course-data/images/course_week1.jpg` 重生成为**空白占位图**，如有对外推送需留意。

---

## v6.20.0 (2026-09-23)

### 修复：上学期课表课程误标"已结束/进行中" + 点击上学期课程详情页"课程信息不存在"（前端，2026-09-23）
- **用户反馈**：打开上学期课表 → 选「与本周相同的周次」→ 上学期（及对应本周）课程变灰；点上学期任一课程 → 课程详情页显示「课程信息不存在」。
- **根因一（变灰）**（`pages/coursetable/index.tsx` 的 `buildCellMap`）：
  - "进行中/已结束"实时态的判定 `isRealCurrentWeek` 仅比较「展示周次 == 真实教学周」，未判断"展示的学期是否就是当前学期"；
  - 打开上学期并选了与本周相同的周次时 `displayWeekNumber === currentWeekNumber` 成立，今天的课程被误判 `isPast`（灰底灰字）甚至 `isOngoing`（"正在上课"徽章），但上学期是历史数据，本不该出现实时态。
- **根因二（详情不存在）**（`pages/coursetable/index.tsx` + `pages/coursedetail/index.tsx`）：
  - 课表页跳转详情页只带 `id` 与 `week_number`，**缺 `semester_id`**；详情页 `getWeek(weekNumber)` 默认查当前学期，上学期课程的 `schedule_id` 在当前学期里查不到 → 空态"课程信息不存在"。
  - `schedule`（时间轴）页跳转详情页同样缺 `semester_id`，存在同类问题，一并修复。
- **改动**：
  - `buildCellMap` 新增第 4 参 `isCurrentSemester`：`isRealCurrentWeek` 须同时满足「展示学期 == 当前学期」才标实时态——历史学期不再灰化/误标进行中；
  - 课表页与时间轴页跳转详情页时追加 `&semester_id=<选中学期>`（当前学期/未选时省略，不影响既有逻辑）；
  - 详情页 `useLoad` 读取 `semester_id` 参数并透传给 `getWeek(weekNumber, semesterId)`，与课表页当前查看的学期/周次一致。
- **验证**：`tsc --noEmit` 通过；`taro build --type weapp` 成功；产物 `dist/pages/coursedetail/index.js`、`dist/pages/coursetable/index.js`、`dist/pages/schedule/index.js` 均含 `semester_id` 透传逻辑，`process.env` 残留为 0。

### 修复：IconArrow 箭头与同行文字中线不对齐（前端，2026-09-23）
- **用户反馈**：「我发现好多 `>` 符号都不是和文字的中线对齐的」——指定项目用纯 CSS 矢量 `<IconArrow>` 组件替换的 `>` 箭头。
- **排查手段**：用无头 Chrome（`--headless=new --dump-dom` + 内联 JS 实测 `getBoundingClientRect()` 中心差值）复刻 `.icon-arrow` 与多组 flex 行容器（含 line-height 1/1.4、拉丁文、inline 包裹、漏设 `align-items:center` 的行）。
- **实测结论**：
  - 箭头作为 **flex 直接子元素且父行已 `align-items:center`** 时，与文字中心差值 = **0**（本就完美居中）——项目绝大多数列表行容器已满足此条件；
  - 偏移只出现在两类边界：①箭头被 **inline 包裹**（无文字同行）→ 偏低约 2.4~3.8px；②父行 **漏设 `align-items:center`**，定高箭头被推到交叉轴起点（顶部）→ 整体偏高、与文字中线错开。
- **根因**：`.icon-arrow` 自身无"强制自身居中"的兜底，一旦所在行容器忘了写 `align-items:center`，定高箭头就被 flex 默认 `stretch` 推到顶部。
- **改动**（仅 `components/IconArrow/index.scss` 的 `.icon-arrow` 基类，零行为变更）：
  - 加 `align-self: center;`——即使所在行容器忘了 `align-items:center`，箭头也按自身在交叉轴居中（已是 flex 居中行的场景：`align-self` 与父级 `align-items` 一致，**零副作用**）；
  - 加 `vertical-align: middle;`——inline / 被文本行包裹场景的基线对齐兜底（flex 场景下被忽略，无副作用）。
- **验证**：无头 Chrome 实测多组行——flex 居中行 r1/r2/r3 差值 = 0.0；漏设 `align-items:center` 的行 r5 修复前偏移、加 `align-self:center` 后恢复 **0.0**；`tsc --noEmit` 退出码 0；`taro build --type weapp` 编译成功。
- **待真机确认**：开发者工具 / 真机上各列表页箭头与文字的观感（尤其个别未显式写 `align-items:center` 的行）。

### 修复：「我的」页底部「退出登录」与底部 TabBar 粘连（前端，2026-09-23）
- **用户反馈**：「我的页面 往下拉到这就拉不动了，这个退出登录和这个导航栏连起来很难看」。
- **根因**（`pages/profile/index.scss`）：
  - 自定义 TabBar（`custom-tab-bar/index.scss`）实际高度为 `calc(112rpx + env(safe-area-inset-bottom))`，而 `.profile-page` 只预留 `padding-bottom: calc(108rpx + env(safe-area-inset-bottom))`——**比 TabBar 少 4rpx**，页面滚到底时内容底边必然落进 TabBar 的覆盖区（原注释写「98rpx」同样是错的）；
  - `.logout-btn` 的 `margin-bottom` 又是 `0`，「退出登录」卡与 TabBar 两块白色底直接贴合，看起来像长在 TabBar 上；
  - 「我的」页内容高度本就接近一屏，可滚动量极小，配合上述贴合，观感即「拉不动 + 连成一片」。
- **改动**（仅 `pages/profile/index.scss`）：
  - `.profile-page` 底部预留 108rpx → **112rpx**（与 TabBar 真实高度对齐）+ 再叠加 `$spacing-lg`(32rpx) 页脚留白，注释同步更正；
  - `.logout-btn` 的 `margin` 第三值 `0` → `$spacing-lg`，与顶部间距对称。
  - 两者合力：滚到底时「退出登录」卡与 TabBar 之间约 **64rpx** 间距（32rpx 页脚 + 32rpx 卡片底），整页同时获得约 32rpx 的舒适下拉余量（原先内容≈一屏，几乎拉不动）。
- **验证**：`taro build --type weapp` 编译成功（仅原有 285KB 体积告警）；产物 `dist/pages/profile/index.wxss` 已输出 `.profile-page{...padding-bottom:calc(112rpx + env(safe-area-inset-bottom) + 32rpx)}` 与 `.logout-btn{...margin:32rpx 24rpx...}`；`process.env` 残留 0。
- **待真机确认**：「退出登录」与底部 TabBar 的间距观感。

### 变更：小程序用电记录改为「按用电日一天一条」并新增用电详情页（前后端，2026-09-22）
- **用户反馈**：「宿舍电量的用电有些不合理了，为什么？…不够直观…应该一天显示一条总的用电，并且如果想看详细的点击那条数据就要跳到详细页面」。排查后确认「不合理」有**三重根因**，且都能在库里实证：
  1. **一天两条**：一个宿舍有**两块分表**（`31栋512` 与 `310512`），同一次爬取各写一条、`record_time` 完全相同，列表直接铺原始明细就是"同一天两行"，每行只有一半的量（截图中 `2026-09-18 00:09` 出现 0.75 与 1.71 两条，合计才是当天真实用量 2.46）。
  2. **日期整体错后一天**：`electricity_records.record_time` 是**结算时刻**（= 实际用电日 + 1 天的 `00:0x`），直接当日期展示，列表写 09-18、站内信日报写「统计日期 09-17」，同一天的电看起来是两天。
  3. **口径不一致**：`get_usage_trend()`、周报/月报 `get_statistics_by_range()`、`get_monthly_usage()` **本就全按天合计**，只有这个列表返回原始明细——不一致的只有它。
- **后端**：
  - `app/repository/electricity_repository.py` 新增「按用电日聚合」区块（含口径依据注释）：`get_daily_aggregates`（按结算日 `GROUP BY` 求和 + 分页）、`count_daily_aggregates`（`COUNT(DISTINCT day)`，分页单位是「天」）、`get_records_of_usage_day`（用电日 D 的原始记录落在 `[D+1 00:00, D+2 00:00)`）、`get_daily_totals_between`（对比口径用，一次查出区间内每日合计）、`get_remaining_at_or_before`（还原某历史用电日结算时点的剩余电量）。`func.date()` 在 MySQL 返回 `date`、SQLite 返回 `str`，统一由 `_to_date_str` 归一为 `'YYYY-MM-DD'`。
  - `app/services/electricity_service.py` 新增 `get_daily_records(limit, offset)`（返回 `days:[{date(用电日), total_usage, settle_time}]`，`date` 已由 `_settle_date_to_usage_date` 换算，前端不再做偏移）与 `get_daily_detail(usage_date)`（`total_usage` / `meters`（按 `normalize_meter` 归一后合并、按用量倒序、带 `percent`）/ `prev` + `diff_prev` / `avg_recent` + `avg_recent_days` + `diff_avg` / `remaining` + `remaining_at`）。对比口径取「该日之前**有记录**的最近一天 / 最近 7 天」，跳过缺数据的日子，与周报「日均 = 总用量 ÷ 有记录天数」一致，不把没采集到的日期当 0 度稀释。原有 `get_usage_records` / `count_usage_records` **保留**（管理端 `admin_routes.py` 与 `electricity_routes.py` 仍在用）。
  - `app/api/miniapp_routes.py`：`GET /api/miniapp/electricity/history` **契约变更**——返回体由 `records` 改为 `days`，`limit`/`offset` 单位由「条」改为「天」，并**删除 `days` 查询参数**（原前端未使用，留着会与"按天显示"语义混淆）；新增 `GET /api/miniapp/electricity/daily/<date>`（日期格式非法 400、该日无记录 404）。
  - `app/model/user_notification.py` + repository + service 新增 `payload`（TEXT，可空）列与 `create(payload=...)` 透传；`tasks._build_report_payload()` 为日报/周报/月报生成结构化 payload（电表名已归一化、`daily` 升序、日报无 `daily` 字段）。**正文 `content` 仍是纯文本、格式未动**（向后兼容），`payload` 只用于前端结构化渲染，老消息无该字段照旧按纯文本显示。
- **前端（小程序）**：
  - `pages/electricity/index`：「用电记录」由原始明细改为**按天一条**（用电日 + `昨天/前天` 标签 + 星期 + 当日合计），每行可点，跳 `/pages/electricity-daily/index?date=YYYY-MM-DD`；文案「共 N 条」→「共 N 天」，「查看更多记录（N）」→「查看更多（还剩 N 天）」；`loadMore` 的 offset 改用「已加载天数」。电表名解析简化为直接用 `current.meter`（后端 `get_building_meter()` 已从记录中解析出楼栋名，前端不再从明细里翻）。
  - **新增 `pages/electricity-daily`**：头部沿用「消息详情」排版，「用电概况」（当日总量 + 较前一日 + 较近 7 日均值）、「各电表用电详情」（每块分表一行 + 占比条，说清"合计是怎么来的"）、「结算信息」（统计日期 / 结算时间 / 当时剩余电量）。**刻意不照搬日报的纯文本**，改成结构化 + 只在最易困惑的"分表占比"处加占比条（与页面既有折线图不重叠）。分隔线用相邻兄弟选择器（`.a + .a`）而非 `:last-child`——末尾还有说明文字，`:last-child` 会失效。
  - `pages/message-detail`：带 `payload` 的电量报告改为结构化渲染（概况大数字 + 三列统计 + 各电表 + **每日用电可点击进当日详情**，日报则给一条直达当日明细的入口）；payload 经 `asReportPayload()` 运行时收窄，结构不符即退回纯文本。日期口径辅助函数 `weekdayCNFromDate` / `relativeDayLabel` 收口到既有 `utils/date.ts`（不另立一套）。
- **不兼容变更与迁移**：
  - `/api/miniapp/electricity/history` 响应字段 `records` → `days`（老版本小程序需同步更新，否则该列表为空）。管理端接口未受影响。
  - `user_notifications` 新增 `payload` 列：本地已跑 `python init_db.py migrate`；**生产需手动执行** `ALTER TABLE user_notifications ADD COLUMN payload TEXT;`（或跑同一迁移脚本），否则站内信详情读不到 payload（不影响纯文本正文）。
- **验证**：
  - 新增 `tests/test_electricity_daily_aggregate.py`（11 条：分表合并、按天分页/倒序、用户隔离、用电日窗口与**左闭右开边界**、区间合计升序、结算日→用电日换算（含跨月/跨年/非法值）、`_build_report_payload` 结构、`days_count=0` 不除零、以及一条**读真实库**的一致性校验：`days` 严格倒序不重复、同日各分表之和 == 当日合计、占比合计 ≈100%）。
  - 原 `test_miniapp_phase2.py::test_electricity_history_passes_limit` 按新契约重写为 `test_electricity_history_returns_daily_aggregates`，并补 3 条 `/electricity/daily/<date>` 用例（400 / 404 / 200）。
  - **全量 `pytest`：231 passed**（改动前 227 passed + 1 failed，失败那条正是旧契约用例）。
  - 小程序端 `tsc --noEmit` 退出码 0；`taro build --type weapp` 编译成功。
- **待真机确认**：列表点击态、详情页占比条观感、消息详情页结构化正文在真机上的排版。

### 修复：登录页「同意」勾选图标改为 CSS 矢量（前端，2026-09-22）
- **问题**：勾选态用文本字符 `✓`（U+2713），属 dingbat 类字符，字形与粗细随用户自定义字体变化（Apple / Android / 各中文字体对 `✓` 的渲染差异很明显），与已修的 `+` / `×` / 箭头属同一类问题。
- **改动**（仅 `pages/login/`）：
  - `index.tsx`：`<Text className="login-agree-check-tick">✓</Text>` → `<View className="login-agree-check-tick" />`。
  - `index.scss`：`.login-agree-check-tick` 由 `font-size: 24rpx` + 文本改为 CSS 绘制——`::before` 一个 8×14rpx 矩形只留 `border-right` + `border-bottom` 后 `rotate(45deg)` 得到勾形，描边用 `currentColor` 继承 `color: $text-inverse`（白勾）。
- **验证**：`tsc --noEmit` 退出码 0；`taro build --type weapp` 编译成功；源码 `✓` 残留 0（仅注释中提及原字符）；产物 `pages/login/index.wxss` 已输出 `.login-agree-check-tick` 与 `::before` 规则；产物 js 确认渲染为空 `View` 且不含 U+2713；`process.env` 残留 0。

### 修复：剩余 6 处"文本字符 / emoji 当图标"改用 iconfont 或 CSS 绘制（前端，2026-09-22）
上一轮审计出 6 处会被渲染的字符图标，本轮按「优先 iconfont，无合适字形再 CSS 画」全部处理完。**字形选型不靠字形名猜，而是用仓库内 `font_5227727_2cehpso97e2/iconfont.ttf` 把全部 59 个字形渲染成对照图后逐个确认**（脚本 `技术总结/dev-scripts/render_iconfont_preview.py`，输出 `技术总结/iconfont-preview.png`）。

| 位置 | 原字符 | 改为 | 依据 |
|---|---|---|---|
| `pages/announcement/detail:291` | 回形针 emoji | iconfont `icon-RectangleCopy1`（`\ue6a7`，文档轮廓） | 渲染确认；容器 `.attach-icon` 为 64rpx 方块 + 橙色浅底，深色文档图标可读 |
| `pages/announcement/detail:340` | `★` / `☆` | iconfont `icon-a-rongqi2231x`（`\ue67c`，五角星轮廓） | 渲染确认；原以为可用的 `icon-xz` 实际是**实心爱心**、`icon-guanbi` 是**实心方块**，均不可用 |
| `pages/profile:378` | `☆` | 同上 | 同一列表其余 4 项本就用 iconfont，此处是遗漏 |
| `pages/favorites:91` | `★`（96rpx 金色） | 同上 | 同上 |
| `pages/weather:368-370` | 水滴 emoji ×3 | **CSS 绘制水滴** | iconfont 里雨相关字形语义全不对：`雨伞`是遮阳伞、`雾霾`是云加雨滴、`湿度`是水滴，故改画 |
| `pages/privacy-policy` / `pages/user-agreement` | `·` 共 **20 处** | **CSS 绘制圆点** | 见下条 |

- **星标两态并非视觉降级**：先前担心改单色字形后「已收藏 / 未收藏」无从区分，复查发现本页**早已存在** `.action-btn.action-active .action-icon { color: #faad14 }`——激活态本来就是靠颜色区分的，与同栏「分享」「已阅」一致，故换字形不损失任何状态表达。
- **雨滴的绘制与自检**：`border-radius: 0 50% 50% 50%`（左上角留尖）+ `rotate(45deg)`。
  - **踩坑并修正**：初版写成 `rotate(-45deg)`。按 CSS 旋转语义（屏幕坐标 y 轴向下、正角顺时针）代入矩阵可知左上角会转到 **9 点方向（朝左）**；用已知为真的案例自检同一算式——「只留 `border-top`/`border-right` 的方块 `rotate(45deg)`」算得指右，与项目里 `IconArrow` 的实际表现一致，算式可信，故改为 `+45deg`。另渲染成图复核（脚本 `技术总结/dev-scripts/render_raindrop_direction.py`，输出 `技术总结/raindrop-direction.png`），确认 `+45deg` 尖朝上、`-45deg` 尖朝左。
  - 盒尺寸取原字号的约 0.71 倍（26/20/16rpx，原字号 36/28/22rpx）：旋转后的对角长度≈原字号，列的占位高度不变。
- **验证**：`tsc --noEmit` 退出码 0；`taro build --type weapp` 编译成功（仅保留原有 285KB 体积告警）；产物核对——`pages/weather/index.wxss` 输出 `.raindrop{background:#3887de;border-radius:0 50% 50% 50%;opacity:.85;transform:rotate(45deg)}` 与三档尺寸，`pages/profile|favorites|announcement/detail` 的 js 渲染为 `iconfont icon-a-rongqi2231x ...` / `iconfont icon-RectangleCopy1 attach-file-icon`，`app-origin.wxss` 含 `@font-face font-family:iconfont` 且字形 `\ue67c` / `\ue6a7` 已定义；全量 dist 中回形针 / 水滴 / 星号 / 勾 / 文本箭头残留 **0**，`process.env` 残留 **0**。
- **待真机确认**：星标为轮廓形（旧实心星在列表里更"跳"），雨滴与水珠的观感需在开发者工具里定夺。

### 修复：法务页列表点由「· 」文本改为 CSS 圆点（前端，2026-09-22）
- **范围修正**：上一轮记录为「1 处（`privacy-policy:61`）」，实际是全项目 **20 处**——`pages/privacy-policy` 10 处、`pages/user-agreement` 10 处；`section-list` / `section-li` 两页之外无任何使用，改动面可控。
- **为什么值得改（实测数据，非推测）**：按 24rpx 字号把 `·`（U+00B7）实际渲染后测量（脚本 `技术总结/dev-scripts/measure_middle_dot.py`）——墨迹直径 **2.4~5.7rpx**、「· 」前进宽度 **12.9~36rpx**（宋体的 `·` 是全角，接近雅黑的 3 倍）。同一份法务文案在不同机型上缩进能差近 3 倍，正是"文本字符当图标"的典型症状。
- **改动**：
  - 两个 `index.tsx`：20 行 `className="section-li">· ` 去掉字面 `· `（渲染结果不变，且复制文本不再带出多余点号）。
  - 两个 `index.scss`：`.section-li::before` 画 6rpx 圆点 `border-radius:50%` + `background:currentColor`（自动继承 `$text-secondary`），`display:inline-block` + `margin-right:8rpx`（合计前进 14rpx，取各字体实测中位）+ `vertical-align:middle`。
  - **刻意不用绝对定位**：改用内联 `inline-block` 是因为（1）换行后仍回到左边缘，与原来的文本流行为一致，不引入悬挂缩进；（2）不依赖 `<text>` 元素对 `position` 的支持——该点本地无法验证。
- **验证**：产物 `pages/privacy-policy/index.wxss` 与 `pages/user-agreement/index.wxss` 输出 `.section-list .section-li::before{background:currentColor;border-radius:50%;content:"";display:inline-block;height:6rpx;margin-right:8rpx;vertical-align:middle;width:6rpx}`，`position:absolute` 与 `translateY` 残留均为 **0**；两页 js 中 `·` 计数 **0**，首条文案为 `section-li",children:"微信身份信息：...`（点号已不在文本里）。

### 重构：小程序箭头图标统一抽成共享组件 `IconArrow`（前端，2026-09-22）
- **背景**：上一轮把反馈页/公告页的 `›` 换成 CSS 矢量时，是在各页 `.scss` 里**手写同一套 `::before` 配方**（正方形 + `border-top`/`border-right` + `rotate(45deg)`）；同时全项目仍有约 25 处箭头用**文本字符**（`›` / `‹` / `∧`）——用户自定义字体会改写其字形与基线。故收敛为单一组件，避免配方抄多份、以及"一半组件一半文本字符"的混乱。
- **新增 `src/components/IconArrow`**：
  - `index.tsx`：`<IconArrow direction="right|left|up|down" size="sm|md|lg" className="..." />`，只渲染一个空 `View`（无文本、无字体依赖）。
  - `index.scss`：`.icon-arrow` 基类 + `.is-left/up/down` 方向修饰 + `.icon-arrow--sm/md/lg` 尺寸档（容器 14/18/24rpx，内框 9/12/16rpx，描边 2/3/4rpx）。描边颜色刻意用 **`currentColor`** → 箭头自动跟随所在元素的 `color`，页面样式里只需写 `color`，无需为箭头单独配色。
  - 尺寸档选择基准：`sm` 配 22-24rpx 文字（内联「更多」）、`md` 配 28-36rpx、`lg` 配 40rpx 以上。
- **接入范围（10 个文件 / 25 处）**：
  - `components/NoticeCard`、`components/ReminderCard`：首页两张卡的「更多 ›」由 `Text` 改 `View` 包一层并加 `<IconArrow size="sm" />`，样式补 `display:flex; align-items:center; gap:4rpx`。
  - `pages/home`：`card-more-arrow`、`home-login-tip-arrow`（`md`）。
  - `pages/messages`：`msg-item-arrow`（`lg`）、底部「查看更多 ›」（`sm`）。
  - `pages/profile`：5 处 `profile-arrow`（`md`）+ 宿舍用电卡的「更多 ›」（`sm`）。
  - `pages/settings`：5 处 `set-arrow`（`md`）。
  - `pages/profile-detail`：`detail-card-title-arrow` ×2、`detail-edit-entry-arrow`（均 `md`）。
  - `pages/electricity`：4 处自绘返回键 `elec-navbar-back` 的 `‹`（`direction="left" size="lg"`）、「查看更多记录（N） ›」（`sm`）、「收起 ∧」→ `direction="up"`（`sm`）。
  - `pages/feedback/list`、`pages/feedback/submit`、`pages/announcement/index`：把上一轮**手写的** `.fb-item-arrow` / `.fb-topbar-arrow` / `.alist-more-arrow` 三段配方删除，改为调用组件，页面样式只留 `color` / `margin`。`styles/theme.scss` 的 `.card-more-arrow` 同样由 `font-size`/`line-height` 简化为只留 `color` + `margin-left`。
- **一处有意的配色修正**：电费页「查看更多记录」的箭头原来在 `.elec-more-text` 内部（继承主色），拆成独立节点后会掉成正文默认色 → 在容器 `.elec-more-btn` 上补 `color: $primary-color`，保持原观感。
- **技术前提（已核实，非新引入风险）**：`::before` + `content` 在本项目**生产已在用**——整套 iconfont 走的就是 `.iconfont.icon-xxx::before`（自 v6.16.0 / 2026-08-31 起），`styles/common.scss` 的 `button::after` 同理。
- **验证**：
  - `tsc --noEmit` 退出码 0；`taro build --type weapp` 编译成功（仅保留原有 285KB 体积告警）。
  - 全项目 `src/**/*.tsx` 与 `src/**/*.scss` 中**渲染用的** `›` / `‹` / `∧` 残留 **0**（仅注释里的 ASCII 布局示意图保留 `›` 表示"此处有箭头"）。
  - 产物核对：组件被抽为公共块 `common.js` / `common.wxss`，`app.wxss` 已 `@import "./common.wxss"`（全局可用）；`.icon-arrow` 及三档尺寸、四个方向规则均已输出（`solid` 后省略颜色是 cssnano 的正确优化，`border-color` 初始值本就是 `currentColor`）；电费页 js 中确认渲染为 `{className:"elec-navbar-back",direction:"left",size:...}`、`<IconArrow size="sm">`、「收起」+ `{direction:"up",size:"sm"}`；全量 dist `process.env` 残留 **0**。
- **待真机确认**：三档尺寸与各处文字的实际比例（14/18/24rpx），需在开发者工具里看；若某处偏大偏小，只改调用处的 `size` 即可，不必再动 CSS。

### 修复：小程序「通知公告」列表「查看更多」箭头改为 CSS 矢量（前端，2026-09-22）
- **问题**：底部「查看更多 ›」的 `›`（U+203A）是**文本字符**，与之前反馈模块同类问题——用户自定义字体（font-family）会改变其字形与基线，有失美观。
- **改动**：
  - `pages/announcement/index/index.tsx`：`<Text>查看更多 ›</Text>` 拆为 `<Text>查看更多</Text>` + `<View className="alist-more-arrow" />`。
  - `pages/announcement/index/index.scss`：新增 `.alist-more-arrow`（CSS 绘制：`::before` 12rpx 正方形 + `border-top`/`border-right` 3rpx + `rotate(45deg)`，参数与反馈列表页 `.fb-item-arrow` 完全一致）；`.alist-more` 增加 `align-items:center` 以对齐箭头与文字。
- **验证**：`tsc --noEmit` 退出码 0；`taro build --type weapp` 编译成功；源码 `›` 残留计数 **0**；产物 `index.js` 已确认渲染为 `children:"\u67e5\u770b\u66f4\u591a"`（查看更多）+ 同级 `className:"alist-more-arrow"`，`.alist-more-arrow::before` 规则已进 `index.wxss`；全量 dist 中 `process.env` 残留 **0**。
- **待确认（用户侧）**：小程序其余 8 处文件仍有同类文本字符箭头（`card-more-arrow` / `profile-arrow` / `set-arrow` / `msg-item-arrow` / `elec-navbar-back` 的 `‹` 等，共约 18 处），本次未擅自扩大范围改动，见会话说明。

### 修复：小程序「通知公告」列表卡片上下粘连（前端，2026-09-22）
- **问题**：`pages/announcement/index` 的多条公告共用一个白卡容器（`.alist-card`），条目之间仅靠一条 `1rpx` 细分割线分隔、无任何留白，视觉上「上下粘连」，用户反馈「非常有违和感」。
- **改动**（`pages/announcement/index/index.scss`，**仅样式**，DOM/逻辑未动）：
  - `.alist-card`：由「白底 + 圆角 + 描边 + `overflow:hidden` 的卡片容器」改为**透明间距容器**（`display:flex; flex-direction:column; gap:$spacing-md`）。
  - `.alist-item`：由「纯条目 + `border-bottom` 分割线（含 `&:last-child{border-bottom:none}`）」改为**独立卡片**（`background:$card-background` + `border-radius:$radius-large` + `box-shadow:$shadow-card`），规格与「我的消息」页 `.msg-item` 对齐（同一份圆角/阴影令牌）。
  - `.alist-item-top`：保留左侧 `6rpx` 色条（`border-left` + `padding-left` 补偿），现色条沿卡片圆角走边。
  - `.alist-item-cover`：圆角由 `$radius-small` 提到 `$radius-medium`，并加 `margin-bottom:$spacing-xs`，贴合新卡片的内嵌横幅观感。
  - `.alist-section`：段间距由 `$spacing-md` 放宽到 `$spacing-lg`。
- **兼容性说明**：flex `gap` 在本页原实现中已在使用（`.alist-item` / `.alist-item-main` 均有 `gap`），本次未引入新的 CSS 能力依赖。
- **验证**：`taro build --type weapp` 编译成功；产物 `dist/pages/announcement/index/index.wxss` 已逐条核对——`.alist-card{display:flex;flex-direction:column;gap:24rpx}`、`.alist-item{background:#fff;border-radius:24rpx;box-shadow:0 4rpx 16rpx rgba(0,0,0,.04);...}`、`.alist-item-top{padding-left:18rpx}`、`.alist-item-cover{border-radius:16rpx;...}` 均按预期输出，残留 `border-bottom` 分割线计数为 **0**。真机/开发者工具最终视觉待用户确认。

### 仓库整理：未跟踪的临时脚本与草稿移出仓库树（2026-09-22）
- `Push_System_Flask/` 下 6 个未跟踪脚本（`_dup_analysis.py` / `_dup_analysis2.py` / `_inspect_db.py` / `dedupe_electricity.py` / `diagnose_electricity.py` / `diagnose_weeks.py`）与根目录 2 个未跟踪草稿（`小程序审核说明_草稿.md` / `校园信息聚合与智能推送系统.md`）移入 `技术总结/dev-scripts/` 与 `技术总结/`。`技术总结/` 被 `.gitignore` 忽略 → 不入库、不随部署、可随时移回，**未删除任何文件**。
- 反向处理：`tests/test_electricity_dedup.py` 是真正的回归测试（非临时件），已纳入版本管理（见下方「测试」条目）。
- 说明：`dedupe_electricity.py` / `diagnose_weeks.py` 是生产运维脚本（runbook 曾引用），因此仅归档不删除；如希望随代码部署，可再挪进 `Push_System_Flask/scripts/`。

### 测试：更新课程相关过期测试到 v6.19.x 新契约（后端，2026-09-22）
- **背景**：跑全量 `pytest` 发现 5 个失败，均为**早前会话改行为后未同步更新测试**（那两次只跑了 `py_compile`，未跑全量测试），并非功能回归。
- `tests/test_course_admin_protection.py`（4 项）：旧契约（去重键含 `course_code`；手动课按「`course_code` 相同」或「同时间槽 `(week_day, period_idx, week_number)` 被占」保护）已随 v6.19.x 改为「身份 = `course_key = md5(课名|星期|排序节次|教室|教师)`，按 `(semester_id, course_key)` 去重，手动课保护仅在 course_key 命中时跳过」。据此重写：
  - 覆盖保护用例改为「爬虫行与手动课同 course_key」→ 断言 `created==0 且 updated==0`，手动课字段与 `weeks` 未被改写；
  - 原「同槽位不挤占」用例改名为 `test_crawler_inserts_when_key_differs_in_admin_slot`，固化新行为（身份不同即新建，手动课不被触碰）；
  - 「正常 upsert」用例改为只变更**非身份字段**（`course_code` / `building` / `weeks`）→ 断言更新不新建；admin 来源用例同理；
  - 批次数据统一补 `semester_id`——保护集与匹配均按学期作用域，缺失会回落到「当前学期」而与夹具的 `20251` 不一致导致误判。
- `tests/test_miniapp_phase2.py::test_schedule_today_filters_by_date`：旧断言按 `extra_info.full_date` 过滤（v6.19.0 已改「`day_of_week == 今天` 且 `当前教学周 ∈ weeks`」）。夹具原固定 `day_of_week=1`（周一），**对星期几敏感**；改为按 `date.today().isoweekday()` 构造并 `mock` `get_current_week_number`，任意星期稳定通过。
- **说明**：本次仅改测试，未改任何业务代码；新契约的既有副作用（改名/改教师/改教室会改变 `course_key` 视作另一门课、同槽位不再拦截）已写入测试 docstring 备案。
- **另**：将一直未跟踪的 `tests/test_electricity_dedup.py`（电量用电记录去重回归测试，覆盖 2026-09-08 的两条语义，用例用假 user_id + flush/rollback 不落库）纳入版本管理，避免丢失。
- **验证**：`pytest -q` → **217 passed, 0 failed**。

### 新增：公告封面 + 发布/新注册时「我的消息」留站内信（后端 + 管理端 + 小程序，2026-09-22）
- **背景**：公告此前只走企业微信群机器人，学生端「我的消息」无感知；且注册晚于公告的学生看不到近期通知。本次让公告在「我的消息」留痕，并新增封面展示。
- **后端（模型）**：
  - `Announcement` 新增 `cover_url`（String(500)，可空，随 `to_dict` 输出）。
  - `UserNotification` 新增 `cover_url` / `ref_type`（索引）/ `ref_id`（索引），并加 `UniqueConstraint(user_id, ref_type, ref_id)`（`uq_user_notif_ref`）。
  - `UserNotificationRepository.create` / `UserNotificationService` 透传上述三字段。
- **后端（推送，新增 `app/services/announcement_push_service.py`）**——双路径覆盖「注册时间 ≤ 7 天」：
  1. `push_announcement_to_new_users`：公告创建即发布 / 状态改为发布时，给 `role='student' AND is_active AND created_at >= now-7d` 的学生写站内信（`category=announcement`、`ref_type=announcement`、`ref_id=公告ID`、带 `cover_url`）。
  2. `push_recent_announcements_to_new_user`：学生微信首次登录（`wechat_auth_service.login` 的 `is_new_user` 分支）时，补写近 7 天已发布且未过期（`expired_at IS NULL OR > now`）的公告。
  - 幂等：写前查 `(user_id, ref_type, ref_id)` 已存在则跳过 + 模型层唯一约束兜底；失败仅告警，不影响发布/登录主流程。触发点见 `announcement_service.py` 的 `create(publish_now)` 与 `update_status`。
- **后端（封面接口）**：管理端 `POST /api/admin/announcements/upload-cover`（复用正文图安全校验 IMAGE_EXTS / IMAGE_MAX_SIZE / sha256 重命名 + EXIF 校正，落盘 `output/announcement-covers/`，返回 `{url}`）；公开 `GET /api/announcement-covers/<name>`（扩展名白名单 + `send_from_directory` 防穿越，学生端无鉴权加载）。
- **管理端**：`Announcements.tsx` 表单新增「封面图（可选）」picture-card 上传（上传即写入 `cover_url`、可移除）+ 顶部 Alert 补充「发布时会给近 7 天新注册学生推送站内通知（带封面，点击跳转详情）」；`api/announcement.ts` 增 `uploadCover` 与 `cover_url` 字段。
- **小程序（全部条件渲染，无图不占位）**：
  - 布局：公告详情 → 标题区下方横幅；消息详情 → 标题下方横幅（标题在上、图片在下）；公告列表卡片 → 卡片顶部横幅；我的消息列表 → 公告类站内信左侧 132rpx 缩略图。**原实现漏配封面样式，本次补齐四页 `.scss`。**
  - 消息页点击公告类站内信改走 `openAnnouncementNotification`：先 `notificationsApi.markRead(id)` 乐观清未读与计数，再跳公告详情（与公告未读角标一致）；`CATEGORY_LABEL` 增「新公告」。
  - 类型：`AnnouncementItem` / `UserNotificationItem` 增 `cover_url`（后者另加 `ref_type` / `ref_id`）。
- **部署注意**：`init_db.py migrate` 只按 `Table.indexes` 补索引，**不会**从 `__table_args__` 建唯一约束 → 生产需手动补建 `uq_user_notif_ref`（`ALTER TABLE user_notifications ADD UNIQUE KEY uq_user_notif_ref (user_id, ref_type, ref_id)`）；`cover_url` / `ref_type` / `ref_id` 列由 migrate 补。
- **验证**：后端 9 文件 `py_compile` 通过；小程序 `tsc --noEmit` 退出码 0、`taro build --type weapp` 编译成功、`process.env` 残留 0，四页封面样式已进产物。
- **本地端到端验证（通过）**：在真实本地库跑通两条补推路径（脚本自造数据、结束自动清理，库行数回到起始值）——①发布时广播写入 2 条，`category` / `ref_type` / `ref_id` / `cover_url` / `title` / `content`（auto_summary）全部正确，重复发布幂等（0 新增）；②注册时补推写入 1 条，幂等（0 新增）；③`uq_user_notif_ref` 唯一约束确实拒绝重复 `(user_id, ref_type, ref_id)`；④非近 7 天注册用户不被补推。**仍属服务环境才能验的**：小程序真机点开看封面实际渲染、以及生产需手动补建该唯一约束（见上「部署注意」）。

### 修复：小程序反馈模块图标字与图片预览（前端，2026-09-22）
- **问题**：①提交页「添加」块与列表页悬浮按钮的「+」、提交页删除角标的「×」均为**文本字符**，会被用户自定义字体（font-family）改变字形与基线，有失美观；②意见反馈页 / 我的反馈页 / 反馈详情页的图片仅渲染，点击无法放大预览。
- **改动**：
  - `src/utils/imagePreview.ts`（新增）：收口 `previewImages(current, urls)`，统一把后端相对 URL 拼 `API_BASE_URL` 后调 `Taro.previewImage`（单点处理，三页复用）。
  - `pages/feedback/submit/index.tsx`：截图加 `onClick` 预览；「+」由 `<Text>+</Text>` 改空 `<View className="fb-img-add-plus" />`；「×」由 `<Text>×</Text>` 改空 `<View className="fb-img-del-x" />`。
  - `pages/feedback/list/index.tsx`：列表缩略图加 `onClick`（`stopPropagation` 防误进详情）预览全部图片；悬浮按钮「+」改空 `<View className="fb-fab-plus" />`。
  - `pages/feedback/detail/index.tsx`：详情大图加 `onClick` 预览。
  - 三个 `.scss`：`.fb-img-add-plus` / `.fb-fab-plus` / `.fb-img-del-x` 由文本字号样式改为 `::before`+`::after` 两条线段**CSS 绘制矢量图标**（彻底不依赖任何字体，用户换字体也不会变形）。
  - 两页的 `›` 箭头（提交页「我的反馈 ›」入口、列表项右侧箭头）同步由文本字符改为同一套 CSS 矢量（`fb-topbar-arrow` / `fb-item-arrow`），避免同类字体依赖问题。
- **说明**：项目 iconfont（项目 5227727）内无语义干净的「加号」字形（名为「加」的 `RectangleCopy` 实为矩形，且被 `CampusCard` 占用），故加号/关闭号采用 CSS 绘制而非字体图标。
- **验证**：`tsc --noEmit` 退出码 0；微信端运行态视觉与预览行为待用户在开发者工具确认。

### 修复：课程爬虫入库根治——(semester_id, course_key) 稳定去重 + 强制全周次 + 对账软删（后端，2026-09-22）
- **根因**：`executors.run_spider` 调爬虫未带 `--all-weeks`，定时/手动只爬「当前周」视图，导致 `weeks` 落库成单周（`=[爬取周]`）；旧去重键 `course_code+week_day+period_idx+week_number` 中的 `week_number`（=爬取周）随每次爬取漂移，每爬一周新增一批重复行，库只增不减。本地库曾出现 124 行、同课被拆成「单节×周段×房间」多行、weeks 散落单周。
- **改动**：
  - `app/tasks/executors.py`：定时/手动爬取强制 `run_spider_process(["--all-weeks"])`，整学期周次位图由爬虫「选全部」解析得到。
  - `app/model/course.py`：新增 `course_key`（与周次无关的稳定身份，`md5(课名|星期|排序节次|教室|教师)`），普通索引 `idx_course_key`（历史软删行可能重复，故先非唯一，重复由 `create_batch` 逻辑去重）。
  - `app/repository/course_repository.py`：新增 `compute_course_key`；`create_batch` 去重键改为 `(semester_id, course_key)`；新增 `_find_existing_course`（主匹配 `course_key`，兜底匹配 `course_key IS NULL` 行按身份补 key，防漏跑回填又重复）；手动课保护改为基于 `course_key`（爬虫行 key 命中 `admin` 行则整条跳过）；新增 `reconcile=True` 全量爬取对账软删（本学期 `full` 源本次未被命中行软删，`deleted_reason='stale_reconcile'`）。
  - `app/cqie-course-timetable/pipeline.py`：单周护栏——`full` 源解析出周次集合仅 1 周时**拒绝入库**并发企微告警，避免「整学期变单周」覆盖现有整学期数据。
  - 数据校正（本地）：`技术总结/backfill_course_key.py`（**复用模型 `compute_course_key`，含 `period_idx` 回退，幂等可重跑**）回填 `course_key`；`技术总结/cleanup_courses.py`（备份优先软删）合并单节碎片、去重、学期名归一。本地执行后 124→63 行、0 重复、key 与模型算法 100% 一致。
- **验证**：4 文件 `py_compile` 通过；本地 DB 直连核查：`course_key` 列存在、回填后 0 不一致、清洗后 63 行 / 0 空 key / 0 重复 / 学期名规范（`2025-2026-2` 等）。
- **遗留**：真实整学期 `weeks` 需带 `--all-weeks` 的真实全量爬取覆盖（依赖学校认证，无法无人值守跑）；该爬取会触发 `create_batch` 按正确 key 更新 + `reconcile` 软删残留，本地与生产均可自愈。
- **生产**（用户部署后）：①`python init_db.py migrate` 补 `course_key` 列；②可选跑 `backfill_course_key.py` + `cleanup_courses.py`；③触发一次全量/指定学期 `--all-weeks` 爬取（旧行 `course_key` 为 NULL 时兜底按身份匹配更新并写正确 key，即便不跑脚本也能自愈）。

## v6.19.0 (2026-09-18)

### 调整：降雨提醒改为「分时段 + 每段每天仅一次」播报（后端，2026-09-18）
- **背景**：原逻辑把「当天之内 + 概率≥70%」的所有逐小时一次性罗列，并用全局 3h/4h 冷却去重；且时间解析失败（`except: pass`）时会把次日时段混入，导致「范围太广、有时到第二天」。
- **改动**（`app/modules/weather/analyzer.py` + `message.py`）：
  - 排除夜间（<06:00 或 ≥22:00），白天 06:00–22:00 等分为 4 段（上午/中午/下午/傍晚，各 4 小时，半开区间）。
  - 每次仅播报「当前所处时段」内、晚于当前时刻、概率≥70% 的小时；大雨判定为段内连续≥2 小时概率≥80%。
  - 去重改为「`rain_seg:日期:段序号` 当天仅播一次」，状态持久化到冷却状态文件并自动清理历史日期键；不再使用时间冷却。
  - 文案用具体时段（如「上午（06:00-10:00）」）替代模糊的「未来几小时/下午」。
  - 同步修复**每日晨报** `get_daily_summary`：降雨概率只统计「当天白天」，不再把夜间/次日高概率算进来误报「今日有雨」。
  - 时间解析失败的条项目直接跳过（不再保守保留导致混入次日）。
- **验证**：新增 `tests/test_weather_analyzer.py` 单元测试 5 项全过（当前段播报、每段当天仅一次、夜间全排除、低概率不播、晨报只取白天），覆盖「排除夜间/次日、仅当前段、去重」等用户诉求；`py_compile` 通过。运行态（30 分钟定时任务的端到端推送）待用户在服务环境确认。

### 修复：小程序首页「今日课程」跨周后恒显示「今日无课」（后端，2026-09-17）
- **根因**：`app/services/schedule_service.py` 的 `get_today_schedules()` 旧实现只按 `extra_info.full_date == 今天` 精确匹配；`full_date` 由 `_calculate_date` 基于课程静态字段 `week_number`（爬虫写死当周，不随真实教学周推进）相对当前周偏移得到，跨周后整体偏移到过去/未来周，命中 0 条。周视图走 `day_of_week + weeks` 口径故不受影响。
- **修复**：改为与 `/schedule/week` 一致的口径——「`day_of_week == 目标日星期` 且 `当前教学周 ∈ 课程 weeks`」筛选，命中后把 `full_date` 与 `_timeInfo` 时间戳修正为目标日（保证 CourseCard 进行中/已结束状态计算正确）。
- **验证**：连真实库跑真实代码路径，修复前 0 条 → 修复后正确返回当天课程；`py_compile` 通过。

### 修复：管理端消息中心 WangEditor 点击保存报 Repeated create toolbar（前端，2026-09-17）
- **根因**：`@wangeditor/editor-for-react` 的 `Toolbar` 组件 `useEffect` 仅依赖 `[editor]` 且无清理；在 React `StrictMode` 双调 effect 或路由 `id` 变化（新建保存后 replace 到 `/edit/:id`）时，会在同一 DOM 节点重复调用 `createToolbar`，命中 core 的 `data-w-e-toolbar` 重复检测抛错。
- **修复**（`admin-frontend/src/pages/MessageEditor.tsx`）：
  - 自定义 `SafeToolbar` 替换官方 `Toolbar`：创建前与 cleanup 均显式 `removeAttribute("data-w-e-toolbar")` 并清空容器，绕开重复检测；
  - 新增 `useLayoutEffect(() => setEditorInstance(null), [id])`，路由 `id` 变化时同步清空失效的 editor 实例；
  - 保留 `.editor-wrapper` 整体 key；`editorConfig` / `toolbarConfig` 用 `useMemo` 缓存。
- **验证**：`tsc --noEmit` 通过（运行时点击保存的端到端验证待用户在 dev/build 环境确认）。

### 调整：管理端仪表盘重做（前端，2026-09-17）
- **背景**：后端 `/api/admin/dashboard` 实际返回的数据多于前端 `DashboardData` 接口声明（系统 `app_name/debug/auth_enabled/uptime/timestamp`、模块 `schedule` 统计、任务 `task_stats` 队列、`process_stats.status_counts/period/recent_tasks`、`scheduled_jobs.jobs`，以及**按天×类型的任务趋势** `type_trend.dates+series`）。上一版仅把隐藏字段堆成 Tag 群与自绘色块，属低信息量填充物，已被否定重做。本次按「专业 + 全面、仅前端」方向重构信息架构。
- **改动**（`admin-frontend/src/pages/Dashboard.tsx` + `admin-frontend/src/api/admin.ts` 接口声明）：
  - 顶部系统环境条：在线状态 + 版本 + 环境(生产/DEBUG) + 鉴权 + 运行时长 + 数据时间。
  - **核心 KPI 行**：期间执行（含今日/本月次轴）、任务成功率（≥90 绿/≥70 黄/否则红）、失败任务（含占比）、队列积压（待处理+处理中）。
  - **模块健康三卡**：天气（实况/预报/预警缓存 + 城市/晨报时间）、电量（Cookie 已配 + 采集器运行态 + 已配人数/低电量阈值）、课表（数据就绪 + 条目/今日/课程/教师 + 更新时间 + 课表爬虫运行态）。
  - **任务执行趋势**（视觉中心）：用 `type_trend` 真实时间序列渲染多类型面积/折线图（面积↔折线可切换），支持时间范围筛选；空数据降级 `Empty`。
  - **两个 ECharts 环形图**：任务类型分布、任务状态分布（按业务状态配色，中心显示总数），替代原来自绘的堆叠色块。
  - **最近任务时间线** + **定时任务表** + **快捷操作** 保留并归入统一栅格。
  - 加载态 `<Skeleton>` 骨架屏按新栅格布局。
  - 派生变量统一用带类型的 `??` 回退，消除 `period` / `scheduled_jobs` / `recent_tasks` 类型收窄错误。
- **验证**：`tsc --noEmit` 退出码 0；`vite build` 成功（11866 模块，40.88s，仅 chunk 体积告警非错误）。运行时视觉效果待用户在 dev/build 环境确认。

### 优化：仪表盘图表补充扇区标注 + 任务类型中文名与固定配色（前端，2026-09-17）
- **背景**：任务类型分布 / 状态分布环形图此前 `label: { show: false }`，扇区无标注、只能看底部图例；且图例直接显示后端原始键名（`course_full_crawl` / `weather` 等），不专业。
- **改动**：
  - `admin-frontend/src/constants/statusMaps.ts`：新增共享 `TASK_TYPE_MAP`（任务类型 → 中文名 + 十六进制固定色），来源为 `Processes.tsx` 原本地 `typeMap`。
  - `admin-frontend/src/pages/Processes.tsx`：删除本地 `typeMap`，改引共享 `TASK_TYPE_MAP`（消除重复定义，行为不变）。
  - `admin-frontend/src/pages/Dashboard.tsx`：
    - 两个环形图开启扇区标注（名称 + 数量 + 占比，`labelLine` + `labelLayout.hideOverlap`），并给每个扇区按任务类型固定配色；图例与趋势图序列名统一改用中文名。
    - 趋势图各序列按任务类型取色（`color` 数组与序列一一对应），与环形图配色语义一致。
- **验证**：`tsc --noEmit` 退出码 0；`vite build` 成功。运行时视觉效果待用户确认。

### 新增：系统设置「课程」面板加入课表爬虫总开关（前端，2026-09-17）
- **背景**：后端 `scheduler.py` / `crawl_task_service.py` 早已以 `course.spider_enabled` 作为「爬虫总开关唯一入口」（关闭后停止定时爬取与预约/立即任务自动拾取，管理页手动触发不受影响），且 `module_config.py` 已定义该配置项、`config_routes.py` 保存后会 `reload_scheduler` 即时生效。但设置页只在通用配置表格里以一行布尔值存在，需翻找。
- **改动**（`admin-frontend/src/pages/Settings.tsx`）：在「课程」折叠面板顶部加入独立快捷开关（沿用天气面板「企业微信天气预警推送」开关的模式），按开/关状态动态配色（开=蓝底「运行中」/关=红底「已停止」），带说明 Tooltip；乐观更新 + 失败回滚；调用 `configApi.update('course','spider_enabled', checked)`，保存后后端即时重载调度器，无需重启。
- **验证**：`tsc --noEmit` 退出码 0；`vite build` 成功。后端开关链路由代码核查确认（配置项存在、更新接口触发 `reload_scheduler`、`config_service.get` 正确解析布尔），未做线上实测。

## v6.18.0 (2026-09-09)

> 本次发布含管理端「解绑/收回身份」新能力、小程序端身份状态主动监察，以及审核整改/匿名会话令牌/公开接口/登录守卫等增强（覆盖 2026-09-08 ~ 09-09 累积改动）。

### 调整：停用课表爬虫定时爬取（后端，2026-09-10）
- **背景**：用户 2026-09-10 决定停用课表定时爬取（与教务系统账密登录失效的排查相关）。爬虫模块全部结构（`main.py` / `spider_runner` / `executors` / `crawl_task_service` 等）保留，仅关闭自动触发，可随时恢复。
- **方案**：
  - `core/config.py` 新增 `is_spider_schedule_enabled()`：读环境变量 `COURSE_SPIDER_SCHEDULE_ENABLED`（默认 `false`），优先级高于 `module_config` 表中可能遗留的 `spider_enabled=true`。
  - `model/module_config.py`：`spider_enabled` 默认值 `true` → `false`。
  - `services/crawl_task_service.py`：`dispatch_scheduled_crawls` 开头加总闸，未启用则记录日志并 `return`，不再拾取定时爬取任务。
  - `tasks/scheduler.py`：`start_scheduler` / `reload_scheduler` 均以 `(spider_enabled and spider_schedule_enabled)` 决定是否注册爬虫定时任务，并区分跳过原因日志。
- **恢复方式**：`.env` 设置 `COURSE_SPIDER_SCHEDULE_ENABLED=true` 后重启服务。
- **验证**：`py_compile` 四文件全部通过；`is_spider_schedule_enabled` 定义（`config.py:25`）与使用点（`crawl_task_service.py` / `scheduler.py`）齐备；当前 `.env` 未设置该变量 → 取默认 `false`，定时爬取处于停用态（未启动服务实测调度器行为，仅静态核查）。

### 清理：删除废弃的 `profile-edit` 页（小程序端，2026-09-10）
- **背景**：`miniapp-frontend/src/pages/profile-edit/` 自 2026-09-07 个人资料页改为「原地编辑」（`profile-detail`）后**已无入口且从未在 `app.config.ts` 注册**——小程序内不可达，属遗留死代码（排查「联系方式」文案时被它误导过一次）。
- **改动**：删除该目录 3 个文件（`index.config.ts`/`index.scss`/`index.tsx`），同步更新 `settings/index.tsx` 注释中对该页的表述（「源码亦已删除，可在历史 git 中找回」）。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 成功；产物 `pages/` 22 项、不含 `profile-edit`（其本就不参与打包）；`dist` 无 `process.env` 残留（0）。

### 调整：反馈移除「联系方式」——提交页/管理端不再收集与展示（2026-09-10）
- **背景**：按「涉及索要账号/联系方式的一律不要」的原则移除反馈模块的联系方式。用户澄清要删的是**提交页**的「联系方式（选填）」输入框（首轮按「反馈详情页」字面误删的是详情页展示行，本轮改正并把管理端同类展示一并移除）。
- **小程序端**（`src/pages/feedback/submit/index.tsx` + `index.scss`）：删除「联系方式（选填）」输入框（`Input` + `contact` state + 提交参数）；`import` 去掉 `Input`；表单字段注释同步；删除仅该输入框使用的孤儿样式 `.fb-input`。（详情页展示行已于同日早些的提交移除；`fb-detail-row`/`fb-detail-key`/`fb-detail-val` 被「提交时间」行复用故保留。）
- **管理端**（`admin-frontend/src/pages/Feedback.tsx`）：删除详情抽屉的「联系方式」`Descriptions.Item`（原 `current.contact` 条件渲染）；头部注释同步。
- **保留说明**：API 层 `FeedbackCreateParams.contact`（可选）与后端 `feedbacks.contact` 字段**保留不动**（历史数据与接口契约不受影响），仅前端不再采集与展示。
- **验证**：小程序 `tsc --noEmit` 0、`build:weapp` 成功、`dist` 无 `process.env` 残留（0）、`dist/pages/feedback` 下「联系方式」计数 0、`.fb-input` 产物计数 0；管理端 `tsc --noEmit` 0、`vite build` 成功、产物「联系方式」仅剩用户协议「十、联系方式」章节（法律文本，保留）。

### 调整：登录引导改纯气泡提示 + 绑定状态静默回收 + 首页绑定后补拉（小程序端，2026-09-10）
- **背景**：审核整改后遗留三处体验粗糙——①游客点受限功能用「累计 3 次弹 LoginModal」，交互啰嗦且弹窗易被判「反复弹窗」；②上次放弃绑定后再次打开小程序，持久化登录态撞 403 会弹「已退出登录」，用户刚进 app 无「正在使用」体感却被打扰；③登录页面确认已绑定后返回首页，「今日课程」为空需手动下拉刷新。
- **①登录引导简化**（`hooks/useLoginGuard.ts` + `home`/`profile`/`announcement/detail`/`login`）：游客点受限功能**只弹气泡提示**（`toastLoginRequired`），移除模块级 `privateClickCount`/`PRIVATE_CLICK_THRESHOLD`/`resetPrivateClickCount`/`runPrivateClick` 与 hook 返回的 `modalProps`；相应移除 profile 页、公告详情页的 `LoginModal` 用法（首页今日课程占位卡的弹窗入口保留）。登录入口由页面显式按钮/卡片（我的页头像区、宿舍用电「去登录」）承担。
- **②绑定状态静默回收**（`utils/bindGuard.ts` + `hooks/useBindStatusWatcher.ts` + `utils/request.ts`）：新增模块级 `bindConfirmedThisRun` + `hasBindConfirmedThisRun()` / `markBindConfirmed()`。绑定确认回调（`finishBindGuide`）/ bind-status 返回 `bound` 时置位。`useBindStatusWatcher` 检出未绑定、且「本周期从未确认过绑定、本地也无学号缓存」时**静默**降级游客（清登录态 + 清身份，不弹提示）；`request.handleStudentNotBound` 同理（进入路径前先取 `hadIdentity`，无历史身份则直接 return 不 toast）。曾真正绑定过（如使用中被解绑）仍明确提示。
- **③绑定后事件广播 + 首页补拉**（`bindGuard.ts` + `home/index.tsx` + `bind/index.tsx`）：`finishBindGuide()` 广播 `BIND_GUIDE_FINISHED_EVENT`（`bindGuide:finished`），首页新增 `privateLoadedRef` + 订阅该事件补拉今日课程/资料（本轮已拉过则跳过，防重复请求）；登出时重置标记并清空旧账号课程。绑定页检出「已绑定」误入时先 `finishBindGuide()` 再跳首页（清标记 + 触发补拉，避免标记残留吞掉后续真实 403 降级）。
- **④顺带修复**（`pages/bind/index.tsx` + `index.scss`、`pages/weather/index.tsx`）：绑定页学校行的原生 `Picker` 外套 `bind-row-picker-wrap`（普通 View 承担 flex 布局，使 Picker 与学号/绑定码行右对齐一致——原生 picker 宿主内部自带包裹结构，直接对其设 flex 不可靠）；天气页 Canvas 绘制时间标签前显式重置 `textAlign`/`textBaseline`（修复前一处降水角标遗留的对齐状态导致「时间右移、图标偏左」）。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 成功（18.09s）；`dist` 无 `process.env` 残留（0）；产物含 `bindGuide:finished` 事件与 `toastLoginRequired` 文案；已删符号（`runPrivateClick`/`modalProps`/`PRIVATE_CLICK_THRESHOLD` 等）全项目零残留引用。

### 调整：首页常用功能去掉「更多功能」与「自定义」（小程序端，2026-09-10）
- **背景**：首页「常用功能」宫格里的「更多功能」是无落地页的占位项（`DEFAULT_ITEMS` 中无 `action`/`pagePath`，点击只弹「等待学校开放接口」toast），卡片头部还有一个纯展示、无点击行为的「自定义」文本。二者均无实际功能，按需求移除。
- **方案**（`src/components/QuickAccess/index.tsx`）：删除 `DEFAULT_ITEMS` 的 `{ key: 'more', label: '更多功能', icon: 'gengduogongneng_24' }`（宫格由 8 项变 7 项）；删除 `card-header` 内的 `<Text className="card-more">自定义</Text>`；同步更新组件注释。
- **说明**：`QuickAccess` 仅首页引用，`more` key 无其他引用，删除不影响他处；`icon-gengduogongneng_24` 类定义随 iconfont 全局字体保留（未被引用，无影响）。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 成功（18.09s）；`dist` 无 `process.env` 残留（0）；产物中「更多功能」「自定义」文案计数 0。

### 调整：身份绑定页改极简分组表单（小程序端，2026-09-09）
- **背景**：用户对绑定页视觉不满意——此前是灰填充框 + 独立字段卡 + 重阴影的"卡片堆叠"样式，被批"这个卡片垃圾死了""渐变才更像 AI"；要求改**简约克制、有设计感**的表单。
- **方案**（`src/pages/bind/index.tsx` + `index.scss`）：去掉独立字段卡 / 灰填充框 / 渐变 hero，改为**近白底 + 单张分组卡（细描边圆角）+ 行内细分隔线**的 iOS 分组表单式结构：
  - 顶部一句引导「选择所在学校并填写认证信息」（不重复导航栏标题）；
  - 单张 `.bind-group` 卡内三行（高 108rpx、细分隔线分隔）：学校（右侧显值 + `.icon-jinru` 进入箭头，点击弹原生 Picker）/ 学号（Input 右对齐）/ 绑定码（Input 右对齐、等宽感）；
  - 全宽实心主色圆角提交按钮 `.bind-submit`（克制的按压缩放）+ 底部辅助说明「绑定码由管理员发放，一次性有效」；
  - 逻辑全部保留：学校列表空态/错误态（401/403→引导登录、其余→点击重试）、`handleSubmit` 三段校验、绑定成功 `finishBindGuide` + 返回首页、`useUnload` 时 `cancelBindGuide`。
  - 顺带清理：`schoolErrorMsg` state 仅 set 无人读（JSX 错误行已是固定文案「加载失败，点击重试」），属死代码，删除声明与两处 setter 调用。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 成功（19.33s，仅既存 CSS 体积/异步 chunk 警告）；`dist` 无 `process.env` 残留（0）；新类名 `bind-group`/`bind-row-divider`/`bind-footnote`/`bind-intro` 编入 `pages/bind/index.wxss`，旧类名 `bind-form`/`bind-field`/`bind-input-row`/`bind-head` 计数 0。

### 增强：学生身份「解绑/收回身份」（管理端，2026-09-09）
- **背景**：此前「学生身份」列表删除一条已绑定名单，只会删白名单行（`StudentRosterService.delete` 仅 `session.delete(row)`）、不碰该学生 `student_profiles`，导致学生身份被"孤儿化"——保留旧身份卡死、且因 `bind_student` 的 `ALREADY_BOUND` 护栏无法重新绑定；管理员也无从收回学生身份。
- **方案**：管理端「学生身份」列表对已绑定行新增「解绑」按钮，后端新增 `POST /api/admin/roster/students/<id>/unbind`（`@admin_required`）。`StudentRosterService.unbind` 按 `(school, student_number)` 定位绑定用户，清空身份字段（学号/学校/学院/专业/班级/年级/姓名/校园卡号，保留昵称/手机号/电表 cookie），吊销该用户全部活跃会话（强制重新登录走绑定流程），**名单保留**并重发一次性绑定码。
- **前端**：`admin-frontend` 新增 `rosterApi.unbind` + 列表行「解绑」按钮（仅 `bound_user_id` 非空显示，Popconfirm 确认，成功后复用绑定码弹窗展示新码并刷新）；删除确认文案改为准确描述（删名单会孤儿化身份、建议改用解绑）。
- **语义区分**：删除名单 = 移除白名单（已绑定身份孤儿化）；解绑 = 保留白名单、仅收回身份并立即重发绑定码，学生可一步重绑同一条名单。
- **验证**：后端 `py_compile` 通过；前端 `tsc --noEmit` 0 错误；`vite build` 成功，`dist` 含「已收回身份」「解绑」字符串。

### 增强：小程序端承接「解绑/收回身份」（2026-09-09）
- **缺口**：原仅靠请求撞 403 `STUDENT_NOT_BOUND` 才跳绑定页；且 `profile` 页 `loadAll` 用 `!profile ? getProfile() : profile` 永不刷新，解绑后学号/班级永久显旧值（冷启动也从 persist 恢复旧值）；跳转时未清身份缓存。
- **改动**：`utils/request.ts` 的 `redirectToBind()` 增加 `useUserStore.getState().setProfile(null)` 清本地身份缓存；新增 `hooks/useBindStatusWatcher.ts`，在 home/schedule/profile 三个 tab 页 `useDidShow` 主动调 `getBindStatus()`（仅 `@student_required`，未绑定返 `bound:false` 不 403），已绑定却被判未绑定→清缓存+跳绑定页，已绑定但无缓存→补拉资料；profile/home 资料改为始终 `getProfile()`（昵称编辑即时生效 + 解绑后 403 跳绑定页）。
- **链路**：解绑→会话吊销→下次请求 401→刷新失败→跳登录→重新登录→首页 `useDidShow` 探 `bind-status` 未绑定→跳绑定页；或在前台切 tab 被 watcher 主动感知。绑定页本就支持重绑（名单保留 + 新码）。
- **验证**：`build:weapp:clean` 成功（仅 webpack 既存 CSS 顺序/体积警告）；`dist` 无 `process.env` 残留（计数 0）；新逻辑入 `dist/common.js`。

### 修复：小程序审核整改——先体验后授权（2026-09-09）
- **背景**：微信审核驳回"进入首页即强制授权登录"。按规范放开公开浏览，受限功能改登录引导弹窗。
- **后端放开公开浏览**：天气（`/weather/current`、`/weather/hourly`）取消鉴权装饰器，游客可直接访问；校园通知（`/announcements` 列表/详情、`/announcements/unread-count`）由 `@student_bound_required` 改为新增的 `@miniapp_optional`（携带合法 token 时写 `g.current_user`，否则 `g.current_user=None` 但始终放行）。`announcement_service.unread_count` 加 `user_id is None → 返回 0` 守卫。
- **前端拦截器改造**（`utils/request.ts`）：401 分支区分「无 token 游客」与「会话过期」——游客（`getAccessToken()/getRefreshToken()` 均为空）抛 `'请先登录后查看'` 且不强制 `reLaunch` 登录页；仅会话过期才清 token 并跳登录。
- **登录引导弹窗**：新增 `components/LoginModal`，首页/我的/时间轴（schedule）游客态渲染登录引导卡，点"确定/登录" `navigateTo` 登录页；登录成功后 `getCurrentPages().length > 1` 则 `navigateBack()` 返回触发页。首页快捷入口 `requireLogin` 时仅 `notice`/`weather` 公开，其余弹登录。
- **验证**：`test_miniapp_phase2.py` 调整——`test_no_token_401` 仅断言电量/学生资料返回 401；新增 `test_public_endpoints_anonymous_ok` 断言天气/公告 4 接口游客 200；admin 403 仅断言电量；`test_deleted_user_returns_401_user_gone` 改用 `/electricity/current`。**15 项全部通过**。补 `@miniapp_optional` 定义 + 路由 import 后，此前因未导入导致的蓝图加载 `NameError` 已消除。

### 增强：公开接口匿名会话令牌（可溯源，2026-09-09）
- **背景**：天气 / 公告等公开接口对未登录用户零凭证开放，此前只能按 IP 溯源，无法区分同一出口下的不同匿名访客。
- **核心约束**：微信小程序 `wx.request` **不维护 cookie**（服务端 `Set-Cookie` 不会自动存/回传），服务端 session cookie 方案在小程序端不可行。
- **方案**：服务端签发带时间戳的匿名会话令牌 `X-Anon-Token`（格式 `<uuid>.<exp_ts>.<hmac签名>`，TTL 24h，HMAC-SHA256 用 `SECRET_KEY` 签名防篡改）：
  - 新增 `app/utils/anon_session.py`：`issue_anon_token` / `parse_anon_token`（签名比对 + 过期校验）/ `is_public_path` / `attach_anon_session`（after_request 挂载，抽成函数供 `create_app` 与测试夹具共用）。
  - `app/__init__.py` 的 `create_app` 调 `attach_anon_session(app)`：仅对 `/api/miniapp/weather*` 与 `/api/miniapp/announcements*` 下发令牌；客户端回传有效令牌则**原样回写**（会话稳定不旋转），否则签发新令牌；同时 INFO 日志记录 `path/method/status/anon_id/ip` 供溯源。
  - 前端 `utils/request.ts`：`X-Anon-Token` 响应头捕获存本地、请求时回传（`getAnonToken` / `captureAnonToken`）；**未改动 401 游客逻辑**，不影响"先体验后授权"。
- **限流职责划分（重要，曾一度回退后修正）**：限流**仍按 IP**（延续原有 `60 per minute` / `10 per second` / `3600 per hour` 兜底），匿名令牌**专职做访问日志溯源，不参与限流 key**。原因：令牌是客户端可自行清空/轮换的，若用它做限流 key，攻击者丢弃令牌重领即可让每次请求落进全新桶、绕开 IP 闸门（可放大约 60 倍）。故 `extensions.get_identity_key` 匿名分支保持 `get_remote_address()` 不变。
  - 若后续确需"会话级配额"，正确做法是叠加一层**令牌签发节流**（限制单 IP 单位时间可领取的新令牌数），而不是把限流 key 换成会话——本版未实现。
- **验证**：新增 `test_public_endpoint_issues_anon_token`（断言天气接口下发令牌、公告接口回显同一令牌）；`test_miniapp_phase2.py` **16 项全部通过**；`tsc --noEmit` 退出码 0；`build:weapp:clean` 成功、`process.env` 残留 0。

### 修复：天气页 5 个端点漏放公开，补齐"先体验后授权"（2026-09-09）
- **背景**：天气页（`pages/weather/index.tsx`）对未登录用户 5 个端点 401——`/weather/daily`、`/weather/alerts`、`/weather/air`、`/weather/indices`、`/weather/minutely`。先前只放了 `current` 和 `hourly` 两个端点，**漏了同一类公开信息**。
- **修复**：去掉这 5 个端点的 `@student_bound_required` 装饰器（`app/api/miniapp_routes.py:553-634`）。这 5 个端点只读和风天气/空气质量/分钟降水/生活指数缓存，不依赖任何用户身份，与 `current`/`hourly` 同性质，理应一并公开。
- **测试**：`test_public_endpoints_anonymous_ok` 扩展为覆盖 9 个公开端点（7 天气 + 2 公告）；cache/fetcher 用 mock 兜底避免依赖真实 Redis/外网。`test_miniapp_phase2.py` **16 项全过**。
- **前端零改动**：`utils/request.ts` 不变；天气页已是无脑发请求，鉴权放开后 401 自动消失。

### 增强：登录守卫 hook + 游客态完整 UI + 受限功能登录引导（2026-09-09）
- **背景**：游客进入「我的」页只渲染极简占位（"未登录"卡片 + 登录按钮），与首页"先体验后授权"完整 UI 不一致；公告详情页点击「收藏/已阅」直接发请求再 401 报错，弹错乱弹窗。两类问题都需要"游客态保留 UI + 点击再引导登录"。
- **新增 `useLoginGuard` hook**（`src/hooks/useLoginGuard.ts`）：封装"未登录 → 弹 LoginModal；已登录 → 执行 action"模式。点 LoginModal「确定」跳登录页，登录成功后由用户重新点击触发原动作（不自动重放，规避副作用重复）。
- **「我的」页改造**（`src/pages/profile/index.tsx`）：去掉"游客态早返回"分支，**整页 UI 保留**——头像/昵称、校园卡、宿舍用电、功能列表、版本号都正常渲染；游客态用 `--` 占位数据、点击任何受限项（头像/消息/电量卡/功能列表 5 项）弹 LoginModal；游客态不再显示「退出登录」按钮、不显示未读角标、不调任何需登录的接口。
- **公告详情页守卫**（`src/pages/announcement/detail/index.tsx`）：`handleFavorite` / `handleMarkRead` 包 `guard()`，游客点收藏/已阅先弹 LoginModal，**不再发请求 → 不再 401 报错**。重复的 `import { ScrollView }` 顺手合并到顶部。
- **`useFeedbackBadge` 游客态保护**（`src/hooks/useFeedbackBadge.ts`）：`refresh()` 开头加 `if (!isLoggedIn) return;`，避免 tabBar 预加载/他处被动调用此 hook 时发请求再 401 噪音。
- **验证**：`tsc --noEmit` 退出码 0、错误 0；`build:weapp:clean` 成功，`process.env` 残留 0，`dist/app.js` 生成。

### 修复：小程序审核整改（第二轮）——登录环节可取消、取消强制登录、弹窗改累计（2026-09-09）
- **驳回原文**：「小程序【登录】登录环节，需为用户提供显著有效的可取消/拒绝或返回按钮，不得反复弹窗或强制用户进行登录才能体验，请整改后再提交审核」。
- **登录页增加两个拒绝入口**（`pages/login/index.tsx` + `index.scss`）：本页 `navigationStyle: custom`，没有原生导航栏，此前进入后**无任何退出方式**（典型的"强制登录"）。
  - 左上「返回」按钮：页面栈 >1 时 `navigateBack()`，栈底（被 reLaunch 直达）时 `switchTab` 首页；
  - 底部「暂不登录，随便看看」次级按钮：直接以游客身份 `switchTab` 首页；
  - 页内补充提示「不登录也可浏览天气、通知公告等公开内容」。
  - 协议勾选区整行可点（链接 `stopPropagation`），点登录按钮未勾选时仍 toast 提示。
- **取消自动弹窗**：`pages/schedule/index.tsx` 游客进入「时间轴」不再 `setShowLogin(true)` 自动弹窗（这是"反复弹窗"主因），只渲染引导卡；引导卡「登录 / 注册」按钮改为**直接 `navigateTo` 登录页**，去掉中间弹窗层。
- **登录引导弹窗改为累计触发**（`hooks/useLoginGuard.ts`）：新增模块级 `privateClickCount` + `PRIVATE_CLICK_THRESHOLD = 3`。游客点私有模块前 2 次只出气泡 toast「该功能需登录后使用」，第 3 次才弹一次 LoginModal，弹完归零重新累计；登录成功调 `resetPrivateClickCount()` 清零。非 hook 场景（首页宫格/「全部课程」/今日课程占位）用导出的 `runPrivateClick(onThreshold)` 复用同一策略。
- **点头像直达登录页**：「我的」页头像区游客态不再走 guard 弹窗，直接 `navigateTo` 登录页；游客头像占位字由「游」改为「登」，游客展示名由「未登录」改为「登录」。宿舍用电「去登录」按钮同样直达登录页。
- **取消强制跳转登录页**：`utils/request.ts` 401 且 refresh 失败时，不再 `reLaunch('/pages/login/index')`，改为 `useAuthStore.getState().logout()` 降级为游客 + 只 toast 一次「登录状态已过期，可继续浏览公开内容」（并发 401 用 `sessionExpiredNotified` 节流，避免反复打扰）。删除未使用的 `redirectToLogin`。
- **认证环节也给出口**：`pages/bind/index.tsx` 新增「暂不认证，先去逛逛」（保留登录态回首页）与「退出登录」；`useBindStatusWatcher` 检测到被管理员解绑后不再 `reLaunch` 绑定页，仅清缓存 + 提示一次（同一学号只提示一次）。`pages/profile-detail` 注销账号后由 `reLaunch` 登录页改为 `switchTab` 首页游客态。
- **验证**：`tsc --noEmit` 0 错误；`rm -rf dist && npm run build:weapp` 成功（仅既存的 app-origin.wxss 体积与 NoAsyncChunks 警告）；产物 `process.env` 残留 0；新增文案均以 unicode 转义形式进入 `dist/pages/login/index.js`、`dist/pages/bind/index.js`、`dist/common.js`。

### 重构：登录/身份验证页改用 WeChat 原生顶栏（2026-09-09）
- **用户复盘**：上一轮在登录页自绘了左上「‹ 返回」+ 底部「暂不登录，随便看看」+ tip 文案，绑定页加了「暂不认证，先去逛逛」+「退出登录」。实测发现自绘 + 原生顶栏的双重入口体感割裂，要求统一改为 WeChat 原生标准顶栏（左侧自动 `< 返回`、居中标题），与"退出公告"等页面一致。
- **登录页**（`pages/login/index.{ts,scss,config.ts}`）：去掉 `navigationStyle: 'custom'`、新增 `navigationBarTitleText: '登录'`；删除自绘的 `.login-nav` / `.login-skip` / `.login-guest-tip` 及对应 handler。
- **身份验证页**（`pages/bind/index.{ts,scss}`）：配置本就是原生顶栏；删除 `.bind-foot`（"暂不认证，先去逛逛" + "退出登录"）及 `handleSkip / handleLogout`；`useEffect` 与提交成功后跳转首页由 `reLaunch` 改为 `switchTab`。
- **`utils/request.ts`**：`redirectToBind` 由 `reLaunch` 改为 `navigateTo`，**保留栈**让原生 `< 返回` 能直接回上一页（原 reLaunch 会清栈变死路）。
- **验证**：`tsc --noEmit` 0 错误；`build:weapp` 21.65s 成功；产物 `login-skip / login-guest-tip / login-nav / bind-foot / bind-skip / bind-logout` 自定义类与「暂不登录」「暂不认证」文案均消失；`dist/pages/login/index.json` 确认 `navigationBarTitleText: "登录"`、无 `navigationStyle: custom`；`process.env` 残留 0。

### 修复：登录成功未绑定身份 / 会话中被解绑 的死状态回收（2026-09-09）
- **问题**：① 登录成功但用户不绑定身份，此时 `isLoggedIn=true` 但所有业务接口一律 403 `STUDENT_NOT_BOUND`——既用不了功能、又无出口退回游客态；② 会话中被管理员解绑后本地仍保留登录态，同样卡在"已登录却啥都干不了"的半死状态。
- **登录页补"登录后立刻确认绑定状态"**（`pages/login/index.tsx`）：`handleLogin` 在 `setAuth` 之后同步调 `userApi.getBindStatus()`（该接口仅 `@student_required`、未绑定返 `bound:false` 不 403）。已绑定 → toast「登录成功」+ `getCurrentPages().length>1 ? navigateBack : switchTab home`；未绑定 → toast「登录成功，请先完成身份认证」+ **`redirectTo('/pages/bind/index')` 替换登录页**（避免原生「< 返回」退回"已登录"的登录页造成死循环）。
- **`useBindStatusWatcher` 重写：把"已登录未绑定"定义为无效登录态，整体回退游客**（`hooks/useBindStatusWatcher.ts`）：
  - 新增 `revokeSession(message, noticeKey)`：同步执行 `useAuthStore.getState().logout()` + `useUserStore.getState().setProfile(null)` + `resetPrivateClickCount()` + 一次性 toast（节流，避免切 Tab/多页面重复提示）。只清本地令牌、不回调后端 logout：解绑场景服务端已 `delete_all_user_sessions` 吊销会话；未绑定场景残留会话无业务数据访问权、1h 自然过期，无风险。
  - Tab 页 `useDidShow`（home/profile/schedule）触发：已登录且 `getBindStatus().bound=false` → 调 `revokeSession`；按成因给不同提示——本地曾缓存过学号（会话中被解绑）=「身份已被管理员解绑，请重新登录并认证」；从未绑定=「尚未完成身份认证，已退出登录」。
  - 导出 `resetBindNotice()`：登录成功后清空提示节流，避免上一次未绑定提示被吞。
- **放弃绑定场景兜底**：登录页未绑定走 `redirectTo` 绑定页（替换登录页），用户在绑定页点原生「< 返回」回到上一 Tab 页，`useDidShow` 的 watcher 立即感知未绑定并回退游客态——不会卡在半死状态。非 Tab 来源页进入绑定再返回时，也由下一次切换到 Tab 页的 watcher 兜底回收。
- **合规**：全程只回退本地状态，**不强制跳转**任何页面；游客仍可浏览天气/公告等公开内容。
- **验证**：`tsc --noEmit` 退出码 0、错误 0；`build:weapp` 成功（`Compiled successfully`）；产物 `dist` 中 `process.env` 残留计数 0；登录页 bundle 含 `redirectTo` 至 `pages/bind/index` 逻辑。

### 修复：登录成功未绑定 / 会话解绑 的导航叠加（2026-09-09 第十四轮）
- **复现**：登录成功但未绑定 → 身份绑定页"压"在登录页之上（登录页没消失）；点返回退回登录页；再返回登录态虽被清，却又弹出一次身份绑定页。
- **根因**：`utils/request.ts` 的 `redirectToBind()` 用 `Taro.navigateTo` 把绑定页**压栈**到当前页（登录页 / Tab 页）之上。登录后若某个后台业务请求命中 403 `STUDENT_NOT_BOUND`，拦截器就把绑定页 push 到登录页上方，与登录页 `handleLogin` 自己的 `redirectTo`（替换登录页）相互打架，造成登录页残留 + 绑定页层层叠加。
- **修复**：`redirectToBind` 改为 `handleStudentNotBound`，**不再自动跳转**。拦截器只负责清空本地身份缓存（`useUserStore.setProfile(null)`，避免"我的"页显旧学号）+ 抛出可读错误。绑定页进入路径收敛为两处：①登录页 `handleLogin` 检测到未绑定用 `redirectTo` 替换登录页进入（登录页随之消失）；②会话中被解绑后由 `useBindStatusWatcher` 降级为游客态，用户重新登录再次进入。同步更新 `pages/bind/index.tsx` 顶部注释（原"由请求层统一跳转"已不实）。
- **效果**：登录成功未绑定 → 登录页消失、仅余一个绑定页；放弃绑定点原生返回 → 回到上一 Tab 页、`useDidShow` 的 watcher 立即回退游客态，**不再弹出第二个绑定页**。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 成功（20.41s，`Compiled successfully`）；`dist` 中 `process.env` 残留 0。

### 修复：会话解绑场景的"已登录未绑定"盲区回收（2026-09-09 第十五轮）
- **背景**：第十四轮已让拦截器不再自动跳转绑定页，但 `useBindStatusWatcher` 仅在 Tab 页 `useDidShow` 触发回收。若用户停在**非 Tab 子页**（如 coursetable 等经 `navigateTo` 打开的页面）时被解绑 / 未绑定，watcher 永不触发，会卡在"已登录却啥都干不了"的半死状态。
- **改动**：`utils/request.ts` 的 `handleStudentNotBound()`（命中 403 `STUDENT_NOT_BOUND` 时）在"清空本地身份缓存"之外，新增**把本地登录态降级为游客**（`useAuthStore.logout()`，**不跳转页面**），并节流提示一次「身份未绑定，已退出登录」。该降级对任意页面（含非 Tab 子页）均生效，与 watcher 形成双保险；因不跳转、不 `navigateTo`，绝不引入第十四轮修掉的绑定页叠加问题。
- **注意**：`getBindStatus` 本身返回 200 `{bound:false}`，不会触发本分支；仅真正业务请求 403 时才降级，不会误伤已绑定用户。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 成功（21.06s，`Compiled successfully`）；`dist` 中 `process.env` 残留 0。
- **同步**：`小程序审核说明_草稿.md` 第 5 点补充"绑定页以替换方式进入、返回不退回已登录登录页、不反复弹身份认证页"。

### 重构：个人资料详情页按用户示意图重排编辑布局
- **初始全黑**：6 个只读行（学号/班级/学校/学院/专业/校园卡号）去掉 `detail-row-locked` 置灰类；`.detail-row-value` 由 `#666` 改 `#1a1a1a`。只读不可编辑的语义靠"无编辑入口"保证，不再用颜色暗示"禁用"。
- （本条初版曾实现为「hero 变身编辑表单」，**已被下方「编辑表单由 hero 移入卡片」条目取代**，最终编辑交互收敛在「编辑信息」卡内。）
- **保存语义**：`chooseAvatar` 不再即时 `updateAvatar`，头像改本地暂存 `pendingAvatarUri`；仅「保存」才先 `updateAvatar`(若有) 再 `updateProfile`；「取消」丢弃全部暂存。没点保存后端/全局 store 一个都不改。
- 改动文件：`miniapp-frontend/src/pages/profile-detail/{index.tsx,index.scss}`。
- SCSS 同步清理 6 组孤儿类（`detail-row-locked` / `detail-row-link`(+active) / `detail-row-arrow` / `detail-row-input` / `detail-row-placeholder` / `detail-row-avatar`），grep 确认无引用后删除；另 `detail-avatar-sm` / `detail-avatar-text-sm` 当时一并删除，**后续因编辑表单移入卡片而重新引入**（见末条）。
- 验证：`tsc --noEmit` 退出码 0；`npm run build:weapp` 18.60s 成功（备份 `dist_bak_20260908_185306`）。

### 修复：electricity.ts 漏引 ElectricityMonthlyResult 类型（2026-09-08）
- `Cannot find name 'ElectricityMonthlyResult'`（`miniapp-frontend/src/api/electricity.ts:49,44` / `:50,14`）：类型已在 `src/types/api.ts:307` 定义，纯导入块漏引。
- 改动：导入块补 `ElectricityMonthlyResult`。type-only，babel 编译擦除，运行时无影响。
- 验证：`tsc --noEmit` 退出码 0。

### 优化：编辑态下不可编辑行变灰（2026-09-08）
- 在「非编辑态全黑」基础上加一层**编辑态视觉提示**——进入编辑后，身份信息（学号/班级/学校）+ 学籍信息（学院/专业/校园卡号）的值文字变浅灰（`#b8b8b8`），明确"这些不能改"边界；可编辑的头像 / 昵称（位于「编辑信息」卡内）保持黑字 + 蓝下划线突出。取消编辑立即恢复全黑，不污染查看态。
- 改动文件：`miniapp-frontend/src/pages/profile-detail/{index.tsx,index.scss}`。6 个 `<Text>` 改为条件 `className`（`editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'`），新增 `.detail-row-value-readonly` 单一样式规则。
- 验证：`tsc --noEmit` 退出码 0；`npm run build:weapp` 18.70s 成功；产物 `dist/pages/profile-detail/index.wxss` 确认新类 `detail-row-value-readonly{color:#b8b8b8}` 已编入、基础类 `color:#1a1a1a` 不变、`process.env` 残留 0。

### 优化：小程序天气页图标由 emoji 换真实 PNG + 修复弱对比度（2026-09-08）
- **换真图**：天气状况图标此前全用 emoji，不同设备渲染不一致。改为 8 张和风天气 PNG（晴 / 多云 / 阴 / 小雨 / 大雨 / 雪 / 雷 / 雾），新增 `miniapp-frontend/src/assets/weather/` 与映射工具 `src/utils/weatherIcons.ts`（`textToIconKey` 中文状况 → 图标 key，含「多云」优先判 sun-cloud、「大雨/暴雨」→ heavy-rain）。接入点：天气页 7 天预报 `<Image>`、24 小时折线图 Canvas `drawImage`。
- **修对比度**：灰色云 / 雨图标在蓝色卡片背景上对比过弱。7 天预报走 CSS `.daily-icon-img { filter: drop-shadow(0 1rpx 4rpx rgba(255,255,255,0.6)); }`（沿 PNG alpha 外缘描白，不改布局）；24 小时折线走 Canvas `ctx.shadowColor/shadowBlur=6` 并在 `drawImage` 后立即重置为 0（避免下方时间文字被镀白边）。晴天图标不受影响。
- 改动文件：`miniapp-frontend/src/pages/weather/{index.tsx,index.scss}`，新增 `src/utils/weatherIcons.ts` + `src/assets/weather/*.png`(8)。
- 验证：`tsc --noEmit` 退出码 0；`npm run build:weapp` 17.99s 成功；产物核对白色光晕已在 wxss、Canvas shadow 已在页面 js、8 张图标以 base64 内联、映射关键词（转义形式）在包内、`process.env` 残留 0。

### 重构：编辑表单由 hero 移入「编辑信息」卡片（2026-09-08）
- 头像 / 昵称的编辑项改为**卡片承载**：不再把 hero 变成表单，hero 恢复为**始终纯展示**（大头像 + 已保存昵称 + 班级），始终显示已保存的值。
- 「编辑信息」卡：**与身份/学籍信息卡同构，始终是完整卡片**，承载「头像」「昵称」两行。
  **非编辑态**两行只读黑字展示（不置灰），标题 `编辑信息 ›` 可点进编辑；点击后两行**原地替换为真正的编辑表单**
  ——「头像」行（小头像 + 蓝色「更换」，可点选图）+「昵称」行（Input，蓝下划线）；**保存 / 取消后再变回**只读黑字展示。
- 保存语义不变：头像本地暂存 `pendingAvatarUri`、昵称暂存 `nickname` state，仅点保存才提交；取消丢弃全部暂存。编辑中 hero 不跟着变（始终展示已保存值），保存后才更新。
- 改动文件：`miniapp-frontend/src/pages/profile-detail/{index.tsx,index.scss}`。
- SCSS：删除 6 组 hero 编辑孤儿类（`detail-hero-avatar` / `-editable` / `-hover` / `-change` / `detail-hero-name-input` / `-placeholder`）；新增 `.detail-avatar-edit` / `.detail-avatar-sm` / `.detail-avatar-text-sm` / `.detail-avatar-edit-hint` / `.detail-avatar-edit-hover` / `.detail-row-value-input` / `.detail-row-value-placeholder`。
- 验证：`tsc --noEmit` 退出码 0；`npm run build:weapp` 18.92s 成功（备份 `dist_bak_20260908_193958`）；产物 `dist/pages/profile-detail/index.wxss` 确认新类（`detail-avatar-edit` / `detail-avatar-sm` / `detail-row-value-input`）已编入、旧 hero 类全部 0 命中、`process.env` 残留 0。

### 修复：时间轴切换到未来周后，课程状态全部误判为「已结束」（2026-09-08）
- **症状**：用户在时间轴页切到将来周（如第 3 周，对应日期 9/14-9/20），当日课程全部标"已结束"。实际是将来时，应是"未开始"。
- **根因**：`CourseCard.courseStatus` 用 `Date.now()` 与课程 `_timeInfo.start_ts` 比较；`start_ts` 是后端按**课程在 DB 里存的 `week_number` 字段**算的（一般是这门课第一次开课的周，对应 9/7 周一 08:10），而**不是**前端当前选中的周。当 `week_number` 与显示周不一致时，比较的时间基准是错的——今天 9/8 已经晚于 9/7 08:10 → 误判"已结束"。
- **修复**：`courseStatus(course, targetDate?)` 增加可选 `targetDate`（YYYY-MM-DD）参数。提供时按"该日期 + 课程的 `start_time`/`end_time`"重算有效时间戳再比较；不提供时退回 `_timeInfo`（"今天"接口已按今天过滤，行为不变）。时间轴页 `fetchDayCourses` 调用处传入 `selectedDate`。
- 改动文件：`miniapp-frontend/src/components/CourseCard/index.tsx`、`miniapp-frontend/src/pages/schedule/index.tsx`。
- 验证：`tsc --noEmit` 退出码 0；`npm run build:weapp` 18.89s 成功（备份 `dist_bak_20260908_195556`）；`process.env` 残留 0。
- **未做范围**：课程"时间"显示（`tsToHm(c._timeInfo?.start_ts)`）仍按原 `_timeInfo`——只取 HH:MM 不带日期，故不受此 bug 影响（08:10 / 14:10 一直显示正确）；如要统一以"选中那一天"为基准，只需把同一 `selectedDate` 传进该函数即可，但当前未改。

### 重构：个人资料页编辑布局按示意图彻底重排（2026-09-08 晚）
- **症状**：编辑信息卡布局与用户意图反复不一致（之前在底部追加卡片、hero 始终显示等多次走偏）。
- **最终设计（按用户手绘示意图）**：
  - **非编辑态**：hero（大头像+昵称+班级）→ 身份信息卡 → 学籍信息卡 → 「编辑资料 ›」按钮 → 注销账号。
  - **编辑态**：**hero 让位**，「编辑信息卡」替代顶部位置（含头像行+昵称行），下方仍是身份/学籍信息卡（值变灰）→ [保存][取消] 按钮 → 注销账号。
- **关键改动**：
  - `index.tsx`：渲染分支重写——hero `{!editing && ...}`，编辑信息卡 `{editing && ...}`，底部按钮按态切换（编辑资料 ↔ 保存+取消）。
  - `index.scss`：`.detail-avatar-sm` 自带 `background:#6e8efb`（**不依赖** placeholder 类的 background，避免之前"组合类样式应用顺序"踩坑导致空心圆）。删除已无用的 `.detail-avatar-edit`/`.detail-avatar-edit-hover`/`.detail-avatar-edit-hint`。新增 `.detail-row-link`、`.detail-row-hover`、`.detail-row-right`、`.detail-edit-entry`、`.detail-edit-entry-hover`。
- 验证：`tsc --noEmit` 0；`build:weapp` 成功（128 个产物文件，无 process.env 残留）；产物 `.detail-avatar-sm{background:#6e8efb}` 蓝底生效。
- **症状**：点时间轴页周次徽标弹出「学期+周」选择器抽屉时，底部 custom tabBar 仍可见并盖在抽屉下方，视觉割裂。
- **根因**：项目用 `tabBar.custom: true`（自定义 TabBar），微信的 `wx.hideTabBar` **对 custom TabBar 不生效**（官方文档：custom 模式需"控制 custom-tab-bar 组件自身的 return"）。drawer `position:fixed; bottom:0` 也只能贴到**页面视口**底部，够不到框架层渲的 custom-tab-bar。
- **修复**（走项目已有的 `eventCenter` 事件总线，与 `TAB_INDEX_EVENT` 同一范式）：
  - `src/utils/tabBarState.ts` 新增 `setTabBarHidden(bool)` / `getTabBarHidden()` / `TABBAR_HIDDEN_EVENT` 事件。
  - `src/custom-tab-bar/index.tsx` 订阅 `TABBAR_HIDDEN_EVENT`，`hidden=true` 时 `return null`。
  - `src/pages/schedule/index.tsx` 抽屉开关 `useEffect` 改调 `setTabBarHidden(showWeekPicker)`。
- 改动文件：`utils/tabBarState.ts`、`custom-tab-bar/index.tsx`、`pages/schedule/index.tsx`。
- 验证：`tsc --noEmit` 退出码 0；`npm run build:weapp` 成功；`process.env` 残留 0。
- **先前错误尝试**：第一版用 `Taro.hideTabBar({ animation: false })`，对 custom TabBar 无效（用户反馈"还是这个样"），已撤回。
- **说明**：滚轮本身（`<PickerView>` 编译为微信原生 `<picker-view>`）是原生的；抽屉外壳（半透明遮罩 + 底部弹卡 + 取消/确定栏）是自定义 CSS。本修复只动 tabBar 可见性，不改抽屉实现。

### 修复：编辑信息卡片内小头像变白、无头像用户看不到占位文字（2026-09-08）
- **症状**：点击「编辑信息」进入编辑态后，卡内「头像」行的圆形小头像显示为空白（无头像用户看不到蓝底"w"占位符），与顶部 hero 的蓝底占位头像不一致。
- **根因**：`.detail-avatar-sm` 写了 `background: #fff`，且该规则在 SCSS 中定义于 `.detail-avatar-placeholder` **之后**——同优先级下后写者覆盖，把占位符蓝底 `#6e8efb` 覆盖成白底，白字"w"在白底上不可见 → 视觉空白圆圈。顶部 hero 无此问题是因为 `.detail-avatar-placeholder` 定义晚于 `.detail-avatar`。
- **修复**：从 `.detail-avatar-sm` 删除 `background: #fff`，该类只保留尺寸/形状；背景交给 `.detail-avatar-placeholder`（蓝底）或由图片本身覆盖（`<Image>` 情况背景本就不可见，删除无影响）。加注释说明"勿在此写背景"。
- 改动文件：`miniapp-frontend/src/pages/profile-detail/index.scss`。
- 验证：`npm run build:weapp` 成功（备份 `dist_bak_20260908_200704`）；产物 `detail-avatar-sm{border-radius:50%;height:72rpx;width:72rpx}`（无背景）+ `detail-avatar-placeholder{...background:#6e8efb...}` 并存、`process.env` 残留 0。

### 修复：拦截器与 watcher 重复弹「身份未绑定」提示（2026-09-09）
- **症状**：从子页（如 coursetable）原生返回 Tab 页时，可能先后弹出两条「身份未绑定」类提示——先由 `useBindStatusWatcher` 的 `revokeSession`（Tab 页 `useDidShow` 探 `bind-status` 判未绑定→降级游客 + 弹一次 toast），再由仍在飞行中的业务请求撞 403 `STUDENT_NOT_BOUND` 触发 `handleStudentNotBound` 又弹一次。
- **根因**：第十五轮在 `handleStudentNotBound` 加了 `logout()` 降级 + toast，与 watcher 的回收构成「双保险」，但两者都可能弹 toast，缺「谁先到谁提示」的互斥。
- **修复**：`handleStudentNotBound` 进入时先读 `const wasLoggedIn = useAuthStore.getState().isLoggedIn`；**若已是游客（说明 watcher 已先行回收降级），则早退**——不再重复 `logout()`、不再重复提示。仅当拦截器比 watcher 先到（请求 403 时本地仍 `isLoggedIn=true`）才由其负责降级 + 提示。配合既有模块级 `studentNotBoundNotified` 节流（3 秒窗口内只提示一次），并发多请求也仅提示一次。
- 改动文件：`miniapp-frontend/src/utils/request.ts`。
- 验证：`tsc --noEmit` 退出码 0；`build:weapp` 20.30s `Compiled successfully`；`dist` 中 `process.env` 残留 0。

### 重构：身份认证页去 AI 模板感，改白底细边 + 字段分组（2026-09-09）
- **背景**：此前只删了页面内重复标题、调了文案，结构仍是「灰底上浮一张带重阴影的白卡 + 发光药丸按钮」——典型的 AI/模板生成观感，与用户「专业一点、少点 AI 味」的诉求差距大。
- **改动**（`pages/bind/index.tsx` + `index.scss`，+94/-67）：
  - 去掉浮卡重阴影：容器改为白底 + `1rpx` 细边的 `.bind-form`，radius-large，不再用 `$shadow-card`。
  - 表单拆成字段组 `.bind-field`，相邻分组用 `border-top` 细分隔线分隔，形成清晰层级（学校 / 学号 / 绑定码）。
  - 输入框由描边框改为**浅灰填充**（`background: $border-color`、无边框、定高 88rpx、radius-medium）——现代表单做法，弱模板感。
  - 学校选择由自由换行 chips 改为**两列网格**（`grid-template-columns: repeat(2,1fr)`），更规整；选中态主色浅底。
  - 提交按钮做**平实主色、无发光**、radius-medium、定高 92rpx，补 `hoverClass` 点击态（opacity 0.88），禁用态灰底。
  - 头部 `.bind-head` 只保留一句上下文说明（`bind-intro`），不重复导航栏「身份认证」标题；文案延续去客套/废话。
- 验证：`tsc --noEmit` 0；`build:weapp` 19.93s `Compiled successfully`；`dist` 新类名（bind-form/bind-field/bind-intro/bind-input-row 各 2 处）编译进去、旧类名（bind-card/bind-title/bind-desc 全 0）清除、`process.env` 残留 0。
- 提交 `44044a4`（本地，未推送）。

### 修复：身份绑定页「学校列表」被前端错误吞噬误显为数据丢失（2026-09-09）
- **症状**：预览设备进入绑定页，学校处显示「暂无学校选项」，用户误以为学校数据丢失。后端 `/api/miniapp/student/schools` 逻辑正确，本地库 `org_units` 表存在 `school` 节点（`id=2, name=cqie`），数据本身未丢。
- **根因**：原 `useEffect` 用 `Promise.all([getSchools(), getBindStatus()])`，**任一请求失败即进 `catch` 且空处理**——`getSchools` 一旦失败（网络抖动 / 预览设备指向无数据环境 / 后端偶发 5xx），`schools` 永远停在 `[]`，前端把「加载失败」伪装成「暂无数据」，造成数据丢失的错觉。
- **修复**（`pages/bind/index.tsx`，提交 `881df30`）：
  - 拆为独立 `loadData`：两个请求各自 `try/catch`，`getSchools` 失败不影响绑定状态查询，反之亦然。
  - `getSchools` 失败时 `setSchoolError(true)` + `Taro.showToast('学校列表加载失败，请检查网络')`，不再静默。
  - 空状态按 `schoolError` 区分：「加载失败，点击重试」（可点击 `loadData()` 重拉）/ 「暂无学校选项，请联系管理员」（真无数据）。
  - 绑定状态查询失败不阻断页面，用户可停留重试。
- **验证**：`tsc --noEmit` 0；`build:weapp` 20.02s `Compiled successfully`；`dist` 中 `process.env` 残留 0、新类名 `bind-school-chip` 编入 `index.wxss`/`index.js`、错误文案「学校列表加载失败…」以 unicode 转义进入 `index.js`。
- **后续提示**：若上传新 `dist` 后学校列表仍空，需检查小程序 `baseUrl` 是否指向正确后端（本地 `29528` vs 生产 `yuetang.cloud`）及该环境 `org_units` 是否确有 `school` 节点。

### 修复：绑定页学校列表「加载失败」透出真实错误并引导登录（2026-09-09 夜间）
- **复现**：用户实测学校列表仍「加载失败」。经全链路核查，数据层与服务端均无问题——本地库 `org_units` 确有 `school` 节点（`id=2, name=cqie`）；生产 `yuetang.cloud` 的 `/api/miniapp/student/schools` 实测可达，无 token 返回 `401 缺少认证令牌`、带合法 token 即返回数据（路由 `student_schools` + `OrgUnitService.list_schools` + `OrgUnit.to_dict` 均正确）。
- **结论**：「加载失败」是 `getSchools()` 请求**真抛错**（非 2xx 或网络层），而非数据丢失。结合 `request.ts` 拦截器行为，最可能原因是打该接口时请求**未携带有效学生 token**（401 被拒）——即用户停留在绑定页时本地无有效会话（如开发者工具直接打开了绑定页未先登录、或登录态过期）。token 链路本身正确：`useAuthStore.setAuth` 已调用 `setTokens` 持久化，`request.ts` 从 storage 读取并注入 `Authorization`。
- **修复**（`pages/bind/index.tsx` + `index.scss`，提交 `a3eff6f`）：
  - `getSchools` 失败时不再笼统 toast「请检查网络」，而是把真实错误（`ApiError.message` / `code`）记录下来；
  - 空状态按成因三态显示：**401/403（未登录/会话失效）→「登录已失效，请先登录」**（可点跳登录页）；**其它请求错误 →「学校列表加载失败：<真实原因>，点击重试」**；**真无数据 →「暂无学校选项，请联系管理员」**。
- **验证**：`tsc --noEmit` 0；`build:weapp` 19.65s `Compiled successfully`；`dist` `process.env` 残留 0、「登录已失效，请先登录」以 unicode 转义编入 `index.js`。
- **给用户**：上传新 `dist` 后若仍提示「加载失败」，请点开微信开发者工具「Network」面板看 `/api/miniapp/student/schools` 的**状态码**——401/403 即未登录（先走登录）；500 即后端报错（看响应体）；`net::ERR` 即网络/合法域名未配。

### 修复：登录成功未绑定时被后台请求反噬降级游客（2026-09-09 夜间）

- **症状**：登录成功 → 提示「身份未绑定，已退出登录」→ 过一秒才弹出身份绑定页。时序错乱，用户以为登录又被踢下线。
- **根因**：登录成功 `setAuth` 后 `isLoggedIn` 变 true，后台**已 mount 的 Tab 页**（用户来源页，如首页/我的）的 `useEffect([isLoggedIn])` 会**立即**重新 `loadAll()`。其中 `getProfile`（首页还有 `getToday`）是 `@student_bound_required` 接口，**未绑定用户必然 403 `STUDENT_NOT_BOUND`** → `request.ts` 拦截器 `handleStudentNotBound()` 把「刚登录、正要引导绑定」的登录态误判为无效登录态 → `logout()` 降级游客 + 弹「身份未绑定，已退出登录」。随后 `handleLogin` 的 `redirectTo('/pages/bind/index')` 才执行，于是用户看到「刚登录又被退出 → 才进绑定页」。这与登录页正要引导绑定的流程打架，属顺序 bug。
- **修复**：新增模块级「绑定引导期」护栏 `utils/bindGuard.ts`（`beginBindGuide`/`finishBindGuide`/`cancelBindGuide`/`isBindGuideActive`，单一 `var` 标志）：
  - 登录页判定未绑定、`redirectTo` 绑定页**前** `beginBindGuide()`；
  - `request.ts` 的 `handleStudentNotBound()` 在引导期生效时**只清 `profile`、跳过 `logout()` 与「已退出登录」提示**——未绑定期后台 403 属预期（本就无业务访问权），不应反噬正要引导绑定的登录态；
  - 绑定成功 `finishBindGuide()`；离开绑定页（`useUnload`）`cancelBindGuide()`，**防止标志残留**误吞后续真正的 403（如会话中被解绑）降级。
- **产物单实例验证**：`bindGuard` 编译为 webpack 模块 2807（位于共享 common.js，`$m`=isBindGuideActive/`MB`=beginBindGuide/SV=finishBindGuide/vj=cancelBindGuide，单一 `var r`）；login 页 `p=s(2807)` 调 `MB`、request 的 `handleStudentNotBound` 读 `(0,m.$m)()` 均解析到**同一模块实例**，跨 chunk 单实例标志成立（无复制分裂）。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 21.33s `Compiled successfully`；`dist` `process.env` 残留 0。

### 增强/修复：绑定页学校改原生下拉 + 引导期不再抢发私有接口（2026-09-09 夜间）

- **一、学校选择改原生下拉（用户要求）**：`bind/index.tsx` 学校从「两列网格 chips」改为 `<Picker mode="selector">` 原生下拉（微信标准底部滚轮选择器，契合项目"登录/身份页原生化"路线）。复用 `.bind-input-row` 视觉（浅灰填充行 + 右侧箭头），选中值/占位/箭头与学号输入行统一；空态错误提示保留（登录失效 / 加载失败重试 / 真无数据）。
- **二、根治「登录成功未绑定 → 后台 Tab 抢发私有接口 → 全 403」的浪费**：
  - 症状：用户在登录/绑定过渡期看到 `student/profile`、`schedule/today`、`electricity/*`、`feedback`、`unread-count` 等一串 403——**未登录态打私有接口纯浪费 + 刷 403 噪音**（且此前 bindGuard 只抑制了 logout/toast，没抑制请求本身）。
  - 根因：`setAuth` 使 `isLoggedIn=true` 后，后台已 mount 的 Tab 页 `useEffect([isLoggedIn])` 立即 `loadAll()`，但未绑定用户打 `@student_bound_required` 接口必然 403。
  - `login/index.tsx`：`beginBindGuide()` **提前到 `setAuth` 后、`await getBindStatus` 前**，覆盖整个登录→查询绑定窗口（原置于 getBindStatus 之后，恰在 Tab useEffect 抢跑之后才置位，拦不住首次抢跑）；已绑定则 `finishBindGuide()`。
  - `home/index.tsx`：`loadAll` 的 `getToday`/`getProfile` 分支加 `!isBindGuideActive()` 守卫。
  - `profile/index.tsx`：抽 `refreshPrivate()`（`!isLoggedIn || 引导期` → return），`useLoad`/`useDidShow`/`useEffect([isLoggedIn])` 三入口统一走它——电费 current/monthly/refresh、资料、反馈角标、消息未读角标在引导期均不再抢发。
  - `schedule/index.tsx`：`useLoad`/`useEffect([isLoggedIn])` 加引导期守卫；`fetchDayCourses` 引导期直接 return（避免降级走 `getToday` 撞 403）。
- **验证**：`tsc --noEmit` 退出码 0；`build:weapp` 20.15s `Compiled successfully`；`dist` `process.env` 残留 0。

### 修复：时间轴页游客态误发 schedule/today（2026-09-09 深夜）

- **复现**：未登录（游客态）点开「时间轴」页，Network 即发 `GET /schedule/today?date=...` → 401。游客打需登录接口纯浪费 + 刷噪音。
- **根因**：时间轴 `useLoad` 虽有 `if(!isLoggedIn) return`（不 `loadAll`），但页内 `useEffect([selectedDate])`（初次 selectedDate=今天）**无条件**调 `fetchDayCourses` → 游客态 `weekCourses` 为空 → 无本地过滤 → 降级走 `getToday` 网络请求 → 401。此前只给 `fetchDayCourses` 加了 `isBindGuideActive()` 守卫，游客态 `bindGuideActive=false` 故放行，**漏防游客态**。
- **修复**：`fetchDayCourses` 开头 `!isLoggedIn || isBindGuideActive()` 任一为真直接 return（游客打需登录必 401、引导期打需绑定必 403，均不发）；`useCallback` 依赖补 `isLoggedIn`。时间轴游客态本只渲染引导卡，不发任何需登录接口。
- **验证**：`tsc --noEmit` 0；`build:weapp` 19.75s `Compiled successfully`；`dist` `process.env` 残留 0。

### 修复：公告附件下载游客态点附件改登录引导（2026-09-09 深夜）

- **场景**：公告详情对游客公开浏览（合规"先体验后授权"），但附件走 `@student_bound_required` 鉴权下载接口。游客点附件 `downloadFile` 带空 token 直发 → 401。
- **修复**：复用页面既有 `useLoginGuard` 的 `guard`——游客点附件先弹登录引导（与收藏/已阅一致），已登录才进入下载。
- **核查结论**（Explore 全量只读排查）：其余子页面（feedback 列表/详情/电量/coursetable/favorites/messages 等）只能经登录守卫 `navigateTo` 进入、游客 UI 无法到达，非冷启动泄漏；三 Tab 页（home/profile/schedule）与 schedule `fetchDayCourses` 的冷启动泄漏已在前面修复。**不为不可达页面加冗余守卫**（避免过度防御/增耦合）。
- **验证**：`tsc --noEmit` 0；`build:weapp` 20.13s `Compiled successfully`；`dist` `process.env` 残留 0。

## v6.17.1 (2026-09-08)

> 类型：**缺陷修复（patch）**。针对线上暴露的三类问题修复：**宿舍电量三大数据错误**（趋势图按日求和成倍放大、不同页面"本月已用"数值不一致、总容量与剩余电量矛盾）、**小程序站内消息体验**（电量日报等长文改列表摘要 + 详情页）、**小程序网络通道修复**（反馈图片上传、公告附件下载在登录态过期或域名白名单未配时的失败）。

### 修复：宿舍电量数据三大错误（2026-09-08）
- **趋势图数据成倍放大**（实际每天约 7 度，折线图却显示 22 度）：根因是入库去重按「时间戳精确到秒 + 电表原始字符串」匹配，而同一块电表在库中存在多种写法（历史脏数据 `电表: 31栋512照明`、清洗后 `31栋512`），写法一变就匹配不上 → 同一天被反复插入多份；趋势按日求和时被成倍累加、记录条数虚高。修复：新增 `ElectricityRepository.normalize_meter()`（去「电表:」前缀 +「照明」后缀）作为单一真相源，入库去重改为按「用户 + 用电日期 + 归一化电表」维度（保留两块分表、合并写法差异导致的重复）；`ElectricityService.clean_meter` 改为委托 `normalize_meter`。附清理历史脏数据的 `dedupe_electricity.py`（演练 + `--apply`）。
- **「我的」页与电量详情页"本月已用"不一致**（如 162.93 与 74.04）：此前两页各自拉取用电记录在本地累加（我的页拉 1000 条、详情页只取首屏 20 条），口径不同。改为后端统一按自然月聚合：新增 `GET /api/miniapp/electricity/monthly`（`ElectricityService.get_monthly_usage`），两个页面共用一个数据源。
- **总容量显示 100 度但剩余 125 度、百分比恒 100%**：`electricity_total_capacity` 表对应用户无记录时，容量管理器回落默认值 100。修复：`update_remaining` 增加首次容量基准——无任何容量记录时以 `max(当前剩余, 100)` 记录初始基准（INITIAL）。

### 新增 / 优化：消息中心电量日报等改「列表摘要 + 详情页」（2026-09-08）
- 小程序「我的消息」列表不再整篇铺开正文，改为最多 2 行摘要 + 右侧箭头，点击进入新的消息详情页看完整内容，进入即自动标记已读，返回后列表已读态自动刷新。
- 后端新增 `GET /api/miniapp/notifications/messages/<id>`（`UserNotificationService.get_notification`，按 id + user_id 双过滤防越权）。

### 修复：小程序上传 / 下载在登录态过期或域名未配时的失败（2026-09-08）
- **反馈图片上传**：`Taro.uploadFile` 不走统一的 request 封装，登录态过期即 401 失败且无自动续期。修复：`request.ts` 新增 `ensureFreshAccessToken()`，`feedbackApi.uploadImage` 上传前预刷新 token、遇 401 强制刷新重试一次；错误归一化——域名未配白名单时明确提示"上传域名未加入小程序白名单"。
- **公告附件下载用错字段**：详情页原来拿 `file_url`（磁盘存储相对路径）直接 `Taro.downloadFile`，必然失败且绕过鉴权。改为走后端带鉴权的 `download_url`（`/api/miniapp/announcements/attachment/<id>`）并拼完整 URL、带登录态下载，区分 401/404/域名白名单提示。附件类型补 `download_url` 字段。
- 前端补丁类修复需重新构建后生效。

### 修复：小程序天气图标跨设备不一致（2026-09-08）
- 天气状况图标由 emoji 改为统一 PNG 素材（晴/多云/阴/雨/大雨/雪/雷/雾 8 张），杜绝 emoji 在不同设备渲染不一致。`WeatherCard`、7 天预报、24h 折线图 Canvas 三处改 `<Image>` / `ctx.drawImage` 引用本地素材。

### 修复：个人资料编辑信息卡两行基线对齐 + 编辑资料按钮文字横排（2026-09-08 晚）
- **症状 1 对齐**：编辑信息卡「头像」行与「昵称」行右侧内容（圆 + › / Input + ›）**基线错位**——头像行偏高、昵称行偏低。**症状 2 按钮文字竖排**：底部「编辑资料 ›」入口按钮中，"编辑资料"四字 + › 箭头被垂直堆叠成一列。
- **对齐根因**：`.detail-row-right` 内子项最高 72rpx（圆），昵称行 Input 默认 ~40rpx 不强制，两行行高不同（128rpx vs 96rpx），`.detail-row { align-items: center }` 让两行基线错位。
- **按钮竖排根因**：Taro 3.x `<Text>` 默认 `display: block`，在 flex row 容器内仍按 block 排（不横排）——表现就是按钮内 4 字 + 箭头竖成一列。
- **修复**：
  - `.detail-row-right` 加 `height: 72rpx; justify-content: flex-end`，强制头像行 / 昵称行右侧容器等高 → 两行基线对齐。
  - `.detail-edit-entry` 加 `flex-direction: row; white-space: nowrap`，子 Text（`.detail-edit-entry-text` / `.detail-edit-entry-arrow`）显式 `display: inline-block`，保证文字横排。
- 改动文件：`miniapp-frontend/src/pages/profile-detail/{index.tsx,index.scss}`。
- 验证：`tsc --noEmit` 0；`build:weapp` 成功；产物 `.detail-row-right{height:72rpx}` 与 `.detail-edit-entry{flex-direction:row}` 生效。

### 修复：admin-frontend 会话失效改上视口气泡 + 绑定码"复制并关闭"真正关闭（2026-09-08 晚）
- **症状 1 会话失效提示塞卡片**：原本走 `Modal.warning` 居中弹窗，且 `Login.tsx` 还在登录卡片内渲染 `Alert` 显示失效原因——双层冗余、阻塞视线，且用户不希望塞到登录卡片里。
- **修复 1**：删除 `Login.tsx` 中 `sessionExpiredMsg` state + Alert 渲染，改为读 `sessionStorage("session_expired_reason")` 后直接调 `message.warning(reason, 3)`（顶部气泡，3s 自动消失）；`sessionExpiry.ts:76` 居中 `Modal.warning` 改为静态 `message.warning({ content, duration: 1.5 })`（顶部气泡，跳转 1.8s 前可见）。静态 `message` 不用 `App.useApp()`——因调用方在 axios 拦截器 / 心跳钩子中常脱离 React 上下文。
- **症状 2 "复制并关闭"不关弹窗**：`UserManagementRoster.tsx` 的 `copyCode` 仅复制 + `message.success`，未调 `setCodeModal` 置空 `rosterId`，弹窗可见性由 `codeModal.rosterId !== null` 控制，复制成功后没置空所以不关。
- **修复 2**：`copyCode` 复制成功后追加 `setCodeModal({ rosterId: null, code: null, loading: false })`；复制失败保留弹窗给用户重试。
- 改动文件：`admin-frontend/src/utils/sessionExpiry.ts`、`admin-frontend/src/pages/Login.tsx`、`admin-frontend/src/pages/UserManagementRoster.tsx`。
- 验证：`tsc --noEmit` 0；`npm run build` 成功（12.10s）；产物含 `message.warning` 调用。
- 天气状况图标由 emoji 改为统一 PNG 素材（晴/多云/阴/雨/大雨/雪/雷/雾 8 张），杜绝 emoji 在不同设备渲染不一致。`WeatherCard`、7 天预报、24h 折线图 Canvas 三处改 `<Image>` / `ctx.drawImage` 引用本地素材。

## v6.17.0 (2026-09-07)

> 类型：**新功能 + 功能重构（minor）**。在 v6.16.0（微信小程序学生端第一/二阶段）基础上继续深化：**学生身份体系组织树化 + 一次性绑定码门禁**（学校→学院→专业→班级树维护，杜绝先到先得冒绑）、**电量模块用户化**（独立电表、Cookie 学生自配、推送改小程序站内通知）、**消息中心三合一**（校园通知+自定义推送单页 Tab + WangEditor v5 独立编辑页）、**学生名单/绑定合一管理**（学院+专业维度）。**本版补齐运营侧能力**：管理端富文本图片上传修复（token 刷新 + 文件级判定 + 编辑器内部崩溃兜底）、公告正文图 / 反馈截图**孤儿图自动回收**（更新/删除后即时 + 每日 03:30 定时兜底，带 24h 保护期）、**企业微信天气预警推送开关**（天气管理页顶部 + 系统设置页两处独立开关，仅关推送渠道不影响小程序天气数据）、后端**课程缓存主动失效**、小程序课表日期淡化 + 组件按需注入(lazyCodeLoading)。

### 新增 / 优化：消息中心图片上传修复、公告图 / 反馈图自动回收、天气预警推送开关、课程缓存主动失效（2026-09-07）
- **管理端富文本图片上传修复**（`admin-frontend/src/pages/MessageEditor.tsx`）：改为 `customUpload` 走统一 `request`（自动带 `Authorization` 并刷新过期 token，根治"只有图片传不上、其余正常"的 401）；修正 `errno` 判定（响应拦截器已解包一层，不再二次取 `res.data`，避免误判失败）；`onCreated` 给 WangEditor 5.1.x 的 `reportAllChanges` 包 try-catch，吞掉孤儿节点导致的 `reading 'startTime'` 内部崩溃。
- **公告标题单行省略号**（`Messages.tsx`）：标题列 inline-block + maxWidth + ellipsis + title 悬停看全文。
- **登录页提示条移除**（`Login.tsx`）：删掉直达登录页时"没有上一页可返回"的蓝色 info 提示 + `canGoBack` 判断。
- **公告正文图自动回收**（`app/services/announcement_service.py`）：编辑保存/删除公告**提交后**自动删除不再被任何正文引用的 `output/announcement-images/` 图片；引用判定查未软删公告 + 全部自定义推送正文（`announcement-images/<name>` 带 '/' 边界避免前缀误匹配）；`tools/clean_orphan_announcement_images.py` 两步：先清正文坏图 `<img>` 引用再回收磁盘文件（默认 dry-run）。
- **反馈截图 GC + 每日定时回收**（新增 `app/services/feedback_image_gc.py` + `scheduler.py` 03:30 `image_gc_job`）：反馈无删除接口，孤儿来自"上传截图未提交反馈"，带 24h 保护期回收 `output/feedback-images/` 无人引用文件；统一入口 `run_image_gc()` 一次回收公告图+反馈图。
- **企业微信天气预警推送开关**（`admin-frontend/src/pages/Weather.tsx` + `Settings.tsx`）：天气管理页顶部（Card extra）与系统设置页天气面板各加醒目独立开关，写入后端 `weather/alert_enabled`（复用既有模块配置，仅关推送渠道，天气数据照常采集、小程序展示不受影响；后端预警推送任务遇 `alert_enabled=false` 跳过企业微信推送）。
- **后端课程缓存主动失效**（`app/api/course_routes.py`）：6 处写库 commit 后调 `schedule_service.load_schedules()` 主动刷新，避免管理端改课后小程序最长 60s 才看到新数据。
- **小程序体验**：课表列头日期颜色淡化（`coursetable/index.scss`）；`app.config.ts` 启用 `lazyCodeLoading: 'requiredComponents'`（组件按需注入）。



### 修复：课程详情页长课名溢出/不可换行（2026-09-04）
- **现象（用户反馈「还是渲染错误」）**：进入课详情页后，蓝色头部标题「综合实训（毕业设计）：智慧人工服务平台开发（5-8节）」超长且不可断行，文字挤压/溢出头部卡片（时间、节次、地点 meta 行被挤乱）。
- **定位**：截图里节次文字已是正确的「5-8 节」（数据链路此前已修复），剩余问题是**纯排版**：`coursedetail/index.scss` 的 `.cd-header-title`（38rpx 粗体）默认不断行，中文无空格长课名单行溢出；meta 行未允许换行被挤压。
- **改动**（`miniapp-frontend/src/pages/coursedetail/index.scss`）：
  - `.cd-header-title`、`.cd-header-sub` 增加 `word-break: break-all; overflow-wrap: anywhere;`，超长课名在任意字符处断行而非溢出；
  - `.cd-header-meta` 增加 `flex-wrap: wrap;`，窄屏 meta 项自动换行不被挤在一行。
- **验证**：`tsc --noEmit` 0 错误；`npm run build:weapp:clean` 成功；`dist/pages/coursedetail/index.wxss` 已含 `break-all` 规则。
- **用户侧**：微信开发者工具重新编译（或直接重载 dist）后重进课详情页确认。

### 优化：时间轴课表同名合并条件改用 full_date（2026-09-04）
- **背景**：之前综合实训"5-8节却显示1-8节"的原因查下来 DB/ORM/`schedule_service._transform` 都干净（综合实训 20261 学期 4 行 wd=2/3/4/5 periods=[5,6,7,8]/[1,2,3,4]，无重复行），重启后端缓存刷新后理应正确。但前端 `pages/schedule/index.tsx` 的同名合并条件只看 `day_of_week + course_name`——抽象星期几，不够精确，**极端边界下可能把多条同名课的 periods 拼成过大区间**（如同时持有 1-4 节与 5-8 节两段数据时输出 1-8 节）。
- **改动**：合并条件由 `course_name + day_of_week` 改为 `course_name + extra_info.full_date`（具体日期），避免任何抽象星期匹配可能带来的边界合并。
- **验证**：`tsc --noEmit` 0 错误；`npm run build:weapp:clean` 成功。

### 修复：课表缓存条数不变时永远不刷新（2026-09-04）
- **现象**：DB 修正了综合实训等课程的 `periods`（从 [5] → [5,6,7,8]）后，`/api/miniapp/schedule/*` 接口仍返回旧 periods，小程序课表仍显示错误的节次范围；定时器每 60 秒自动刷新也不生效，重启才恢复。
- **根因**：`app/services/schedule_service.py` 的 `load_schedules` 缓存更新条件只比 `len(transformed) != len(self._schedules)`。只**更新字段（UPDATE 同一行的 periods/period_idx）不增减条数**，缓存永远不覆盖，定时器查了 DB 也赋不进去，进程内 API 持续返回旧数据。
- **修复**：去掉"条数门控"，定时器每 60 秒读 DB 后无条件覆盖 `self._schedules`（反正每次都查 DB，不增加成本）。仍保留锁与 `_data_ready` 标记。
- **铁律**：内存缓存的"是否变更"判断**不能只看条数**，字段级更新同样需要触发刷新；或干脆每次都覆盖，由调用方按需刷新。
- **验证**：`py_compile` 通过；全量 `pytest` **188 passed**。
- **用户侧解法**：重启后端进程（缓存随进程消失，init_app 会重新 load 一次），重启后下次再出现"修了 DB 但接口不更新"也能自动跟上。

### 修复：小程序「个人资料」页无样式（2026-09-04）
- **现象（用户反馈）**：「我的」页顶部用户条点进去的"个人资料"页面只有纯文本堆叠（学号/班级/学校/学院/专业等都挤在 default Text 字体），不像其他页面有卡片、标题、按钮样式；「编辑资料」跳的「账号设置」页样式正常。
- **根因**：`miniapp-frontend/src/pages/profile-detail/index.tsx` 用了大量 `detail-*` 类名，但**漏了 `import './index.scss';`**——scss 文件齐全且定义了所有类，却从未进 bundle，所以页面上全是裸 Text/View 默认渲染。同目录 `profile-edit/index.tsx:8` 正确 import，作为对照。
- **扫描**：用 shell 遍历所有有 scss 配对的页面，只此一个漏 import。
- **修复**：在 profile-detail `index.tsx` 末尾加 `import './index.scss';`，重新 `build:weapp:clean`（dist 已生成，`profile-detail/index.wxss` 1733 字节）。tsc 0 错误。
- **铁律**：新增 Taro 页面模板时必须 `import './index.scss';`，建议后续加 ESLint 规则自动检查（每个 pages/*/index.tsx 有同名 scss 时必须 import）。

### 修复：小程序旧 token 用户已删除时 bind 报 500（2026-09-04）
- **现象（用户反馈）**：小程序身份绑定页提交后 `POST /api/miniapp/student/bind` 返回 **500**；此前所有业务接口 `403`（未绑定属正常拦截，会跳绑定页）。日志：`IntegrityError (1452) Cannot add or update a child row ... student_profiles FOREIGN KEY (user_id) REFERENCES users (id)`。
- **根因**：组织树化重构「存量清空重录」时删除了旧的微信登录账号（users 表只剩管理员，最大 id=74），但**小程序本地还缓存着旧 JWT（user_id=75）**。JWT 签名有效（SECRET_KEY 未变），而 `student_required` 与 `miniapp_refresh` 只验签名/角色、**不查库校验用户仍存在** → 请求一路放行：业务接口查不到 profile → 403 引导绑定（正常）；绑定码校验通过后 INSERT `student_profiles` 时 FK `user_id→users.id` 失败 → 500。
- **修复**（两处校验，前端零改动）：
  - `app/utils/student_auth.py` `student_required`：role 校验通过后查 `users` 表（`id` + `is_active=True`），用户不存在/被禁用返回 **401 + `code=USER_GONE`**。覆盖 bind 及全部学生端接口。
  - `app/api/miniapp_auth_routes.py` `miniapp_refresh`：刷新成功后同样校验（否则 401→refresh→重放会卡死；`_retried` 只防无限重试不解决根源）。返回同码 401。
  - 闭环：旧 token 任意接口 → 401 USER_GONE → 小程序 refresh 失败 → 清 token → 静默重新登录（wx.login）→ 新建账号 → 重新绑定成功，全程用户无感知（仅需重填一次绑定表单）。
- **测试适配**：`test_miniapp_phase2.py` 的 `_FakeQuery` 对 `User` 模型返回「存在」桩；`test_miniapp_notification.py` fixture 预插 `users` 记录；新增回归用例 `test_deleted_user_returns_401_user_gone`（查无用户 → 401 USER_GONE）。全量 `pytest` **188 passed**。
- **注意**：校验按模型类查询（`db.query(User)` 而非 `User.id`），便于测试桩按模型路由；查询代价为主键 SELECT，规模可忽略。
- **用户侧立即解法**：小程序删除后重新进入（或清除缓存重新登录）即可，无需改后端。

### 重构：学生身份组织树化 + 一次性绑定码门禁（2026-09-04）
- **背景（用户提出）**：学生组织本为 学校→学院→专业→班级(含年级)→学生 五层，一个班约 40 人。原实现让管理员在名单每行重复填写 学校/学院/专业/班级——无层级复用、易错，学校选项还是硬编码含"模糊干扰项"。用户建议改为「先建学校 → 学院 → 专业 → 班级，最后添加学生，学生继承层级」，学校等末端选项在小程序端自动生成、便于维护。同时追问安全：后端添加学生后是否应生成密钥发放，学生凭密钥进入——即把「知识校验（答对学号+班级）」升级为「持有凭证校验」。
- **安全动因**：学号与班级在校园属半公开信息，原「学校+学号+班级」门禁存在**先到先得冒绑**漏洞——任何人知道他人学号班级即可抢先绑定，真学生反而永远绑不上（既有 ALREADY_BOUND 只防重复绑定覆盖，防不了抢先）。一次性码由管理员私下发放、绑定即核销，从根上消除。
- **数据模型**：
  - 新增 `org_units` 组织树表（自引用 `parent_id`+`node_type` 四层 school/college/major/class；同父同级名称唯一由 service 校验；删父受子节点与名单引用保护；指纹迁移自动建表，全库 31 张表）。模型 `app/model/org_unit.py` 已注册进 `__init__.py`。
  - `student_rosters` 加 `class_id`（FK org_units，node_type=class）与 `bind_code_hash`（一次性码 sha256，绑定成功即清空）；原 school/college/major/class_name 文本列**保留为冗余列**（NOT NULL 兼容 + 展示免 join），由服务端从树路径带出写入；`to_dict()` 输出 `class_id`/`has_bind_code`。指纹迁移实测 4 处变更（2 列 + 索引 + 新表）。
- **后端**：
  - `app/services/org_unit_service.py`（新建）：`create`（层级校验+同父查重）/`list_schools`（学校选项数据源）/`tree`（嵌套树，管理端用）/`rename`（同事务级联刷新子树名单冗余路径名）/`delete`（有子节点或被班级名单引用拒绝）/`find_class_by_path`（批量导入按名称路径定位）/`get_path`。
  - `student_roster_service.py`：`create` 改按 `class_id` 挂班级（冗余路径由树继承带出，不再收文本组织名）；`create_batch` 按 学校/学院/专业/班级 名称路径定位班级节点；新增 `generate_bind_code`/`generate_bind_codes`（8 位随机码，字符集去易混淆 0O1I，库内仅存 sha256，明文只返回一次）/`verify` 改为「学校+学号+绑定码」三要素；`list` 支持 `class_id` 过滤；`update` 支持换班（class_id）。
  - `admin_roster_routes.py`：新增 `/org/tree`、`POST/DELETE /org`、`PUT /org/<id>`；`/students` 列表/新建/编辑适配 class_id；批量导入表头扩展 学校,学院,专业,班级,学号,姓名,备注（名称须与已建组织一致）；`POST /students/<id>/bind-code`（单个生成，明文仅本次返回）与 `POST /students/bind-codes`（勾选批量生成，返回列表供复制/导出）；`/schools` 改为从组织树动态读取（删除硬编码 SCHOOL_OPTIONS 与模糊干扰项）；模板下载加组织列。
  - `miniapp_routes.py`：`bind_student` 改收 `bind_code`（不再收班级）；命中后 profile 的 school/student_number/class_name/college/major 全量以名单冗余列（组织树继承结果）为准写入并核销码；`/student/schools` 动态读取组织树。
- **管理端**（`UserManagementRoster.tsx` 重构 + `api/admin.ts` 扩展）：左组织树右名单双栏——组织树可新建学校/学院/专业/班级、重命名（提示关联名单组织名同步刷新）、删除（受保护提示）；名单按左侧选中班级过滤；「添加学生」班级级联选择（学校→学院→专业→班级）后组织名自动继承，仅填学号/姓名/备注；行操作新增「生成码/重新发码」（Modal 大字展示仅一次 + 复制）；勾选可「批量生成码」（弹窗列出学号-码表）；绑定状态列三态：已认领（蓝）/已发码未绑定（橙）/未绑定（灰）；已绑定学生不可再发码（复选框与按钮均禁用）。`RosterStudent` 类型加 `class_id`/`has_bind_code`。
- **小程序端**：`pages/bind/index` 班级输入改为**绑定码输入**（8 位等宽大字距样式，自动转大写）；绑定页文案同步（绑定码由管理员发放、一次性）；`user.ts` bind 入参改 `bind_code`。班级/学院/专业绑定后由组织树继承写入资料，学生无需填写。
- **验证**：后端 pytest **180 passed**（新增组织树链/重名拒绝/非法层级/重命名级联刷新/删除保护/名单冗余继承/错误班级拒绝/批量定位/码生成校验核销/错码与缺码 403/绑定继承写入等 12+ 用例；`test_bind_and_delete_account.py` 加 org_units 表、seed 改带码、SQLite session `expire_on_commit=False` 适配 service 各自 close 语义）；指纹迁移 4 处变更 + SHOW COLUMNS 复核；管理端 `tsc --noEmit` 0 错误 + `vite build` 成功（17.15s）；小程序 `tsc --noEmit` 0 错误 + `build:weapp:clean` 成功。
- **存量说明**：本地原 1 条名单 + 0 绑定（测试数据），经确认清空重录——组织树与名单上线后按新结构重建，无需迁移脚本。

### 修复：课程表/周历"今天"日期比实际多一天（2026-09-04）
- **现象（用户反馈）**：课程模块显示的"今天"比真实日期多一天（如真实 9/4，表头标 9/5 甚至 9/7），质疑"日期是不是私有的而非标准时间"。
- **根因**：`teaching_week_service.build_available_weeks` 与 `get_current_teaching_week` 以 `semester_start_date` 直接当作「第 1 周周一」推算周历。若开学日不是周一（2026 秋学期 9/1 是周二），整张周历会比真实日历整体偏移 `(开学日星期几-1)` 天；而 `schedule_service._calculate_date`（决定推送/课程真实日期）按**真实周一**锚定，两套口径不一致，表头/周历"今天"与真实日期对不齐。
- **修复**：两处统一改为先锚定到「开学日所在周的真实周一」(`start - timedelta(days=start.isoweekday()-1)`) 再推算周次与周区间。网页端 `src/utils/semester.ts` 的 `getWeekDate` 兜底路径同步周一对齐，保持与后端一致。
- **影响面**：仅改周历/表头日期锚点，学期周数、教学周上限、假期判定逻辑不变；管理端课程表、小程序周历均消费 `available_weeks.start_date`，后端重启即生效（无需重装小程序）。验证：`build_available_weeks(20261)` 第 1 周区间变为 `2026-08-31~2026-09-06`（周一锚定），真实 2026-09-04 正确落入第 1 周；前端 `tsc --noEmit` 0 错误、`vite build` 成功。

### 修复：综合实训等跨多节课程被压成单节（2026-09-04）
- **现象（用户反馈）**：新学期课表爬取后，「综合实训（毕业设计）：智慧人工服务平台开发」本应跨 1-4 节 / 5-8 节，却只显示 1 格（周二/周四落库 `periods=[5]`、周三/周五落库 `periods=[1]`），前端 `rowSpan` 只算 1 行。
- **根因**：爬虫产物 `processed_course_table.json` 的 `periods` 本就正确（`[5,6,7,8]`/`[1,2,3,4]`），但**入库环节忽略 JSON 里已算好的 `periods`，改用 `period_name` 文本重推**。旧解析器只支持「第X节」单节与「第X、Y、Z节」枚举两种格式，**不认识「第X至Y节」范围格式**（如「第五至八节」），被单节分支只截到「第五」→ 落库 `[5]`。枚举格式（`第一、二节`）能正常展开，所以只有 3 节及以上的「至」格式课中招。
- **修复**（两处导入链路口径统一）：
  - `app/cqie-course-timetable/pipeline.py` `parse_period_name`：在枚举分支**之前**新增「第X至Y节」范围匹配（`re.match(r"第([一二三四五六七八九十]+)至([一二三四五六七八九十]+)节")`，返回 `list(range(a,b+1))`）。全量爬虫落库走此路径。
  - `app/api/course_routes.py` `import_courses`（管理端「导入」按钮，自带内联解析、不复用 pipeline）：补齐同样的「至」范围分支，并补 `十一/十二` 中文映射（原内联 `cn_num_map` 缺失）。两条路径行为现已一致。
- **存量数据修正**：直接 UPDATE 已中招记录（按 `course_name+week_day+start_time+semester_id` 定位 20261 学期 4 行「综合实训」，用修正解析器重算 `periods` 与 `period_idx`，提交生效）；随后对 20261 学期全部 7 行与正确 JSON 做全量比对，确认无其余被压窄记录。
- **验证**：`parse_period_name` 单测 `第五至八节→[5,6,7,8]`、`第一至四节→[1,2,3,4]`、`第十一至十二节→[11,12]`、`第十至十二节→[10,11,12]`、`第一、二节→[1,2]`、`第五节→[5]` 全过；`course_routes` 内联解析同 7 例单测通过；`tests/test_parser_utils.py` 新增 `TestParsePeriodNameRange` 回归用例；`pytest tests/test_parser_utils.py` **21 passed**；`py_compile course_routes.py` 通过。

### 优化：学生身份管理首屏与空状态（2026-09-04）
- **背景（用户反馈）**：组织树清空后首屏出现"暂无组织"与"暂无名单记录"两类空态叠加、文案重复显得 ui 错乱；左侧"选中班级可只看该班"提示与右侧空态布局不合理，缺少明确的"请先新建学校"引导。
- **改动**（`UserManagementRoster.tsx`）：① 左侧组织树空态改为简洁引导 + 内嵌「新建学校」按钮（图片降级为 PRESENTED_IMAGE_SIMPLE），比纯文字更明确；② 右侧提示条按"是否已有组织"分流——无组织时橙色引导"请先新建学校→学院→专业→班级"，有组织时灰色说明"选中班级只看该班、组织名自动继承"；③ 右侧空态三态区分：尚无组织 → "尚未创建组织，暂无法添加学生"；选中某班级无数据 → "该班级暂无学生名单"；其余 → "暂无学生名单记录"，消除"重复暂无"的观感；④ 左右两栏加**竖向分隔线**（`Divider type="vertical"` + `alignSelf: stretch` 撑满栏高，色值 `rgba(0,0,0,0.06)`），解决两栏仅靠 16px 间距、边界不清的问题；移动端为上下堆叠布局，该竖线条件隐藏（靠 gap 分隔），避免多出一条突兀竖线。

### 优化：学生身份管理左栏等高滚动 + 组织树默认展开（2026-09-04）
- **背景（用户提出）**：左组织树与右名单两栏应等高——左栏默认跟随右栏高度，条目超出时左栏内部滚动，且右栏高度变化（翻页/筛选）时左栏高度随之改变；另外只有一个学校时，组织树默认全展开到「专业」层，方便直接做增删，不用反复手动展开节点。
- **改动**（`UserManagementRoster.tsx`）：
  - **等高与滚动**：外层 flex 容器改 `alignItems: "stretch"`；左栏 Card 改 `display:flex; flexDirection:column`，body 改 `flex:1; minHeight:0; overflow:auto`（去掉写死的 `maxHeight:560`）；用 `ResizeObserver` 实测右栏 `offsetHeight` 作为左栏 `maxHeight`，右栏高度变化时自动跟随。
  - **默认展开**：组织树改受控 `expandedKeys` + `onExpand`（原 `defaultExpandAll={false}` 无法在树数据异步到达后再生效）；首次加载且**仅一个学校**时自动展开「学校 + 各学院」，即露出到专业层（班级层不展开，避免一次性铺开过长）。此后完全交由用户手动控制，不会被 effect 覆盖（`autoExpandedRef` 只触发一次）。
  - 新建节点后自动把父节点并入 `expandedKeys`，保证新节点立即可见。
  - **移动端**：容器改 `flexDirection: column` 纵向堆叠（原 `nowrap` + 左栏 `width:100%` 会把右栏挤成 0 宽），且左栏不套用右栏高度上限。
- **验证**：`tsc --noEmit` 0 错误；`vite build` 成功（43.92s）。

### 新增：学生身份绑定 + 预录学生名单（2026-09-01）
- **背景**：小程序登录后需选择学校（下拉为模糊选项但必须含重庆科创职业学院）、输入学号与班级，用于筛出无关人员；管理员提前录入学生名单，只有指定学号的学生才有权查看对应信息。绑定为强制流程——未绑定身份时小程序全部功能不可用（仅显示绑定引导页）。
- **数据模型**：新增 `student_rosters` 预录白名单表（`school`+`student_number` 联合唯一，含 `class_name`/`real_name`/`remark`/`is_active`，全库共 30 张表）；`student_profiles` 新增 `school` 列；新表/新列由 `init_db.py migrate` 指纹迁移自动补齐。
- **后端**：
  - `app/services/student_roster_service.py`（新建）：`create`（必填+查重）、`create_batch`（事务内文件内+库内查重，返回 `{created, failures:[{row, reason}]}`）、`verify`（学校+学号+班级三项全匹配且 `is_active`）、`list`（分页+学校/关键字筛选）、`update`（学校/学号只读）、`delete`。
  - `app/api/admin_roster_routes.py`（新建，`/api/admin/roster`，均 `@admin_required`）：学生列表/新建/批量导入（CSV 支持 UTF-8-SIG/GBK 编码，xlsx 用 openpyxl 解析，表头中英文兼容）/编辑/启停/删除/学校选项/CSV 模板下载。
  - `app/utils/student_auth.py` 新增 `student_bound_required` 装饰器：在 `student_required` 基础上校验 `StudentProfile.student_number` 非空，未绑定返回 403 `code=STUDENT_NOT_BOUND`；miniapp/feedback 全部业务路由由 `@student_required` 切换为 `@student_bound_required`（`/user/me` 保留）。
  - `miniapp_routes.py`：新增 `GET /student/bind-status`（绑定快照）、`GET /student/schools`（复用管理端学校选项）、`POST /student/bind`（三项校验通过才写回 profile）；`PUT /student/profile` 白名单移除 `school`/`student_number`/`class_name`，防止绕过名单直接填学号。
- **管理端**：用户管理页改为双 Tab（「用户管理」+「学生名单」）；新增 `UserManagementRoster.tsx`：查询筛选（学校 Select+关键字）/新建/编辑（学校学号只读）/启停 Switch/删除/批量导入（结果弹窗展示失败明细）/模板下载。
- **小程序端**：新增 `pages/bind/index` 绑定页（学校 chips 选中态高亮 + 学号/班级输入；已绑定直接 reLaunch 首页；成功回写 profile）；`request.ts` 对 403 `STUDENT_NOT_BOUND` 防抖（2s）reLaunch 绑定页并抛 ApiError；资料编辑页学号/班级改为只读身份信息块。
- **验证**：后端 test_client 冒烟 10 项全过（未绑定 403 拦截、名单新建、学校列表、班级不匹配拒绝、三项匹配绑定成功、绑定后放行、绑定快照回读一致、防绕过 400、未登录 401）；`py_compile` 通过；管理端 `vite build` 成功；小程序 `tsc --noEmit` 0 错误 + `build:weapp` 成功。
- **测试适配**（权限收紧同步更新既有用例）：`test_miniapp_auth.py` 登录用例补 `_bind_student` 预置绑定身份，`student_number` 改断言为不可经 PUT 篡改（400）；`test_miniapp_phase2.py` `_FakeSession` 支持按模型返回已绑定身份桩 + mock 目标改为路由实际使用的 `get_electricity_service` 工厂（修复电量用户化重构遗留的"mock 单例不生效"）；`test_miniapp_notification.py` 建 `student_profiles` 表并预置绑定身份。全量 `pytest` **158 passed**（此前电量 2 用例长期失败，本次一并修复）。

### 修复：管理端「新建学生」学校下拉为空（2026-09-01）
- **现象**：管理端「学生名单」Tab 新建学生 Modal 中学校下拉显示 `No data`，无任何学校可选（包括必须保留的重庆科创职业学院）。截图复现于部署新版管理端 dist 后。
- **根因**：`api_success(schools=SCHOOL_OPTIONS)` 走 `**extra` 路径，`schools` 字段位于响应**顶层**（`{"status":"success","schools":[...]}`，无 `data` 字段）。管理端 `rosterApi.getSchools()` 泛型声明为 `ApiResponse<string[]>` 并从 `res.data` 取 → 拿到 `undefined → []` → 下拉空。小程序端 `getSchools` 从顶层 `schools` 取，所以未受影响。
- **修复**（`admin-frontend/src/api/admin.ts` + `UserManagementRoster.tsx`，单点最小改动）：
  - `admin.ts` 泛型改为 `ApiResponse<unknown> & { schools?: string[] }`，与实际响应结构对齐。
  - `loadSchools` 改为 `setSchools(res.schools || [])`，与小程序端 `SchoolsResult` 类型（`extends ApiSuccess { schools: string[] }`）保持一致。
- **回归测试**（新建 `tests/test_admin_roster_routes.py`）：断言 `/api/admin/roster/schools` 响应顶层含 `schools` 数组且包含「重庆科创职业学院」；学生 token 访问被 admin_required 拦截 403。全量 `pytest` **160 passed**。
- **验证**：`npm run build` 成功（16.86s）。

### 安全加固：bind 防重复绑定 + 账号注销 + 个人详情页（2026-09-01）
- **背景**：用户自查发现测试账号学校字段未填也能正常使用，「小程序只管绑定那一次，如果利用非法手段就没事了吗？」——审计确认 `POST /student/bind` 可被**重复调用**：已绑定用户再次调 bind 会用新提交的学号/班级**覆盖**原身份，绕过「只绑一次」的预期。
- **修复 1：bind 防重复绑定**（`app/api/miniapp_routes.py`）：`bind_student()` 开头（名单校验之前）先查当前用户 `StudentProfile.student_number`，已绑定直接 403 `code=ALREADY_BOUND`（提示「已绑定身份，不可重复绑定。如需换绑请联系管理员」），杜绝重复 bind 覆盖为他人学号；换绑仅能由管理员后台处理。
- **修复 2：账号注销**（`app/api/miniapp_auth_routes.py` 新增 `DELETE /api/miniapp/auth/user/me`，`@student_required`）：软删 `users.is_active=False`（保留数据）+ 撤销 access token（reason=`account_delete`）+ 可选撤销 refresh token（query 传 `refresh_token`）双保险；`wechat_auth_service` 登录时已检测 `is_active`，注销后同微信号无法重新登录。
- **修复 3：个人详情页**（`miniapp-frontend/src/pages/profile-detail/` 三件套新建）：「我的」页头部（头像+昵称区域）点击跳转详情页；详情页展示身份信息（学号/班级/学校只读）+ 基础资料（校园卡号/学院/专业/年级/手机 + 编辑入口）+ 底部红色「注销账号」按钮（二次确认 → `deleteAccount(refreshToken)` → 清登录态 reLaunch 登录页）。
- **前端支撑**：`request.ts` 新增 `del` 便捷方法（DELETE query 参数手动编码拼 URL）；`src/api/user.ts` 新增 `deleteAccount(refreshToken?)`；`app.config.ts` 注册 `pages/profile-detail/index`。
- **回归测试**（新建 `tests/test_bind_and_delete_account.py` 4 用例）：首次绑定成功；已绑定重复 bind → 403 `ALREADY_BOUND` 且 `student_number` 未被覆盖（安全核心断言）；注销后 `user.is_active is False` + access token 进入 TokenBlacklist；注销后携原 token 访问保护接口 → 401。全量 `pytest` **164 passed**；`build:weapp:clean` 成功。

### 修复 + 重构：用户与权限模块扁平化 + 名单/绑定合一（2026-09-04）
- **顺带修复**：管理员端「学生名单」列表恒为空（加了学生不显示）。根因 `list_students` 用 `api_success(total=..., items=...)`，`items` 走 **extra 路径落在响应顶层、无 data 字段；前端 `UserManagementRoster.load()` 读 `res.data` → 恒 undefined → 列表空。改回 `api_success(data=data["items"], total=..., page=..., page_size=...)` 对齐前端契约（与「学校下拉为空」同源的 api_success 顶层语义错配）。回归测试 `test_list_returns_data_array_not_items` 锁定结构。
- **重构动因**：用户与权限模块是逐次打补丁长出来的——`/access`(AccessControl) 三层嵌套（用户→用户管理→学生名单），学生名单（预录白名单）被埋在最深处；且「用户管理」把网页 admin 用户与微信 student 用户混排，密码/MFA/主管理员操作只对网页用户有意义，前端靠 disabled 硬控。三个本应关联的「学生」概念（预录名单 / 已绑定身份 / 登录账号）彼此割裂，管理端看不到「这条名单被谁认领」。
- **目标架构（扁平四分区）**：`/access` 改为 `账号 / 学生身份 / 会话 / 访问控制` 四个并列 Tab：
  - 账号 = `UserManagement`（去嵌套，仅保留账号表；来源列已存在，密码/MFA/主管理员操作维持仅非微信用户可用）。
  - 学生身份 = `UserManagementRoster`（预录名单 + 绑定状态合一）。
  - 会话 = `SessionManager`、访问控制 = `Blacklist`（不变）。
- **绑定状态聚合（后端，零模型改动）**：`StudentRosterService.list` 按 `(school, student_number)` 关联 `student_profiles` + `users`，给每条名单附加 `bound_user_id`/`bound_username`/`bound_at`；抽纯函数 `_merge_binding`（便于单测）。名单表新增「绑定状态」列（已认领显示用户名+绑定时间，未绑定灰标）。
- **验证**：前端 `tsc --noEmit` 0 错误 + `npm run build` 成功；后端 pytest **167 passed**（新增 `_merge_binding` 2 例 + `test_list_returns_data_array_not_items` 锁定结构）；`AccessControl` 改用 `IdcardOutlined` 图标。

### 补全：学生名单/绑定增加 学院+专业 组织维度（2026-09-04）
- **背景**：学生组织是 学校→学院→专业→班级（含年级）→学生（约 40 人/班）五层，而名单只有 学校/学号/班级——用户发现少了学院、专业两个字段。经确认采用「名单落库 + 绑定写入 profile」方案：学院/专业由管理员预录，绑定成功后随身份一并写入学生资料（年级维持仅学生自填，名单不存）。
- **数据模型**：`student_rosters` 新增 `college`/`major` 两列（`VARCHAR(100)` 可空，`init_db.py migrate` 指纹迁移自动加列，已实测 2 处变更）；`StudentRoster.to_dict()` 输出两字段。
- **后端**：
  - `student_roster_service.py`：`create`/`create_batch`/`update` 支持透传 `college`/`major`（空值落 NULL）；`list` 关键字搜索扩展为 学号/班级/学院/专业/姓名。
  - `admin_roster_routes.py`：单条新建/编辑路由透传两字段；批量导入 `HEADER_MAP` 兼容「学院/专业 + college/major」中英文表头；CSV 模板下载增加两列与示例行。
  - `miniapp_routes.py` `bind_student()`：绑定校验仍为「学校+学号+班级」三项（学院/专业非学生自答项，避免增加绑定摩擦）；命中名单后把 `college`/`major` 一并写入 `StudentProfile`（已有列，此前无人填）。小程序资料详情页/UserInfoCard 原本就渲染 `profile.college`/`major`，绑定后自动可见，无前端改动。
- **管理端**（`UserManagementRoster.tsx` + `api/admin.ts`）：名单表新增「学院」「专业」两列（班级之后）；新建/编辑表单加「学院（选填）」「专业（选填）」输入；搜索框提示更新为 学号/班级/学院/专业/姓名；`RosterStudent` 接口与 create/update 入参类型补两字段。
- **验证**：后端 pytest **173 passed**（新增 create/update/batch 透传 3 例 + 路由透传 2 例 + bind 写入 profile 1 例）；指纹迁移补列成功并 SHOW COLUMNS 复核；前端 `tsc --noEmit` 0 错误 + `vite build` 成功（15.55s）。

### 修复：小程序请求层 access token 预刷新，消除过期后首请求 401 噪音（2026-09-01）
- **背景**：微信开发者工具控制台出现 `GET /api/miniapp/feedback|weather/current|weather/hourly|schedule/today 401` 红字。排查（后端日志 + 实测）：**非功能性 bug**——storage 里的旧 access token 超 1 小时过期后，页面初始化并发请求带旧 token → 全部 401「token 已过期」→ `request.ts` 单飞锁自动 `refreshOnce()` **刷新成功**（日志 20:20:34,115 生成新 token、旧 refresh 撤销）→ 4 个请求全部重放成功（天气/课表/反馈/电量数据均正常落库返回）。401 红字是微信开发者工具网络层固有日志，即使应用层自动刷新重放成功也无法抑制，仅造成"报错"错觉。
- **改动**（`miniapp-frontend/src/utils/storage.ts` + `request.ts`，最小改动）：
  - `storage.ts`：`setTokens` 记录 access token 签发时间戳（`miniapp.tokenIssuedAt`，配合原有 `expiresIn`）；新增 `isAccessTokenExpiringSoon(leewayMs=60s)`——签发时间 + 有效秒数齐备才判断剩余有效期，storage 无 token（DEV_TOKEN 预览回退场景）时返回 false 不触发。
  - `request.ts`：发起请求前，若 `auth && isAccessTokenExpiringSoon() && getRefreshToken()` → 复用单飞锁 `refreshOnce()` 提前换新，请求直接带新 token；刷新失败不阻断，仍走原 401 → refresh → 重放兜底。DEV_TOKEN 场景（30 天有效、无 refresh token）不预刷新，行为不变。
- **验证**：`tsc --noEmit` 0 错误；`build:weapp` 成功（产物确认含 `miniapp.tokenIssuedAt`）；后端实测带 dev token 请求 `weather/current` 返回 200。

### 「我的」页消息中心：入口整合 + 新公告提醒 + 校园卡号修复（2026-09-01）
- **背景**：小程序「我的消息」此前仅从设置页进入，发现成本高；「我的」页顶部二维码图标为无功能占位（点击仅 toast「二维码开发中」）；消息列表只含电量类站内通知，新发布的校园公告（首页有卡片但无独立提醒）无法在消息里感知；校园卡卡片编号误用学号（`studentNumber` 直传 `profile.student_number`），而校园卡号（一卡通号）与学号不同。
- **入口整合**（`miniapp-frontend/src/pages/profile/index.tsx` + `index.scss`）：
  - 顶部右上角二维码占位替换为**消息图标**（`icon-tongzhi`），点击进「我的消息」；右上角红色角标显示未读总数（>99 显示 `99+`，样式自绘于 `profile-msg-badge`，白描边适配 hero 渐变背景）。
  - 功能列表新增「我的消息」行（图标 + 未读角标，复用 `FeedbackBadge`），与顶部图标双入口，避免找不到。
  - 未读数 = 站内通知未读 + 公告未读，每次进入/切回「我的」页经轻量接口刷新（`useLoad` + 非首次 `useDidShow`）。
- **消息功能健全**（后端 `app/api/miniapp_routes.py`、`app/services/announcement_service.py`）：
  - `GET /api/miniapp/notifications/messages` 首页附带 `announcements`（未读公告，置顶优先最多 5 条）+ `announcement_unread` + `total_unread`（翻页 `offset>0` 不再重复携带）。
  - 新增轻量接口 `GET /api/miniapp/notifications/unread-count`：`{unread, announcement_unread, total}`，供「我的」页角标。
  - `POST /api/miniapp/notifications/messages/read` 不传 id（全部已读）时联动 `announcement_service.mark_all_read(user_id)` 清空未读公告（新增方法：把当前可见公告全部写 `announcement_reads`），返回 `announcement_unread` / `total_unread`。
  - 消息页 `pages/messages/index.tsx` 顶部新增「新公告」区块（置顶红标/分类蓝标 + 标题 + 部门 + 时间），点击进公告详情（详情页自动记已读）；从详情返回时 `useDidShow` 自动刷新区块；「全部已读」一次清空站内通知 + 公告。
- **校园卡号修复**（后端 `app/model/student_profile.py`、`app/api/miniapp_routes.py`；前端 `CampusCard`、`profile-edit`）：
  - `student_profiles` 新增 `campus_card_number` 列（指纹迁移自动加列，启动日志可见），`to_dict()` 输出；`PUT /api/miniapp/student/profile` 白名单加入该字段，且显式传 `null`/空串视为清空（存 NULL）。
  - `CampusCard` prop 由 `studentNumber` 改为 `cardNumber`，展示 `campus_card_number`；未绑定显示「未绑定校园卡号」（弱化样式）；资料编辑页新增「校园卡号」输入行（提示"一卡通号，非学号"）。
- **验证**：后端冒烟 9 项全过（校园卡号写入/回读/清空、unread-count、messages 附带公告、全部已读联动、造已发布测试公告 → 未读+1 → 消息列表携带 → 全部已读清零 → 已读不再出现 → 物理清理）；前端 `tsc --noEmit` 0 错误、`build:weapp` 成功。

### 修正：「我的」页顶部消息图标位置（2026-09-01）
- **背景**：上一版误把消息图标替换到顶部**二维码**位置（用户原意是替换**二维码下面**那个图标功能）。本次按用户澄清修正：二维码保留在原位（首位），消息图标移到原「更多」图标位置（二维码下方），依旧带未读角标；同时删除原「更多」ActionSheet（设置/帮助反馈/关于/退出登录的入口在功能列表/底部按钮已有对应覆盖）。
- **改动**（`miniapp-frontend/src/pages/profile/index.tsx` + `index.scss`）：
  - JSX：`profile-header-actions` 改为 `profile-qr`（上，`icon-erweima` + `Taro.showToast({title:'二维码开发中'})`） + `profile-msg`（下，带 `profile-msg-badge` 角标，跳 `/pages/messages/index`）。
  - SCSS：恢复 `.profile-qr` 圆钮样式；`.profile-msg` 加 `position: relative` 承载角标；移除已无引用的 `.profile-more` / `.profile-more-icon` 选择器。
- **验证**：`tsc --noEmit` 0 错误；`build:weapp` 成功。

### 修正：低电量提醒「充值方式」文案（2026-09-01）
- **背景**：低电量站内通知模板（`ElectricityFormatter.format_low_power_alert`）旧文案为「关注重庆工程学院公众号 → 智慧校园 - 电费缴纳 → 选择宿舍号进行充值」——学校名错误（应为重庆科创职业学院）、菜单路径错误（实为注册缴费 → 宿舍电费 → 绑定宿舍 → 点击充值缴费）。截图（用户推送卡片）确认推送内容错误，已影响 2026-09-01 20:00 触达学生。
- **改动**（`app/modules/electricity/formatter.py`，单文件单点）：将 159-162 行三步文案改为：
  1. 打开「重庆科创职业学院」微信公众号
  2. 注册缴费 → 宿舍电费 → 绑定宿舍
  3. 点击充值缴费
- **未改**：cookie 抓包路径（用户确认沿用同一公众号路径 → 用抓包工具点开用量记录 → 抓 dk.cqie.cn 发送请求的 cookie）；后端推送模板本轮保持最小改动，抓包说明已单独同步到小程序电表配置页（见下一条目）。

### 补充：电表配置页「如何获取 Cookie」步骤同步公众号抓包路径（2026-09-01）
- **背景**：用户澄清 cookie 抓包不在电脑浏览器登录电表查询系统，而在「重庆科创职业学院」微信公众号路径下：绑定宿舍后，用抓包工具点开「用量记录」，抓 dk.cqie.cn 发送请求的 Cookie。原小程序电表配置页「如何获取 Cookie」说明仍写「电脑浏览器 + F12 开发者工具」，与实际抓包方式不符。
- **改动**（`miniapp-frontend/src/pages/electricity-config/index.tsx`，仅说明文字，无逻辑改动）：
  1. 打开「重庆科创职业学院」微信公众号，进入「注册缴费」→「宿舍电费」，绑定您宿舍的电表
  2. 使用抓包工具（如 Charles、Fiddler 等）开启抓包
  3. 在公众号内点开「用量记录」，在抓包结果中找到 dk.cqie.cn 的请求，复制请求头中 Cookie 一行的完整内容
  4. 粘贴到下方输入框，点击「测试」，有效后点击「保存」
- **验证**：`tsc --noEmit` 0 错误；全 src 无其它「F12 / 开发者工具 / 电表查询系统」旧文案残留。

### 修复：小程序电表 Cookie 保存/测试被 XSS 中间件误判拦截（2026-09-01）
- **背景**：小程序「电表配置」页保存/测试 Cookie 报 `PUT /api/miniapp/electricity/cookie 400 (BAD REQUEST)`。日志定位为安全中间件 `Blocked xss attack: XSS in JSON field "cookie"`：XSS 模式 `on\w+\s*=\s*["\']?[^"\'>]+["\']?`（本意拦截 `onclick=` 等 DOM 事件属性）会把 Cookie 中任何以 `on` 开头的正常键值对（如 `online=1`、`onetime=...`）误判为 XSS，`scan_request_for_attacks()` 在路由执行前直接返回 400「Bad Request」（已用 `detect_xss` 实测复现）。此前管理端全局 Cookie 接口（7-20）能保存成功只是因为当时的 Cookie 内容恰好不触发。
- **修复**（`app/utils/security.py`，最小改动单点处理）：新增 `JSON_SCAN_EXEMPT_FIELDS`（method, path, key 三元组）字段级扫描豁免，对 `PUT /api/miniapp/electricity/cookie` 与 `POST /api/miniapp/electricity/cookie/test` 的 `cookie` 字段跳过 SQL/XSS 检测。豁免依据：该字段是学生爬虫鉴权凭证，仅存库 + 服务端转发给教务系统，`GET` 只返回脱敏预览（前4后2），绝不回显页面，SQL/XSS 检测不适用；且两接口均有 `@student_required` 认证（仅本人可读写）。全局攻击扫描不受影响，其它路径/字段行为不变。
- **验证**：py_compile 通过；test_client 模拟含 `online=1` 的 Cookie：无 token 401（认证层拦截而非 400 攻击拦截）、假 token 401「认证令牌无效」（证明已通过扫描）、真实 student token PUT 保存 200、GET 配置 200（`configured=true` + 脱敏预览 `ASP.****bc`）、空 Cookie 400「Cookie 不能为空」（业务校验正常）。测试写入的假 Cookie 已清空恢复现场。

### 电量模块用户化重构（2026-09-01）
- **背景**：每个宿舍有独立电表，原实现共用一个全局 Cookie（管理员配置），数据与推送不分用户，不适用于多宿舍场景；自动化无法代学生获取 Cookie，故改为学生自配、系统按其配置分别采集与推送。
- **数据模型**：电量三表（`electricity_records` / `electricity_remaining` / `electricity_total_capacity`）新增 `user_id` 列（NULL = 历史全局数据 / 管理员视图）；`student_profiles` 新增 `electricity_cookie` 列（学生私密凭证，`to_dict()` 不输出，仅本人可读写）；新增 `user_notifications` 站内通知表（user_id / category / title / content / is_read / created_at + 复合索引）。新表/新列由 `init_db.py migrate` 指纹迁移自动补齐。
- **后端**（按用户隔离）：
  - `app/services/electricity_service.py` 重写：新增 `get_electricity_service(user_id, meter, cookie)` 实例缓存（按 `(user_id, meter)` 键，避免多用户冷却状态/容量串数据）与 `set_cookie()`；全部方法按 `user_id` 过滤；crawler 用学生自配 Cookie 构造，不再读全局 `Config.ELECTRICITY_CRAWLER_COOKIE`。
  - `app/repository/electricity_repository.py`：CRUD/统计方法全部加 `user_id` 参数（`create_records_batch` 去重按"用户+时间+电表"，历史全局数据用 `is_(None)` 匹配）。
  - `app/modules/electricity/capacity_manager.py`：单例改按 `(user_id, meter)` 键缓存，`_get_recent_low_power_record` 加 user_id 过滤。
  - `app/modules/electricity/tasks.py` 重写：所有定时任务（每日/每周/每月报告、Cookie 检测、低电量检测、全量爬取）遍历"配置了 Cookie 的学生"（`_iter_students_with_cookie()`）为每人独立爬取/落库/通知；无学生配置时任务空转。统计改由 Repository 按用户查询（替代旧 JSON 文件统计）；低电量去重改查该用户最近 `low_power` 站内通知；旧的 `update_cookie_in_memory` / `_send_markdown` / `_send_image` / `_make_stats` 已删除。
  - `app/modules/electricity/formatter.py` 重写为纯文本（适配站内通知，不再渲染 Markdown）；`format_cookie_invalid` 引导"小程序 - 设置 - 电表配置"。
  - 通知渠道：新增 `app/model/user_notification.py` + `app/repository/user_notification_repository.py` + `app/services/user_notification_service.py`（单例），**企业微信电量推送整体移除**。
  - API：`miniapp_routes.py` 电量四接口（current/refresh/history/trend）按 JWT 用户隔离，返回 `cookie_configured` 字段，未配置时不发起爬取；新增 `GET/PUT /electricity/cookie`（脱敏预览前4后2，仅本人读写）、`POST /electricity/cookie/test`（不落库仅检测）、`GET /notifications/messages`（列表+未读数）、`POST /notifications/messages/read`（单条或全部已读）。`admin_routes.py` / `electricity_routes.py` 移除管理端 Cookie 配置接口，模块状态改用 `configured_students`；`admin_user_routes.py` 删除用户时级联清理 `user_notifications`。
  - `app/core/config.py`：`ELECTRICITY_CRAWLER_COOKIE` 标注弃用（保留向后兼容，代码不再读取）；`scheduler.py` 移除全局 Cookie 判断，电量任务总是注册。
- **小程序端**：设置页新增「服务」分组（电表配置 / 我的消息 两个入口）；新增 `pages/electricity-config/index`（受控表单 + 测试/保存，展示脱敏预览与获取 Cookie 步骤说明）、`pages/messages/index`（站内通知列表：未读数 / 全部已读 / 点击单条已读 / 触底分页）；电量详情页与「我的」页宿舍用电卡片在未配置 Cookie 时显示引导（"去设置"跳电表配置页）；`src/api/electricity.ts` 新增 getCookieConfig/saveCookie/testCookie，新增 `src/api/notifications.ts`。
- **管理端**：`Electricity.tsx` 模块配置 Tab 移除「爬虫 Cookie」表单，改为提示"Cookie 由学生在小程序自配"+ 展示已配置学生数；`admin.ts` 删除已废弃的 `updateElectricityCookie`；Dashboard 电量模块状态由 "Cookie: 已配置/未配置" 改为 "已配置: N 人"。
- 验证：后端 `py_compile` 通过；小程序 `build:weapp:clean` 编译成功；管理端 `vite build` 成功。

### 管理端电量页改版（2026-09-01）
- **背景**：电量用户化后，管理端旧电量页仍读全局视图（用户化前单电表、NULL 归属）与废弃 JSON 文件（`usage_records.json` / `remaining_power.json`），与学生维度数据完全脱节；普通用户（网页端 `role=user`）无任何学生数据可看。本次按学生维度整体改版。
- **用户决策**：① 学生总览范围 = 全部学生（含未配置，标灰 +「未配置」标记，顶部统计卡：总人数 / 已配置数 / 低电量数）；② 历史全局数据（NULL）完全移除展示（数据留库不展示）；③ 明细形式 = 独立 Tab 切换（选中学生切入「用电明细」，返回按钮回列表）。
- **后端**：
  - `app/services/electricity_service.py` 新增 `parse_statistics_range(range_type, start_date_str, end_date_str)` 静态方法（把原 `electricity_routes.py::get_statistics` 的时间范围解析抽为共用，供 admin 新统计接口复用）。
  - `app/api/admin_routes.py` 新增 4 个学生维度接口（均 `@admin_required`）：`GET /api/admin/electricity/students`（全部 `role=student` 用户 + `student_profiles` 外连，返回 summary 统计 + 每人配置状态/最新剩余电量/低电量标记，不返回 base64 头像避免响应体膨胀）、`GET /students/<id>/remaining`、`GET /students/<id>/records`（`limit/offset/meter_filter` 分页）、`GET /students/<id>/statistics`（复用 `parse_statistics_range`，响应结构与旧全局统计一致，供图表无缝切换）。
  - `app/api/admin_routes.py` 删除读废弃 JSON 的死接口 `GET /electricity/records`、`GET /electricity/remaining`（用户化后数据全走 MySQL，两接口已死）；清理多余 `json` import。
  - `app/api/electricity_routes.py` 删除全局视图查询接口 `GET /remaining`、`GET /records`、`GET /statistics` 与无前端引用的 `POST /trigger/daily|weekly|monthly|cookie_check`（管理端触发统一走 `/api/admin/electricity/trigger`）；保留 `/health`、`/status`、`POST /trigger/fetch_all`（进程管理页运维入口）、`DELETE /records`；删除随之失去引用的 `_trigger_task` 辅助函数与 `jwt_required` import。
- **管理端前端**：
  - `src/pages/Electricity.tsx` 重构为 3 Tab「学生总览 / 用电明细 / 模块配置」：总览 = 顶部统计卡 + ResponsiveTable（首字母 Avatar + 配置状态 Tag + 剩余电量/低电量红色标记，未配置标灰）+「触发数据采集」按钮（全量爬取/清空记录入口与列表轮询已移除）；明细 = 返回按钮 + 学生信息头 + 剩余电量卡片 + 用电记录分页表 + 数据可视化（`ElectricityChart` 传入 `userId`）；配置 Tab 保持模块级配置。
  - `src/components/ElectricityChart.tsx` 增加 `userId` prop，改调 `adminApi.getStudentElectricityStatistics`；未选学生时显示空态提示。
  - `src/api/admin.ts` 新增 `getElectricityStudents` / `getStudentElectricityRemaining` / `getStudentElectricityRecords` / `getStudentElectricityStatistics` 与对应类型（`ElectricityConfig` 字段补全），删除 `getElectricityRecords` / `getElectricityRemaining`。
  - `src/api/electricity.ts` 删除全局视图方法（`getRemaining` / `getRecords` / `getStatistics` / `deleteAllRecords`）与无引用类型，保留 `triggerFetchAll`（进程管理页仍在用）。
  - `src/layouts/AdminLayout.tsx` 普通用户（非管理员）菜单移除「电量管理」入口；`src/App.tsx` 的 `/electricity` 路由补 `AdminGuard`（用户化后普通用户无学生数据可看，仅管理员可访问）。
- 验证：后端 `py_compile` 通过、路由注册核验（4 个新接口在、6 个被删接口消失）；test_client 冒烟测试通过（总览/remaining/records/statistics/非法日期 400/无 token 401）；管理端 `vite build` 成功。

### 管理端电量页：全量爬取入口明确化 + 学生头像显示（2026-09-01）
- **背景**：改版后学生总览页虽有「触发数据采集」按钮（后端 `POST /api/admin/electricity/trigger` → `tasks.fetch_electricity_data` 遍历所有已配置 Cookie 学生爬取保存），但文案不直白、无确认步骤，且文件头注释误写"不再提供全量爬取入口"；学生头像（`users.avatar`，小程序上传的 data URI）未在管理端展示（改版时因响应体大小顾虑刻意不返回）。
- **后端**（`app/api/admin_routes.py::get_electricity_students`）：总览每名学生新增返回 `avatar` 字段（`user.avatar` data URI，无头像返回空串），供管理端有则显示、无则首字母兜底。
- **管理端**（`src/pages/Electricity.tsx` + `src/api/admin.ts`）：
  - 「触发数据采集」按钮明确为「全量爬取」，点击弹 `modal.confirm` 确认（提示将爬取所有已配置学生 N 人、未配置不爬、进度可在「进程管理」查看），避免误触；文件头注释修正。
  - 学生总览表格与用电明细页学生信息头：有头像（`record.avatar`）时渲染 `<Avatar src>`，无头像回退首字母（未配置仍标灰）。
  - `ElectricityStudent` 类型新增 `avatar?: string | null`；顺手修复 `fetchRemaining` 缺失的 `res.data` 空值检查（`ApiResponse.data` 为可选，`setRemaining(res.data)` 会触发 TS2345）。
- **验证**：后端 test_client 冒烟——`GET /admin/electricity/students` 200 且学生项含 `avatar`（`data:image/jpeg;base64,...`）；`POST /admin/electricity/trigger {fetch_electricity_data}` 200「电量数据采集 任务已触发」；管理端 `vite build` 成功（14.35s）。

### 小程序电量：首次进入自动懒采集补全记录（2026-09-01）
- **背景**：学生第一次进电量详情页时若管理员从未手动触发过采集、定时任务尚未覆盖，`history` 接口返回空记录，学生以为功能坏了。需在用户侧首次访问时自动补一次全量爬取。
- **后端**（`app/modules/electricity/tasks.py` + `app/api/miniapp_routes.py`）：
  - `tasks.py` 新增 `lazy_fetch_for_user(user_id)`：未配置 Cookie（前端已有引导）或有任何用电记录时不触发；冷却窗口（300 秒，内存字典，单机部署）内不重复触发；触发则后台线程执行 `_fetch_and_save(user_id, cookie)`（首次=全量 50 页，与既有策略一致），异步不阻塞响应。
  - `GET /api/miniapp/electricity/history`：`total == 0` 时调用 `lazy_fetch_for_user`，响应新增 `fetch_triggered` 布尔字段（本次是否已自动触发首次采集）。
- **小程序端**：`src/pages/electricity/index.tsx` 首屏 `getHistory` 返回 `fetch_triggered=true` 时 Toast 提示「正在首次采集电量数据，请稍后下拉刷新查看」；`src/types/api.ts` `ElectricityHistoryResult` 新增 `fetch_triggered?: boolean`。
- **验证**：py_compile 通过；单测 4 分支——无 profile 不触发 / mock 无记录有 Cookie 触发（`_fetch_and_save` 收到真实 Cookie 参数）/ 冷却期内不重复触发 / 有记录不触发（user 75 现有 752 条，返回 `fetch_triggered=false`）；`GET /history` 200 且响应含 `fetch_triggered` 字段；小程序 `build:weapp` 编译成功（16.04s，dist 已清空重建）。测试后冷却字典与 mock 已清理，未对真实数据产生爬取。

### 小程序端：修复 3 处历史 TypeScript 类型错误（2026-09-01）
- **背景**：小程序端 `tsc --noEmit` 长期存在 3 处类型错误（webpack 构建不受影响，但类型不安全、IDE 红波浪）。
- **修复**：
  - `src/api/feedback.ts`：`FeedbackCreateParams as Record<string, unknown>` 直接断言类型不重叠（缺索引签名）→ `as unknown as` 双重断言。
  - `src/pages/coursedetail/index.tsx`：`<EmptyState text=...>` prop 名错误（组件定义是 `title`）→ 改 `title`，避免文案丢失。
  - `src/pages/weather/index.tsx`：`setPressedIndex(it.type || it.name)` 可能传 `undefined` 与 `string | null` 状态不符 → 补 `|| null`。
- **验证**：`tsc --noEmit` 0 错误退出（此前 3 处）；`build:weapp` 编译成功（14.48s）。

### 数据库工具修复：手动 init_db 命令失效（2026-09-01）
- **背景**：排查新表迁移时发现 `_import_all_models()` / `_ensure_all_models()` 是空壳——只 `from app.core.database import Base` 并返回，从未真正导入 `app.model`（docstring 与实现不符）。后果：手动执行 `python init_db.py migrate` 时 `Base.metadata` 为空（0 张表），迁移恒判定"所有表已存在"什么都不做；`fingerprint/check` 定义侧 schema 恒空，所有实例表被判为"多余表"，`cleanup` 甚至可能建议 DROP 全部表。生产此前未受影响是因为启动路径（`bootstrap.py` 导入模型）metadata 完整，自动迁移正常——即"重启后端=自动迁移"一直有效，手动命令从未真正生效。
- **修复**：
  - `app/schema/common.py` 的 `_import_all_models()` 与 `app/core/db_fingerprint.py` 的 `_ensure_all_models()` 补上 `import app.model`（触发全部模型注册进 `Base.metadata`）。
  - `app/model/__init__.py` 补注册 3 个此前遗漏的模型：`IPBlacklist` / `IPSecurityEvent`（ip_blacklist 相关）与 `ServerSession`（server_sessions）——否则指纹比对会把这三张生产表误判为"多余表"。
  - `app/schema/common.py::ALL_TABLES` 补全 6 张新表（holiday_periods / notifications / student_profiles / wechat_accounts / feedbacks / user_notifications）；`init_db.py` HELP_TEXT 更新为 29 张表（并移除不存在的 `course_weeks`）。
- **验证**：两个导入入口均识别 29 张表且集合一致；本地执行 `python init_db.py status` 精准报出缺失表/列；`migrate` 成功建 `user_notifications` 表、补电量三表 `user_id` 列与索引、补 `student_profiles.electricity_cookie` 列（8 处变更）；`check` 返回 [OK] 一致 exit 0。

### 管理端用户管理：微信端 / 网页端分流（2026-09-01）
- **背景**：微信端小程序学生用户（`role=student`，openid 登录）与网页端用户（`admin`/`user`，账号密码 + MFA 登录）是两套认证体系；微信端无账号密码、无 MFA 概念（`password_hash` 为随机 bcrypt 占位哈希，密码登录路径天然关闭）。
- **后端**（`app/api/admin_user_routes.py`）：
  - `GET /api/admin/user/users` 每个用户新增 `source` 计算字段（`student → wechat`，其余 `→ web`），前端据此分流展示。
  - `reset-password` 对 `student` 返回 403「微信端用户无需密码，不可重置」；`reset-mfa` 对 `student` 返回 400「微信端用户不启用MFA」——双保险防 API 直调。
  - `update_user` 对 `student` 锁定身份字段：`role` 只接受 student（忽略其它值，避免前端禁用项提交触发白名单 400）、`username`（openid）不可改、`is_primary` 不可设。
  - `delete_user` 级联清理 `wechat_accounts` / `student_profiles` 子表（两 FK 均无 ondelete 级联，直接删 User 会外键失败）。
- **管理端**（`UserManagement.tsx` + `types/user.ts`）：列表新增「来源」列（微信端绿 Tag / 网页端默认）；微信端用户行隐藏「重置密码」「重置MFA」操作；编辑弹窗对微信端用户锁定用户名与角色（显示"微信端用户"）、隐藏主管理员选项；移动端卡片同步加来源 Tag、隐藏密码/MFA 操作。
- **筛选功能**（`UserManagement.tsx`）：列表顶部新增筛选栏（来源 / 角色 / MFA / 用户名关键字搜索），`useMemo` 派生 `filteredUsers`，桌面表格与移动端卡片共用同一份筛选结果；筛选无结果时显示空态提示（桌面表格 `emptyText`、移动端 `Empty` 组件）。轮询刷新不重置筛选条件。
- **决策**：不设密码（微信端用户维持随机占位哈希，管理端不提供密码重置入口）；分流复用 `role` 判断（不加 `source` 列、不改表迁移）。
- 验证：后端 `py_compile` 通过；管理端 `vite build` 成功，dist 含「微信端」分流逻辑。

### 小程序设置页（账号设置 + 通用）
- **后端数据模型**：`student_profiles` 新增 `nickname`（昵称，展示名优先于真实姓名）列，启动指纹迁移自动补列，不破坏现有表结构。
- **后端接口**：`PUT /api/miniapp/student/profile` 白名单扩展 `nickname` 字段；新增 `PUT /api/miniapp/user/avatar`（`@student_required`）——data URI 形式，复用管理端 `validate_avatar_data_uri` 校验（MIME 白名单显式拒绝 SVG / 文件头 Magic Bytes 防伪造 / 解码后 2MB 上限），学生端不套用管理端「一年 3 次」修改配额，成功落 `users.avatar` 并返回最新用户信息。
- **小程序端设置页**：新增 `pages/settings/index`（`app.config.ts` 注册）——账号设置（头像 / 昵称 / 学号 / 班级，行内编辑失焦自动保存）、通用（清除缓存 / 关于 / 退出登录）。
- **「我的」页接线**：左侧「设置」列表项与右上「更多」弹层首项（原「消息设置」占位改为「设置」）统一跳转设置页，两处「功能开发中」占位消除；展示名优先级改为 昵称 → 真实姓名 → 用户名 → 兜底。
- **清除缓存边界**：仅清 `feedback.viewedStatus`（反馈红点已读状态）与 `miniapp.user`（学生资料缓存）及内存共享红点计数，保留 `miniapp.auth` 登录态不清登。
- **移除「我的页背景」功能（2026-09-01 用户确认砍掉）**：删除 `student_profiles.profile_bg` 列定义、`PUT` 白名单中 `profile_bg` 及预设 key 白名单校验、设置页背景预设区块、`profile` 页 hero 的 `bg-*` 渐变主题；`student_profiles` 表残留的 `profile_bg` 列不参与任何读写（指纹迁移只补不删，如需彻底删除可在数据库手工 `ALTER TABLE student_profiles DROP COLUMN profile_bg`）。
- 验证：后端 `py_compile` 通过；小程序 `build:weapp:clean` 编译成功（无类型错误，dist 无 `bg-*`/`profile_bg` 残留）。

### 消息中心三合一重构（管理端）
- **列表页合并**：新增 `src/pages/Messages.tsx`，一个页面用 Tab 切换「公告 / 推送」两种消息，顶部统计卡片（通知总数 / 已发布 / 推送记录 / 待发送）复用原 `Announcements` + `Push` 列表逻辑，统一 dataSource / columns 断言解决两种类型不兼容；编辑跳转 `/messages/edit/:id?type=announcement|push`，支持从 URL 读取初始 Tab。
- **独立富文本编辑页**：新增 `src/pages/MessageEditor.tsx`（非 Modal），路由 `/messages/create?type=xxx` 与 `/messages/edit/:id?type=xxx`；富文本采用 **WangEditor v5**（`@wangeditor/editor` + `@wangeditor/editor-for-react`），以动态 `import()` 加载并在失败时降级到纯 `TextArea`，避免编辑器模块加载失败拖垮整页。公告模式含标题 + 富文本 + 分类 + 部门 + 置顶 + 过期时间 + 摘要 + 附件；推送模式含标题 + 富文本/图片/模板 + 推送类型（即时 / 定时 / 周期）。
- **路由与菜单合并**：`src/App.tsx` 新增 `/messages`、`/messages/create`、`/messages/edit/:id` 路由（AdminGuard 包裹），旧 `/push`、`/announcements` 路由改为 `<Navigate>` 重定向到 `/messages?tab=...`；`src/layouts/AdminLayout.tsx` 侧边栏删除「自定义推送」「校园通知」两项，合并为单一「消息中心」入口（SendOutlined 图标）。
- **依赖**：`admin-frontend/package.json` 新增 `@wangeditor/editor@^5.1.23`、`@wangeditor/editor-for-react@^1.0.6`（此前安装成功但漏写回 package.json，本次补录以保证可重现构建）。

### 小程序校园通知卡片接入真实数据
- `miniapp-frontend/src/components/NoticeCard/index.tsx` 移除「通知功能开发中，敬请期待」硬编码占位，改为调用 `notificationApi.getUpcoming({ limit: 3 })` 拉取真实即将到来的通知；`normalizeItem()` 统一兼容 list / events / 数组多种响应结构，`formatRelativeTime()` 输出相对时间；「查看更多」暂以 Toast 占位（后续建 `pages/notification/index` 列表页）。
- `index.scss` 重写：修正原不存在的 SCSS 变量（`$radius-md`→`$radius-medium`、`$text-quaternary`→`$text-tertiary`），新增 loading / list / item 样式。

### 修复：小程序端 401
- `miniapp-frontend/config/index.ts` 新增 `loadTaroEnv()`，读取 `.env` 的 `TARO_APP_*` 经 `defineConstants` 注入编译产物（等价 @tarojs/plugin-dotenv 但零依赖）；`defineConstants: loadTaroEnv()` 替换原空对象，使 `TARO_APP_DEV_TOKEN` 进入小程序包，解决 `/api/miniapp/*` 因缺 Bearer token 返回 401 的问题。

### 验证
- 前端：`tsc --noEmit` 零类型错误；`vite build` 成功（含 WangEditor，约 10s）。
- 小程序：`build:weapp:clean` 编译成功（约 10s）。
- 401 修复实测：小程序包含 dev token 后，活接口（天气/课表）带 token 请求 29528 返回 200。

### 意见与反馈（独立反向通道，与消息中心解耦）
> 学生 → 管理员 的反馈通道，与「消息中心」（管理员 → 学生推送）是完全不同的业务方向：独立成表、独立页面、独立导航，不并入消息中心。

- **数据模型**：新增 `feedbacks` 表（`app/model/feedback.py`），字段含 user_id / type / content / contact / images(JSON) / status / reply / replied_by / replied_at；`FEEDBACK_TYPES`（功能异常/功能建议/咨询求助/其他）与状态枚举（待处理/处理中/已解决）集中在模型层，`to_dict` 统一输出中文 `type_label` / `status_label` 与解析后的 `images` 数组。
- **后端接口**：`app/api/feedback_routes.py` 拆为两个蓝图（学生侧 `/api/miniapp/feedback`、管理侧 `/api/admin/feedback`）。学生侧：`POST` 提交（含类型/内容/联系方式/截图 URL 校验，内容 ≤2000 字）、`GET` 我的反馈列表、`GET /<id>` 详情（仅本人）、`POST /upload` 截图上传（WangEditor 约定返回，存 `output/feedback-images/`，EXIF 校正，复用公告图片安全校验）。管理侧：`GET` 列表（按状态筛选）、`GET /<id>` 详情、`POST /<id>/resolve` 标记状态、`POST /<id>/reply` 回复并置已解决。公共访问路由 `GET /api/feedback-images/<name>` 在 `app/api/routes.py` 注册（扩展名白名单 + `send_from_directory`）。
- **小程序端**：新增 `pages/feedback/submit`（提交页：类型选择 / 内容 / 联系方式 / 截图上传最多 9 张 / 提交后跳我的反馈）、`pages/feedback/list`（我的反馈列表，状态下拉筛选 + 悬浮提交入口）、`pages/feedback/detail`（反馈详情，展示管理员回复）；`src/api/feedback.ts` 封装 create/list/detail 与 `uploadImage`（Taro.uploadFile）；「我的」页「意见与反馈」与右上「帮助反馈」均跳转提交页。
- **管理端**：新增 `src/pages/Feedback.tsx`（列表按状态 Segmented 筛选 + 详情 Drawer，支持标记处理中/已解决、回复学生）、`src/api/feedback.ts`（list/detail/resolve/reply）、侧边栏「意见与反馈」入口（CommentOutlined，AdminGuard 保护）、`src/App.tsx` 路由 `/feedback`。
- **未读红点（已受理提醒）**：新增 `src/utils/feedbackBadge.ts`（本地已读集合 + `computeUnread` 计数 + 模块级共享计数 + `Taro.eventCenter` 实时通知）、`src/hooks/useFeedbackBadge.ts`（拉取「我的反馈」全量计算红点数 + 同步写入共享计数）、`src/components/FeedbackBadge`（红色圆形红点，count≤0 不渲染）。「已受理」= 反馈被管理员回复且状态置 `resolved`；用户在详情页查看（确有回复）即写入本地已读集合，红点 -1；计数为 0 不显示。红点同时出现在「我的」页「意见反馈」条目与提交页「我的反馈」顶栏，进入/返回对应页面时刷新。
- **自定义 TabBar（支持角标）**：原生微信 TabBar 不支持单个 tab 角标，切换为 `custom: true` 自定义 TabBar（`src/custom-tab-bar/index.tsx`）。框架级组件（`component: true`），微信自动渲染为底部导航栏，无需各 tab 页手动引入。三个 tab 图标/高亮与原生一致；「我的」tab 右上角显示反馈未读角标（通过 eventCenter 实时更新）；三个 tab 页根容器加 `padding-bottom` 防内容被遮挡。
- **修复 TabBar 选中要点击两次 / 点一下跳回首页**：原乐观 `setCurrent(idx)` 仍不稳——自定义 TabBar 组件在切换时可能被框架重建（`useState` 重置回首页 0），且 profile「我的课表」等其它页 `switchTab` 直达 tab 页时不经过 TabBar 点击处理、选中态错位。改为新增模块级选中态 `src/utils/tabBarState.ts`（`getTabIndex`/`setTabIndex` + `eventCenter` 广播 `tab:index`）；`custom-tab-bar` 初值取模块态、订阅广播实时同步 `setCurrent`，不再依赖组件生命周期；三个 tab 页（home/schedule/profile）在 `useDidShow` 各自广播自身下标，覆盖任何进入路径。冷启动角标：在 `app.tsx` 的 `useLaunch` 预取反馈未读并写入共享计数（`useFeedbackBadge.refresh`），TabBar「我的」角标在启动即可见，无需先进入「我的」页。
- **管理端反馈待处理角标（与小程序端呼应）**：管理员端「意见与反馈」侧边栏菜单项在有未处理反馈时显示红色数字角标。后端新增 `GET /api/admin/feedback/count`（单次 GROUP BY，返回 pending/processing/resolved/total 与 `unresolved=pending+processing`）；前端新增 `feedbackApi.count()`。共享状态 `src/contexts/FeedbackBadgeContext.tsx`（仅管理员登录后每 30s 轮询，非管理员/未登录不轮询并清零），在 `src/App.tsx` 内、`UserProvider` 之下挂载；`AdminLayout` 的 `menuItemRender` 对 `/feedback` 项在 `pending>0` 时渲染 antd `Badge`；`src/pages/Feedback.tsx` 在标记处理/回复成功后调用 `refresh()` 立即更新角标（无需等下一轮轮询）。角标语义=「待处理」数：标记为「处理中」或「已解决」即从待处理移除，待处理归零时红点消除（即便仍有「处理中」也不再红点提示，因为已开始处理），与小程序端「已受理未读」红点形成双向呼应。
- **修复反馈红点不随「处理中」消除**：原角标数 `unresolved=pending+processing`，导致管理员把反馈标记为「处理中」后仍计入未解决、红点不消失，需全部「已解决」才消除。改为 `AdminLayout` 侧边栏 `Badge` 直接取 `feedbackApi.count()` 的 `pending`（待处理）计数——标记「处理中」或「已解决」都会让该反馈离开待处理队列，待处理归零即红点消失。`FeedbackBadgeContext` 仍保留 pending/processing/unresolved 三值供其它视图使用，仅侧边栏红点的判定口径收窄为 pending。验证：`tsc --noEmit` 零错、`vite build` 成功。
- **小程序反馈红点覆盖「处理中」状态变更（不仅是已处理）**：原红点仅数 `resolved`（已受理）且未看过的反馈，管理员把反馈标为「处理中」时小程序无红点提醒。改为红点对 `processing`（处理中）与 `resolved`（已处理/已解决）两种状态均提醒；并把「已读」从「id 集合」升级为「id→上次查看状态」映射（存储键 `feedback.viewedStatus`），使每次状态流转（pending→processing→resolved）都能重新提醒、看过后即消，规避「看过 pending 后不再提醒后续状态」与「处理中永远消不掉」两类缺陷。详情页 `markViewed(id, status)` 改为进入时记录当前状态（不再限定「有回复才标记」）；`useFeedbackBadge` 相应改用 `getViewedStatusMap()`。验证：`build:weapp:clean` 编译成功（无类型错误）。
- **修复个人中心「更多」动作面板取消报错（MiniProgramError: showActionSheet:fail cancel）**：`pages/profile/index.tsx` 的 `handleMore` 调 `Taro.showActionSheet` 只写了 `success` 回调，用户点「取消」或点空白关闭时微信走 `fail` 并 reject（errMsg 含 `cancel`），因无处理器被当作未捕获异常抛出。补 `fail` 回调并仅对 `cancel` 静默忽略（取消是正常操作，非错误）。验证：`build:weapp:clean` 编译成功（无类型错误）。
- **修复反馈模块 UI 问题（含多轮校正）**：1) 「我的反馈」空状态图标从 `💬` emoji 改为与个人中心「意见反馈」菜单一致的 `icon-yijianyufankui` 图标（纯图标、无容器、无底色，蓝色 96rpx 半透明），两处图标统一；2) 反馈表单 Textarea `min-height` 从 200rpx 增至 320rpx，Input 固定高度 88rpx 并增大 padding，解决提示文字上下截断问题；3) 表单聚焦时 placeholder 正常消失（移除曾误加的 `adjust-position={false}`，恢复默认键盘上推行为，避免 placeholder 上移不消失的 bug）；4) 个人中心「我的收藏」实心五角星改为空心 `☆`，「意见反馈」菜单图标保持蓝色 `icon-yijianyufankui` 不变（不擅自改色）。
- **管理端会话失效自动跳登录页（不再需手动刷新/点确认）**：原 `utils/sessionExpiry.ts` 的 `notifySessionExpired` 只弹一个需手动点「确认」的 Modal，且 `request.ts` 里 `isRedirectingToLogin` 模块标志一旦置位便永久不清除——一旦首次 401 刷新失败后该标志被占用，后续 401 被 `request.ts` 直接吞掉、不再触发跳转，表现就是「登录失效后点啥都无效，只有手动刷新浏览器才回到登录页」。修复：`notifySessionExpired` 改为**总是执行跳转**（`window.location.replace("/login")`，1.8s 后兜底自动跳，期间弹窗说明原因），弹窗仅展示一次（`shown` 只控制弹窗不控制跳转）；失效原因写入 `sessionStorage`，登录页 `Login.tsx` 挂载时读取并以 `Alert` 兜底提示「为何被登出」后清除。心跳 `useSessionHeartbeat` 调同一函数，空闲超时也能自动跳登录页。验证：`tsc --noEmit` 零错、`vite build` 成功。

### 验证
- 后端：`test_client` 伪造合法 JWT 端到端跑通——学生提交→学生列表→管理列表→管理回复(置已解决)→管理详情(含回复)→学生详情(可见回复)，且学生访问管理接口正确返回 403；测试数据已清理。
- 小程序：`build:weapp:clean` 编译成功。
- 管理端：`tsc --noEmit` 零类型错误；`vite build` 成功。

---

## v6.16.0 (2026-08-27)

> 发版类型：**新功能（minor）**。微信小程序第二客户端落地（第一 + 第二阶段）：`student` 角色 + `StudentProfile` / `WechatAccount` 模型 + 微信 code 登录 + JWT 双 Token 签发 + `student_required` 权限装饰器 + 小程序用户/学生资料 API + 课表/天气/电量只读接口。遵循《微信小程序扩展开发指南》红线：不重写 JWT、不动管理员 MFA、管理端认证流程零改动、业务逻辑一律复用现有 Service。

### 新增数据模型（只加表，不改任何现有表）
- `student_profiles`：与 User 1:1（user_id 唯一），存放学号/学院/专业/班级/年级/手机号等学生身份信息，避免塞进 User 主表；首次登录只建骨架，由学生本人（`PUT /api/miniapp/student/profile`）或后续管理端补充。
- `wechat_accounts`：openid 唯一作为微信身份标识，另存 unionid 与 session_key（服务端专用，`to_dict` 不外泄）；建表走现有 `create_all` + 指纹迁移兜底，`users` 表零改动。

### 微信小程序认证（/api/miniapp/auth）
- `POST /login`：`wx.login()` code → 后端调微信官方 `code2Session` 换取 openid（**绝不信任客户端提交的 openid**）→ 首次登录自动创建 `User(role=student)` + `WechatAccount` + `StudentProfile` 骨架，再次登录复用已有用户 → 复用现有 `JWTManager.generate_tokens` 签发双 Token（返回在响应体，小程序端自行保存，不写 httpOnly cookie）。
- 学生 User 的 `password_hash` 生成**随机 bcrypt 哈希**：既满足 `users.password_hash NOT NULL` 约束，又保证随机密码无人可知、学生账号无法走 `/api/auth/login` 密码登录。
- `POST /refresh`：Body 携带 refresh_token 轮换（旧 refresh 自动进黑名单）；`POST /logout`：Bearer access_token 撤销（可选一并撤销 refresh_token）。
- AppSecret 只存服务端环境变量（`WECHAT_MINIAPP_APPID` / `WECHAT_MINIAPP_SECRET` / `WECHAT_SESSION_TIMEOUT`），未配置时登录返回 503；小程序前端代码不含任何敏感配置。

### 权限隔离（student_required）
- 新增 `app/utils/student_auth.py`：在现有 `jwt_required` 之上检查 `role == 'student'`，非学生 403。
- 角色互斥：student 访问 `@admin_required` 接口 → 403；admin 访问小程序学生接口 → 403；管理端密码 + MFA 流程零改动。

### 小程序用户 API（/api/miniapp，第一阶段范围）
- `GET /user/me`：当前学生用户信息（user_id 取自 JWT，防越权）。
- `GET /student/profile` / `PUT /student/profile`：本人学生资料查询/更新，只允许更新传入白名单字段（学号/姓名/学院/专业/班级/年级/手机号），客户端无法通过传 `user_id` 篡改归属（IDOR 防护）。

### 课表 / 天气 / 电量接口（/api/miniapp，第二阶段范围）
- 全部 `@student_required` 保护，路由层只做鉴权与编排，业务查询**一律复用现有 Service**（`schedule_service` / `weather_service` / `electricity_service`），不复制业务逻辑。
- **课表**：`GET /schedule/today`（今日课程，复用 `get_today_schedules`）；`GET /schedule/week`（指定周课表，缺省当前教学周，按 `weeks` 字段 + `is_course_in_week` 过滤，附带 `available_weeks` 可选周列表）；`GET /schedule/current`（当前教学周信息：week_number/is_teaching_week/date/week_day）。
  - 说明（遵循指南 §35）：Course 表为全校/单账号爬取的唯一课表数据，**无学生身份维度**，小程序查询的即该份课表，接口按周过滤返回，未擅自给 Course 表加 user_id。
- **天气**：`GET /weather/current`（实时天气，30 分钟 TTL 过期后台刷新）；`GET /weather/hourly`（24 小时逐小时预报，60 分钟 TTL）；`GET /weather/alerts`（生效中预警，包装为 `warnings`）。
- **电量**：`GET /electricity/current`（剩余电量，含百分比/总量/低电量标记）；`GET /electricity/history`（用电记录，默认最近 30 条、`days=None` 避免北京/UTC 时区错配截断，支持 `limit` 参数上限 1000）。

### 验证
- `tests/test_miniapp_auth.py` 14 例（SQLite 内存库 + mock 微信 code2Session）：首次/再次登录、缺 code 400、微信侧错误 40029→401、配置缺失→503、access 过期 401、无 token 401、student↔admin 双向 403、资料 GET/PUT 防 IDOR、refresh 轮换（旧 token 二次刷新 401）、logout 撤销后原 token 失效。
- `tests/test_miniapp_phase2.py` 13 例（mock Service 方法 + 注入课表内存缓存）：无 token 401、admin 403、today 按日期过滤、week 按周过滤/默认当前周/非法周 400、current 周信息、天气三端、电量 current/history（limit 透传）。
- 全量回归 `pytest`：**151 通过**（含既有全部用例；本轮开发过程中曾出现的 `test_course_spider_skip` MySQL 凭据环境性失败，在本地 MySQL 就绪后同步通过）。
- 真实后端实测（重启后）：`/api/ping`、`/api/health`（version 6.16.0）、小程序蓝图挂载（无 token 401）、微信 code2Session 真实调用（40029 → 401 映射）、管理端登录回归全部符合预期；测试环境额外补齐 `beautifulsoup4`/`lxml`（电量服务链依赖，requirements.txt 本就包含）。

### 部署说明（生产机）
- 需在服务端 `.env` 新增 `WECHAT_MINIAPP_APPID` / `WECHAT_MINIAPP_SECRET`（真实小程序后台获取），未配置时小程序登录接口不可用（503）；`.env.example` 已同步占位。
- 新增 2 张表由启动期自动迁移创建（指纹迁移兜底），无需手写 DDL；无需 `pip install`（复用已有 requests/bcrypt 依赖）。

---

## v6.15.3 (2026-08-25)

> 发版类型：**安全修复 + 移动端体验优化（patch）**。登录爆破防护升级（单账号临时封禁 + 前置限流 Redis 化），并完成一批手机端布局治理（折叠预警列表、左滑返回、全站留白收敛、系统设置/进程管理/Webhooks 专项优化）。

### 单账号暴力破解升级为临时封禁
- `ACCOUNT_FAIL_TIERS` 增加第 2 级：同一 IP 对同一账号 5 分钟内失败 **10 次** → 写黑名单**临时封禁 1 小时**（`source=login_brute_tier2`），后续请求在 login 入口 `is_ip_blocked` 处于密码校验**之前**直接 403 拦截；到期自动解除，仅手动封禁可永久，持正确凭据的自助解封通道不变。
- 修复 `evaluate_login_failure` 维度一硬编码 `action="rate_limit"` / `duration_hours=None` / `source=None` 的 bug（此前即使 `_match_tier` 返回更高层级也永远只限流不封禁），改为从层级配置读取。
- `_login_failure_response` 的 `temp_block` 分支 reason 文案补充 `ip_account` 场景（此前误写成"不同账号失败"）。
- 新增回归测试 `test_evaluate_password_per_ip_account_tier2_temp_block`（含隔离性断言）。

### 前置登录限流改为 Redis 共享计数
- `_check_login_rate_limit`（60 秒内同 IP 超过 5 次登录请求 → 429，位于密码校验之前）由进程内存字典改为 **Redis 固定窗口计数**（`INCR` + `EXPIRE`，key `login_rate:{ip}`），Gunicorn 多 worker 共享同一计数，不再被轮询分发绕过。
- Redis 不可用或异常时自动降级原进程内存路径（滑动窗口），并告警日志；恢复后自动重连（复用 `ip_blacklist_service._get_redis_client` 冷却期机制）。
- 新增 `tests/test_login_rate_limit.py` 4 例：Redis 路径前 5 放行第 6 起 429、内存降级路径、Redis 异常降级、不同 IP 隔离。

### 验证
- `tests/test_ip_blacklist.py` + `tests/test_login_rate_limit.py` 共 34 例全部通过。
- 前置限流与信号感知层（`evaluate_login_failure`，Redis 滑动窗口）分工：前置限流挡"请求总量"，信号感知层挡"失败信号"，两者计数相互独立、互不干扰。

### 手机端登录页"左滑退不出/变刷新"修复
- **根因**：iOS Safari / 内置浏览器在历史栈无可退条目时，右缘左滑手势 = 刷新当前页（浏览器行为，页面无法阻止）；而项目多处整页跳转（`window.location.href`）与 `Navigate replace` 混用，进一步污染历史栈——直达登录页时栈底无前页，左滑即刷新；会话过期/登出后整页跳转会堆叠 `/login` 条目，左滑退回业务页又立刻被踢回，形成"退不出"。
- 修复（让历史栈可退到站外 / 明确告知无路可退）：
  - `sessionExpiry.ts`：会话失效跳转 `window.location.href` → `window.location.replace("/login")`，替换掉已失效业务页，不再堆叠历史。
  - `AdminLayout.tsx`：登出跳转 `navigate("/login")` → `navigate("/login", { replace: true })`。
  - `Welcome.tsx`：快捷入口整页跳转改为 SPA 内 `navigate`。
  - `Login.tsx`：登录成功 / MFA 成功 / MFA 引导跳转全部加 `{ replace: true }`，登录页条目被业务页替换，左滑可直接退回登录前页面；栈底（直达登录页/微信内打开）时显示提示条"没有上一页可返回，请直接关闭浏览器标签页"，避免用户反复左滑困惑。
  - **后续清理（按用户反馈"返回按钮在登录页无意义"）**：删除原 `canGoBack` 状态下显示的"返回"按钮——第一次访问栈底时本就不显示，而退出登录后到达登录页时回退会落到已登出页面再被 AuthGuard 踢回登录形成死循环。提示条保留（告知栈底真实情况）。
- 边界说明：手机浏览器在"历史栈唯一条目"上的左滑刷新是系统级行为，任何网页代码都无法拦截；本次修复保证有历史可退的场景能正常退到站外，并给无历史场景明确提示。

### 天气预警历史列表优化（手机端）
- 预警历史改为**折叠列表**：默认只显示"标题 + 已推送状态 + 时间"，点击展开查看完整描述——避免单条数百字的预警（如高温橙色预警全文）把列表撑得超长。
- **当前预警同步改为折叠列表**：标题 + 等级标签（红/橙/黄/预警，按 `color_code` 映射）+ 时间，点击展开描述；空状态保持"当前无天气预警"。
- **标题过长省略号**：标题超过 **10 个字**时截断为"前 10 字 + ..."（`shortenTitle`），完整标题放 `title` 属性长按可查看；标签/时间 `flexShrink: 0` 不会被挤压换行，CSS ellipsis 兜底。
- **实时天气"更新时间"独立一行**：原来"城市/天气/更新时间"三列在手机上挤不下、更新时间被挤换行；改为城市+天气一行、更新时间独立一行（左对齐）。
- 每页条数 20 → **5 条**（前端 `getAlertHistory(page, 5)`，后端接口无需改动）。
- "加载更多"按钮**居中显示**。

### 进程管理页面去除多余 Card 包裹
- "执行历史"和"爬取预约"两个 tab 原本各自套了一层 `<Card title="...">`，在移动端 Tabs padding + Card 24px padding + 折叠面板自身 padding 累加，列表内容被挤成窄条。
- 去掉两个外层 Card 包裹，原 Card 标题（"任务进程管理"、"爬取预约任务"）改为 tab 内容顶部的独立标题行（带 Badge 徽章的 flex 行/普通 h3），列表内容获得完整可用宽度。
- **执行历史工具条布局修复**：原来"执行历史"标题与 3 个 Select + 刷新按钮用 `display: flex; justify-content: space-between` 同一行横排，mobile 端左侧标题被挤成竖排、刷新按钮被挤到第二行。改为标题独占一行、筛选控件用 `flex-wrap: wrap` 自然换行。

### 全站移动端左右留白治理（跨页面）
- **AdminLayout**：`PageContainer` 移动端内容区左右 padding 降为 `8px`（在 children 外包一层响应式 div，`PageContainer` 本身不支持 `contentStyle` 属性），一次性缓解所有页面"PageContainer + 页面 Card"的留白累加。
- **Tasks**：双层 Card 嵌套（分类 Card 24px + 任务 Card 16px）在移动端降为 12/8（新增 `Grid.useBreakpoint`）。
- **Electricity**：外层 Card 与"剩余电量"内层 Card 移动端 body padding 24 → 12（`Card → Tabs → Card` 三层留白）。
- **Dashboard**：任务执行统计主 Card 移动端 body padding 24 → 12。
- 已适配不动：Course（已有 isMobile 降级）、Blacklist/SessionManager（已有 useBreakpoint 卡片视图）、Push/Webhooks/HolidayMode（单层 Card 靠 ResponsiveTable 兜底，由全局 contentStyle 缓解）。
- **Settings**：配置项表格"外层 Card → Collapse 面板 → ResponsiveTable 移动端卡片"三层嵌套，移动端外层 Card body padding 24→12、Collapse 面板 size=middle→small 缩内边距、MFA Card 同步 12/24。
- **Webhooks**：去重 PageContainer 自动生成的"Webhook 管理"标题（去掉 Card title，避免与面包屑重复）；工具条"重载配置 / 添加 Webhook"从 Card extra 改为 Card children 顶部独立行（`flex-wrap: wrap, justifyContent: flex-end`），移动端不再被挤压；Card body padding 24→12。
- **UserManagement / Blacklist 移动端"白色容器"消除**：两个页面的外层 Card 移动端加 `variant="borderless"` 去除白色边框 + body padding 0，让内容直接贴 Tabs 边缘，消除"Card 进一步限制内容宽度 + 视觉割裂"问题。桌面端保持原 outlined + 24px padding。
- **Settings 移动端专用紧凑卡片**：原移动端用 ResponsiveTable 把每个配置项渲染成"配置项/当前值/说明/操作"4 字段竖排卡片（每项 4 行文字，手机端眼花）。改为移动端专属紧凑卡片：第一行"配置项名（粗体+省略号）+ 当前值 + 操作"，第二行小字说明；编辑态输入控件与保存/取消独占行。桌面端保持原表格。
- **Settings 移动端隐藏"配置说明" Alert**：3 条说明（可编辑/只读/敏感）占用手机首屏大量空间，对"快速操作"场景价值低，移动端用 `!isMobile` 隐藏，桌面端保留。
- **Settings 全部说明性 Alert 改为"标题旁问号图标 + 弹窗详情"（按用户建议重构）**：顶部"配置说明"Alert 与课程/电量面板内的"爬取计划"Alert 全部移除，改为三个 `?` 图标——外层 Card 标题"系统设置"旁、课程面板标题旁、电量面板标题旁；点击弹出 Modal 展示对应说明（面板内图标 `stopPropagation` 不触发折叠）。移动端首屏直接进入配置列表，说明信息按需查看。
- **Settings 移动端折叠面板默认收起**：桌面端 `defaultActiveKey` 全部展开（便于浏览），移动端默认 `[]` 全部收起（手机上同时展开 5 个模块过于拥挤）。
- **用户端首页（Welcome）移动端留白收缩**：根容器 `padding: 24` 与 PageContainer 8px 累加导致手机左右各约 32px 留白，移动端降为 `8px`（桌面端保持 24px）。
- **Welcome "使用提示"布局崩坏修复 + Card 留白收缩**：原 `<div display:flex>` 包裹 Tag + Text（Antd Text 渲染为 `<span>`），Text 在 flex 容器内**没有 `flex: 1; min-width: 0`**，长文字被挤压成几个字就换行（截图现象）。修复：Tag `flexShrink: 0` 固定宽，Text 加 `flex: 1; min-width: 0` 占满剩余空间并自然换行；Card body padding 移动端 24→12。
- **Welcome "使用提示"对齐统一（按用户建议改为指标符式列表）**：原 `display:flex` 横排 Tag + Text，文字长折行导致行高不一，Tag 视觉上"参差不齐"。改为统一列表结构：固定高度的"彩色圆角标签条"（替代 Tag，宽 56 / 高 22，背景色 + 主题色文字）+ Text `flex:1 minWidth:0`。三行视觉一致（统一高度 22px 标签条 + 文字自然换行），首行折行不再影响对齐。

### 安全事件封禁：同一 IP 全部事件一并处置
- 后端 `ban_event_ip`：封禁某条安全事件对应的 IP 后，**自动将该 IP 其余未处理事件（未封禁且未忽略）一并标记为已封禁**，返回消息附带一并处置的数量（如"IP 1.2.3.4 已加入黑名单，并一并处置了 18 条同类事件"）。同一 IP 在黑名单表始终只有 1 条记录（`block_ip` 按 IP 更新而非新增），不会因多条事件累加。
- 前端确认弹窗（桌面表格 + 手机卡片）提示文案补充"该 IP 其余同类事件将一并标记为已处置"。
- 新增回归测试 `test_ban_event_ip_marks_siblings`（含已忽略事件不被改动、黑名单不累加断言）。

---

## v6.15.2 (2026-07-20)

> 发版类型：**功能移除（patch）**。砍掉冗余且会在假期误发的文本版每周课表推送（"本周课程安排…祝本周学习顺利！"），保留图片版周课表。

### 移除文本版每周课表推送
- 删除 `weekly_schedule` 默认规则（`rule_service._rules`）及其两个触发 handler（`_check_weekly_schedule`、`_check_weekly_schedule_force`），规则引擎不再生成 `sub_type="weekly"` 的推送任务。
- 删除配套模板 `schedule_summary_weekly`：`app/services/template_service.py` 内置默认模板 + `app/services/templates.json` 条目一并移除。
- 清理死代码：移除 `task_service._get_priority` 中 `("schedule_summary", "weekly")` 优先级映射、`delivery_service._get_adapter_name_for_task` 路由元组里的 `"weekly"`（保留 `"weekly_image"`）、`process_routes.get_dynamic_rules` 的 `weekly_schedule` 映射与 `trigger_desc` 分支、`admin_routes` / `routes` 中过时的 `push_weekly_schedule` 文档字符串；`executors._send_weekly_image` 的 `rule_id` 标签由 `weekly_schedule` 更正为 `weekly_image`。
- 图片版周课表（`generate_weekly_course` → `_send_weekly_image`，`sub_type="weekly_image"`）不受影响，仍是每周课表的主推送形态。

### 为什么砍掉（兼答"假期里它怎么还发出来"）
- 文本版与图片版内容重复，属历史遗留的冗余推送；且在假期里仍会按规则（每周一 08:00）+ 数据库里上学期残留的课程数据把文字版发出。
- 根因：假期静默**不是自动生效**，而是需要显式开启——要么管理员打开紧急静默总开关（`system.holiday_mode_enabled`），要么今天命中某条启用的假期区间。运行实例若未配置这两项，`holiday_service.is_active()` 返回 False，第一道闸不拦。
- 即便未开静默，第二道闸 `_is_in_teaching_week()` 也只按校历学期（`course_meta.json` 的 weeks / 开学日推算）判定"是否在校历学期内"，**不consult假期静默**。若学期定义仍覆盖当前日期，教学周判定返回 True，第二道闸也不拦。
- 两道闸都不拦 → `check_push_rules` 正常推进 → `_check_weekly_schedule` 在配置日触发 → 旧课程数据仍在库 → 文字版照发。这也就是它"逃脱假期静默"的完整链路。

---

## v6.15.1 (2026-07-20)

> 发版类型：**功能修正（patch）**。假期静默语义重构与前端命名统一：将「假期模式」拆分为「紧急静默（永久/手动）」与「假期条目短期静默（按日期自动）」两个独立来源；假期卡片展示与静默开关解耦；学期下拉/全量爬取补全所有学期；前端侧边栏与页面文案统一为「推送静默」，系统级开关更名为「紧急静默」；假期条目开关增加 hover 描述。

### 假期静默语义重构（紧急静默 + 假期条目短期静默）
- 原「假期模式总开关」语义歧义（开关关则假期区间完全不生效），重构为两个独立静默来源，任一为真即静默：
  - **紧急静默**（系统级 `system.holiday_mode_enabled`）：开启即全体面向用户推送永久静默，不依赖任何假期区间，直到手动关闭（用于紧急情况或长期静默）。
  - **假期条目短期静默**：某条假期条目自身 `enabled` 且今天落在其区间内时，按日期自动静默、离开区间自动恢复（短期）。
- `holiday_service.is_active()` 改为「来源1 或 来源2」决策；配置读取异常仍 fail-open 回退不静默。
- 安全告警（系统/IP 安全事件）与电量运维状态告警仍不受静默影响（不变）。

### 假期卡片展示与静默开关解耦
- 课程页假期卡片「是否显示」只由「假期条目自身 enabled + 当前日期命中区间」决定，与紧急静默开关无关——只要条目开关开了、日期在区间内、且看当前学期，即显示假期卡片；紧急静默开关仅控制推送/爬取是否静默。
- 后端 `holiday_service.get_status()` 的 `period`（卡片/横幅用）忽略总开关；`active`（各页面静默禁用按钮用）仍为「紧急静默开关开 + 命中」语义。
- 新增回归锁定测试 `TestHolidayServiceGetStatusDecoupled` 与 `is_active` 新语义测试（共 4 例），防止被未来重构改回。

### 学期选项补全（教学周 / 全量爬取）
- 新增 `course_repository.candidate_semester_pairs(years_back=3)`：基于当前日期生成候选学期（eams_id = DB id 末三位）。
- `course_routes.get_semesters` 改为「course_meta 精确 eams_id 优先 + 候选学期补全」，不再只取最近 6 个；`crawl_task_service._all_semester_pairs()` union course_meta + 候选学期，全量爬取覆盖所有学期（修复此前只剩 `25-26-2` 一个选项的问题）。

### 前端命名统一 + 假期条目 hover 描述
- 侧边栏菜单「假期模式」→「推送静默」（与页面标题同源）。
- 系统级开关「总开关」→「紧急静默」；页面所有用户可见「假期模式」文案统一为「推送静默」（横幅、tooltip、加载/开关反馈、帮助文），后端配置描述与注释同步刷新。
- 假期区间表格中每条假期的启用开关增加 Tooltip 描述（短期静默语义）。
- 接口契约保留：`set_master` / `/api/holiday/master` / 前端 `setMaster` 不变。

### 验证
- 后端 pytest **118 passed** 零回归；ruff 全过。
- 前端 `npm run build` 通过（tsc 无类型错误）。
- 生产机升级：整目录覆盖 + `systemctl restart push-system.service`（顺带 `DROP TABLE IF EXISTS course_weeks;`）；`.env` 的 `APP_VERSION` 须手动改为 6.15.1（不入库）。

---

## v6.15.0 (2026-07-20)

> 发版类型：**架构整理 + 功能修正（minor）**。后端启动/初始化与任务调度职责拆分收口（新增 schema 包、bootstrap、process_service、executors、scheduler_state、parser_utils、course_helpers、teaching_week_service、notification_service）；剔除 `course_weeks` 表，教学周改为基于开学日推算（修正第21周 / 周次下拉默认选中）；全仓库 ruff-format + prettier 格式化，补齐 CI / 格式化 / 测试脚手架。

### 后端架构整理（模块拆分，职责收口）
- 新增 `app/schema/` 包：将原仓库根 `init_db.py` 按职责拆分为 `common` / `status` / `create_tables` / `migrate` / `seed` / `reset` / `fingerprint` 子模块，根 `init_db.py` 仅作 CLI 装配入口。
- 新增 `app/core/bootstrap.py`：把 `create_app` 中「启动期副作用」（建表、补列、清僵尸进程、写默认配置与管理员、指纹自动迁移/清理）收敛到 `run_bootstrap(app)`；提供 `flask bootstrap` CLI；受 `AUTO_MIGRATE_ON_START` 开关控制，可灰度关闭改为人工执行。
- 新增 `app/services/process_service.py`：收敛原 `app/api/process_routes` 中被 service / 模块 / 调度层反向调用的进程写入入口（`create_task_process` / `update_task_progress` / `complete_task_process`），修正分层倒置。
- 新增 `app/tasks/executors.py` + `app/tasks/scheduler_state.py`：把课表爬虫 / 推送执行逻辑与调度器共享状态从 `scheduler.py` 拆出，集中共享状态到 `scheduler_state`，消除「生命周期 ↔ 执行」相互 import 的循环依赖。
- 新增 `app/cqie-course-timetable/parser_utils.py`：从 `main.py` 的 `CourseTableTool` 抽取与浏览器状态无关的纯解析函数，可单测、可复用，不改 spider_runner 以 subprocess 调用 `main.py` 的契约。
- 新增 `app/utils/course_helpers.py`：把课程时间 / 周次纯计算逻辑从 `course_routes` 顶部下沉到 utils 层（依赖图叶子节点，仅依赖标准库），消除「service 反向 import api 层」的分层倒置。
- 新增 `app/services/teaching_week_service.py`：教学周服务单例，基于开学日推算当前教学周（见下「剔除 course_weeks」）。
- 新增 `app/services/notification_service.py`：统一状态告警收口（替代爬虫 `pipeline._send_status_alert`），失败静默、不依赖 Flask 请求上下文。
- 新增单测：`test_course_split.py` / `test_delivery_service.py` / `test_no_is_true_false_antipattern.py` / `test_parser_utils.py`。

### 剔除 course_weeks 表（治本，不再查表推算周次）
- 删除 `app/model/course_week.py` 及 `model/__init__.py` 注册、`schema/common.py` 的 `('course_weeks', ...)` 条目；删除 `course_repository.get_week_number`（含危险的 `MAX(week_number)` 兜底）。
- 移除 `crawl_task_service.py` / `tasks/executors.py` 中 `sync_course_weeks_from_dir` 调用。
- 教学周改为**纯推算**：`teaching_week_service` 基于开学日（`system.semester_start_date` 配置优先，否则按学期 term 推算：秋季 9/1、春季次年 3/2）推算当前周，上限 22 周；前端 `available_weeks` 由 `build_available_weeks(semester_id)` 生成，字段结构不变，前端零改。
- 开学日权威来源：新增 `system.semester_start_date` 配置项（默认空，空时按 term 推算，管理员可覆盖）。

### 爬虫越权收回（系统差遣，两阶段；前序 v6.14 已立项）
- 阶段1：`pipeline.save_to_database` 收敛为纯落库，不再承担周次 / 进程 / 图片 / 告警决策。
- 阶段2：`main.py` 新增 `--only-image` 子命令（图片生成由系统按需调用）；移除 `pipeline._send_status_alert`，告警统一收口 `notification_service.send_status_alert`。

### 教学周推算修正（本版本两轮）
- **周次下拉默认选中**：暑假 `get_current_week_number()` 返回 0 时，`course_routes` 回退第1周（`or 1`），避免 Ant Design Select 因 `0` 为 falsy 不选中导致下拉显示空框（选项 1~25 仍在，仅缺默认值）。
- **第21周修正**：`teaching_week_service._get_weeks_max()` 原硬编码 20，把开学日(3/2)推算的第21周(7/20)误判为非教学周 → 0；改为动态取值 `system.teaching_weeks_max` → 教务系统真实界限（`course_meta.json` 的 `weeks` 最大值，爬虫已从教务系统「教学周」下拉框抓取）→ 兜底 22。验证 7/20 正确返回第21周；真暑假（8月，推算 ≥23 周）仍正确归非教学周。

### 假期模式前端修复（补 v6.14.0）
- `src/pages/Tasks.tsx`：假期静默时禁用按钮补全至 16 个（含 `push_daily_schedule` / `push_weekly_image` / `fetch_all` / `check_cookie_validity` 等），统一 `cursor:not-allowed` + `opacity` + `title` 提示。
- `src/style.css`：`.task-action-btn` 增加 `:disabled` / `[aria-disabled]` 规则（`!important` 覆盖内联），修复假期禁用按钮鼠标悬停无禁止光标的问题。

### 全仓库格式化与工具链补齐
- 后端 ruff-format（import 重排、去除 `# -*- coding: utf-8 -*-`）；前端 prettier（单引号转双引号、import 多行换行）。
- 新增 `.pre-commit-config.yaml`（ruff + ruff-format + eslint + prettier）、`Push_System_Flask/ruff.toml`、前端 `eslint.config.js` / `.prettierrc.json` / `.prettierignore` / `vitest.config.ts` 与测试脚手架（`src/test/setup.ts`、`src/utils/__tests__/datetime.test.ts`、`src/utils/__tests__/semester.test.ts`）。
- 新增 CI 工作流 `.github/workflows/ci.yml`。

### 验证
- 后端 pytest **113 passed**（仅 `datetime.utcnow()` 弃用告警，非错误）；前端 `npm run build`（tsc 无类型错误）通过。
- 生产机升级步骤：部署后需手动 `DROP TABLE IF EXISTS course_weeks;`（模型已删除，SQLAlchemy 不会再管理该表，旧表须手动清理，否则成为孤儿表）。

---

## v6.14.0 (2026-07-20)

> 发版类型：**新功能（minor）**。新增「假期模式」：进入寒假/暑假后系统自动全体静默（不再向用户推送任何消息），并跳过课表爬取以节省资源；配套前端独立配置页。同时并入原拟单独发布的周课表教学周修复。

### 假期模式（全体静默）
- **需求**：用户在毕业设计答辩/寒暑假期间希望系统「全体静默」——自动停掉一切面向用户的推送，且能配置假期区间（寒假/暑假/自定义），无需手动逐个关开关。
- **设计原则（单点收口 + 双层防护）**：
  - **真实发送出口单点收口**：静音的最终生效点压在真正的发送出口，确保任何来源的消息都不会漏发；同时在各定时 job 顶部提前 `return` 做性能优化（假期不浪费爬取/渲染资源）。
  - **覆盖全部真实出口**：经排查，天气/电量/自定义推送「立即发送」均为直接 `adapter.send()`，**不经过 `delivery_service` 队列**；课程定时与每日推送经 `delivery_service` 队列。故在 4 个出口分别落闸：`delivery_service._process_pending_tasks`、`push_routes._send_push`/`send_push_now`、天气 `tasks._send_markdown`、电量 `tasks._send_markdown`/`_send_image`。
  - **安全告警绝不静音**：`system` 安全告警适配器（IP 黑名单等）不在静音范围内，账号安全事件照常推送。
  - **fail-open 原则**：`holiday_service.is_active()` 自身异常时回退「不静音」，避免配置异常导致永久失声。
  - **总开关保守默认**：`system.holiday_mode_enabled` 默认 `false`，关闭时假期区间完全不生效。
  - **保留运维状态告警**：电量 `_send_markdown(notify_only=True)` 管理员运维状态告警不受假期静音影响。
- **数据模型**：新增 `holiday_periods` 表（`app/model/holiday_period.py`），字段 `name` / `holiday_type`（winter/summer/custom）/ `start_date` / `end_date`（DATE 闭区间，复用 `course_weeks` 范式 `start_date <= today <= end_date`）/ `enabled` / `note`；`init_database()` 自动建表。
- **后端实现**：
  - 新增 `app/services/holiday_service.py` 单例 `holiday_service`：`is_active()` 返回 `(是否静音, 命中期)`；`get_status()` 供前端横幅；`list/create/update/delete_period`、`set_enabled`、`set_master`（写 `module_configs`）。
  - 新增蓝图 `app/api/holiday_routes.py`（`/api/holiday`，全部 `@admin_required`）：`GET /status`、`PUT /master`、`GET/POST/PUT/DELETE /periods`。
  - `app/modules/electricity/tasks.py`、`app/modules/weather/tasks.py`、`app/tasks/scheduler.py`（含 `check_push_rules`/`generate_weekly_course`/`run_spider`）、`app/services/delivery_service.py`、`app/api/push_routes.py` 增加假期闸口。
  - **闸口分层（入口早退 + 发送点兜底）**：课程定时任务（`run_spider`/`check_push_rules`/`generate_weekly_course`）与天气、电量**面向用户的推送函数**均在函数**入口**提前 `return`——假期里被调度器调用即立刻返回，不拉取 API、不分析、不渲染（与「各定时 job 顶部提前 return」设计原则一致）。具体落点：天气 `push_weather_daily`/`push_weather_analysis`；电量 `push_electricity_daily`/`push_electricity_weekly`/`push_electricity_monthly`/`push_electricity_full_crawl`/`check_low_power`。发送点闸口（`weather/electricity._send_markdown`/`_send_image`、`delivery_service._process_pending_tasks`、`push_routes._send_push`）保留为最终兜底（防其他路径漏网）。**数据更新类 job 也静默**：天气 `update_weather_now`/`update_weather_hourly`/`update_weather_alert` 在假期里同样入口早退（不拉取/不持久化），避免误标 `completed`；因高频（10/30/60 分钟）故走 `skip_if_active(record=False)` 按天聚合为 1 条 skipped 汇总记录（见下方「调整」），既保留历史又防止刷屏进程表。电量 `check_cookie_validity`（Cookie 有效性系统运维检测）仍**不拦截**，保持假期照常运行（属系统运维检测，非面向用户推送）。
  - 推送任务新增 `skipped` 状态：假期静默的**面向用户推送**在入口调用 `holiday_service.skip_if_active(name, task_type)` 建 `skipped` 进程记录（原因「假期模式静默（<假期名>）」），进程管理可见、区别于 `completed`/`failed`；高频数据更新 job 静默早退，按天聚合为 1 条 skipped 汇总记录（见下方「调整」）。统一助手方法 `skip_if_active` 定义在 `holiday_service.py`（fail-open：建记录失败仍静音）。
- **前端实现**：
  - 新增 `src/api/holiday.ts`（`holidayApi`：status/master/list/create/update/remove）。
  - 新增 `src/pages/HolidayMode.tsx`：总开关 Switch + 实时状态横幅（未开启/静默中/非假期）+ 说明 Alert + 区间表格（名称/类型 Tag/起止/状态 Switch/备注/操作）+ 新增/编辑 Modal 表单。
  - `src/App.tsx` 增加 `/holiday` 路由，`src/layouts/AdminLayout.tsx` 侧边栏增加「假期模式」入口（仿 Webhooks 范式）。
- **验证**：后端导入校验通过；前端 `npm run build`（tsc 无类型错误）通过；`init_db` 自动建表 + 播种 `holiday_mode_enabled`。
- **单元测试**：新增 `Push_System_Flask/tests/test_holiday_mute.py`（共 35 用例，全部通过），覆盖 `is_active()` 决策单元（总开关关闭/开启命中/开启无命中/区间禁用/配置异常 fail-open）、`skip_if_active()` 统一助手（不活跃不记录、活跃 record=True 建 skipped 记录且 reason 含假期名、活跃 record=False 不建记录、is_active 异常 fail-open 回退静音、建记录异常仍静音），以及 10 个定时 job 入口闸口契约（运行时：假期激活时早退不调用 `create_task_process`；结构：闸口为首个 if；并断言 `check_cookie_validity` 刻意不静音）。隔离方案：SQLite 内存库（StaticPool 保活连接）+ 桩 `get_config_service`/`holiday_service.get_db`；注意 `holiday_service` 在模块顶层 `from app.core.database import get_db`，patch 须打在 `app.services.holiday_service.get_db` 而非 `app.core.database.get_db`，否则会落到真实 MySQL。

### 周课表教学周修复（并入本期，原拟 v6.13.2）
- **问题**（提交 `22c2a7d`）：`generate_weekly_course` 每周一 00:00 直接 `run_spider` + `_send_weekly_image` 发图，绕过 `rule_service` 推送规则引擎，且无「无课」判断，导致暑假仍发整周课表长图。
- **修复**：新增 `_is_in_teaching_week()` 基于 `course_weeks.start_date~end_date` 真实日期范围判断今天是否在教学周内；不在任何教学周内即视为「这一周没课」跳过推送。避免依赖易错的 `_calculate_date`（其在假期把 `week_number=1` 误算成本周日期）；异常时回退 True（继续推送），避免 `course_weeks` 数据缺失时静默漏推。与每日推送「无课不推」语义对齐。

### 调整（并入本期，未单独升版）
- **停用进程记录自动清理（保留历史）**：`app/tasks/scheduler.py` 中每日 02:00 的 `clean_old_processes` 定时任务不再注册。用户 2026-07-20 决定保留历史进程记录、不做自动清理；`clean_old_processes` 函数体保留（此前 `datetime` 导入 bug 已修正，仅不再被定时触发），必要时可手动调用。
- **课程爬虫联动假期/教学周（自动停爬）**：此前每日课表爬虫 `run_spider`（7:00/13:00 各一次）只被假期模式总开关拦截，默认（总开关关）会在暑假照常爬取学校教务系统、空耗资源。`run_spider` 在假期闸口之后新增 `_is_in_teaching_week()` 判断——**不在任何教学周（暑假/寒假/任意假期）即跳过爬取**，与周课表推送同源逻辑，无需手动开假期模式即可自动停爬；异常时 fail-open 回退「继续爬」。同时把 `generate_weekly_course` 的 teaching-week 判断提前到 `run_spider()` 调用之前，避免假期里爬到空数据后被误判为「爬虫执行失败」发告警。新增 `tests/test_course_spider_skip.py`（4 用例）覆盖：不在教学周跳过、假期模式开启跳过、在教学周且未放假则真正爬取、周课表路径不在教学周时不调 run_spider。
- **课程推送联动假期/教学周（自动停推）**：`check_push_rules`（每日课表推送规则引擎，含 daily_schedule / weekly_schedule / daily_no_class 等）此前同样只被假期模式总开关拦截，默认（总开关关）暑假仍照常跑规则、推送「无课」类消息。在假期闸口之后新增 `_is_in_teaching_week()` 判断——**不在教学周即跳过规则检查、不创建推送任务**，与课程爬虫同源同规则（是假期/不在教学周就跳过）。异常 fail-open 回退「继续检查」。新增 `tests/test_course_push_skip.py`（3 用例）覆盖：不在教学周跳过、假期模式开启跳过、在教学周且未放假则正常调用规则引擎。至此课程「爬 + 推」在假期均自动停，无需手动开假期模式。
- **前端「已静音」状态可见 + 假期生效横幅**：`src/constants/statusMaps.ts` 的 `PROCESS_STATUS_MAP` 与 `TASK_STATUS_MAP` 补充 `skipped` 映射（`{ color:'default', icon:StopOutlined, text:'已静音' }`），修复此前假期静默的 skipped 进程记录在前端无文案/颜色（显示为空白或未知状态）的问题。`src/pages/Processes.tsx` 与 `src/pages/Dashboard.tsx` 顶部接入 `holidayApi.getStatus()`，假期模式生效时渲染 Alert 横幅「假期模式生效中（<假期名>）·推送已静音」，让静默不再只能从日志看出。
- **高频静默每日汇总记录（历史可见且不刷屏）**：天气 `update_weather_now`/`update_weather_hourly`/`update_weather_alert` 等高频 job 走 `skip_if_active(record=False)`，此前假期里完全不建进程记录、前端无痕。现改为按「天 + task_type」聚合为 1 条 `skipped` 汇总进程记录（名称「假期高频静默汇总」，message 含累计次数，如「假期模式静默（2026年暑假）·天气高频任务已静音 3 次」），跨天自动新建；既保留历史可见性，又避免每 10/30/60 分钟刷一条记录撑爆进程表。对应 `app/core/task_state.py` 新增 `TaskStatus.SKIPPED='skipped'` 并纳入 `TERMINAL_STATUSES`；`holiday_service.skip_if_active` 新增 `_record_daily_summary()` 聚合逻辑。新增单测 4 例（`test_holiday_mute.py` 的 `TestHolidayDailySummary`）：同日同类型累加、不同类型各自独立、record=True 不写汇总、跨天新建，单测总数 31→35。

- **手动触发接口假期前置拦截（与定时任务同源）**：此前假期/非教学周拦截只作用于定时调度（`run_spider`/`check_push_rules`），手动点「立即执行」仍会起线程跑一个立刻跳过的任务——前端只回「任务已触发」造成误导，且增加无意义请求（间接放大进程列表高频轮询触发的 429 限流）。现对三个手动触发接口补假期前置拦截，与 `run_spider` 同源双条件（`holiday_service.is_active()` 静默 OR `_is_in_teaching_week()` 非教学周）：
  - `trigger_weather_task`（`/admin/weather/trigger`）：触发前查假期静默，命中即返回 `api_success(message='假期模式静默（<假期名>），<任务>已跳过', skipped=True)`，不起线程。
  - `trigger_electricity_task`（`/admin/electricity/trigger`）：仅对面向用户的推送任务（`push_electricity_daily/weekly/monthly`、`check_low_power`）拦截；`check_cookie_validity`/`fetch_electricity_data` 属系统运维/采集，假期不静默、保持可触发。
  - `trigger_spider`（`/admin/tasks/spider/trigger`）：双条件拦截（假期静默 OR 非教学周），命中即返回 `skipped=True`；运行前仍先判 `running` 返回 409。
  - 全部拦截统一返回 `skipped=True` 标记（经 `api_success(**extra)` 透传），供前端区分「跳过」与「成功」。fail-open：拦截判断自身异常时不当误拦截，照常触发。
- **前端假期模式禁用「立即执行」按钮 + 统一 skipped 反馈**：天气/电量/课程/任务/仪表盘各页接入 `holidayApi.getStatus()`，假期 `active` 时：
  - 天气页「更新天气数据」、课程页「同步课表/全量爬取」、任务页 spider 类 + 天气类 + 电量推送类（fetch_all/check_cookie_validity/课程手动推送不禁用，因后端假期不拦截、应保持可用）、仪表盘四个快捷操作（更新天气/天气晨报/电量日报/课表爬虫）全部置灰禁用，从源头杜绝假期静默期的无意义触发。
  - 各处触发函数对 `res.skipped` 显示 `message.warning(<原因>)` 且不开「已完成」轮询，作为假期状态未加载完成时的兜底防护。

### 课程管理假期视图（联动假期模式）
- **问题**：课程管理页表头日期由前端写死学期开学日（3/2）推算；后端 `get_current_week_number()` 在暑假（7/19 之后）写死返回最后一周=20，导致页面冻结在最后教学周（7/13–7/19），表头显示 13 号而非今天，且无假期提示。
- **修复/优化**：
  - 表头日期改用后端 `available_weeks`（course_weeks 真实日期区间）的 `start_date` 推算，与后端完全一致，任意周次日期均正确。
  - **优先联动管理员配置的假期模式**（权威来源，`GET /api/holiday/status`）：假期模式生效（总开关开 + 命中 enabled 区间覆盖今天）时，课程页直接接管为假期视图，展示管理员填写的假期名称/类型/起止区间；界限清楚、数据可靠。
  - **回退逻辑**：未配置假期模式（或假期模式未生效）时，由课程页依 `available_weeks` 日期区间自行判定「今天是否在任一教学周内」，不在即视为非教学周，兼容真实校历（7/20 若在某教学周范围内则正常显示该周，不会误判假期）。
  - **后端根因修复**：`app/api/course_routes.py:get_current_week_number()` 原在暑假/寒假**写死返回 week_number=20**，导致前端页面冻结在第 20 周（表头显示 07-13 而非今天 07-20），且「(本周)」「今天」标记全部错位。现改为按开学日动态推算真实周次（暑假自然算出第 21 周及以后），由前端 `inBreak` / 假期模式联动接管假期展示。
  - **按「选中周」判定而非「今天」**：假期视图接管条件原以「今天是否在假期区间」为准，导致全局接管、用周次选择器切历史教学周也被假期卡片顶掉。现改为以「选中的周（`selectedWeek`，默认当前周）对应的日期区间是否与假期区间重叠」为准——选中的周落在假期区间内显示假期提示，选中的周为历史教学周（非假期区间）则正常显示课表，周次选择器可自由切换。判定优先用后端 `available_weeks` 真实日期区间，超出教学周范围时用开学日推算兜底。

---

## v6.13.1 (2026-07-20)

> 发版类型：**缺陷修复（patch）**。修复数据库初始化工具与生产启动期因元数据锁（MDL）导致的卡死/报错，并加 Redis 分布式锁防多 worker 并发 ALTER。

### 数据库初始化工具与生产启动稳定性修复（init_db.py / app/__init__.py）
- **问题**：生产机 `python3 init_db.py status` 在逐表 `SELECT COUNT(*)` 处无限挂起（Ctrl+C 才退出）；`create_app` 启动期指纹自动迁移/清理在 `ALTER TABLE users` 处永久卡死，gunicorn 无法就绪。根因为 MySQL `lock_wait_timeout` 默认约 1 年，遇 MDL 锁等待即无限挂起；且指纹检查位于 `create_app` 内、每个 worker 启动都跑，多 worker 并发 ALTER 同一表加剧锁竞争。
- **修复**：
  - `init_db.py`：`cmd_status` 逐表 `COUNT` 与列检查改用函数内独立连接并设 `lock_wait_timeout=3 + innodb_lock_wait_timeout=3`，超时即跳过（不再无限挂起）；`cmd_migrate`/`cmd_cleanup`/`_fix_nullability` 共 7 处 DDL 连接同样加 3 秒锁超时。
  - `app/__init__.py`：启动期指纹自动迁移/清理外包 Redis 分布式锁（`SET key token NX EX 600`，Lua 仅释放自己持有的锁；Redis 不可用时降级本地执行），确保仅单进程执行，杜绝多 worker 并发 ALTER。
- **验证**：生产机 `git pull` 后 `systemctl restart gunicorn` 正常就绪（监听 29528、4 workers），日志显示指纹「实例与定义一致，跳过迁移」；`init_db.py status` 完整输出无 Traceback；`[Redis] 已连接` 限流探活成功。
- **版本**：按约定 bump patch（6.13.0→6.13.1），四处版本号（config.py / version.ts / package.json / .env）与两份 README 徽标已同步。

---

## v6.13.0 (2026-07-19)

> 发版类型：**新功能（minor）**。新增「境外 IP 拦截」防火墙：仅允许中国 IP 访问，其余请求在请求最前端直接 403 断开。

### 境外 IP 拦截（防火墙）
- **需求**：作为纵深防御，仅放行国内 IP，阻断海外扫描/爆破流量。用户明确要求「只对国外 IP 进行拦截、直接断开连接」，本期收窄为仅国家级（不做省份级，避免误伤移动/外省用户）。
- **实现**：
  - 新增 `app/services/geo_service.py`：基于本地 ip2region 离线库（`ip2region_v4.xdb`，官方 Python 绑定已 vendoring 进仓库 `Push_System_Flask/ip2region/`，含 LICENSE）判断 IP 所属国家。整库载入内存（线程安全、零外部网络依赖）；私有/本地地址直接放行；IPv6 与未识别地址按「境外」fail-closed 处理；数据库缺失或加载失败时降级为放行，避免误杀全站；IP→国家结果带内存缓存。
  - `app/utils/security.py`：在 `security_before_request` 的 `/health`、`/static/` 跳过之后、登录白名单跳过之前插入 `_check_foreign_ip`，连 `/api/auth/login` 一并拦截；命中条件为「开关开启 且 非例外 IP 且 非中国 IP」，返回 403。
  - `app/core/config.py`：新增 `ENABLE_FOREIGN_IP_BLOCK`（默认 `true`）与 `REGION_BLOCK_EXCEPTIONS`（逗号分隔的例外 IP/CIDR，作管理员白名单防自锁）。
- **数据来源说明**：PyPI 上无 `ip2region` 包、且本机 pip 无法连接 PyPI，因此将官方 Python 绑定源码 vendoring 进仓库（非 pip 依赖）；离线库 `ip2region.xdb`（约 11MB）一并纳入版本控制，置于 `Push_System_Flask/` 根目录（避开被 `.gitignore` 的 `data/` 目录，且 git 不允许在已忽略目录内用 `!` 重新包含文件）。
- **验证**：`geo_service` 国家判断经多组 IP 抽样核对（国内地址/私有地址放行，海外地址拦截）；`py_compile` 通过。
- **版本**：按约定 bump minor（6.12.3→6.13.0），四处版本号（config.py / version.ts / package.json / .env）与两份 README 徽标已同步。

---

## v6.12.3 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。天气管理「预警历史」改为后端分页 + 前端「加载更多」折叠，与个人设置页登录日志保持一致，避免长列表一次性渲染。

### 天气预警历史分页折叠（weather_routes.py / weather.ts / Weather.tsx）
- **问题**：天气管理「预警历史」此前一次性返回全部已失效预警并完整渲染，历史较多时列表冗长、无折叠。用户希望与「个人设置 → 登录日志」一致的「加载更多（已显示 XX / XX）」折叠交互。
- **后端**：`/weather/alert/history` 由固定 `.limit(50)` 改为支持 `page` / `page_size`（最大 100）分页，返回结构与登录日志一致：`api_success(data=[...], pagination={'page','page_size','total','total_pages'})`。不再有 50 条硬上限。
- **前端**：
  - `weather.ts` 的 `getAlertHistory(page, page_size)` 透传分页参数，并采用与登录日志相同的 `ApiResponse<T> & { pagination }` 交叉类型，确保 `res.pagination.total` 类型正确。
  - `Weather.tsx` 新增 `alertHistoryPage` / `alertHistoryTotal` / `alertHistoryLoading` 状态；`fetchAlertHistory(page)` 在 `page>1` 时累积追加、`page===1` 时替换；渲染区在列表下方增加「加载更多（已显示 XX / XX）」按钮（仅在 `alertHistoryTotal > alertHistory.length` 时显示），首次加载用 Spin 占位。
- **验证**：`npm run build` 通过（tsc + vite build，exit 0）。
- **版本**：按约定 bump patch（6.12.2→6.12.3），四处版本号（config.py / version.ts / package.json / .env）与两份 README 徽标已同步。

---

## v6.12.2 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。补充审计请求日志静默名单遗漏的常驻轮询端点。

### 审计请求日志静默名单补充（app/utils/security.py）
- **问题**：运行期频繁打印 `AUDIT_REQUEST ... PATH=/api/admin/processes/scheduled`。v6.11.6 的 `SILENT_AUDIT_PATHS` 已收录 `/api/admin/processes`、`/api/admin/processes/running`，但漏了同为 Processes 页常驻轮询（POLL_NORMAL=5s）的 `/api/admin/processes/scheduled`（固定列表端点，非带 `{id}` 的临时轮询）。
- **修复**：`security.py` 的 `SILENT_AUDIT_PATHS` 新增 `/api/admin/processes/scheduled`；匹配为精确 `path not in SILENT_AUDIT_PATHS`。`log_request_audit` 仅抑制该 INFO 行，登录日志与登录事件等审计证据不受影响。
- **验证**：`py_compile` 通过；当前静默名单共 15 个路径（精确匹配，不含带 `{id}` 的动态路径）。
- **版本**：纯日志治理，按约定 bump patch（6.12.1→6.12.2），四处版本号（config.py / version.ts / package.json / .env）与两份 README 徽标已同步。

---

## v6.12.1 (2026-07-19)

> 发版类型：**缺陷修复（patch）**。修复数据库指纹自动清理无法修正"可空性变更（NULL↔NOT NULL）"的问题，消除 users 表 is_active/is_primary 由 NULL 改为 NOT NULL 后需手动 cleanup 的兜底告警。

### 数据库指纹：可空性变更拆分与自动修正（app/core/db_fingerprint.py / init_db.py / tests/test_db_fingerprint.py）
- **问题**：`user.py` 将 `is_active`/`is_primary` 由 `nullable=True` 改为 `nullable=False` 后，实例库仍是旧的 NULL 状态。指纹描述符为 `类型|null|pk` 拼串，`bool|null=1`→`bool|null=0` 仅可空性变化，却被 `diff_fingerprints` 整串不等判为 `type_changed`，`summarize_diff` 误报"类型变更"。而 `cmd_cleanup` 的 `_filter_actionable_type_changes` 对 `bool↔bool` 直接跳过，清理逻辑也缺少改可空性的 ALTER，于是自动迁移+自动清理都修不掉，最终兜底提示手动 `python init_db.py cleanup`。
- **修复**：
  1. `db_fingerprint.py`：`diff_fingerprints` 将变更拆为 `type_changed`（逻辑类型族真不同）与 `null_changed`（类型相同、仅可空性不同），两者均计入 `match`；`summarize_diff` 单独输出"可空性变更"，不再误报"类型变更"。
  2. `init_db.py` `cmd_cleanup`：新增 `null_changed` 展示与执行阶段，自动 `ALTER MODIFY` 修正 NULL/NOT NULL。配套辅助函数——`_fix_nullability`：要改为 NOT NULL 且表内已有 NULL 行时，先用模型标量默认值填充（如 `Boolean default=True`→`1`）再 ALTER，避免失败/丢数据；无可用默认则跳过并告警；`_null_fill_value` 将 `True/False` 归一为 `1/0` 适配 MySQL `TINYINT`。启动流程已自动调用 `cmd_cleanup(auto=True)`，现可自动修掉，不再喊手动。
  3. `cmd_fingerprint` 详情展示新增可空性变更小节。
  4. 新增 `tests/test_db_fingerprint.py`：5 例覆盖变更归属拆分、`summarize_diff` 文案、NULL 行默认值填充。
- **验证**：`pytest tests/` 38/38 绿色无回归；`py_compile` 通过。

### 启动顺序优化：指纹检查前移紧贴建库时机（app/__init__.py）
- **问题**：指纹比对原本排在 `init_services`（课表/规则/模板/适配器加载等）之后，服务初始化的耗时（数秒）把指纹日志推到启动流程末尾，漂移告警来得太晚，用户期望它紧贴"数据库已存在"的建库时机。
- **修复**：将 `create_app` 中"僵尸清理 → `init_default_configs` → 默认管理员创建/检查 → 指纹比对+自动修复"整段前移至 `init_services` 之前；服务初始化改为在指纹段之后执行。指纹依赖配置键结构与管理员存在性，故必须排在这两项写入之后，但两步骤本身毫秒级，不再被服务初始化阻塞。
- **附带收益**：服务初始化在 schema 已对齐、默认配置与管理员已就绪的前提下运行，启动前提更充分。
- **验证**：`python -c "import run"`（触发 `create_app` 完整初始化、不进入 `app.run` 常驻）实测——指纹日志由原先滞后约 6 秒提前至紧贴管理员检查之后、服务初始化之前；`py_compile` 通过。

- **版本**：本次为缺陷修复，按约定 bump patch（6.12.0→6.12.1），四处版本号（config.py / version.ts / package.json / .env）已同步。

---

## v6.12.0 (2026-07-19)

> 发版类型：**新功能（minor）**。数据库指纹漂移检测（定义码 vs 实例码）。

### 数据库指纹漂移检测（app/core/db_fingerprint.py / init_db.py / app/__init__.py / admin_routes.py）
- **动机**：数据库初始化定义（模型 schema + 种子配置键 + 默认管理员）随代码更新而变化，缺乏快速判断"实例是否跟上定义"的手段。
- **实现**：
  - **定义码**：`compute_definition_fingerprint()` 纯代码推导，哈希 SQLAlchemy 全部 20 张表的列/类型/nullable/主键 + `DEFAULT_CONFIGS` 37 个配置项的 (module,key,value_type,is_editable,is_sensitive) 结构 + 默认管理员存在性标志。无需数据库连接。
  - **实例码**：`compute_instance_fingerprint(session)` 读取 `INFORMATION_SCHEMA` 实际表/列 + `module_configs` 实际配置键 + 判断 `username='admin'` 是否存在。
  - **比对**：`diff_fingerprints` 输出结构化差异（缺失/多余表、列、类型变更、配置键增减、管理员状态）；`check_db_fingerprint` 高层入口返回 `{definition_hash, instance_hash, match, ...diff}`。
- **设计原则（避免误报）**：
  - 仅哈希结构与键名，**不哈希配置值**——管理员自定义 `class_name`/`spider_interval_hours` 等不会触发漂移告警。
  - 类型归一化：整数族 (`int(11)`/`INTEGER`/`BIGINT`) 统一为 `int`，消除 SQLAlchemy 模型定义与 MySQL INFORMATION_SCHEMA 之间的格式差异。
  - 模型导入复用 `_import_all_models` 显式清单（20 表），确保 `from app import model` 未覆盖的电量/天气等子模块也被纳入。
- **交付三面**：
  1. **CLI**：`python init_db.py fingerprint`（打印定义码+实例码+差异明细）、`check`（静默模式，一致 exit 0 否则 1，供 CI/脚本用）。
  2. **启动告警**：`create_app` 在种子数据写入后自动调用 `check_db_fingerprint`；一致打印 INFO，不一致打印 WARNING 并提示运行 `python init_db.py migrate`。
  3. **管理端接口**：`GET /api/admin/db/fingerprint`（需 admin JWT），返回两码与结构化 diff。
- **验证**：定义码运行期确认含 20 表/37 配置键/64 位 sha256；`py_compile` 4 文件全过；`pytest tests/` 33/33 绿色无回归。
- **启动优化**：`cmd_migrate` 新增 `quiet` 参数，应用启动时传 `quiet=True`——无迁移时跳过逐表 checklist 与"无需迁移"横幅，仅在有实际变更（补表/补列/补索引）或类型不兼容时打印。配合指纹比对（仅一行 INFO/WARNING），启动日志大幅精简。
- **启动流程改为指纹先行**：`create_app` 在种子数据写入后先跑 `check_db_fingerprint`；一致则跳过 `cmd_migrate`（省去 inspector 全部查询，仅一行 INFO）；不一致则自动 `cmd_migrate(quiet=True)` 修复 schema 漂移后重检。进一步压缩无漂移场景的启动时间。
- **指纹比对逻辑修正**：类型归一化放宽（`varchar(100)` 与 `varchar(255)` 均归一为 `varchar`），消除历史库长度微调引发的类型变更误报；match 采用严格模式——全部项（含多余表/列/配置键/类型变更）一致才算一致，不因"只是多出来"而放行。有差异用 `cleanup` 或 `migrate` 修到干净为止。
- **init_db.py cleanup 全貌清理**：基于指纹 diff 的全量差异，一键处理：多余表（`DROP TABLE`）、多余列（`DROP COLUMN`）、多余配置键（`DELETE`）、安全类型变更（同族 `varchar↔text`、`int↔int` 自动 `MODIFY COLUMN`）。跨类型差异（如 `varchar↔int`）标记需手动处理，避免丢数据。`_instance_schema` 改为查全部用户表以检测额外表。默认需确认，传 `--yes` 跳过。

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

### 审计请求日志静默名单扩充（security.py）
- **问题**：`log_request_audit` 的 `SILENT_AUDIT_PATHS` 已覆盖一批高频轮询列表接口，但后台仍频繁打印 `AUDIT_REQUEST` INFO。用户要求"整个项目扫一遍，轮询类非错误日志全部压下去"。
- **排查范围（2026-07-19）**：
  - 前端：遍历全部轮询 hook（`useIntervalPolling` / `useSessionHeartbeat` / `useRunningTasksPolling` / `useTaskPolling`）与轮询页（Course / Dashboard / Tasks / Processes / SessionManager / UserManagement / ServerStatusProvider），逐一映射其实际请求的 `/api/...` 路径。
  - 后端：确认唯一每请求日志来自 `security_before_request → log_request_audit`（`after_request` 仅加响应头、不写日志）；APScheduler 定时任务的 `logger.info` 均为**启动时注册一次**，真正的任务执行日志（爬虫跑完、推送发出等）属有用运维记录予以保留。
- **修复**：将全部"常驻轮询"端点加入 `SILENT_AUDIT_PATHS`，最终覆盖：`/api/auth/session/status`、`/api/auth/me`、`/api/auth/mfa/status`、`/api/auth/sessions`、`/api/admin/user/users`、`/api/admin/user/profile`、`/api/admin/user/login-logs`、`/api/admin/processes`、`/api/admin/processes/running`、`/api/course/crawl-tasks`、`/api/course/semesters`、`/api/admin/tasks/spider/status`、`/api/ping`、`/api/admin/dashboard`。
- **说明**：按任务 ID 的临时轮询（`/api/admin/processes/{id}`、`/api/course/crawl-tasks/{id}`）命中终态即停、非常驻噪音，且路径动态无法精确名单匹配，故未纳入；按页面导航触发的一次性读取（如课表/规则/调度列表）非轮询、未纳入。仅抑制该 INFO 日志行；登录日志与登录事件记录不受影响，审计链路不丢关键证据。

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
