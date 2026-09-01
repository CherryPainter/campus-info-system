import { get, post } from '@/utils/request';
import type { UserNotificationListResult, UserNotificationReadResult } from '@/types/api';

/**
 * 个人站内通知 API（/api/miniapp/notifications/messages）
 *
 * 与「近期提醒」（教学日历事件）、「校园公告」不同：
 * 这里是个人的站内消息 —— 电量日报/周报/月报、低电量提醒、Cookie 失效提醒等，
 * 由后端定时任务按用户生成，学生在「我的消息」页查看。
 */

/** 通知列表（limit 每页条数，offset 偏移；unreadOnly 为 true 时仅返回未读） */
export function getMessages(
  limit = 20,
  offset = 0,
  unreadOnly = false,
): Promise<UserNotificationListResult> {
  const params: Record<string, unknown> = { limit, offset };
  if (unreadOnly) params.unread_only = 1;
  return get<UserNotificationListResult>('/api/miniapp/notifications/messages', params);
}

/** 标记已读：id 指定单条；不传 id 则全部标记已读 */
export function markRead(id?: number): Promise<UserNotificationReadResult> {
  const data: Record<string, unknown> = {};
  if (id != null) data.id = id;
  return post<UserNotificationReadResult>('/api/miniapp/notifications/messages/read', data);
}
