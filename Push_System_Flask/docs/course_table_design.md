# 课程表结构设计文档

## 当前表结构分析

**表名**: `courses`
**问题**:
1. 缺少学期信息（无法区分不同学期的课程）
2. 缺少课程代码（无法唯一标识课程）
3. `weeks` 字段用JSON存储，查询效率低
4. 缺少教师、教室等详细信息

## 新表结构设计

### 方案：优化单表结构（推荐）

保持单表结构，添加必要字段，优化索引。

```sql
CREATE TABLE `courses` (
  -- 主键和标识
  `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
  `course_code` VARCHAR(50) NOT NULL COMMENT '课程代码（如：220110460.02）',
  `course_name` VARCHAR(100) NOT NULL COMMENT '课程名称',
  
  -- 学期信息
  `semester_id` INT NOT NULL COMMENT '学期ID（教务系统）',
  `semester_name` VARCHAR(100) NOT NULL COMMENT '学期名称（如：2025-2026-2）',
  `academic_year` VARCHAR(20) NOT NULL COMMENT '学年（如：2025-2026）',
  `term` TINYINT NOT NULL COMMENT '学期（1=春季，2=秋季）',
  
  -- 课程时间信息
  `week_day` INT NOT NULL COMMENT '星期几（1-7，1=周一）',
  `period_idx` INT NOT NULL COMMENT '起始节次索引（1-12）',
  `start_time` VARCHAR(10) NOT NULL COMMENT '开始时间（HH:MM）',
  `end_time` VARCHAR(10) NOT NULL COMMENT '结束时间（HH:MM）',
  
  -- 周次信息（优化：使用JSON存储，但添加生成列用于查询）
  `weeks` JSON NOT NULL COMMENT '上课周次（JSON数组，如：[1,2,3,4]）',
  `weeks_bitmap` VARCHAR(30) NOT NULL COMMENT '周次位图（如：111100...，用于快速查询）',
  
  -- 教师和教室信息
  `teacher` VARCHAR(100) DEFAULT NULL COMMENT '教师姓名',
  `classroom` VARCHAR(100) DEFAULT NULL COMMENT '教室',
  `building` VARCHAR(50) DEFAULT NULL COMMENT '教学楼',
  
  -- 课程属性
  `course_type` VARCHAR(20) DEFAULT NULL COMMENT '课程类型（必修/选修/实践）',
  `credit` DECIMAL(3,1) DEFAULT NULL COMMENT '学分',
  
  -- 软删除和推送控制
  `is_deleted` BOOLEAN DEFAULT FALSE NOT NULL COMMENT '是否已删除（软删除）',
  `deleted_at` DATETIME DEFAULT NULL COMMENT '删除时间',
  `deleted_reason` VARCHAR(255) DEFAULT NULL COMMENT '删除原因',
  `push_enabled` BOOLEAN DEFAULT TRUE NOT NULL COMMENT '是否推送提醒',
  
  -- 元数据
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
  `crawled_at` DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '爬取时间',
  
  -- 唯一约束：同一学期、同一课程代码、同一时间，只能有一条记录
  UNIQUE KEY `uk_semester_course_time` (`semester_id`, `course_code`, `week_day`, `period_idx`),
  
  -- 索引
  INDEX `idx_semester` (`semester_id`),
  INDEX `idx_week_day` (`week_day`, `period_idx`),
  INDEX `idx_weeks` ((CAST(`weeks` AS UNSIGNED ARRAY))),  -- MySQL 8.0+ 支持JSON索引
  INDEX `idx_course_code` (`course_code`),
  INDEX `idx_is_deleted` (`is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='课程表';
```

### 关键改进点

1. **添加学期信息**：`semester_id`, `semester_name`, `academic_year`, `term`
   - 支持多学期课程管理
   - 可以查询某个学期的所有课程

2. **添加课程代码**：`course_code`
   - 唯一标识课程
   - 用于去重和更新

3. **优化周次存储**：`weeks` + `weeks_bitmap`
   - `weeks`: JSON数组，存储周次列表
   - `weeks_bitmap`: 位图字符串，用于快速查询（如：查找第5周的所有课程）

4. **添加课程属性**：`course_type`, `credit`
   - 支持更丰富的课程信息展示

5. **优化索引**：
   - 唯一约束：防止重复数据
   - JSON索引：支持高效查询周次

## 爬虫改进方案

### 目标：遍历所有周次，获取完整课程数据

**当前问题**：
- 课表页面默认只显示当前周的课程
- 选择"全部"周次失败（selectize插件问题）

**解决方案**：
在同一个浏览器会话中，遍历所有周次（1-20），分别获取数据。

**实现步骤**：
1. 登录后，获取学期ID
2. 遍历周次 1-20：
   - 选择周次下拉框
   - 等待页面刷新
   - 获取该周的课程数据
   - 保存到临时文件
3. 合并所有周次的课程数据
4. 生成最终的 `processed_course_table.json`

**预计耗时**：20周 × 30秒 = 10分钟

## 后续优化

1. **教师信息获取**：
   - 当前课表页面不显示教师信息
   - 需要访问课程详情页或使用其他API

2. **增量更新**：
   - 只爬取变化的周次（对比上次爬取时间）
   - 减少爬取时间

3. **错误重试**：
   - 某个周次爬取失败时，自动重试
   - 提高爬取成功率
