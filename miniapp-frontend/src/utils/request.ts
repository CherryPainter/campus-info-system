import Taro from '@tarojs/taro';

import { getAccessToken, getRefreshToken, isAccessTokenExpiringSoon, setTokens } from './storage';
import { useUserStore } from '@/stores/userStore';
import { useAuthStore } from '@/stores/authStore';

/**
 * 统一请求层（全项目唯一出口）
 *
 * - 自动注入 `Authorization: Bearer <accessToken>`
 * - 401 时自动用 refreshToken 换新（单飞锁防并发），成功后重放原请求
 * - refresh 失败 → 降级为游客 + 只提示一次（**不强制跳转登录页**，合规要求）
 * - 所有错误归一为 ApiError（用户可读中文消息），页面无需感知底层 HTTP
 *
 * 使用：
 *   const data = await request<LoginResult>({ url: '/api/miniapp/auth/login', method: 'POST', data: { code }, auth: false });
 */

export const API_BASE_URL: string =
  process.env.TARO_APP_API_BASE || 'http://127.0.0.1:29528';

// 匿名会话令牌（服务端在公开接口下发 X-Anon-Token，客户端存本地、后续带回，
// 用于公开接口按会话溯源 + 限流）。此处仅做本地存取，不参与任何鉴权。
const ANON_TOKEN_KEY = 'miniapp.anonToken';

function getAnonToken(): string {
  try {
    return (Taro.getStorageSync(ANON_TOKEN_KEY) as string) || '';
  } catch {
    return '';
  }
}

function captureAnonToken(header?: Record<string, string>): void {
  if (!header) return;
  // 微信会把响应头 key 转小写，两种都试
  const t = header['X-Anon-Token'] || header['x-anon-token'];
  if (t && typeof t === 'string' && t.length > 0) {
    try {
      Taro.setStorageSync(ANON_TOKEN_KEY, t);
    } catch {
      /* 存储失败忽略 */
    }
  }
}

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

/**
 * 保证返回一个「未过期」的 accessToken（临近过期则先刷新再返回）
 *
 * 供 `Taro.uploadFile` / `Taro.downloadFile` 等**不走 request 封装**的场景使用：
 * 这些原生 API 没有 401 自动续期能力，若不预先刷新，上传会因 accessToken 过期
 * 直接 401 失败（表现为「反馈图片传不上去」，而其它接口却正常）。
 *
 * @returns 可用的 accessToken；刷新失败或无 token 时返回空串/null
 */
export async function ensureFreshAccessToken(force = false): Promise<string | null> {
  if (force || isAccessTokenExpiringSoon()) {
    const ok = await refreshOnce();
    if (!ok) return null;
  }
  return getAccessToken();
}

/** 会话过期提示节流标记：并发请求同时 401 时只提示一次，避免反复打扰 */
let sessionExpiredNotified = false;

/**
 * 会话过期处理（合规改造）
 *
 * 旧行为：清空令牌 + reLaunch 到登录页 —— 属于「强制用户登录才能继续使用」，
 * 且刷新失败时多个并发请求会连续触发跳转，违反微信审核
 * 「不得反复弹窗或强制用户进行登录才能体验」。
 *
 * 新行为：仅把本地登录态降级为游客 + 提示一次（toast，非弹窗），
 * 用户可继续浏览天气/通知公告等公开内容；需要登录的功能在用户**主动点击**时
 * 由各页面 LoginModal 引导，登录后即可正常使用。
 */
function handleSessionExpired(): void {
  try {
    useAuthStore.getState().logout();
  } catch {
    /* store 不可用时忽略：令牌已失效，后续请求自然走游客分支 */
  }
  if (sessionExpiredNotified) return;
  sessionExpiredNotified = true;
  Taro.showToast({ title: '登录状态已过期，可继续浏览公开内容', icon: 'none', duration: 2000 });
  setTimeout(() => {
    sessionExpiredNotified = false;
  }, 3000);
}

/** 登录成功后重置过期提示节流（登录页调用） */
export function resetSessionExpiredNotice(): void {
  sessionExpiredNotified = false;
}
/** 身份未绑定防抖标记：多个业务请求同时 403 时只触发一次跳转 */
let isRedirectingToBind = false;

/** 403 code=STUDENT_NOT_BOUND 时统一跳身份绑定页（reLaunch 替换栈，无法返回跳过） */
function redirectToBind(): void {
  if (isRedirectingToBind) return;
  isRedirectingToBind = true;
  // 清空本地身份缓存：解绑/未绑定后，"我的"/校园卡/UserInfoCard 不应再显旧学号班级
  try {
    useUserStore.getState().setProfile(null);
  } catch {
    /* 忽略 */
  }
  Taro.reLaunch({ url: '/pages/bind/index' });
  setTimeout(() => {
    isRedirectingToBind = false;
  }, 2000);
}

export async function request<T = unknown>(options: RequestOptions): Promise<T> {
  const { url, method = 'GET', data, auth = true, _retried, timeout = 10000 } = options;

  const header: Record<string, string> = { 'Content-Type': 'application/json' };
  // 回传匿名会话令牌（服务端公开接口据此按会话溯源 + 限流）
  const anonToken = getAnonToken();
  if (anonToken) {
    header['X-Anon-Token'] = anonToken;
  }
  if (auth) {
    // 预刷新：access token 即将过期且有 refresh token 时提前换新，
    // 避免过期后首次请求的 401——微信开发者工具控制台会把每次 401 打印成红字，
    // 即使随后自动刷新重放成功也会造成"报错"错觉。刷新失败不阻断，走下方 401 兜底。
    if (isAccessTokenExpiringSoon() && getRefreshToken()) {
      await refreshOnce();
    }
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
    // 捕获服务端下发的匿名会话令牌（无论成败都回写，公开接口总会下发）
    captureAnonToken(res.header as Record<string, string> | undefined);
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
    // 区分「会话过期」与「游客 / 已登出」：
    // - 本地曾持有令牌（登录态失效）→ 降级为游客并只提示一次，**不强制跳登录页**；
    // - 本地无任何令牌（游客首次进入 / 已登出）→ 不跳转，交由调用方 .catch
    //   展示游客态或弹登录引导，满足「先体验后授权」审核规范，避免一进页面就被弹登录。
    if (!getAccessToken() && !getRefreshToken()) {
      throw new ApiError('请先登录后查看', 401);
    }
    handleSessionExpired();
    throw new ApiError('登录已过期，请重新登录', 401);
  }

  // 403 + code=STUDENT_NOT_BOUND：身份未绑定 → 跳绑定页（绑定接口本身不会触发，
  // 仅业务接口命中；绑定失败的业务码是普通 403 无 code，页面自行 toast）
  if (res.statusCode === 403 && auth) {
    const body = res.data as { code?: string };
    if (body?.code === 'STUDENT_NOT_BOUND') {
      redirectToBind();
      throw new ApiError('请先完成身份认证', 403, res.data);
    }
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

/** DELETE 便捷方法：query 参数拼到 URL（Taro.request 的 data 走 body 不走 query） */
export function del<T = unknown>(url: string, params?: Record<string, unknown>, options?: Partial<RequestOptions>): Promise<T> {
  let finalUrl = url;
  if (params && Object.keys(params).length > 0) {
    const qs = Object.entries(params)
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&');
    if (qs) finalUrl += (url.includes('?') ? '&' : '?') + qs;
  }
  return request<T>({ url: finalUrl, method: 'DELETE', ...options });
}
