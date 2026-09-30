import { get, post } from '@/utils/request';
import type {
  AnnouncementListResult,
  AnnouncementDetailResult,
  AnnouncementChannelsResult,
} from '@/types/api';

/**
 * 校园通知（公告）API（/api/miniapp/announcements）
 *
 * 与「近期提醒」(notifications) 是两套业务：
 * - 校园通知：管理员发布的公告，含标题/摘要/部门/正文，纯拉取
 * - 近期提醒：学校日历类事件（考试/节假日/讲座），带日期与倒计时
 */

export interface AnnouncementListParams {
  category?: string; // notice/activity/urgent/system，缺省或 all 表示全部
  channel?: string; // 频道精确筛选，缺省 / all / 全部 表示全部；"我的关注" 由 only_favorite 处理
  keyword?: string; // 关键词搜索（标题 + 摘要）
  page?: number;
  page_size?: number;
  only_unread?: boolean;
  only_favorite?: boolean; // 我的关注 / 我的收藏
}

/** 校园通知列表（首页卡片用，默认取前 3 条已发布且未过期） */
export function getList(params?: AnnouncementListParams): Promise<AnnouncementListResult> {
  const q = new URLSearchParams();
  if (params?.category && params.category !== 'all') q.set('category', params.category);
  // 「全部」与「我的关注」不是真实频道，不下发 channel 参数（缺省即全部口径）
  if (params?.channel && params.channel !== 'all' && params.channel !== '全部' && params.channel !== '我的关注') {
    q.set('channel', params.channel);
  }
  if (params?.keyword) q.set('keyword', params.keyword);
  if (params?.page) q.set('page', String(params.page));
  if (params?.page_size) q.set('page_size', String(params.page_size));
  if (params?.only_unread) q.set('only_unread', 'true');
  if (params?.only_favorite) q.set('only_favorite', 'true');
  const qs = q.toString();
  return get<AnnouncementListResult>(`/api/miniapp/announcements${qs ? `?${qs}` : ''}`);
}

/**
 * 频道清单（列表页顶部频道标签的数据源）
 *
 * 后端只统计当前可见且填写了频道的公告，返回 [{ key, name, count }]，
 * 按公告数量倒序。该清单始终是全量口径，不随当前筛选变化。
 */
export function getChannels(): Promise<AnnouncementChannelsResult> {
  return get<AnnouncementChannelsResult>('/api/miniapp/announcements/channels');
}

/** 我的收藏列表（only_favorite=1，仅返回该用户收藏过的通知） */
export function getFavorites(params?: { page?: number; page_size?: number }): Promise<AnnouncementListResult> {
  return getList({ ...params, only_favorite: true });
}

/** 通知详情（含正文、附件、相关推荐；首次访问自动记已读） */
export function getDetail(id: number): Promise<AnnouncementDetailResult> {
  return get<AnnouncementDetailResult>(`/api/miniapp/announcements/${id}`);
}

/** 收藏 / 取消收藏（toggle），返回操作后的 is_favorite */
export function toggleFavorite(id: number): Promise<{ data: { is_favorite: boolean } }> {
  return post(`/api/miniapp/announcements/${id}/favorite`);
}

/** 显式标记已读（底部按钮用；正常浏览已自动记已读） */
export function markRead(id: number): Promise<{ data: { is_read: true } }> {
  return post(`/api/miniapp/announcements/${id}/read`);
}
