import { get } from '@/utils/request';
import type {
  WeatherAlertsResult,
  WeatherCurrentResult,
  WeatherDailyResult,
  WeatherIndicesResult,
  WeatherAirResult,
  WeatherMinutelyResult,
  WeatherHourlyResult,
} from '@/types/api';

/**
 * 天气 API（/api/miniapp/weather）
 */

/** 实时天气（后端 30 分钟 TTL，过期后台刷新） */
export function getCurrent(): Promise<WeatherCurrentResult> {
  return get<WeatherCurrentResult>('/api/miniapp/weather/current');
}

/** 24 小时逐小时预报 */
export function getHourly(): Promise<WeatherHourlyResult> {
  return get<WeatherHourlyResult>('/api/miniapp/weather/hourly');
}

/** 生效中的天气预警 */
export function getAlerts(): Promise<WeatherAlertsResult> {
  return get<WeatherAlertsResult>('/api/miniapp/weather/alerts');
}

/** 未来 7 天逐天预报（缓存 3 小时） */
export function getDaily(): Promise<WeatherDailyResult> {
  return get<WeatherDailyResult>('/api/miniapp/weather/daily');
}

/** 生活指数（缓存 6 小时） */
export function getIndices(): Promise<WeatherIndicesResult> {
  return get<WeatherIndicesResult>('/api/miniapp/weather/indices');
}

/** 实时空气质量 AQI（缓存 30 分钟） */
export function getAir(): Promise<WeatherAirResult> {
  return get<WeatherAirResult>('/api/miniapp/weather/air');
}

/** 分钟级降水（缓存 30 分钟） */
export function getMinutely(): Promise<WeatherMinutelyResult> {
  return get<WeatherMinutelyResult>('/api/miniapp/weather/minutely');
}
