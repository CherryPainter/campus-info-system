import { post } from '@/utils/request';
import type { LoginResult, RefreshResult } from '@/types/api';

/**
 * 认证 API（/api/miniapp/auth）
 * - login / refresh 不需要鉴权（auth: false）
 */

export function login(code: string): Promise<LoginResult> {
  return post<LoginResult>('/api/miniapp/auth/login', { code }, { auth: false });
}

export function refresh(refreshToken: string): Promise<RefreshResult> {
  return post<RefreshResult>(
    '/api/miniapp/auth/refresh',
    { refresh_token: refreshToken },
    { auth: false },
  );
}

export function logout(refreshToken?: string): Promise<{ status: string; message?: string }> {
  return post('/api/miniapp/auth/logout', refreshToken ? { refresh_token: refreshToken } : {});
}
