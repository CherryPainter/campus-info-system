/**
 * Token 存储工具模块
 *
 * 注意：现在使用 httpOnly cookie 存储 token，前端无法直接访问
 * 这个文件保留用于兼容性，实际 token 由后端通过 Set-Cookie 设置
 */

/**
 * Token 存储工具类
 *
 * 由于使用 httpOnly cookie，前端无法直接读取 token
 * 所有 API 请求会自动携带 cookie
 */
export const tokenStorage = {
  /**
   * 获取访问令牌
   * @returns 始终返回 null（使用 httpOnly cookie）
   */
  getAccessToken: (): string | null => {
    return null;
  },

  /**
   * 获取刷新令牌
   * @returns 始终返回 null（使用 httpOnly cookie）
   */
  getRefreshToken: (): string | null => {
    return null;
  },

  /**
   * 同时保存访问令牌和刷新令牌
   * @deprecated 现在使用 httpOnly cookie，前端不再存储 token
   */
  setTokens: (access: string, refresh: string): void => {
    // 不再存储到 localStorage，token 由后端通过 cookie 设置
    console.warn("Token 现在使用 httpOnly cookie 存储，前端不再存储");
  },

  /**
   * 清除所有令牌
   * 调用后端登出接口会自动清除 cookie
   */
  clearTokens: (): void => {
    // 清除任何遗留的 localStorage 数据
    localStorage.removeItem("admin_access_token");
    localStorage.removeItem("admin_refresh_token");
  },
};
