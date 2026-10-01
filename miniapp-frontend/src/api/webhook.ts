import { get, post, put, del } from '@/utils/request';
import type { ApiSuccess } from '@/types/api';

/**
 * 第三方消息通知（学生自建 webhook）API
 * 路径前缀 /api/miniapp，路由见 app/api/miniapp_routes.py
 *
 * 服务端强制 scope=student + scope_target=[本人]，客户端无法篡改接收范围。
 */

/** 学生自建 webhook 结构（与后端 Webhook.to_dict 对齐） */
export interface ThirdPartyWebhook {
  id: number;
  name: string;
  url: string;
  /** 模块名逗号串，如 "course,electricity" */
  modules: string;
  /** 由 modules 解析出的模块数组 */
  module_list: string[];
  /** 固定为 student（服务端强制） */
  scope: 'student';
  /** 固定为 [本人 user_id]（服务端强制） */
  scope_target: number[] | null;
  is_enabled: boolean;
  description?: string | null;
  last_test_status?: 'success' | 'failed' | 'pending' | null;
  last_test_time?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  owner_user_id?: number | null;
}

export interface WebhookListResult extends ApiSuccess {
  data: ThirdPartyWebhook[];
}

export interface WebhookDetailResult extends ApiSuccess {
  data: ThirdPartyWebhook;
}

/** 学生可配置的个人相关模块白名单（与后端 _STUDENT_WEBHOOK_MODULES 一致） */
export const STUDENT_WEBHOOK_MODULES = [
  { value: 'course', label: '课表' },
  { value: 'electricity', label: '电量' },
  { value: 'weather', label: '天气' },
] as const;

/** 列出本人创建的 webhook */
export function listMine(): Promise<WebhookListResult> {
  return get<WebhookListResult>('/api/miniapp/webhooks');
}

/** 创建本人 webhook */
export function createWebhook(data: {
  name: string;
  url: string;
  modules?: string | string[];
  description?: string;
  is_enabled?: boolean;
}): Promise<WebhookDetailResult> {
  return post<WebhookDetailResult>('/api/miniapp/webhooks', data);
}

/** 更新本人 webhook */
export function updateWebhook(
  id: number,
  data: {
    name?: string;
    url?: string;
    modules?: string | string[];
    description?: string;
    is_enabled?: boolean;
  },
): Promise<WebhookDetailResult> {
  return put<WebhookDetailResult>(`/api/miniapp/webhooks/${id}`, data);
}

/** 删除本人 webhook */
export function deleteWebhook(id: number): Promise<ApiSuccess> {
  return del<ApiSuccess>(`/api/miniapp/webhooks/${id}`);
}

/** 测试本人 webhook */
export function testWebhook(id: number): Promise<ApiSuccess> {
  return post<ApiSuccess>(`/api/miniapp/webhooks/${id}/test`);
}
