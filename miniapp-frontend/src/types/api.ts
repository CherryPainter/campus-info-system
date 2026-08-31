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
  data: { electricity: ElectricityCurrent | null };
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
