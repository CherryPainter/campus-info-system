/**
 * 前端 API 类型定义（唯一依据：后端 Flask 接口实际返回结构，勿虚构字段）
 */

// ==================== 通用 ====================

export interface ApiSuccess {
  status: string;
  message?: string;
}

// ==================== 认证（/api/miniapp/auth） ====================

export interface UserInfo {
  id: number;
  username: string;
  email: string | null;
  avatar: string | null;
  role: string;
  is_active: boolean;
  is_primary: boolean;
  last_login: string | null;
  last_login_ip: string | null;
  created_at: string | null;
}

export interface LoginResult extends ApiSuccess {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: UserInfo;
  is_new_user: boolean;
}

export interface RefreshResult extends ApiSuccess {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

// ==================== 用户 / 学生资料（/api/miniapp/user、/student） ====================

export interface StudentProfile {
  user_id: number;
  student_number: string | null;
  real_name: string | null;
  nickname: string | null;
  college: string | null;
  major: string | null;
  class_name: string | null;
  grade: string | null;
  phone: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface UserMeResult extends ApiSuccess {
  user: UserInfo;
}

export interface StudentProfileResult extends ApiSuccess {
  profile: StudentProfile;
}

// ==================== 课表（/api/miniapp/schedule） ====================

export interface ScheduleCourse {
  schedule_id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  course_name: string;
  course_code: string;
  period_idx: number;
  periods: number[] | string;
  extra_info: {
    teacher: string;
    building: string;
    classroom: string;
    weeks: number[] | string;
    credits: string;
    full_date: string;
  };
  _timeInfo: {
    start_ts: number;
    end_ts: number;
    is_today?: boolean;
  };
}

export interface ScheduleTodayResult extends ApiSuccess {
  data: { courses: ScheduleCourse[] };
}

export interface AvailableWeek {
  week_number: number;
  start_date: string;
  end_date: string;
}

export interface ScheduleWeekResult extends ApiSuccess {
  data: {
    courses: ScheduleCourse[];
    week_number: number;
    available_weeks: AvailableWeek[];
  };
}

export interface ScheduleCurrentResult extends ApiSuccess {
  data: {
    week_number: number;
    is_teaching_week: boolean;
    date: string;
    week_day: number;
    semester_id: number;
    semester_name: string;
    available_weeks: AvailableWeek[];
  };
}

// ==================== 天气（/api/miniapp/weather） ====================

export interface WeatherNow {
  city_name?: string;
  temp?: number;
  text?: string;
  humidity?: number;
  wind_dir?: string;
  wind_scale?: string;
  feels_like?: number;
  vis?: number;
  cloud?: number | null;
  pressure?: number | null;
  update_time?: string;
  created_at?: string;
}

export interface WeatherCurrentResult extends ApiSuccess {
  data: { weather: WeatherNow | null };
}

export interface WeatherHourlyItem {
  fx_time?: string;
  fxTime?: string;
  temp?: string;
  text?: string;
  pop?: string | number;   // 降水概率(%)，和风返回字符串
}

export interface WeatherHourlyResult extends ApiSuccess {
  data: { hourly: WeatherHourlyItem[] };
}

export interface WeatherAlert {
  alert_id?: string;
  headline?: string;
  severity?: string;
  color_code?: string;
  description?: string;
  city_name?: string;
  created_at?: string;
}

export interface WeatherAlertsResult extends ApiSuccess {
  data: { warnings: WeatherAlert[] };
}

// 逐天预报（/api/miniapp/weather/daily）
export interface WeatherDailyItem {
  fx_date?: string;
  temp_max?: string | number;
  temp_min?: string | number;
  text_day?: string;
  text_night?: string;
  icon_day?: string;
  pop?: string | number;
  wind_dir_day?: string;
  wind_scale_day?: string;
}

export interface WeatherDailyResult extends ApiSuccess {
  data: { daily: WeatherDailyItem[] };
}

// 生活指数（/api/miniapp/weather/indices）
export interface WeatherIndexItem {
  type?: string;
  name?: string;
  category?: string;
  text?: string;
}

export interface WeatherIndicesResult extends ApiSuccess {
  data: { indices: WeatherIndexItem[] };
}

// 空气质量（/api/miniapp/weather/air）
export interface WeatherAir {
  aqi?: string | number;
  category?: string;
  primary?: string;
  level?: string | number;
  pm2p5?: string | number;
  pm10?: string | number;
  update_time?: string;
}

export interface WeatherAirResult extends ApiSuccess {
  data: { air: WeatherAir | null };
}

// 分钟级降水（/api/miniapp/weather/minutely）
export interface WeatherMinutelyItem {
  fx_time?: string;
  precip?: string | number;
  type?: string;
}

export interface WeatherMinutelyResult extends ApiSuccess {
  data: {
    minutely: {
      summary?: string;
      minutely: WeatherMinutelyItem[];
    } | null;
  };
}

// ==================== 电量（/api/miniapp/electricity） ====================

export interface ElectricityCurrent {
  remaining: number;
  total_capacity: number;
  percentage: number;
  is_low_power: boolean;
  recorded_at?: string;
  created_at?: string;
  meter?: string;
}

export interface ElectricityCurrentResult extends ApiSuccess {
  data: { electricity: ElectricityCurrent | null; cookie_configured: boolean };
}

export interface ElectricityRecord {
  id?: number;
  time?: string;
  record_time?: string;
  usage: number;
  meter?: string;
  created_at?: string;
}

export interface ElectricityHistoryResult extends ApiSuccess {
  data: {
    records: ElectricityRecord[];
    total: number;
    offset: number;
    limit: number;
  };
}

export interface ElectricityTrendPoint {
  date: string; // YYYY-MM-DD
  usage: number;
}

export interface ElectricityTrendResult extends ApiSuccess {
  data: { points: ElectricityTrendPoint[] };
}

// ==================== 电表 Cookie 配置（/api/miniapp/electricity/cookie） ====================

export interface ElectricityCookieConfigResult extends ApiSuccess {
  data: {
    configured: boolean;
    cookie_preview: string; // 脱敏预览（前4后2），未配置为空串
  };
}

export interface ElectricityCookieTestResult extends ApiSuccess {
  data: {
    valid: boolean;
    reason: string;
  };
}

// ==================== 个人站内通知（/api/miniapp/notifications/messages） ====================

export interface UserNotificationItem {
  id: number;
  user_id: number;
  category: string; // electricity_daily / electricity_weekly / electricity_monthly / low_power / cookie_invalid / fetch_error
  title: string;
  content: string | null; // 纯文本，\n 换行
  is_read: boolean;
  created_at: string | null;
}

export interface UserNotificationListResult extends ApiSuccess {
  data: {
    notifications: UserNotificationItem[];
    unread_count: number;
    offset: number;
    limit: number;
  };
}

export interface UserNotificationReadResult extends ApiSuccess {
  data: {
    affected: number;
    unread_count: number;
  };
}

// ==================== 近期提醒（v6.16.0 第三阶段）====================

export interface NotificationEvent {
  id: number;
  title: string;
  event_date: string;            // ISO 时间
  event_date_label: string;      // MM-DD（直接展示用）
  category: 'exam' | 'holiday' | 'activity' | 'other';
  remind_days: number;
  sort_order: number;
  is_active: boolean;
  description: string | null;
  days_left: number;             // 距离事件天数（负=已过期）
  is_expired: boolean;
}

export interface NotificationListResult extends ApiSuccess {
  data: { events: NotificationEvent[]; count: number };
}

// ==================== 校园通知（公告）====================

export interface AnnouncementItem {
  id: number;
  title: string;
  category: string;              // notice/activity/urgent/system
  category_label: string;        // 中文标签，如「通知」
  summary: string | null;        // 摘要（列表页展示）
  department: string | null;     // 发布部门
  is_top: boolean;               // 是否置顶
  status: string;                // published 等
  published_at: string | null;   // ISO 时间
  published_label: string | null; // 已格式化，如「2026-08-31 14:30」
  expired_at: string | null;
  view_count: number;
}

export interface AnnouncementListResult extends ApiSuccess {
  data: {
    items: AnnouncementItem[];
    total: number;
    page: number;
    page_size: number;
  };
}

/** 公告附件 */
export interface AnnouncementAttachment {
  id: number;
  announcement_id: number;
  file_name: string;
  file_size: number;
  file_size_label: string; // 如 "1.2 MB"
  file_url: string;
}

/** 相关推荐条目（详情页底部）*/
export interface RelatedAnnouncement {
  id: number;
  title: string;
  category: string;
  published_label: string | null;
}

/** 公告详情（含正文/附件/相关推荐/收藏状态） */
export interface AnnouncementDetail extends AnnouncementItem {
  content: string | null;           // 富文本正文
  attachments: AnnouncementAttachment[];
  related: RelatedAnnouncement[];
  is_favorite: boolean;
  is_read: boolean;
}

export interface AnnouncementDetailResult extends ApiSuccess {
  data: { announcement: AnnouncementDetail };
}

// ==================== 意见与反馈（/api/miniapp/feedback） ====================

/** 反馈类型（与后端 FEEDBACK_TYPES 一一对应） */
export type FeedbackType = 'bug' | 'suggest' | 'consult' | 'other';

/** 反馈处理状态 */
export type FeedbackStatus = 'pending' | 'processing' | 'resolved';

/** 反馈列表项（列表用，with_reply=false，不含管理员回复） */
export interface FeedbackItem {
  id: number;
  user_id: number;
  type: FeedbackType;
  type_label: string;
  content: string;
  contact: string;
  images: string[];
  status: FeedbackStatus;
  status_label: string;
  created_at: string;
  updated_at: string;
}

/** 反馈详情（含管理员回复） */
export interface FeedbackDetail extends FeedbackItem {
  reply: string;
  replied_at: string;
}

export interface FeedbackListResult extends ApiSuccess {
  data: {
    items: FeedbackItem[];
    total: number;
    page: number;
    page_size: number;
  };
}

export interface FeedbackDetailResult extends ApiSuccess {
  data: { feedback: FeedbackDetail };
}

export interface FeedbackCreateResult extends ApiSuccess {
  data: { id: number };
}

/** 图片上传返回（WangEditor 约定：{ errno, data:{ url } }） */
export interface FeedbackUploadResult {
  errno: number;
  data: { url: string; alt?: string; href?: string };
  message?: string;
}
