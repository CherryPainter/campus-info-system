# Task #13: 课程学期分类 - 完成总结

## 一、完成的工作

### 1. 后端API层（3个新端点）

**文件**: `Push_System_Flask/app/api/course_routes.py`

#### 1.1 获取学期列表
- **端点**: `GET /api/course/semesters`
- **功能**: 获取教务系统的学期列表，自动识别当前学期
- **返回**:
  ```json
  {
    "status": "success",
    "data": {
      "semesters": [
        {"id": "270", "name": "2024-2025-2"},
        {"id": "271", "name": "2025-2026-1"}
      ],
      "current_semester_id": "271",
      "current_semester_name": "2025-2026-1",
      "weeks": ["1", "2", ..., "18"]
    }
  }
  ```

#### 1.2 触发课表爬取
- **端点**: `POST /api/course/crawl`
- **功能**: 触发课表爬取，支持立即执行和预约执行
- **请求体**:
  ```json
  {
    "semester_id": "271",       // 学期ID（可选，默认当前学期）
    "week": 15,                    // 周次（可选，默认全部）
    "schedule_type": "immediate",  // 执行方式：immediate=立即, scheduled=预约
    "schedule_time": "2026-06-29 23:00:00"  // 预约时间
  }
  ```
- **返回**:
  ```json
  {
    "status": "success",
    "message": "爬取任务已创建",
    "data": {
      "task_id": 123,
      "schedule_type": "scheduled",
      "schedule_time": "2026-06-29 23:00:00"
    }
  }
  ```

#### 1.3 获取爬取任务状态
- **端点**: `GET /api/course/crawl/status/:task_id`
- **功能**: 获取爬取任务的执行状态
- **返回**:
  ```json
  {
    "status": "success",
    "data": {
      "task_id": 123,
      "task_name": "课表爬取（学期=271, 周次=全部）",
      "task_type": "course_spider",
      "status": "running",
      "total_items": 1,
      "processed_items": 0,
      "created_at": "2026-06-29T11:00:00",
      "started_at": "2026-06-29T11:00:10",
      "completed_at": null,
      "schedule_time": null,
      "error_message": null
    }
  }
  ```

---

### 2. 前端API层

**文件**: `admin-frontend/src/api/course.ts`

添加了3个新接口：
- `getSemesters()` - 获取学期列表
- `triggerCrawl(data)` - 触发爬取
- `getCrawlStatus(taskId)` - 获取任务状态

添加了类型定义：
- `SemesterInfo` - 学期信息接口

---

### 3. 前端界面层

#### 3.1 爬取调度弹窗组件

**文件**: `admin-frontend/src/pages/CrawlScheduler.tsx`

**功能**:
- ✅ 学期下拉选择（自动加载，标记当前学期）
- ✅ 周次选择（可选，支持选择指定周次或全学期）
- ✅ 执行方式选择（立即执行 / 预约执行）
- ✅ 预约时间选择（DatePicker，限制选择未来时间）
- ✅ 表单验证（学期必选，预约时间必填）
- ✅ 成功后提示（立即执行：提示任务已启动；预约执行：提示预约时间）

**使用方法**:
```tsx
import CrawlScheduler from '@/pages/CrawlScheduler';

<CrawlScheduler
  visible={crawlModalVisible}
  onClose={() => setCrawlModalVisible(false)}
  onSuccess={() => {
    message.success('爬取任务已启动，数据刷新中...');
    fetchTimetable(selectedWeek);
    fetchCourses(selectedWeek);
  }}
/>
```

#### 3.2 课程管理页面改造

**文件**: `admin-frontend/src/pages/Course.tsx`

**改造内容**:
- ✅ 导入 `CrawlScheduler` 组件
- ✅ 添加状态管理：`crawlModalVisible`（控制弹窗显示）
- ✅ 修改"同步课表"按钮：
  - 原：点击后立即触发爬取
  - 新：点击后打开 **爬取调度弹窗**，支持选择学期、周次、执行方式
- ✅ 在页面末尾添加 `CrawlScheduler` 组件

---

## 二、测试方法

### 1. 启动后端服务

```bash
cd D:\Tool\push_system\Push_System_Flask
python run.py
```

** expected output**:
```
* Running on all addresses (0.0.0.0:5000)
* Running on http://127.0.0.1:5000
* Running on http://[::1]:5000
```

---

### 2. 测试后端API（使用curl或Postman）

#### 2.1 测试获取学期列表

```bash
curl http://localhost:5000/api/course/semesters
```

**Expected response**:
```json
{
  "status": "success",
  "data": {
    "semesters": [
      {"id": "270", "name": "2024-2025-2"},
      {"id": "271", "name": "2025-2026-1"}
    ],
    "current_semester_id": "271",
    "current_semester_name": "2025-2026-1",
    "weeks": ["1", "2", ..., "18"]
  }
}
```

#### 2.2 测试触发爬取（立即执行）

```bash
curl -X POST http://localhost:5000/api/course/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "semester_id": "271",
    "schedule_type": "immediate"
  }'
```

**注意事项**:
- 这个测试会实际触发爬虫，可能需要较长时间（取决于网络和教务系统响应）
- 爬虫在后台线程中运行，不会阻塞API响应

#### 2.3 测试触发爬取（预约执行）

```bash
curl -X POST http://localhost:5000/api/course/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "semester_id": "271",
    "schedule_type": "scheduled",
    "schedule_time": "2026-06-29 23:00:00"
  }'
```

**Expected response**:
```json
{
  "status": "success",
  "message": "爬取任务已创建（scheduled）",
  "data": {
    "task_id": 123,
    "schedule_type": "scheduled",
    "schedule_time": "2026-06-29 23:00:00"
  }
}
```

---

### 3. 测试前端界面

#### 3.1 编译前端

```bash
cd D:\Tool\push_system\admin-frontend
npm run build
```

**Expected output**:
```
✓ 11825 modules transformed.
✓ built in 9.23s
```

#### 3.2 启动前端开发服务器

```bash
cd D:\Tool\push_system\admin-frontend
npm run dev
```

**Expected output**:
```
  VITE v8.0.14  ready in 500 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

#### 3.3 测试界面功能

1. 访问 `http://localhost:5173/`
2. 登录管理员账号
3. 进入"课程管理"页面
4. 点击"同步课表"按钮
5. **Expected result**: 弹出"课程表爬取调度"弹窗

**弹窗功能测试**:
- ✅ 学期下拉框：自动加载学期列表，标记当前学期
- ✅ 周次选择：可选择指定周次，或留空爬取全学期
- ✅ 执行方式：可选择"立即执行"或"预约执行"
- ✅ 预约时间：选择"预约执行"后显示，必填
- ✅ 立即执行：点击"立即执行"按钮，提示任务已启动
- ✅ 预约执行：点击"预约执行"按钮，提示预约成功

---

## 三、待完成的工作（交接重点）

### 1. 真机验证爬虫核心层

**文件**: `Push_System_Flask/app/cqie-course-timetable/main.py`

#### 1.1 验证学期切换功能

- **方法**: 运行 `python main.py --semester-id 270`
- **验证点**:
  - ✅ 是否能成功切换学期（POST `accessSemester!access.action`）
  - ✅ 切换后是否能正确爬取该学期的课表

#### 1.2 验证学期列表获取

- **方法**: 运行 `python main.py --semester-id 271`，检查输出的 `course_meta.json`
- **验证点**:
  - ✅ `course_meta.json` 中的 `semesters` 字段是否包含多个学期
  - ⚠️ **注意**: `dataQuery.action` 的真实返回格式未知，需根据实际返回调整 `_parse_semester_options` 函数

#### 1.3 实现本地按周筛选逻辑

- **当前状态**: `start_week` 参数只作为元信息记录，尚未真正实现按周过滤
- **需实现**:
  1. 解析课表单元格的 `[X]周` 标注（如 `课程名(代码)([18]周,教室)`）
  2. 根据指定的 `week` 参数过滤课程
  3. 参考 `app/api/course_routes.py` 的 `is_course_in_week()` 函数

---

### 2. 实现预约执行的调度器

**当前状态**: 预约执行的任务已创建（`status=scheduled`），但未实现自动调度

**需实现**:
1. 在 `app/tasks/scheduler.py` 中添加定时任务
2. 定时任务：每分钟检查 `TaskProcess` 表中 `status=scheduled` 且 `schedule_time <= now` 的任务
3. 找到待执行任务后：
   - 更新状态为 `running`
   - 启动后台线程执行爬取
   - 执行完成后更新状态为 `completed` 或 `failed`

**参考实现**: `app/api/electricity_routes.py` 中的 `push_electricity_full_crawl` 任务

---

### 3. 前端轮询任务状态

**当前状态**: 前端点击"立即执行"后，未轮询任务状态

**需实现**:
1. 点击"立即执行"后，前端轮询 `GET /api/course/crawl/status/:task_id`
2. 根据任务状态显示进度（如：`正在爬取...`，`爬取完成`）
3. 任务完成后自动刷新课表数据

**参考实现**: `Course.tsx` 中的 `startSpiderPolling()` 函数

---

## 四、文件清单

### 新增文件

1. ✅ `Push_System_Flask/app/api/course_routes.py` - 添加3个新端点（已修改）
2. ✅ `admin-frontend/src/api/course.ts` - 添加API接口和类型定义（已修改）
3. ✅ `admin-frontend/src/pages/CrawlScheduler.tsx` - 爬取调度弹窗组件（新创建）
4. ✅ `Push_System_Flask/test_course_api.py` - 后端API测试脚本（新创建）
5. ✅ `Push_System_Flask/test_course_api.ps1` - 前端API测试脚本（新创建）

### 修改文件

1. ✅ `admin-frontend/src/pages/Course.tsx` - 添加调度弹窗，修改"同步课表"按钮（已修改）

---

## 五、下一步建议

### 优先级1: 真机验证爬虫核心层

**原因**: 爬虫核心层是功能的基础，必须确保学期切换、学期列表获取正常工作

**步骤**:
1. 运行 `python main.py --semester-id 270`
2. 检查 `output/course-data/raw/course_meta.json` 的 `semesters` 字段
3. 如果格式不符，调整 `_parse_semester_options` 函数
4. 运行 `python main.py --semester-id 271 --week 15`
5. 验证是否能正确爬取指定周次的课表

---

### 优先级2: 实现本地按周筛选逻辑

**原因**: 按周筛选是核心需求，当前未实现

**步骤**:
1. 在 `app/cqie-course-timetable/course_processing/process_course_data.py` 中添加周次解析函数
2. 解析 `[X]周` 标注，提取课程所在的周次范围
3. 根据 `week` 参数过滤课程
4. 测试：运行 `python main.py --semester-id 271 --week 15`，验证输出是否只包含第15周的课程

---

### 优先级3: 实现预约执行的调度器

**原因**: 预约执行是用户需求，当前只创建了任务记录，未实现自动调度

**步骤**:
1. 在 `app/tasks/scheduler.py` 中添加定时任务
2. 定时检查 `TaskProcess` 表中的预约任务
3. 到达执行时间后自动触发爬取
4. 测试：创建一个预约任务，等待执行时间，验证是否自动触发

---

### 优先级4: 前端轮询任务状态

**原因**: 提升用户体验，让用户知道任务执行进度

**步骤**:
1. 在 `CrawlScheduler.tsx` 中添加轮询逻辑
2. 点击"立即执行"后，轮询任务状态
3. 根据任务状态显示进度提示
4. 任务完成后自动刷新课表数据

---

## 六、常见问题（FAQ）

### Q1: 爬虫运行失败，提示"CAS登录失败"

**可能原因**:
- 教务系统CAS登录地址变更
- 账号密码错误（检查 `.env` 中的 `JWXT_USERNAME` 和 `JWXT_PASSWORD`）
- 验证码OCR识别失败（需手动验证）

**解决方法**:
1. 检查 `.env` 配置
2. 设置 `JWXT_HEADLESS=false`，观察浏览器行为
3. 如果验证码识别失败，需优化 `CaptchaSolver` 类

---

### Q2: 获取学期列表失败，提示"数据查询接口返回空"

**可能原因**:
- `dataQuery.action` 接口需要登录后的Cookie
- 当前学期ID不正确

**解决方法**:
1. 检查爬虫是否能成功登录CAS
2. 手动访问教务系统，查看 `dataQuery.action` 的真实返回格式
3. 根据实际情况调整 `_parse_semester_options` 函数

---

### Q3: 前端编译失败，提示"Cannot find name 'ScheduleOutlined'"

**可能原因**:
- `@ant-design/icons` 版本问题
- 导入语句错误

**解决方法**:
1. 检查 `@ant-design/icons` 是否已安装：`npm list @ant-design/icons`
2. 如果未安装，运行：`npm install @ant-design/icons`
3. 检查导入语句：`import { ScheduleOutlined } from '@ant-design/icons';`

---

### Q4: 预约执行的任务没有自动触发

**可能原因**:
- 调度器未实现
- 调度器未启动

**解决方法**:
1. 检查 `app/tasks/scheduler.py` 中是否添加了预约任务检查逻辑
2. 检查调度器是否已启动（查看Flask启动日志）
3. 手动触发：将任务的 `status` 改为 `pending`，`schedule_time` 改为当前时间，重启Flask服务

---

## 七、联系人

如有问题，请联系：

- **开发者**: [你的名字]
- **邮箱**: [你的邮箱]
- **项目路径**: `D:\Tool\push_system\Push_System_Flask`

---

**文档版本**: v1.0  
**创建时间**: 2026-06-29  
**最后更新**: 2026-06-29
