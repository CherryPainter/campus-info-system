import Taro from '@tarojs/taro';

import { get, post, API_BASE_URL, ensureFreshAccessToken } from '@/utils/request';
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
  return post<FeedbackCreateResult>('/api/miniapp/feedback', data as unknown as Record<string, unknown>);
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

/** 单次上传（不带任何重试逻辑） */
function uploadOnce(token: string | null, filePath: string): Promise<string> {
  const header: Record<string, string> = {};
  if (token) header.Authorization = `Bearer ${token}`;

  return new Promise<string>((resolve, reject) => {
    Taro.uploadFile({
      url: `${API_BASE_URL}/api/miniapp/feedback/upload`,
      filePath,
      name: 'file',
      header,
      success: (res) => {
        // 注意：uploadFile 的 success 只代表"请求发出并收到响应"，
        // HTTP 4xx/5xx 同样会进这里，必须自己判 statusCode
        if (res.statusCode === 413) {
          reject(new Error('图片过大被服务器拒绝，请压缩后再试'));
          return;
        }
        try {
          const body = JSON.parse(res.data) as FeedbackUploadResult & {
            message?: string;
          };
          if (res.statusCode === 200 && body.errno === 0 && body.data?.url) {
            resolve(body.data.url);
            return;
          }
          // 401 带上标记，便于上层判断是否需要刷新 token 重试
          if (res.statusCode === 401) {
            reject(new Error(`401 ${body.message || '登录已过期'}`));
            return;
          }
          reject(new Error(body.message || `图片上传失败（${res.statusCode}）`));
        } catch {
          reject(new Error(`图片上传失败（${res.statusCode}）`));
        }
      },
      fail: (err) => {
        const msg = (err as { errMsg?: string })?.errMsg || '图片上传失败';
        reject(new Error(normalizeUploadError(msg)));
      },
    });
  });
}

/**
 * 把微信底层错误翻译成人话
 *
 * 线上最常见的失败是「小程序后台没配 uploadFile 合法域名」：
 * uploadFile 的白名单与 request 的白名单是**两个独立配置**，只配了 request 域名时
 * 其它接口全部正常、唯独上传失败；且开发者工具勾选"不校验合法域名"可绕过，
 * 真机/体验版则严格校验 —— 表现为"本地能传，线上不能传"。
 */
function normalizeUploadError(msg: string): string {
  if (/url not in domain list/i.test(msg)) {
    return '上传域名未加入小程序白名单，请在微信公众平台配置 uploadFile 合法域名';
  }
  if (/time ?out/i.test(msg)) {
    return '上传超时，请检查网络后重试';
  }
  if (/fail file (not found|error)/i.test(msg)) {
    return '读取图片失败，请重新选择';
  }
  return msg || '图片上传失败';
}

/**
 * 上传反馈截图（Taro.uploadFile，字段名 file）
 * 成功返回后端图片 URL（如 /api/feedback-images/xxx.png）
 *
 * 说明：uploadFile 不走 request 封装（原生 API 无拦截器），因此这里手动补齐
 * token 预刷新 + 401 重试，否则 token 过期时上传必然失败。
 */
export async function uploadImage(filePath: string): Promise<string> {
  const token = await ensureFreshAccessToken();
  try {
    return await uploadOnce(token, filePath);
  } catch (e) {
    const msg = (e as Error).message || '';
    // 仅鉴权失败时强制刷新 token 后重试一次，其它错误（如域名白名单）直接抛出
    if (/^401/.test(msg)) {
      const fresh = await ensureFreshAccessToken(true);
      if (fresh) return await uploadOnce(fresh, filePath);
    }
    throw e;
  }
}
