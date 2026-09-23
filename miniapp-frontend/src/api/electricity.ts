import { get, post, put } from '@/utils/request';
import type {
  ApiSuccess,
  ElectricityCookieConfigResult,
  ElectricityCookieTestResult,
  ElectricityCurrentResult,
  ElectricityDailyDetailResult,
  ElectricityHistoryResult,
  ElectricityMonthlyResult,
  ElectricityTrendResult,
} from '@/types/api';

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

/** 用电记录（**按用电日聚合，一天一条**；limit/offset 的单位是「天」不是条数） */
export function getDailyRecords(
  limit = 30,
  offset = 0,
): Promise<ElectricityHistoryResult> {
  return get<ElectricityHistoryResult>('/api/miniapp/electricity/history', { limit, offset });
}

/**
 * 某个用电日的用电详情（总用量 + 各分表明细 + 对比 + 结算后剩余电量）
 *
 * 口径：一个宿舍有两块分表，后端已归一化电表名并按天合计。
 * 该用电日无记录时后端返回 404。
 */
export function getDailyDetail(date: string): Promise<ElectricityDailyDetailResult> {
  return get<ElectricityDailyDetailResult>(`/api/miniapp/electricity/daily/${date}`);
}

/** 用电趋势（按日聚合，range: day|week|month），仅返回少量点 */
export function getTrend(
  range: 'day' | 'week' | 'month' = 'week',
): Promise<ElectricityTrendResult> {
  return get<ElectricityTrendResult>('/api/miniapp/electricity/trend', { range });
}

/**
 * 本月累计用电量（后端按自然月聚合）
 *
 * 此前由前端各自拉取记录在本地累加，我的页拉 1000 条、详情页只拉首屏 20 条，
 * 同一月份显示成两个不同数字。统一走后端聚合保证口径一致。
 */
export function getMonthlyUsage(): Promise<ElectricityMonthlyResult> {
  return get<ElectricityMonthlyResult>('/api/miniapp/electricity/monthly');
}

/** 电表 Cookie 配置状态（脱敏：configured + cookie_preview） */
export function getCookieConfig(): Promise<ElectricityCookieConfigResult> {
  return get<ElectricityCookieConfigResult>('/api/miniapp/electricity/cookie');
}

/** 保存本人电表爬虫 Cookie（仅本人可写，存在 student_profiles.electricity_cookie） */
export function saveCookie(cookie: string): Promise<ApiSuccess> {
  return put<ApiSuccess>('/api/miniapp/electricity/cookie', { cookie });
}

/** 测试 Cookie 是否有效（不落库，仅检测） */
export function testCookie(cookie: string): Promise<ElectricityCookieTestResult> {
  return post<ElectricityCookieTestResult>('/api/miniapp/electricity/cookie/test', { cookie });
}
