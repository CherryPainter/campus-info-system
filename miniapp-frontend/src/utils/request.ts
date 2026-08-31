import Taro from '@tarojs/taro';

import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './storage';

/**
 * 统一请求层（全项目唯一出口）
 *
 * - 自动注入 `Authorization: Bearer <accessToken>`
 * - 401 时自动用 refreshToken 换新（单飞锁防并发），成功后重放原请求
 * - refresh 失败 / 无 refreshToken → 清空本地 Token 并回到登录页
 * - 所有错误归一为 ApiError（用户可读中文消息），页面无需感知底层 HTTP
 *
 * 使用：
 *   const data = await request<LoginResult>({ url: '/api/miniapp/auth/login', method: 'POST', data: { code }, auth: false });
 */

export const API_BASE_URL: string =
  process.env.TARO_APP_API_BASE || 'http://127.0.0.1:29528';

export class ApiError extends Error {
  /** HTTP 状态码；网络层错误为 -1 */
  code: number;
  data?: unknown;

  constructor(message: string, code = -1, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.data = data;
  }
}

export interface RequestOptions {
  url: string;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  data?: Record<string, unknown>;
  /** 需要鉴权（默认 true；登录 / 刷新为 false） */
  auth?: boolean;
  /** 内部重试标记，防止 401 死循环 */
  _retried?: boolean;
  /** 超时毫秒，默认 10000 */
  timeout?: number;
}

function friendlyMessage(statusCode: number, body: unknown): string {
  const msg = (body as { message?: string })?.message;
  if (msg) return msg;
  switch (statusCode) {
    case 401:
      return '登录已过期，请重新登录';
    case 403:
      return '没有权限访问';
    case 404:
      return '请求的资源不存在';
    case 429:
      return '请求过于频繁，请稍后再试';
    case 500:
      return '服务器开小差了，请稍后重试';
    default:
      return `请求失败（${statusCode}）`;
  }
}

/** 使用 refreshToken 换新双 Token（不经过 request 包装，避免循环依赖） */
async function doRefresh(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return false;
  }
  try {
    const res = await Taro.request({
      url: `${API_BASE_URL}/api/miniapp/auth/refresh`,
      method: 'POST',
      data: { refresh_token: refreshToken },
      timeout: 10000,
    });
    const body = res.data as { access_token?: string; refresh_token?: string; expires_in?: number };
    if (res.statusCode === 200 && body.access_token && body.refresh_token) {
      setTokens(body.access_token, body.refresh_token, body.expires_in);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

/** 401 单飞锁：多个请求同时 401 时只触发一次 refresh */
let refreshingPromise: Promise<boolean> | null = null;

function refreshOnce(): Promise<boolean> {
  if (!refreshingPromise) {
    refreshingPromise = doRefresh().finally(() => {
      refreshingPromise = null;
    });
  }
  return refreshingPromise;
}

function redirectToLogin(): void {
  clearTokens();
  Taro.reLaunch({ url: '/pages/login/index' });
}

export async function request<T = unknown>(options: RequestOptions): Promise<T> {
  const { url, method = 'GET', data, auth = true, _retried, timeout = 10000 } = options;

  const header: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = getAccessToken();
    if (token) {
      header.Authorization = `Bearer ${token}`;
    }
  }

  let res: Taro.request.SuccessCallbackResult;
  try {
    res = await Taro.request({
      url: `${API_BASE_URL}${url}`,
      method,
      data,
      header,
      timeout,
    });
  } catch (err) {
    // 网络错误 / 超时（Taro 在非 2xx 时也可能走 fail，统一按网络异常处理）
    const msg = (err as { errMsg?: string })?.errMsg || '';
    if (msg.includes('timeout')) {
      throw new ApiError('请求超时，请稍后重试');
    }
    throw new ApiError('网络异常，请检查网络后重试');
  }

  // 2xx 直接返回响应体
  if (res.statusCode >= 200 && res.statusCode < 300) {
    return res.data as T;
  }

  // 401：尝试刷新一次后重放
  if (res.statusCode === 401 && auth && !_retried) {
    const ok = await refreshOnce();
    if (ok) {
      return request<T>({ ...options, _retried: true });
    }
    redirectToLogin();
    throw new ApiError('登录已过期，请重新登录', 401);
  }

  throw new ApiError(friendlyMessage(res.statusCode, res.data), res.statusCode, res.data);
}

/** GET 便捷方法 */
export function get<T = unknown>(url: string, params?: Record<string, unknown>, options?: Partial<RequestOptions>): Promise<T> {
  return request<T>({ url, method: 'GET', data: params, ...options });
}

/** POST 便捷方法 */
export function post<T = unknown>(url: string, data?: Record<string, unknown>, options?: Partial<RequestOptions>): Promise<T> {
  return request<T>({ url, method: 'POST', data, ...options });
}

/** PUT 便捷方法 */
export function put<T = unknown>(url: string, data?: Record<string, unknown>, options?: Partial<RequestOptions>): Promise<T> {
  return request<T>({ url, method: 'PUT', data, ...options });
}
