import { get, post } from '@/utils/request';
import type {
  UnreadCountResult,
  UserNotificationDetailResult,
  UserNotificationListResult,
  UserNotificationReadResult,
} from '@/types/api';

/**
 * 个人站内通知 API（/api/miniapp/notifications/messages）
 *
 * 与「近期提醒」（教学日历事件）、「校园公告」不同：
 * 这里是个人的站内消息 —— 电量日报/周报/月报、低电量提醒、Cookie 失效提醒等，
 * 由后端定时任务按用户生成；同时附带未读公告提醒，学生在「我的消息」页查看。
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

/**
 * 单条通知详情
 *
 * 消息列表只展示摘要（电量日报/月报正文较长，全部铺开会让列表很臃肿），
 * 点进详情页看完整内容；后端进入详情即自动标记已读。
 */
export function getNotificationDetail(id: number): Promise<UserNotificationDetailResult> {
  return get<UserNotificationDetailResult>(`/api/miniapp/notifications/messages/${id}`);
}

/** 标记已读：id 指定单条；不传 id 则全部标记已读（联动清空未读公告） */
export function markRead(id?: number): Promise<UserNotificationReadResult> {
  const data: Record<string, unknown> = {};
  if (id != null) data.id = id;
  return post<UserNotificationReadResult>('/api/miniapp/notifications/messages/read', data);
}

/** 标记已看过（点进详情页细看）：清卡片右上角红点用。仅置该条 is_viewed=True */
export function markViewed(id: number): Promise<UserNotificationReadResult> {
  return post<UserNotificationReadResult>('/api/miniapp/notifications/messages/viewed', { id });
}

/** 消息未读统计（站内通知 + 公告，我的页角标用） */
export function getUnreadCount(): Promise<UnreadCountResult> {
  return get<UnreadCountResult>('/api/miniapp/notifications/unread-count');
}
