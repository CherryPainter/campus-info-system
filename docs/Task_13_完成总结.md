# Push_System_Flask Task #13 完成总结

## 任务概述
Task #13: 课程学期分类 - 实现指定学期/指定周的课表爬取功能

## 已完成的工作

### 1. 爬虫核心层 ✅
**文件**: `app/cqie-course-timetable/main.py`

**新增功能**:
- `get_course_table(semester_id=None, start_week=None)` 方法支持指定学期和周次
- `_switch_semester(page, semester_id)` 方法切换学期
- `_fetch_semester_list(page, entity_id)` 方法获取完整学期列表
- `_parse_semester_options(text)` 方法解析学期数据（兼容JSON和HTML格式）
- `_extract_page_meta(html)` 方法解析页面元信息（学期、周次、学生ID）
- 命令行参数支持：`--semester-id` 和 `--week`

**测试结果**:
- 离线解析测试 9/9 通过
- 真实页面解析成功：学期271 / 2025-2026-2 / ids=905521 / 周18

### 2. 课程处理层 ✅
**文件**: `app/cqie-course-timetable/course_processing/process_course_data.py`

**新增功能**:
- `_extract_course_info()` 支持解析周次范围（如 "[1-16]周"）
- 新增 `_parse_weeks_string()` 方法解析周次字符串

### 3. 后端API层 ✅
**文件**: `app/api/course_routes.py`

**新增端点**:
- `GET /api/course/semesters` - 获取学期列表
- `POST /api/course/crawl` - 触发爬取（支持预约运行）
- `GET /api/course/crawl/status/<task_id>` - 获取爬取任务状态

**功能特性**:
- 支持立即执行和预约执行两种模式
- 预约执行支持指定日期时间（推荐晚上）
- 任务状态跟踪（pending -> running -> completed/failed）

### 4. 前端API层 ✅
**文件**: `admin-frontend/src/api/course.ts`

**新增接口**:
- `getSemesters()` - 获取学期列表
- `triggerCrawl(data)` - 触发爬取
- `getCrawlStatus(taskId)` - 获取任务状态

### 5. 数据库和模型 ✅
- `Course` 模型已支持 `weeks` 字段
- `TaskProcess` 模型已支持任务状态跟踪
- 数据库表已创建（18个表）

---

## 待完成的工作

### 1. 前端界面 - 学期选择和下拉框 ⏳
**需要添加**:
- [ ] 学期选择下拉框（在周次选择旁边）
- [ ] 爬取调度弹窗（选择学期、周次、执行方式）
- [ ] 任务状态显示

**文件**: `admin-frontend/src/pages/Course.tsx`

### 2. 真机测试 - 爬虫联网方法 ⚠️
**需要测试**:
- [ ] `_switch_semester()` 方法实际切换学期
- [ ] `_fetch_semester_list()` 方法获取学期列表
- [ ] 验证 `dataQuery.action` 返回格式

**说明**: 当前两个联网方法未真机验证，需要实际运行爬虫测试

### 3. 本地按周筛选逻辑 ⚠️
**说明**: 当前 `start_week` 参数只记录元信息，未实际筛选课程

**选项**:
- A. 在爬虫处理步骤中筛选
- B. 在API层过滤（推荐，因为数据已存储在数据库）

---

## 使用说明

### 命令行使用
```bash
# 进入爬虫目录
cd app/cqie-course-timetable

# 爬取当前学期
python main.py

# 爬取指定学期
python main.py --semester-id 270

# 爬取指定学期+指定周
python main.py --semester-id 271 --week 15
```

### API使用

#### 1. 获取学期列表
```bash
GET /api/course/semesters
Authorization: Bearer <JWT_TOKEN>
```

#### 2. 触发爬取（立即执行）
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

#### 3. 触发爬取（预约执行）
```bash
POST /api/course/crawl
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

{
  "semester_id": "271",
  "schedule_type": "scheduled",
  "schedule_time": "2026-06-29 23:00:00"
}
```

---

## 技术要点

### 1. 按学期爬取策略
- **策略**: 按学期爬一次 + 本地筛选
- **优点**: 对服务器友好，符合爬虫规范
- **实现**: 教务系统一次性返回整学期数据，本地按周次过滤

### 2. 预约执行机制
- **立即执行**: 接收请求后立即启动后台线程执行爬取
- **预约执行**: 创建任务记录，状态为 `scheduled`，等待调度器触发
- **注意**: 当前预约执行未实现自动调度，需要手动触发或添加调度器支持

### 3. 学期切换机制
- **步骤1**: 修改学期下拉框
- **步骤2**: POST `/eams/accessSemester!access.action` 切换学期
- **步骤3**: 重新加载课表页

---

## 下一步建议

### 优先级1: 完成前端界面
- 添加学期选择下拉框
- 添加爬取调度弹窗
- 测试完整流程

### 优先级2: 真机测试爬虫
- 运行 `python main.py --semester-id 270`
- 检查 `course_meta.json` 的 `semesters` 字段
- 根据实际情况调整代码

### 优先级3: 实现预约执行调度器
- 当前预约执行未实现自动调度
- 需要添加调度器定期检查 `scheduled` 状态的任务
- 到达执行时间后自动触发

---

## 文件清单

### 新增/修改的后端文件
1. `app/cqie-course-timetable/main.py` - 爬虫核心（已修改）
2. `app/cqie-course-timetable/course_processing/process_course_data.py` - 课程处理（已修改）
3. `app/api/course_routes.py` - 课程API（已修改，新增3个端点）

### 新增/修改的前端文件
1. `admin-frontend/src/api/course.ts` - 课程API（已修改）

### 待修改的前端文件
1. `admin-frontend/src/pages/Course.tsx` - 课程管理页面（待添加学期选择和调度弹窗）

---

## 测试检查清单

- [ ] 爬虫核心功能测试（指定学期爬取）
- [ ] API端点测试（获取学期列表、触发爬取、获取状态）
- [ ] 前端界面测试（学期选择、调度弹窗）
- [ ] 完整流程测试（前端触发 -> 后端执行 -> 数据刷新）
- [ ] 预约执行测试

---

**文档结束**

*Task #13 正在进行中，前端界面实现待完成。*
