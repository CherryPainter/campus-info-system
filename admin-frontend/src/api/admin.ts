/**
 * 管理后台 API 模块
 */

import request from "./request";
import type { ApiResponse } from "@/types/api";
import type { User } from "@/types/user";

/** 管理后台响应（部分接口在顶层携带 config / spider） */
export type AdminApiResponse<T = unknown> = ApiResponse<T> & {
  config?: any;
  spider?: SpiderStatus;
};

/** 爬虫状态 */
export interface SpiderStatus {
  running: boolean;
  last_run: string | null;
  last_result: string | null;
  last_error: string | null;
  last_exit_code: number | null;
  running_tasks?: {
    course_full_crawl: boolean;
    electricity_full_crawl: boolean;
  };
}

/** 定时任务 */
export interface ScheduledTask {
  id: string;
  name: string;
  trigger_type: string;
  trigger_desc: string;
  next_run: string | null;
  pending: boolean;
}

/** 仪表盘数据 */
export interface DashboardData {
  status: string;
  service: string;
  version: string;
  system?: {
    version: string;
    uptime: string;
  };
  modules: {
    weather: {
      status: string;
      enabled?: boolean;
      cache: { now: boolean; hourly: boolean; alert: boolean };
    };
    electricity: {
      status: string;
      enabled?: boolean;
      cookie_configured: boolean;
      configured_students?: number;
      data?: { remaining_exists?: boolean };
    };
  };
  spider: SpiderStatus;
  tasks?: {
    spider_status?: {
      course?: { running: boolean };
      electricity?: { running: boolean };
    };
  };
}

/** 系统配置 */
export interface SystemConfig {
  app_name: string;
  app_version: string;
  debug: boolean;
  auth_enabled: boolean;
  cors_origins: string[];
  ip_geo_enabled: boolean;
  ip_geo_allowed_regions: string[];
  class_name: string;
  daily_push_time: string;
  before_class_minutes: number;
}

/** 模块配置项 */
export interface ModuleConfigItem {
  id: number;
  module: string;
  key: string;
  value: string | number | boolean | object;
  value_type: "string" | "integer" | "float" | "boolean" | "json";
  description: string;
  is_editable: boolean;
  is_sensitive: boolean;
  updated_at: string;
}

/** 模块配置分组 */
export interface ModuleConfigGroup {
  name: string;
  configs: ModuleConfigItem[];
}

/** 模块配置 API */
export const configApi = {
  /** 获取所有模块配置（分组） */
  getAll: () => request.get<any, ApiResponse<Record<string, ModuleConfigGroup>>>("/admin/config"),
  /** 获取指定模块配置 */
  getModule: (module: string) =>
    request.get<any, ApiResponse<ModuleConfigGroup>>(`/admin/config/${module}`),
  /** 更新配置项 */
  update: (module: string, key: string, value: string | number | boolean) =>
    request.put<any, ApiResponse<ModuleConfigItem>>(`/admin/config/${module}/${key}`, { value }),
  /** 初始化默认配置 */
  init: () => request.post<any, ApiResponse>("/admin/config/init"),
};

/**
 * 管理后台 API
 */
export const adminApi = {
  /** 获取仪表盘数据 */
  getDashboard: (params?: { time_range?: string; start_date?: string; end_date?: string }) =>
    request.get<any, ApiResponse<DashboardData>>("/admin/dashboard", { params }),

  // ========== 天气模块 ==========
  /** 获取天气配置 */
  getWeatherConfig: () =>
    request.get<
      any,
      AdminApiResponse<{
        auth_type: "jwt_ed25519" | "api_key" | "none";
        credential_id?: string;
        project_id_configured?: boolean;
        private_key_configured?: boolean;
        api_key_configured?: boolean;
        api_host?: string;
        location?: string;
        city_name?: string;
        daily_push_time?: string;
        quiet_hours_enabled?: boolean;
        quiet_hours_start?: string;
        quiet_hours_end?: string;
        daily_push_limit?: number;
        alert_enabled?: boolean;
      }>
    >("/admin/weather/config"),
  /** 更新天气配置 */
  updateWeatherConfig: (data: {
    project_id?: string;
    api_key?: string;
    location?: string;
    city_name?: string;
    daily_push_time?: string;
    quiet_hours_enabled?: boolean;
    quiet_hours_start?: string;
    quiet_hours_end?: string;
    daily_push_limit?: number;
    alert_enabled?: boolean;
  }) => request.put<any, ApiResponse>("/admin/weather/config", data),
  /** 触发天气任务 */
  triggerWeather: (taskType: string) =>
    request.post<any, ApiResponse>("/admin/weather/trigger", { task_type: taskType }),

  // ========== 课程模块 ==========
  /** 触发课程推送任务 */
  triggerCourse: (taskType: string) =>
    request.post<any, ApiResponse>("/admin/course/trigger", { task_type: taskType }),

  // ========== 电量模块 ==========
  /** 获取电量配置 */
  getElectricityConfig: () => request.get<any, AdminApiResponse<ElectricityConfig>>("/admin/electricity/config"),
  /** 更新电量配置 */
  updateElectricityConfig: (data: Partial<ElectricityConfig>) =>
    request.put<any, ApiResponse>("/admin/electricity/config", data),
  /** 学生电量总览（全部学生 + 配置/低电量状态） */
  getElectricityStudents: () =>
    request.get<any, ApiResponse<ElectricityStudentsOverview>>("/admin/electricity/students"),
  /** 指定学生最新剩余电量 */
  getStudentElectricityRemaining: (userId: number) =>
    request.get<any, ApiResponse<StudentElectricityRemaining>>(
      `/admin/electricity/students/${userId}/remaining`
    ),
  /** 指定学生用电记录（分页） */
  getStudentElectricityRecords: (
    userId: number,
    params?: { limit?: number; offset?: number; meter_filter?: string }
  ) =>
    request.get<any, ApiResponse<StudentElectricityRecords>>(
      `/admin/electricity/students/${userId}/records`,
      { params }
    ),
  /** 指定学生用电统计 */
  getStudentElectricityStatistics: (
    userId: number,
    params?: { range_type?: string; start_date?: string; end_date?: string }
  ) =>
    request.get<any, ApiResponse<ElectricityStatisticsData>>(
      `/admin/electricity/students/${userId}/statistics`,
      { params }
    ),
  /** 触发电量任务 */
  triggerElectricity: (taskType: string) =>
    request.post<any, ApiResponse>("/admin/electricity/trigger", { task_type: taskType }),

  // ========== 课表模块 ==========
  /** 获取课表数据 */
  getSchedules: () => request.get<any, ApiResponse>("/admin/schedules"),

  // ========== 爬虫任务 ==========
  /** 触发爬虫 */
  triggerSpider: () => request.post<any, ApiResponse>("/admin/tasks/spider"),
  /** 获取爬虫状态 */
  getSpiderStatus: () =>
    request.get<any, AdminApiResponse<SpiderStatus>>("/admin/tasks/spider/status"),
  /** 获取定时任务列表 */
  getScheduledTasks: () => request.get<any, ApiResponse<ScheduledTask[]>>("/processes/scheduled"),

  // ========== 系统设置 ==========
  /** 获取系统配置 */
  getSystemConfig: () => request.get<any, ApiResponse<SystemConfig>>("/admin/system/config"),
  /** 热重载配置 */
  reloadConfig: () => request.post<any, ApiResponse>("/admin/system/reload"),
};

/** 电量模块配置 */
export interface ElectricityConfig {
  configured_students?: number;
  base_url?: string;
  max_pages?: number;
  low_power_threshold?: number;
  low_power_interval_hours?: number;
  daily_push_time?: string;
  weekly_push_time?: string;
  weekly_push_day?: string;
  monthly_push_time?: string;
  monthly_push_day?: number;
  cookie_check_time?: string;
}

/** 学生电量总览项 */
export interface ElectricityStudent {
  user_id: number;
  display_name: string;
  /** 头像 data URI（小程序上传）；无头像时为空串，前端用首字母兜底 */
  avatar?: string | null;
  student_number: string | null;
  class_name: string | null;
  configured: boolean;
  remaining: number | null;
  recorded_at: string | null;
  is_low_power: boolean;
}

/** 学生电量总览响应 */
export interface ElectricityStudentsOverview {
  summary: {
    total_students: number;
    configured_students: number;
    low_power_count: number;
  };
  students: ElectricityStudent[];
}

/** 指定学生最新剩余电量 */
export interface StudentElectricityRemaining {
  remaining: number;
  total_capacity: number;
  percentage: number;
  is_low_power: boolean;
  recorded_at: string | null;
  meter: string | null;
}

/** 指定学生用电记录（分页） */
export interface StudentElectricityRecords {
  records: Array<{
    id: number;
    record_time: string;
    usage: number;
    meter: string;
  }>;
  total: number;
  limit: number;
  offset: number;
}

/** 指定学生用电统计（与旧全局 /electricity/statistics 结构一致） */
export interface ElectricityStatisticsData {
  daily: Array<{ date: string; usage: number; count: number }>;
  by_meter: Array<{ meter: string; usage: number }>;
  summary: {
    total_records: number;
    total_usage: number;
    avg_daily: number;
    max_daily: number;
    min_daily: number;
    meter_count: number;
  };
  range: {
    type: string;
    start_date: string;
    end_date: string;
  };
}

/** 消息模板 */
export interface PushTemplate {
  id: string;
  name: string;
  description: string;
  params: string[];
  example: Record<string, string>;
}

/** 自定义推送 */
export interface CustomPush {
  id: number;
  title: string;
  content: string | null;
  msg_type: "text" | "image" | "template";
  image_path: string | null;
  template_id: string | null;
  template_params: string | null;
  push_type: "immediate" | "scheduled" | "recurring";
  scheduled_time: string | null;
  cron_expression: string | null;
  status: "pending" | "sent" | "failed" | "cancelled";
  sent_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
}

/** 自定义推送 API */
export const pushApi = {
  /** 获取推送列表（归一为统一的 Paginated<CustomPush>） */
  getList: async (params?: {
    status?: string;
    push_type?: string;
    page?: number;
    per_page?: number;
  }) => {
    const res = await request.get<
      any,
      ApiResponse<{
        data: CustomPush[];
        pagination: { total: number; page: number; per_page: number; pages: number };
      }>
    >("/admin/push", { params });
    if (res.status !== "success") throw new Error(res.message || "请求失败");
    return {
      data: res.data?.data ?? [],
      pagination: res.data?.pagination ?? { total: 0, page: 1, per_page: 20, pages: 0 },
    };
  },
  /** 获取推送详情 */
  get: (id: number) => request.get<any, ApiResponse<CustomPush>>(`/admin/push/${id}`),
  /** 创建推送 */
  create: (data: Partial<CustomPush>) =>
    request.post<any, ApiResponse<CustomPush>>("/admin/push", data),
  /** 更新推送 */
  update: (id: number, data: Partial<CustomPush>) =>
    request.put<any, ApiResponse<CustomPush>>(`/admin/push/${id}`, data),
  /** 删除推送 */
  delete: (id: number) => request.delete<any, ApiResponse>(`/admin/push/${id}`),
  /** 立即发送 */
  send: (id: number) => request.post<any, ApiResponse>(`/admin/push/${id}/send`),
  /** 取消推送 */
  cancel: (id: number) => request.post<any, ApiResponse>(`/admin/push/${id}/cancel`),
  /** 获取内置模板列表 */
  getTemplates: () => request.get<any, ApiResponse<PushTemplate[]>>("/admin/push/templates"),
};

/** 任务进程 */
export interface TaskProcess {
  id: number;
  name: string;
  task_type: "spider" | "weather" | "electricity" | "custom" | "course";
  // 与后端 app/core/task_state.py 的进程状态枚举保持一致
  status: "running" | "completed" | "completed_empty" | "failed" | "cancelled" | "skipped";
  pid: number | null;
  progress: number;
  total_items: number;
  processed_items: number;
  message: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  duration: number;
  created_by: string;
  extra_data: string | null;
}

/** 定时任务计划 */
export interface ScheduledJob {
  id: string;
  name: string;
  trigger_type: "cron" | "interval";
  trigger_desc: string;
  next_run: string | null;
  pending: boolean;
}

/** 动态规则 */
export interface DynamicRule {
  id: string;
  name: string;
  type: string;
  trigger_desc: string;
  status: string;
  priority?: number;
  rule_id?: string;
}

/** 进程管理 API */
export const processApi = {
  /** 获取进程列表（归一为统一的 Paginated<TaskProcess>，并保留 stats） */
  getList: async (params?: {
    status?: string;
    task_type?: string;
    page?: number;
    per_page?: number;
  }) => {
    const res = await request.get<
      any,
      ApiResponse<TaskProcess[]> & {
        pagination: { total: number; page: number; per_page: number; pages: number };
        stats?: {
          total: number;
          completed: number;
          failed: number;
          running: number;
          avg_duration: number;
        };
      }
    >("/admin/processes", { params });
    if (res.status !== "success") throw new Error(res.message || "请求失败");
    return {
      data: res.data ?? [],
      pagination: res.pagination ?? { total: 0, page: 1, per_page: 20, pages: 0 },
      stats: res.stats,
    };
  },
  /** 获取运行中进程 */
  getRunning: () =>
    request.get<any, ApiResponse<{ data: TaskProcess[]; count: number }>>(
      "/admin/processes/running"
    ),
  /** 获取定时任务计划 */
  getScheduled: () =>
    request.get<any, ApiResponse<{ data: ScheduledJob[]; count: number }>>(
      "/admin/processes/scheduled"
    ),
  /** 获取动态规则配置 */
  getRules: () =>
    request.get<any, ApiResponse<{ data: DynamicRule[]; count: number }>>("/admin/processes/rules"),
  /** 获取进程详情 */
  get: (id: number) => request.get<any, ApiResponse<TaskProcess>>(`/admin/processes/${id}`),
  /** 获取任务状态（通过 task_id） */
  getTaskStatus: (id: number) =>
    request.get<any, ApiResponse<TaskProcess>>(`/admin/processes/${id}`),
  /** 停止进程 */
  stop: (id: number) => request.post<any, ApiResponse>(`/admin/processes/${id}/stop`),
  /** 删除进程 */
  delete: (id: number) => request.delete<any, ApiResponse>(`/admin/processes/${id}`),
};

/** Webhook */
export interface Webhook {
  id: number;
  name: string;
  url: string;
  webhook_type: "push" | "status" | "both";
  is_enabled: boolean;
  description?: string;
  last_test_status?: "success" | "failed" | "pending";
  last_test_time?: string;
  created_at?: string;
  updated_at?: string;
}

/** Webhook 管理 API */
export const webhookApi = {
  /** 获取所有 webhook */
  getList: () => request.get<any, ApiResponse<Webhook[]>>("/admin/webhooks"),
  /** 创建 webhook */
  create: (data: Partial<Webhook>) =>
    request.post<any, ApiResponse<Webhook>>("/admin/webhooks", data),
  /** 更新 webhook */
  update: (id: number, data: Partial<Webhook>) =>
    request.put<any, ApiResponse<Webhook>>(`/admin/webhooks/${id}`, data),
  /** 删除 webhook */
  delete: (id: number) => request.delete<any, ApiResponse>(`/admin/webhooks/${id}`),
  /** 测试 webhook */
  test: (id: number) => request.post<any, ApiResponse>(`/admin/webhooks/${id}/test`),
  /** 重载适配器配置 */
  reload: () => request.post<any, ApiResponse>("/admin/webhooks/reload"),
};

// ==================== 近期提醒（小程序时间轴卡片后台定义）====================

/** 近期提醒分类 */
export type NotificationCategory = "exam" | "holiday" | "activity" | "other";

/** 近期提醒项（与后端 Notification.to_dict 对齐） */
export interface NotificationItem {
  id: number;
  title: string;
  event_date: string;
  event_date_label: string;
  category: NotificationCategory;
  remind_days: number;
  sort_order: number;
  is_active: boolean;
  description: string | null;
  days_left: number;
  is_expired: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** 列表分页响应 */
export interface NotificationPage {
  items: NotificationItem[];
  total: number;
  page: number;
  page_size: number;
}

/** 近期提醒分类选项 */
export const NOTIFICATION_CATEGORY_OPTIONS: { label: string; value: NotificationCategory }[] = [
  { label: "考试", value: "exam" },
  { label: "节假日", value: "holiday" },
  { label: "活动", value: "activity" },
  { label: "其他", value: "other" },
];

/** 近期提醒管理 API（/api/admin/notifications） */
export const notificationApi = {
  /** 列表（分页 / 分类 / 关键词 / 仅启用筛选） */
  getList: (params?: {
    page?: number;
    page_size?: number;
    category?: NotificationCategory | "";
    keyword?: string;
    active?: "true" | "false";
  }) =>
    request.get<any, ApiResponse<NotificationItem[]> & { pagination: { total: number } }>(
      "/admin/notifications",
      { params }
    ),
  /** 详情 */
  detail: (id: number) =>
    request.get<any, ApiResponse<NotificationItem>>(`/admin/notifications/${id}`),
  /** 创建 */
  create: (data: Partial<NotificationItem>) =>
    request.post<any, ApiResponse<NotificationItem>>("/admin/notifications", data),
  /** 更新 */
  update: (id: number, data: Partial<NotificationItem>) =>
    request.put<any, ApiResponse<NotificationItem>>(`/admin/notifications/${id}`, data),
  /** 删除 */
  remove: (id: number) =>
    request.delete<any, ApiResponse>(`/admin/notifications/${id}`),
  /** 启停（翻转 is_active） */
  toggle: (id: number) =>
    request.post<any, ApiResponse<NotificationItem>>(`/admin/notifications/${id}/toggle`),
};

/** 用户信息（统一类型，定义在 @/types/user） */
export type { User } from "@/types/user";

/** 登录日志 */
export interface LoginLog {
  id: number;
  user_id: number;
  username?: string;
  login_time: string;
  logout_time?: string;
  duration?: string;
  ip_address?: string;
  user_agent?: string;
  country?: string;
  region?: string;
  city?: string;
  status: string;
  failure_reason?: string;
}

/** 用户管理 API */
export const userApi = {
  /** 获取用户信息 */
  getProfile: () => request.get<any, ApiResponse<User>>("/admin/user/profile"),
  /** 更新用户信息 */
  updateProfile: (data: Partial<User>) =>
    request.put<any, ApiResponse<User>>("/admin/user/profile", data),
  /** 更新用户名 */
  updateUsername: (data: { username: string; password: string }) =>
    request.put<any, ApiResponse<User>>("/admin/user/username", data),
  /** 获取登录日志（归一为统一的 Paginated<LoginLog>） */
  getLoginLogs: async (params?: { page?: number; page_size?: number; status?: string }) => {
    const res = await request.get<
      any,
      ApiResponse<LoginLog[]> & {
        pagination: { page: number; page_size: number; total: number; total_pages: number };
      }
    >("/admin/user/login-logs", { params });
    if (res.status !== "success") throw new Error(res.message || "请求失败");
    return {
      data: res.data ?? [],
      pagination: {
        total: res.pagination.total,
        page: res.pagination.page,
        per_page: res.pagination.page_size,
        pages: res.pagination.total_pages,
      },
    };
  },
  /** 获取所有用户（仅管理员） */
  getUsers: () => request.get<any, ApiResponse<User[]>>("/admin/user/users"),
  /** 创建用户（仅管理员） */
  createUser: (data: { username: string; password: string; role: string }) =>
    request.post<any, ApiResponse<User>>("/admin/user/users", data),
  /** 更新用户（仅管理员） */
  updateUser: (id: number, data: Partial<User>) =>
    request.put<any, ApiResponse<User>>(`/admin/user/users/${id}`, data),
  /** 删除用户（仅管理员） */
  deleteUser: (id: number) => request.delete<any, ApiResponse>(`/admin/user/users/${id}`),
  /** 重置用户密码（仅管理员） */
  resetUserPassword: (id: number, password: string) =>
    request.post<any, ApiResponse>(`/admin/user/users/${id}/reset-password`, { password }),
  /** 重置用户MFA（仅超级管理员） */
  resetUserMfa: (id: number) => request.post<any, ApiResponse>(`/admin/user/users/${id}/reset-mfa`),
};

// ==================== 学生名单（预录白名单）====================

/** 名单条目（与后端 StudentRoster.to_dict 对齐，含绑定状态聚合字段） */
export interface RosterStudent {
  id: number;
  school: string;
  student_number: string;
  class_name: string;
  real_name: string | null;
  remark: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  /** 绑定状态聚合：已被哪个用户认领（按 school+student_number 关联 student_profiles） */
  bound_user_id: number | null;
  bound_username: string | null;
  bound_at: string | null;
}

/** 批量导入结果 */
export interface RosterImportResult {
  created: number;
  failures: Array<{ row: number; reason: string }>;
}

/** 学生名单 API（/api/admin/roster） */
export const rosterApi = {
  /** 分页查询名单（可选学校/关键字筛选） */
  getList: (params?: {
    school?: string;
    keyword?: string;
    page?: number;
    page_size?: number;
  }) =>
    request.get<
      any,
      ApiResponse<RosterStudent[]> & { total: number; page: number; page_size: number }
    >("/admin/roster/students", { params }),
  /** 新建单个名单条目 */
  create: (data: {
    school: string;
    student_number: string;
    class_name: string;
    real_name?: string;
    remark?: string;
    is_active?: boolean;
  }) => request.post<any, ApiResponse<RosterStudent>>("/admin/roster/students", data),
  /** 编辑名单条目（学校/学号只读） */
  update: (
    id: number,
    data: { class_name?: string; real_name?: string; remark?: string; is_active?: boolean }
  ) => request.put<any, ApiResponse<RosterStudent>>(`/admin/roster/students/${id}`, data),
  /** 删除名单条目 */
  remove: (id: number) =>
    request.delete<any, ApiResponse>(`/admin/roster/students/${id}`),
  /** 批量导入（CSV / Excel 文件） */
  import: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request.post<any, ApiResponse<RosterImportResult>>(
      "/admin/roster/students/batch",
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
  },
  /** 学校选项（与小程序绑定页一致，schools 字段在响应顶层） */
  getSchools: () =>
    request.get<any, ApiResponse<unknown> & { schools?: string[] }>(
      "/admin/roster/schools"
    ),
};
