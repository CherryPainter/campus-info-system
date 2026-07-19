# 寒暑假「假期模式」草案（前后端）

> 状态：草案，待评审
> 目标版本：v6.14.0（新功能，升 minor；注意 v6.13.2 周课表修复建议先发或合并）

## 1. 目标与范围

- 进入寒假 / 暑假后，系统**自动全体静默**：不再向用户推送课表、提醒、天气、电量等任何消息。
- 管理员无需记忆"暑假别发图"，只需在每学期初维护好假期区间，系统到点自动静音、到点自动恢复。
- 配置**即时生效**，不重启、不改代码。

### 范围边界（重要）

| 类别 | 假期模式是否影响 |
| --- | --- |
| 面向用户的推送（课表每日/每周、上课提醒、无课提醒、天气、电量、自定义推送） | 静默 |
| 面向管理员的系统告警（爬虫失败 Webhook、推送失败 Webhook、状态通知） | **不静默**（系统健康仍要可见） |
| 爬虫定时任务（run_spider） | 建议同步跳过（省资源，假期无课无需同步） |
| 数据库清理 / Session 清理等运维任务 | 不静默（照常） |

## 2. 设计原则

1. **单点收口 + 双层防护**：真正的"不出消息"由 `delivery_service` 兜底保证；各 job 再提前跳过，避免无谓生成任务、污染队列与日志。
2. **保守默认（fail-safe）**：总开关 `holiday_mode_enabled` 默认 `false`。开关关时，假期区间完全不生效——即使库里有区间也不会静音，避免误配导致永久失声。
3. **区间驱动**：用 `start_date ~ end_date` 真实日期区间判断，不依赖 week_number 推算（此前 `_calculate_date` 在假期会把第 1 周误算成本周，这正是暑假误发长图的根因）。
4. **即时生效**：每次发送 / 生成前实时查库，改完区间立刻生效。

## 3. 数据模型

### 3.1 总开关（复用现有配置体系，零新建表）

在 `module_configs` 表（`app/model/module_config.py` 的 `DEFAULT_CONFIGS`）加一项：

```python
{'module': 'system', 'key': 'holiday_mode_enabled',
 'value_type': 'boolean', 'value': 'false',
 'comment': '假期模式总开关：开启后落在区间内的日期全体静默'}
```

### 3.2 假期区间表（新建）

```sql
CREATE TABLE holiday_periods (
  id          INT PRIMARY KEY AUTO_INCREMENT,
  name        VARCHAR(100) NOT NULL COMMENT '如 2026年暑假',
  holiday_type VARCHAR(20) NOT NULL DEFAULT 'custom'
              COMMENT 'winter=寒假, summer=暑假, custom=自定义',
  start_date  DATE NOT NULL,
  end_date    DATE NOT NULL,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  note        VARCHAR(255) NULL,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) COMMENT='假期静默区间';
```

- 区间范式复用 `course_weeks` 的 `start_date/end_date`（闭区间，`start_date <= today <= end_date` 即命中）。
- 一个学期通常 2 条（寒假 + 暑假），也允许 `custom` 临时区间（如法定节假日、考试周静默）。

## 4. 后端实现

### 4.1 新增 `app/services/holiday_service.py`

```python
class HolidayService:
    def is_active(self) -> tuple[bool, Optional[HolidayPeriod]]:
        """总开关开 且 今天命中某 enabled 区间 → (True, period)，否则 (False, None)"""
        if not config_svc.get('system', 'holiday_mode_enabled', False):
            return False, None
        today = date.today()
        p = session.query(HolidayPeriod).filter(
            HolidayPeriod.enabled.is_(True),
            HolidayPeriod.start_date <= today,
            HolidayPeriod.end_date >= today,
        ).first()
        return (p is not None, p)

    def get_status(self) -> dict:
        active, p = self.is_active()
        return {
            'enabled': config_svc.get('system', 'holiday_mode_enabled', False),
            'active': active,
            'period': p.to_dict() if p else None,
            'now': date.today().isoformat(),
        }

    def list_periods(self) / create_period(...) / update_period(...) / delete_period(...) / set_enabled(...)
```

异常时回退 `is_active() -> (False, None)`（不静音），避免配置读取异常导致永久失声。

### 4.2 静默收口（双层防护）

**第一层 · 兜底闸口（必须）** —— `app/services/delivery_service.py` 的 `_process_pending_tasks()`：

```python
for task in pending:
    active, period = holiday_service.is_active()
    if active:
        reason = f"假期模式静默（{period.name} {period.start_date}~{period.end_date}）"
        task_service.update_status(task['task_id'], 'skipped', {'reason': reason})
        self._update_push_process(process_id, 'skipped', message=reason)
        continue   # 直接丢弃，不进入 adapter.send
    # …原有发送逻辑…
```

这是**唯一保证不出消息的硬闸口**：无论任务从哪来（定时 / 手动 / 自定义），只要走到发送这一步就拦截。

**第二层 · 各 job 提前跳过（推荐，省资源 + 日志清晰）**：

- `generate_weekly_course()`：开头 `if holiday_service.is_active()[0]: logger.info('假期模式，跳过周课表'); return`
  （原有的 `_is_in_teaching_week()` 保留作为数据缺失兜底，二者并列判断）
- `check_push_rules()`：开头判定，命中则不创建 daily / 提醒类任务。
- `app/modules/weather/tasks.py`、`app/modules/electricity/tasks.py` 注册任务处：命中则跳过本轮生成（天气/电量非课表强相关，假期可停）。
- `run_spider()`：命中则 `logger.info('假期模式，跳过爬虫'); return False`（假期无课无需同步；恢复后首次爬取自然补齐）。

> 第二层是"优化"，即使不写也不影响静音正确性——第一层兜底即可。建议一次性补齐，避免队列堆积。

### 4.3 API（新增 `app/api/holiday_routes.py`，全部 `@admin_required`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/holiday/status` | 返回 `enabled / active / period / now`，供前端横幅 |
| PUT | `/api/holiday/master` | 切换总开关（写入 `module_configs`） |
| GET | `/api/holiday/periods` | 列表 |
| POST | `/api/holiday/periods` | 新建区间 |
| PUT | `/api/holiday/periods/<id>` | 修改区间 |
| DELETE | `/api/holiday/periods/<id>` | 删除区间 |

### 4.4 `init_db.py` 改动

- 新增 `holiday_periods` 表建表（复用现有 `_add_column`/`CREATE TABLE IF NOT EXISTS` 范式）。
- 确保 `module_configs` 存在 `system.holiday_mode_enabled` 默认行（DEFAULT_CONFIGS 已含则自动初始化）。

### 4.5 静默任务的状态

推送任务表 `push_task_queue` 新增 `skipped` 状态语义（原已有 `pending/processing/success/retrying/failed`）。假期静默的任务标记 `skipped`，前端任务页可筛选查看，区别于失败。

## 5. 前端实现

### 5.1 新增页面 `src/pages/HolidayMode.tsx`

复用现有 `Blacklist.tsx` / `Webhooks.tsx` 的"独立配置页 + 侧边栏入口"范式。

布局：

1. **状态横幅**（顶部）
   - 总开关 `Switch`：假期模式总开关。
   - 实时状态：`未开启` / `已开启 · 当前非假期` / `静默中：2026年暑假 07-15 ~ 08-31`（红色 Alert）。
   - 数据来自 `GET /api/holiday/status`，轮询或切页刷新。

2. **假期区间表格**（`ResponsiveTable`）
   | 名称 | 类型(Tag) | 开始 | 结束 | 启用(Switch) | 操作 |
   | --- | --- | --- | --- | --- | --- |
   | 2026年暑假 | 暑假(蓝) | 2026-07-15 | 2026-08-31 | ✓ | 编辑 / 删除 |

   类型 Tag：`winter=寒假`(冷色)、`summer=暑假`(暖色)、`custom=自定义`(灰)。

3. **新增 / 编辑弹窗**（`Modal` + `Form`）
   - 名称（Input）
   - 类型（Select：寒假/暑假/自定义）
   - 日期区间（`RangePicker`，返回 `[start_date, end_date]`）
   - 启用（Switch，默认开）
   - 备注（Input，可选）

4. **提示文案**："假期区间内所有面向用户的推送将自动静默，系统告警不受影响；修改即时生效。"

### 5.2 路由与侧边栏

- `App.tsx` 增加路由 `/holiday` → `HolidayMode`。
- `AdminLayout.tsx` 侧边栏新增「假期模式」菜单项（图标建议 `CalendarOutlined` 或 `StopOutlined`）。
- 首页 `Dashboard` 可加一个小状态卡（可选，显示当前是否静默中）。

### 5.3 API 封装 `src/api/holiday.ts`

对应 6 个接口，返回类型与 `api/admin.ts` 保持一致（`{ status, data, message }`）。

## 6. 版本与上线

- 版本：v6.14.0（新功能升 minor）。四处版本号同步（`config.py` / `version.ts` / `package.json` / `.env`）+ README 徽标 + CHANGELOG。
- 上线步骤：
  1. 合入后端 + 前端，前端 `npm run build` 重新部署 `dist`。
  2. 生产 `git pull` + 重启 `push-system.service`（`init_db` 自动建表）。
  3. 管理员在「假期模式」页填入本年寒暑假区间、开启总开关。
  4. 验证：把某区间临时设成"今天"观察次日 00:00 是否仍静默、队列是否出现 `skipped`。

## 7. 待确认决策点

1. **自定义推送（管理员手动发的通知）是否一并静默？**
   - 方案 A（推荐，最贴合"全体静默"）：假期区间内**连手动自定义推送也静默**；紧急情况管理员临时关总开关即可，开学前把结束日设在开学前 1 天本就自然恢复。
   - 方案 B：手动自定义推送**豁免**静默（仅自动推送静音），自定义推送页加"强制发送（忽略假期）"勾选项。适合"假期也要发开学通知"的场景。
   - 草案默认按方案 A 设计，但闸口处留一个 `force_send` 豁免位，将来要切 B 只需前端加勾选 + 后端读该字段。

2. **爬虫在假期是否跳过？** 草案建议跳过（省资源），如你希望假期也保持数据新鲜可保留爬取、仅静音发送。

3. **v6.13.2（周课表教学周修复，提交 22c2a7d）如何处理？** 先单独发 v6.13.2，还是合并进 v6.14.0 一起发？
