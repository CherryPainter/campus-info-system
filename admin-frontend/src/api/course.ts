/** 课程管理 API */
import request from "./request";
import type { ApiResponse } from "@/types/api";

/** 课程数据 */
export interface Course {
  id: number;
  course_name: string;
  semester_id?: number;
  teacher?: string;
  classroom?: string;
  building?: string;
  week_day: number;
  period_idx: number;
  start_time: string;
  end_time: string;
  weeks?: string;
  week_number?: number;
  push_enabled?: boolean;
  created_at?: string;
  updated_at?: string;
}

/** 当前上课状态 */
export interface CurrentStatus {
  current_period: number;
  is_ongoing: boolean;
  current_week_day: number;
}

/** 学期信息 */
export interface SemesterInfo {
  id: number;
  name: string;
  is_current: boolean;
  eams_id?: string | number;
}

/** 爬取预约任务 */
export interface CrawlTask {
  id: number;
  name: string;
  scope: "semester" | "all";
  semester_id: number | null;
  eams_id: string | null;
  schedule_type: "immediate" | "scheduled";
  scheduled_at: string | null;
  week: number | null;
  status: "pending" | "running" | "completed" | "completed_empty" | "failed" | "cancelled";
  message: string | null;
  error_message: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** 课程表数据结构 */
export interface TimetableData {
  courses: (Course & { is_current_course?: boolean })[];
  periods: Record<number, [string, string]>;
  week_number?: number;
  available_weeks: { week_number: number; start_date: string; end_date: string }[];
  current_status: CurrentStatus;
}

/** 星期映射 */
export const WEEK_DAY_MAP: Record<number, string> = {
  1: "周一",
  2: "周二",
  3: "周三",
  4: "周四",
  5: "周五",
  6: "周六",
  7: "周日",
};

/** 教学楼列表 */
export const BUILDINGS = [
  { code: "启智楼", name: "启智楼" },
  { code: "雏鹰楼", name: "雏鹰楼" },
  { code: "语慧楼", name: "语慧楼" },
  { code: "思源楼", name: "思源楼" },
  { code: "讯达楼", name: "讯达楼" },
  { code: "盛德楼", name: "盛德楼" },
  { code: "艺教楼", name: "艺教楼" },
  { code: "图书馆", name: "图书馆" },
  { code: "理工楼", name: "理工楼" },
  { code: "鸿志楼", name: "鸿志楼" },
  { code: "明远楼", name: "明远楼" },
];

/** 第一套时间表（启智楼等） */
export const FIRST_SCHEDULE: Record<number, { name: string; start: string; end: string }> = {
  1: { name: "第一节", start: "08:10", end: "08:55" },
  2: { name: "第二节", start: "09:05", end: "09:50" },
  3: { name: "第三节", start: "10:10", end: "10:55" },
  4: { name: "第四节", start: "11:05", end: "11:50" },
  5: { name: "第五节", start: "14:10", end: "14:55" },
  6: { name: "第六节", start: "15:05", end: "15:50" },
  7: { name: "第七节", start: "16:10", end: "16:55" },
  8: { name: "第八节", start: "17:05", end: "17:50" },
  9: { name: "第九节", start: "18:50", end: "19:35" },
  10: { name: "第十节", start: "19:35", end: "20:20" },
  11: { name: "第十一节", start: "20:30", end: "21:15" },
  12: { name: "第十二节", start: "21:15", end: "22:00" },
};

/** 第二套时间表（艺教楼等） */
export const SECOND_SCHEDULE: Record<number, { name: string; start: string; end: string }> = {
  1: { name: "第一节", start: "08:10", end: "08:55" },
  2: { name: "第二节", start: "09:05", end: "09:50" },
  3: { name: "第三节", start: "10:30", end: "11:15" },
  4: { name: "第四节", start: "11:25", end: "12:10" },
  5: { name: "第五节", start: "14:10", end: "14:55" },
  6: { name: "第六节", start: "15:05", end: "15:50" },
  7: { name: "第七节", start: "16:30", end: "17:15" },
  8: { name: "第八节", start: "17:25", end: "18:10" },
  9: { name: "第九节", start: "18:50", end: "19:35" },
  10: { name: "第十节", start: "19:35", end: "20:20" },
  11: { name: "第十一节", start: "20:30", end: "21:15" },
  12: { name: "第十二节", start: "21:15", end: "22:00" },
};

/** 第一套教学楼 */
const FIRST_SCHEDULE_BUILDINGS = ["启智楼", "雏鹰楼", "语慧楼", "思源楼", "讯达楼", "盛德楼"];

/** 根据楼栋获取时间表 */
export function getScheduleByBuilding(building: string) {
  return FIRST_SCHEDULE_BUILDINGS.includes(building) ? FIRST_SCHEDULE : SECOND_SCHEDULE;
}

/** 默认使用第二套时间表 */
export const PERIOD_MAP = SECOND_SCHEDULE;

/** 课程 API */
export const courseApi = {
  /** 获取课程列表 */
  getList: (params?: { week_day?: number; week_number?: number; semester_id?: number }) =>
    request.get<any, ApiResponse<Course[]>>("/course/list", { params }),

  /** 获取课程表（图形化） */
  getTimetable: (week_number?: number, semester_id?: number) => {
    const params: Record<string, number> = {};
    if (week_number) params.week_number = week_number;
    if (semester_id) params.semester_id = semester_id;
    return request.get<any, ApiResponse<TimetableData>>("/course/timetable", {
      params: Object.keys(params).length ? params : undefined,
    });
  },

  /** 创建课程 */
  create: (data: Omit<Course, "id" | "created_at" | "updated_at">) =>
    request.post<any, ApiResponse<Course>>("/course", data),

  /** 更新课程 */
  update: (id: number, data: Partial<Course>) =>
    request.put<any, ApiResponse<Course>>(`/course/${id}`, data),

  /** 删除课程（硬删除，从数据库中完全删除） */
  delete: (id: number) => request.delete<any, ApiResponse>(`/course/${id}`),

  /** 切换推送提醒状态 */
  togglePush: (id: number, enabled: boolean) =>
    request.post<any, ApiResponse>(`/course/${id}/toggle-push`, { push_enabled: enabled }),

  /** 从爬虫数据导入课程 */
  import: () => request.post<any, ApiResponse<{ imported_count: number }>>("/course/import", {}),

  /** 获取学期列表 */
  getSemesters: () =>
    request.get<
      any,
      ApiResponse<{
        semesters: {
          id: number | string;
          name: string;
          eams_id?: number | string;
          is_current?: boolean;
        }[];
        current_semester_id: number | string;
        current_semester_name: string;
        weeks: string[];
      }>
    >("/course/semesters"),

  /** 爬取预约任务接口（学期切换 / 全量 / 立即 / 预约 + 增删改查） */
  crawlTasks: {
    /** 列表 */
    list: async (params?: {
      status?: string;
      scope?: string;
      page?: number;
      per_page?: number;
    }) => {
      const res = await request.get<
        any,
        ApiResponse<CrawlTask[]> & {
          pagination: { total: number; page: number; per_page: number; pages: number };
        }
      >("/course/crawl-tasks", { params });
      if (res.status !== "success") throw new Error(res.message || "请求失败");
      return {
        data: res.data ?? [],
        pagination: res.pagination ?? { total: 0, page: 1, per_page: 20, pages: 0 },
      };
    },
    /** 详情 / 状态轮询 */
    get: (id: number) => request.get<any, ApiResponse<CrawlTask>>(`/course/crawl-tasks/${id}`),
    /** 创建（scope: semester|all；schedule_type: immediate|scheduled） */
    create: (data: {
      scope: "semester" | "all";
      semester_id?: number;
      eams_id?: string;
      schedule_type: "immediate" | "scheduled";
      scheduled_at?: string;
      week?: number;
      name?: string;
    }) => request.post<any, ApiResponse<CrawlTask>>("/course/crawl-tasks", data),
    /** 更新（仅 pending 可改） */
    update: (
      id: number,
      data: {
        scope?: "semester" | "all";
        semester_id?: number;
        eams_id?: string;
        week?: number;
        schedule_type?: "immediate" | "scheduled";
        scheduled_at?: string;
        name?: string;
      }
    ) => request.put<any, ApiResponse<CrawlTask>>(`/course/crawl-tasks/${id}`, data),
    /** 删除 */
    delete: (id: number) => request.delete<any, ApiResponse>(`/course/crawl-tasks/${id}`),
    /** 取消（pending/running -> cancelled） */
    cancel: (id: number) => request.post<any, ApiResponse>(`/course/crawl-tasks/${id}/cancel`),
    /** 立即执行一个 pending 任务 */
    run: (id: number) => request.post<any, ApiResponse>(`/course/crawl-tasks/${id}/run`),
  },
};
