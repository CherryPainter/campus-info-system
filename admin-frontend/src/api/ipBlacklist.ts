/**
 * IP 黑名单管理 API 模块
 */

import request from './request';
import type { ApiResponse } from '@/types/api';
import { IP_SOURCE_MAP, IP_EVENT_TYPE_MAP } from '@/constants/statusMaps';

/** 黑名单来源中文映射（定义已迁至 statusMaps.ts，此处保留导出以兼容既有引用） */
export const SOURCE_CN = IP_SOURCE_MAP;
/** 事件类型中文映射（定义已迁至 statusMaps.ts，此处保留导出以兼容既有引用） */
export const EVENT_TYPE_CN = IP_EVENT_TYPE_MAP;

/** 黑名单记录 */
export interface IPBlacklistRecord {
  id: number;
  ip_address: string;
  reason: string | null;
  source: string;
  is_active: boolean;
  request_count: number;
  blocked_at: string | null;
  expires_at: string | null;
  created_by: string | null;
  note: string | null;
  created_at: string | null;
}

/** 安全事件记录 */
export interface IPSecurityEvent {
  id: number;
  ip_address: string;
  event_type: string;
  path: string | null;
  method: string | null;
  user_agent: string;
  detail: string | null;
  severity: string;
  is_blocked: boolean;
  is_ignored: boolean;
  created_at: string | null;
}

/** 黑名单列表响应 */
export interface BlacklistListResp {
  records: IPBlacklistRecord[];
  total: number;
  page: number;
  per_page: number;
}

/** 安全事件列表响应 */
export interface SecurityEventListResp {
  events: IPSecurityEvent[];
  total: number;
  page: number;
  per_page: number;
}

const ipBlacklistApi = {
  /** 获取黑名单列表 */
  getList: async (params: { page?: number; per_page?: number; only_active?: boolean }) => {
    const res = await request.get<any, ApiResponse<BlacklistListResp>>('/admin/ip-blacklist', { params });
    if (res.status !== 'success') throw new Error(res.message || '请求失败');
    const d = res.data ?? { records: [], total: 0, page: 1, per_page: 20 };
    return {
      data: d.records,
      pagination: {
        total: d.total,
        page: d.page,
        per_page: d.per_page,
        pages: d.per_page ? Math.ceil(d.total / d.per_page) : 0,
      },
    };
  },

  /** 手动添加 IP 到黑名单 */
  add: (data: { ip_address: string; reason?: string; duration_hours?: number | null; note?: string }) =>
    request.post<any, ApiResponse<IPBlacklistRecord>>('/admin/ip-blacklist', data),

  /** 从黑名单移除 IP */
  remove: (ip: string) =>
    request.delete<any, ApiResponse>(`/admin/ip-blacklist/${encodeURIComponent(ip)}`),

  /** 启用/禁用黑名单记录 */
  toggle: (ip: string, active: boolean) =>
    request.put<any, ApiResponse<IPBlacklistRecord>>(`/admin/ip-blacklist/${encodeURIComponent(ip)}/toggle`, { active }),

  /** 更新黑名单记录（封禁期限/原因/备注/状态） */
  update: (ip: string, data: { reason?: string; duration_hours?: number | null; note?: string; is_active?: boolean }) =>
    request.put<any, ApiResponse<IPBlacklistRecord>>(`/admin/ip-blacklist/${encodeURIComponent(ip)}/update`, data),

  /** 获取安全事件列表（归一为统一的 Paginated<IPSecurityEvent>） */
  getEvents: async (params: { page?: number; per_page?: number; event_type?: string; severity?: string; only_pending?: boolean }) => {
    const res = await request.get<any, ApiResponse<SecurityEventListResp>>('/admin/ip-blacklist/events', { params });
    if (res.status !== 'success') throw new Error(res.message || '请求失败');
    const d = res.data ?? { events: [], total: 0, page: 1, per_page: 20 };
    return {
      data: d.events,
      pagination: {
        total: d.total,
        page: d.page,
        per_page: d.per_page,
        pages: d.per_page ? Math.ceil(d.total / d.per_page) : 0,
      },
    };
  },

  /** 将安全事件标记为已忽略 */
  ignoreEvent: (eventId: number) =>
    request.post<any, ApiResponse>(`/admin/ip-blacklist/events/${eventId}/ignore`),

  /** 封禁安全事件对应的 IP */
  banEvent: (eventId: number, data?: { reason?: string; duration_hours?: number | null }) =>
    request.post<any, ApiResponse>(`/admin/ip-blacklist/events/${eventId}/ban`, data || {}),

  /** 清理过期黑名单记录 */
  cleanup: () =>
    request.post<any, ApiResponse<{ cleaned_count: number }>>('/admin/ip-blacklist/cleanup'),
};

export default ipBlacklistApi;
