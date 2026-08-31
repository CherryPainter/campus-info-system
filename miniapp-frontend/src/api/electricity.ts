import { get } from '@/utils/request';
import type { ElectricityCurrentResult, ElectricityHistoryResult, ElectricityTrendResult } from '@/types/api';

/**
 * 电量 API（/api/miniapp/electricity）
 */

/** 剩余电量（含百分比 / 总量 / 低电量标记） */
export function getCurrent(): Promise<ElectricityCurrentResult> {
  return get<ElectricityCurrentResult>('/api/miniapp/electricity/current');
}

/** 轻量刷新剩余电量：触发一次实时爬取并返回最新值（后端 60s 冷却） */
export function refresh(): Promise<ElectricityCurrentResult> {
  return get<ElectricityCurrentResult>('/api/miniapp/electricity/refresh');
}

/** 用电记录（按需分页：limit 每页条数，offset 偏移；days 可选最近 N 天） */
export function getHistory(
  limit = 30,
  offset = 0,
  days?: number,
): Promise<ElectricityHistoryResult> {
  const params: Record<string, unknown> = { limit, offset };
  if (days != null) params.days = days;
  return get<ElectricityHistoryResult>('/api/miniapp/electricity/history', params);
}

/** 用电趋势（按日聚合，range: day|week|month），仅返回少量点 */
export function getTrend(
  range: 'day' | 'week' | 'month' = 'week',
): Promise<ElectricityTrendResult> {
  return get<ElectricityTrendResult>('/api/miniapp/electricity/trend', { range });
}
