import { get, post, put, del } from '@/utils/request';
import type { ApiSuccess } from '@/types/api';

/**
 * 第三方消息通知（学生端 webhook）API
 * 路径前缀 /api/miniapp，路由见 app/api/miniapp_routes.py
 *
 * 可见/可管理口径（服务端围栏，防 API 直调越权）：
 * - 学生本人自建（owner_user_id == 本人）：可看、可改、可删；
 * - 管理员代建且定向到本人（scope=student 命中本人，或 scope=dorm 命中本人宿舍）：
 *   同样可看、可改、可删，但其 owner/scope/scope_target 属「是谁在用」元数据，不允许学生篡改；
 * - 超出本人范围的（含 global、他人、其他宿舍）：不可见、不可管理。
 * 学生自建时服务端仍强制 scope=student + scope_target=[本人]。
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
  /** 接收范围：student=指定学生；dorm=指定宿舍；global=全局广播。
   *  学生自建恒为 student；管理员代建可为三者之一（按管理端配置）。 */
  scope: 'student' | 'global' | 'dorm';
  /** 接收范围目标：student 时为命中 user_id 列表（数字）；dorm 时为宿舍字符串列表；
   *  global 时为 null。学生自建恒为 [本人 user_id]。 */
  scope_target: (number | string)[] | null;
  is_enabled: boolean;
  description?: string | null;
  last_test_status?: 'success' | 'failed' | 'pending' | null;
  last_test_time?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  /** 为空（NULL）表示管理员代建；非空表示学生本人自建 */
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
