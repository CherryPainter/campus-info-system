/**
 * 认证相关 API 模块
 */

import request from "./request";
import type { ApiResponse } from "@/types/api";
import type { User } from "@/types/user";

/** 认证相关响应（带 MFA token / 登录用户） */
export type AuthApiResponse<T = unknown> = ApiResponse<T> & {
  mfa_token?: string;
  user?: User;
};

/** 登录响应数据类型 */
export interface LoginResponse {
  status: string;
  message?: string;
  mfa_token?: string;
  user?: User;
}

/** MFA 设置响应数据 */
export interface MfaSetupResponse {
  secret: string;
  provisioning_uri: string;
  qr_code_base64: string;
}

/** MFA 状态响应 */
export interface MfaStatusResponse {
  enabled: boolean;
}

/** 活跃会话数据类型 */
export interface UserSession {
  session_id: string;
  ip_address: string;
  user_agent: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  is_active: boolean;
  remember_me: boolean;
  /** 管理员总览视图下返回所属用户信息 */
  owner_username?: string;
  owner_role?: string;
  owner_is_primary?: boolean;
}

/**
 * 认证 API
 */
export const authApi = {
  /**
   * 用户登录
   * @param rememberMe 是否记住我（长会话）：勾选 30 天，不勾 24 小时
   */
  login: (username: string, password: string, rememberMe = false) =>
    request.post<any, LoginResponse>("/auth/login", {
      username,
      password,
      remember_me: rememberMe,
    }),

  /**
   * 刷新访问令牌
   * 后端从 httpOnly cookie 中读取 refresh_token，无需传参
   */
  refresh: () => request.post<any, ApiResponse>("/auth/refresh"),

  /**
   * 用户登出
   */
  logout: () => request.post<any, ApiResponse>("/auth/logout"),

  /**
   * 获取当前登录用户信息
   */
  getMe: () => request.get<any, AuthApiResponse<User>>("/auth/me"),

  /**
   * 获取 MFA 状态
   */
  getMfaStatus: () => request.get<any, ApiResponse<MfaStatusResponse>>("/auth/mfa/status"),

  /**
   * 设置 MFA（生成密钥和二维码）
   */
  setupMfa: () => request.post<any, ApiResponse<MfaSetupResponse>>("/auth/mfa/setup"),

  /**
   * 验证 MFA 代码并启用
   */
  verifyMfa: (code: string) => request.post<any, ApiResponse>("/auth/mfa/verify", { code }),

  /**
   * 禁用 MFA
   */
  disableMfa: (code: string) => request.post<any, ApiResponse>("/auth/mfa/disable", { code }),

  /**
   * 获取当前用户的活跃会话列表
   */
  getSessions: () => request.get<any, ApiResponse<{ sessions: UserSession[] }>>("/auth/sessions"),

  /**
   * 撤销指定会话（踢出特定设备）
   */
  revokeSession: (sessionId: string) =>
    request.delete<any, ApiResponse>(`/auth/sessions/${sessionId}`),

  /**
   * 撤销所有其他会话（保留当前设备）
   */
  revokeAllSessions: () => request.delete<any, ApiResponse<{ count: number }>>("/auth/sessions"),
};
