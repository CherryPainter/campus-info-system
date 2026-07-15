/**
 * Axios 请求实例模块
 * 封装 Axios 并配置请求/响应拦截器
 * 
 * 注意：现在使用 httpOnly cookie 存储 JWT token，前端无需手动设置 Authorization 头
 * 浏览器会自动携带 cookie 到后端
 */

import axios, { type AxiosRequestConfig } from 'axios';
import { notifySessionExpired } from '@/utils/sessionExpiry';

/** 后端 API 基础地址
 * 开发环境（.env.development）配置为 http://yuetang.cloud:29528/api，直接调用后端避免 Cookie 域名问题
 * 生产环境默认使用相对路径 /api，由 Nginx 反向代理转发到后端
 * 可通过 VITE_API_BASE_URL 环境变量覆盖默认行为
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

/** 创建 Axios 实例，配置基础 URL 和超时时间 */
const request = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  // 允许跨域请求携带 cookie
  withCredentials: true,
});

/**
 * 请求拦截器：GET 请求附加时间戳缓存破坏器（_t）
 * 双保险：即便后端未下发 no-store，也能保证每次轮询 URL 唯一，
 * 避免浏览器/代理把爬虫状态、任务详情等 GET 响应缓存成陈旧值。
 */
request.interceptors.request.use((config) => {
  if ((config.method || 'get').toLowerCase() === 'get') {
    config.params = { ...(config.params || {}), _t: Date.now() };
  }
  return config;
});

/** Token 刷新锁，防止并发请求同时触发多次刷新 */
let isRefreshing = false;
/** 等待刷新完成的请求队列 */
let pendingRequests: Array<() => void> = [];
/** 标记是否正在跳转到登录页，防止重复跳转 */
let isRedirectingToLogin = false;
/** 记录最后一次刷新失败的时间，防止短时间内反复重试 */
let lastRefreshFailedAt = 0;
/** 刷新失败后的冷却时间（毫秒），10秒内不再尝试刷新 */
const REFRESH_COOLDOWN_MS = 10000;

/**
 * 响应拦截器
 * - 成功响应：直接返回 response.data（解包一层）
 * - 401 错误：尝试刷新令牌，然后重发原始请求（登录请求除外）
 * - 刷新失败：跳转到登录页
 * - 网络错误：标记为服务器离线状态
 */
request.interceptors.response.use(
  (response) => {
    // 请求成功，触发在线事件
    const event = new CustomEvent('server-online');
    window.dispatchEvent(event);
    return response.data;
  },
  async (error) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean };

    // 检测网络错误（服务器离线）
    if (!error.response) {
      const event = new CustomEvent('server-offline', { 
        detail: { message: '无法连接到服务器，请检查后端服务是否运行' }
      });
      window.dispatchEvent(event);
      return Promise.reject({ ...error, isOffline: true });
    }

    // 检测 502/503/504 错误（网关错误）
    if ([502, 503, 504].includes(error.response?.status)) {
      const event = new CustomEvent('server-offline', { 
        detail: { message: '服务器暂时不可用，请检查后端服务是否运行' }
      });
      window.dispatchEvent(event);
      return Promise.reject({ ...error, isOffline: true });
    }

    // 检测 401 错误且尚未重试过，且不是登录请求
    const isLoginRequest = originalRequest.url?.includes('/auth/login');
    const isRefreshRequest = originalRequest.url?.includes('/auth/refresh');
    
    if (error.response?.status === 401 && !originalRequest._retry && !isLoginRequest && !isRefreshRequest) {
      originalRequest._retry = true;

      // 提取会话失效原因，用于跳转登录页时弹框提示用户
      const errData = (error.response?.data || {}) as {
        message?: string;
        revoke_reason?: string;
        revoke_ip?: string;
      };
      const authFailReason = errData.message || '您的登录会话已失效，请重新登录。';

      // 检查是否在冷却时间内
      const now = Date.now();
      if (now - lastRefreshFailedAt < REFRESH_COOLDOWN_MS) {
        // 在冷却时间内，直接弹框提示并跳登录页，不再尝试刷新
        if (!isRedirectingToLogin) {
          isRedirectingToLogin = true;
          notifySessionExpired({ reason: errData.revoke_reason, ip: errData.revoke_ip });
        }
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // 正在刷新中，将请求加入队列等待
        return new Promise((resolve) => {
          pendingRequests.push(() => {
            resolve(request(originalRequest));
          });
        });
      }

      isRefreshing = true;

      try {
        // 调用刷新接口（会自动使用 httpOnly cookie 中的 refresh_token）
        await axios.post(`${API_BASE_URL}/auth/refresh`, {}, { withCredentials: true });

        // 刷新成功，重置冷却时间
        lastRefreshFailedAt = 0;

        // 通知所有等待中的请求
        pendingRequests.forEach((cb) => cb());
        pendingRequests = [];

        // 重发原始请求
        return request(originalRequest);
      } catch {
        // 刷新失败，记录失败时间并弹框提示后跳登录页
        lastRefreshFailedAt = Date.now();
        pendingRequests = [];
        if (!isRedirectingToLogin) {
          isRedirectingToLogin = true;
          notifySessionExpired({ reason: errData.revoke_reason, ip: errData.revoke_ip });
        }
        return Promise.reject(error);
      } finally {
        isRefreshing = false;
      }
    }

    // 其他错误：不在这里显示 message，让调用方自己处理
    return Promise.reject(error);
  }
);

export default request;
