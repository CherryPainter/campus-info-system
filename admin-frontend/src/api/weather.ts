/**
 * 天气相关 API 模块
 */

import request from "./request";
import type { ApiResponse } from "@/types/api";

/** 实时天气数据 */
export interface WeatherNow {
  city_name: string;
  temp: string;
  feels_like: string;
  text: string;
  humidity: string;
  wind_dir: string;
  wind_scale: string;
  update_time: string;
}

/** 逐小时预报 */
export interface HourlyForecast {
  time: string;
  temp: string;
  text: string;
  pop: string;
  humidity: string;
  wind_dir: string;
}

/** 天气预警 */
export interface WeatherAlert {
  id: string;
  alert_id: string;
  headline: string;
  event_type: string;
  severity: string;
  description: string;
  color_code: string;
  is_active?: boolean;
  is_pushed?: boolean;
  created_at?: string;
  start_time?: string;
  end_time?: string;
}

/** 天气配置 */
export interface WeatherConfig {
  auth_type?: "jwt_ed25519" | "api_key" | "none";
  credential_id?: string;
  project_id_configured?: boolean;
  private_key_configured?: boolean;
  api_key_configured?: boolean;
  api_key?: string;
  project_id?: string;
  location?: string;
  city_name?: string;
  daily_push_time?: string;
  quiet_hours_enabled?: boolean;
  quiet_hours_start?: string;
  quiet_hours_end?: string;
  daily_push_limit?: number;
  alert_enabled?: boolean;
}

/** 天气统计数据 */
export interface WeatherStatistics {
  now: WeatherNow | null;
  hourly: HourlyForecast[];
}

/**
 * 天气 API
 * 所有端点需要 JWT Bearer Token 认证（由 request 拦截器自动添加）
 */
export const weatherApi = {
  /** 获取实时天气 */
  getNow: () => request.get<any, ApiResponse<WeatherNow>>("/weather/now"),

  /** 获取24h预报 */
  getHourly: () => request.get<any, ApiResponse<HourlyForecast[]>>("/weather/hourly"),

  /** 获取预警信息 */
  getAlert: () => request.get<any, ApiResponse<{ warnings: WeatherAlert[] }>>("/weather/alert"),

  /** 获取预警历史（分页加载） */
  getAlertHistory: (page = 1, page_size = 20) =>
    request.get<
      any,
      ApiResponse<WeatherAlert[]> & {
        pagination: { page: number; page_size: number; total: number; total_pages: number };
      }
    >("/weather/alert/history", { params: { page, page_size } }),

  /** 获取天气统计数据（实时 + 24h 预报） */
  getStatistics: () => request.get<any, ApiResponse<WeatherStatistics>>("/weather/statistics"),
};
