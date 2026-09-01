import Taro from '@tarojs/taro';

import { get, post, API_BASE_URL } from '@/utils/request';
import { getAccessToken } from '@/utils/storage';
import type {
  FeedbackCreateResult,
  FeedbackDetailResult,
  FeedbackListResult,
  FeedbackType,
  FeedbackUploadResult,
} from '@/types/api';

/**
 * 意见与反馈 API（/api/miniapp/feedback）
 *
 * 与「校园通知」完全不同方向：这里是学生 → 管理员的反向通道，
 * 后端独立成表（feedbacks），前端独立页面，不混入消息中心。
 */

export interface FeedbackCreateParams {
  type: FeedbackType;
  content: string;
  contact?: string;
  images?: string[];
}

export interface FeedbackListParams {
  page?: number;
  page_size?: number;
}

/** 提交反馈 */
export function create(data: FeedbackCreateParams): Promise<FeedbackCreateResult> {
  return post<FeedbackCreateResult>('/api/miniapp/feedback', data as Record<string, unknown>);
}

/** 我的反馈列表（分页） */
export function getList(params?: FeedbackListParams): Promise<FeedbackListResult> {
  const q = new URLSearchParams();
  if (params?.page) q.set('page', String(params.page));
  if (params?.page_size) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  return get<FeedbackListResult>(`/api/miniapp/feedback${qs ? `?${qs}` : ''}`);
}

/** 反馈详情（含管理员回复） */
export function getDetail(id: number): Promise<FeedbackDetailResult> {
  return get<FeedbackDetailResult>(`/api/miniapp/feedback/${id}`);
}

/**
 * 上传反馈截图（Taro.uploadFile，字段名 file）
 * 成功返回后端图片 URL（如 /api/feedback-images/xxx.png）
 */
export function uploadImage(filePath: string): Promise<string> {
  const token = getAccessToken();
  const header: Record<string, string> = {};
  if (token) header.Authorization = `Bearer ${token}`;

  return new Promise<string>((resolve, reject) => {
    Taro.uploadFile({
      url: `${API_BASE_URL}/api/miniapp/feedback/upload`,
      filePath,
      name: 'file',
      header,
      success: (res) => {
        try {
          const body = JSON.parse(res.data) as FeedbackUploadResult;
          if (res.statusCode === 200 && body.errno === 0 && body.data?.url) {
            resolve(body.data.url);
          } else {
            reject(new Error(body.message || '图片上传失败'));
          }
        } catch {
          reject(new Error('图片上传失败'));
        }
      },
      fail: (err) => {
        const msg = (err as { errMsg?: string })?.errMsg || '图片上传失败';
        reject(new Error(msg));
      },
    });
  });
}
