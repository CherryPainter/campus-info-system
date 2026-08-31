import { get } from '@/utils/request';
import type { NotificationListResult } from '@/types/api';

/**
 * 近期提醒 API（/api/miniapp/notifications）
 *
 * v6.16.0 第三阶段接入真实后端接口：
 * - 列表（卡片用）：GET /api/miniapp/notifications/upcoming?limit=5
 * - 全部（更多页用）：GET /api/miniapp/notifications/all
 */

export interface UpcomingParams {
  limit?: number; // 默认 5，上限 50
}

/** 近期提醒（默认 5 条，首页/时间轴"近期提醒"卡片用） */
export function getUpcoming(params?: UpcomingParams): Promise<NotificationListResult> {
  const q = params?.limit ? `?limit=${Math.max(1, Math.min(params.limit, 50))}` : '';
  return get<NotificationListResult>(`/api/miniapp/notifications/upcoming${q}`);
}

/** 全部未过期活跃事件（"更多"列表页用，不限 remind_days 窗口） */
export function getAll(): Promise<NotificationListResult> {
  return get<NotificationListResult>('/api/miniapp/notifications/all');
}