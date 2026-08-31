/**
 * Token 存储工具模块
 *
 * 鉴权设计（标准 JWT Bearer + httpOnly refresh cookie）：
 * - 登录成功：后端在响应体返回 access_token；前端将其存入 localStorage，
 *   每次请求经 request 拦截器以 `Authorization: Bearer <access_token>` 头携带。
 * - refresh_token 由后端以 httpOnly cookie 下发（JS 不可读），
 *   刷新时浏览器经 withCredentials 自动随请求携带，前端不接触、不存储。
 *
 * 安全边界：
 * - access_token 短时效且可轮换，即使被 XSS 窃取影响有限；
 * - refresh_token 存于 httpOnly cookie，对 XSS 免疫，是现代 SPA 的推荐做法。
 *
 * 同源说明：开发走 Vite 代理（/api → localhost:29528，同源），
 * 生产由 Nginx 同源反代，故 httpOnly cookie 可正常种/读，不会出现跨域丢失。
 */

const ACCESS_TOKEN_KEY = "admin_access_token";

export const tokenStorage = {
  /** 获取当前 access_token（Bearer 头用），无则返回 null */
  getAccessToken: (): string | null => {
    try {
      return localStorage.getItem(ACCESS_TOKEN_KEY);
    } catch {
      return null;
    }
  },

  /** 仅更新 access_token（登录成功 / 刷新成功后调用） */
  setAccessToken: (access: string): void => {
    try {
      localStorage.setItem(ACCESS_TOKEN_KEY, access);
    } catch {
      // localStorage 不可用时静默降级（隐私模式等），不影响当前内存态请求
    }
  },

  /** 登录成功时持久化 access_token（refresh_token 由 httpOnly cookie 承载，前端不持有） */
  setTokens: (access: string): void => {
    try {
      localStorage.setItem(ACCESS_TOKEN_KEY, access);
    } catch {
      // 静默降级
    }
  },

  /** 清除 access_token（登出 / 会话失效时调用；refresh_token 由后端过期失效） */
  clearTokens: (): void => {
    try {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
    } catch {
      // 静默降级
    }
  },
};
