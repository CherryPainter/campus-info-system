# Task #13 完成进度报告

## 已完成的工作

### 1. 爬虫核心层（已完成）✅
- `main.py` 已支持 `semester_id` 和 `start_week` 参数
- 新增 `_switch_semester()` 方法切换学期
- 新增 `_fetch_semester_list()` 方法获取学期列表
- 新增 `_extract_page_meta()` 方法解析页面元信息
- 支持命令行参数：`--semester-id` 和 `--week`

### 2. 课程处理层（已完成）✅
- 更新 `_extract_course_info()` 支持解析周次范围（如 "[1-16]周"）
- 新增 `_parse_weeks_string()` 方法解析周次字符串

### 3. 后端API层（已完成）✅
- 新增 `GET /api/course/semesters` - 获取学期列表
- 新增 `POST /api/course/crawl` - 触发爬取（支持预约运行）
- 新增 `GET /api/course/crawl/status/<task_id>` - 获取爬取任务状态
- 支持立即执行和预约执行两种模式

### 4. 前端API层（已完成）✅
- 更新 `course.ts` 添加新API接口
- `getSemesters()` - 获取学期列表
- `triggerCrawl()` - 触发爬取
- `getCrawlStatus()` - 获取任务状态

### 5. 数据库和模型（已完成）✅
- `Course` 模型已支持 `weeks` 字段
- `TaskProcess` 模型已支持任务状态跟踪
- 数据库表已创建

---

## 待完成的工作

### 1. 前端界面 - 学期选择下拉框 ⏳
**文件**: `admin-frontend/src/pages/Course.tsx`

**需要添加**:
- 学期选择下拉框（在周次选择旁边）
- 调用 `courseApi.getSemesters()` 获取学期列表
- 选择学期后，更新周次选项（不同学期的周次数可能不同）

### 2. 前端界面 - 爬取调度弹窗 ⏳
**文件**: `admin-frontend/src/pages/Course.tsx`

**需要添加**:
- 点击"同步课表"按钮时，打开调度弹窗
- 弹窗内容：
  - 学期选择下拉框
  - 周次选择下拉框（可选）
  - 执行方式选择（立即执行 / 预约执行）
  - 如果选择预约执行，显示日期时间选择器（推荐晚上时间）
- 提交时调用 `courseApi.triggerCrawl()`
- 显示任务状态和进度

### 3. 真机测试 - 爬虫联网方法 ⚠️
**文件**: `app/cqie-course-timetable/main.py`

**需要测试**:
- `_switch_semester()` 方法实际切换学期
- `_fetch_semester_list()` 方法获取学期列表
- 验证 `dataQuery.action` 返回格式
- 根据实际情况调整 `_parse_semester_options()` 方法

### 4. 本地按周筛选逻辑 ⚠️
**说明**: 当前 `start_week` 参数只记录元信息，未实际筛选

**需要实现**:
- 在课程处理步骤中，解析周次标注
- 根据指定周次过滤课程
- 或者在API层过滤（推荐，因为数据已存储在数据库）

---

## 下一步建议

### 方案A: 快速完成前端界面（推荐）
1. 更新 `Course.tsx` 添加学期下拉框
2. 添加爬取调度弹窗
3. 测试完整流程

### 方案B: 先真机测试爬虫
1. 运行 `python main.py --semester-id 270` 测试学期切换
2. 检查 `course_meta.json` 的 `semesters` 字段
3. 根据实际情况调整代码
4. 然后完成前端界面

---

## API使用示例

### 获取学期列表
```bash
GET /api/course/semesters
Authorization: Bearer <JWT_TOKEN>

响应:
{
  "status": "success",
  "data": {
    "semesters": [
      {"id": "271", "name": "2025-2026-2"},
      {"id": "270", "name": "2025-2026-1"}
    ],
    "current_semester_id": "271",
    "current_semester_name": "2025-2026-2",
    "weeks": ["1", "2", ..., "18"]
  }
}
```

### 触发爬取（立即执行）
```bash
POST /api/course/crawl
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

{
  "semester_id": "271",
  "week": 15,
  "schedule_type": "immediate"
}
```

### 触发爬取（预约执行）
```bash
POST /api/course/crawl
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

{
  "semester_id": "271",
  "week": null,
  "schedule_type": "scheduled",
  "schedule_time": "2026-06-29 23:00:00"
}
```

---

## 前端实现指南

### 1. 添加学期下拉框
在 `Course.tsx` 的 `extra` 部分，周次下拉框前面添加学期下拉框：

```tsx
<Select
  value={selectedSemester}
  onChange={handleSemesterChange}
  style={{ width: 180 }}
  placeholder="选择学期"
>
  {semesters.map((s) => (
    <Option key={s.id} value={s.id}>
      {s.name}
    </Option>
  ))}
</Select>
```

### 2. 添加爬取调度弹窗
```tsx
<Modal
  title="同步课表"
  open={crawlModalVisible}
  onOk={handleCrawlSubmit}
  onCancel={() => setCrawlModalVisible(false)}
>
  <Form form={crawlForm}>
    <Form.Item name="semester_id" label="学期">
      <Select placeholder="选择学期">
        {semesters.map((s) => (
          <Option key={s.id} value={s.id}>{s.name}</Option>
        ))}
      </Select>
    </Form.Item>
    <Form.Item name="week" label="周次（可选）">
      <InputNumber min={1} max={25} placeholder="留空表示全部周次" />
    </Form.Item>
    <Form.Item name="schedule_type" label="执行方式">
      <Select>
        <Option value="immediate">立即执行</Option>
        <Option value="scheduled">预约执行</Option>
      </Select>
    </Form.Item>
    {scheduleType === 'scheduled' && (
      <Form.Item name="schedule_time" label="执行时间">
        <DatePicker showTime format="YYYY-MM-DD HH:mm:ss" />
      </Form.Item>
    )}
  </Form>
</Modal>
```

---

**需要我继续完成前端界面的实现吗？**
