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
  school: string | null;
  campus_card_number: string | null;
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

// ==================== 身份绑定（/api/miniapp/student/bind） ====================

/** 绑定状态查询结果 */
export interface BindStatusResult extends ApiSuccess {
  bound: boolean;
  school: string | null;
  student_number: string | null;
  class_name: string | null;
}

/** 提交绑定结果 */
export interface BindResult extends ApiSuccess {
  bound: boolean;
  profile: StudentProfile;
}

/** 可选学校列表 */
export interface SchoolsResult extends ApiSuccess {
  schools: string[];
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
    semester_id?: number;
  };
}

export interface ScheduleSemester {
  id: number;
  name: string;
  academic_year: string;
  term: number;
  is_current: boolean;
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
    semesters?: ScheduleSemester[];
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

/**
 * 单条原始用电记录（后端 electricity_records 表的一行）
 *
 * 注意：小程序端已不再直接展示原始记录（一天会有多块分表记录，不直观），
 * 改由 ElectricityDailyRecord 按天聚合后展示。此类型仅作后端字段对照留存。
 * `record_time` 是**结算时刻**（= 用电日 + 1 天的 00:0x），不是用电日。
 */
export interface ElectricityRecord {
  id?: number;
  time?: string;
  record_time?: string;
  usage: number;
  meter?: string;
  created_at?: string;
}

/**
 * 用电记录（**按用电日聚合**，一天一条）
 *
 * 后端已把同一天的各分表合并求和：一个宿舍有【两块分表】，原始记录是一天两条，
 * 聚合后一天只有一条。`date` 是**用电日**（不是结算时刻的日期）——
 * 记录表的 record_time 是「用电日 + 1 天」的 00:0x 结算时刻，后端已换算好。
 */
export interface ElectricityDailyRecord {
  /** 用电日 YYYY-MM-DD */
  date: string;
  /** 当日各分表合计（度） */
  total_usage: number;
  /** 结算时刻 YYYY-MM-DD HH:mm:ss（用电日次日 00:0x） */
  settle_time: string | null;
}

export interface ElectricityHistoryResult extends ApiSuccess {
  data: {
    /** 按用电日倒序；limit / offset 的单位是「天」 */
    days: ElectricityDailyRecord[];
    /** 有记录的天数 */
    total: number;
    offset: number;
    limit: number;
    /** 后端懒采集标记：该学生此前无任何记录且已配置 Cookie 时，本次已自动触发首次全量采集 */
    fetch_triggered?: boolean;
  };
}

/** 单个用电日的某块分表用量 */
export interface ElectricityDailyMeter {
  /** 归一化后的电表名（已去「电表:」前缀与「照明」后缀） */
  meter: string;
  usage: number;
  /** 占当日总用电量的百分比（0-100） */
  percent: number;
}

/**
 * 某个用电日的用电详情
 *
 * 对比口径：`prev` 是「该日之前有记录的最近一天」，`avg_recent` 是
 * 「该日之前有记录的最近 N 天」的日均（按有记录天数平均，跳过无数据的日子）。
 */
export interface ElectricityDailyDetailResult extends ApiSuccess {
  data: {
    /** 用电日 YYYY-MM-DD */
    date: string;
    settle_time: string | null;
    total_usage: number;
    meter_count: number;
    meters: ElectricityDailyMeter[];
    prev: { date: string; total_usage: number } | null;
    /** 较前一日增减（度），可为负 */
    diff_prev: number | null;
    avg_recent: number | null;
    /** 参与日均计算的有记录天数（通常为 7） */
    avg_recent_days: number;
    /** 较近期日均增减（度），可为负 */
    diff_avg: number | null;
    /** 该日结算时点之后最近一次采集到的剩余电量 */
    remaining: number | null;
    remaining_at: string | null;
  };
}

export interface ElectricityTrendPoint {
  date: string; // YYYY-MM-DD
  usage: number;
}

export interface ElectricityTrendResult extends ApiSuccess {
  data: { points: ElectricityTrendPoint[] };
}

/** 本月累计用电（后端按自然月聚合，/api/miniapp/electricity/monthly） */
export interface ElectricityMonthlyResult extends ApiSuccess {
  data: {
    /** 本月累计用电量（度） */
    month_used: number;
    /** 本月起始日期 YYYY-MM-DD */
    month_start: string;
    /** 已统计天数 */
    days: number;
  };
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

/** 电量报告的每日一行（周报/月报 payload.daily 的元素） */
export interface ElectricityReportDailyItem {
  /** 用电日 YYYY-MM-DD */
  date: string;
  usage: number;
}

/**
 * 电量周报/月报的结构化 payload（站内通知 payload 字段）
 *
 * 正文 content 仍是给人读的纯文本；payload 是同一份数据的结构化形态，
 * 供消息详情页渲染成可点击的「每日用电详情」（点某天跳该日用电详情）。
 */
export interface ElectricityReportPayload {
  kind: 'electricity_report';
  report_type: 'daily' | 'weekly' | 'monthly';
  period_label: string;
  total_usage: number;
  days_count: number;
  avg_daily: number;
  meters: { meter: string; usage: number }[];
  /** 日报无此字段（只有一天） */
  daily?: ElectricityReportDailyItem[];
  remaining?: number;
}

export interface UserNotificationItem {
  id: number;
  user_id: number;
  category: string; // electricity_daily / electricity_weekly / electricity_monthly / low_power / cookie_invalid / fetch_error / announcement
  title: string;
  content: string | null; // 纯文本，\n 换行
  /** 结构化数据（可空）；老消息没有此字段，按纯文本渲染 */
  payload?: ElectricityReportPayload | Record<string, unknown> | null;
  is_read: boolean;
  /** 是否已看过（点进详情页细看）；两层已读模型：is_read=进列表已读（清外部气泡），is_viewed=点进详情已看（清卡片红点） */
  is_viewed?: boolean;
  cover_url?: string | null; // 封面图 URL（关联公告时展示）
  ref_type?: string | null; // 关联业务类型：announcement / null
  ref_id?: number | null; // 关联业务 ID（如公告 ID），点击跳转用
  created_at: string | null;
}

export interface UserNotificationListResult extends ApiSuccess {
  data: {
    notifications: UserNotificationItem[];
    /** 未读公告提醒（仅首页附带，最多 5 条；翻页不重复携带） */
    announcements: AnnouncementItem[];
    unread_count: number; // 站内通知未读（is_read 口径，外部气泡）
    unviewed_count: number; // 站内通知未看过（is_viewed 口径，卡片红点数）
    announcement_unread: number; // 公告未读
    total_unread: number; // 两者之和（角标用）
    offset: number;
    limit: number;
  };
}

/** 单条通知详情（列表只放摘要，点进详情页看全文，后端进入即记已读） */
export interface UserNotificationDetailResult extends ApiSuccess {
  data: {
    notification: UserNotificationItem;
  };
}

export interface UserNotificationReadResult extends ApiSuccess {
  data: {
    affected: number;
    unread_count: number;
    /** 剩余未看过数（/messages/viewed 接口返回；is_viewed 口径） */
    unviewed_count?: number;
    announcement_unread: number;
    total_unread: number;
  };
}

/** 消息未读统计（/api/miniapp/notifications/unread-count，角标用） */
export interface UnreadCountResult extends ApiSuccess {
  data: {
    unread: number; // 站内通知未读
    unviewed: number; // 站内通知未看过（is_viewed 口径，卡片红点数）
    announcement_unread: number; // 公告未读
    total: number; // 未读 + 公告未读之和
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
  cover_url?: string | null;     // 管理员配置的封面图（详情页 / 消息推送卡片展示；列表卡片不配图）
  channel?: string | null;       // 频道/栏目（学校要闻 / 学院动态 / 媒体聚焦…）
  channel_label?: string | null; // 频道中文（与 channel 同值）
  is_read?: boolean;             // 当前用户是否已读（详情页 GET 自动记已读；列表用于已读淡化）
  is_favorite?: boolean;         // 当前用户是否收藏
  /**
   * 列表卡片实际展示图（后端已按「配置封面 → 正文第一张图」回退）
   * 为 null 表示两者都没有；v2 列表卡片统一不配图，该字段列表不再使用。
   */
  display_cover?: string | null;
}

export interface AnnouncementListResult extends ApiSuccess {
  data: {
    items: AnnouncementItem[];
    total: number;
    page: number;
    page_size: number;
  };
}

/** 频道（列表页顶部标签，count 为该频道当前可见公告数） */
export interface AnnouncementChannel {
  key: string;
  name: string;
  count: number;
}

export interface AnnouncementChannelsResult extends ApiSuccess {
  data: {
    items: AnnouncementChannel[];
    /** 当前可见公告总数（含未填频道的），供标签上的条数定位 */
    total: number;
  };
}

/** 公告附件 */
export interface AnnouncementAttachment {
  id: number;
  announcement_id: number;
  file_name: string;
  file_size: number;
  file_size_label: string; // 如 "1.2 MB"
  /** 磁盘相对路径（不可直接下载，勿用） */
  file_url: string;
  /**
   * 小程序端下载入口（相对接口路径，需拼 API_BASE_URL）
   * 形如 /api/miniapp/announcements/attachment/<id>，走带鉴权的下载接口
   */
  download_url?: string;
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
