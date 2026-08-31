import Taro from '@tarojs/taro';

/**
 * Token / 用户信息持久化（封装 Taro 同步 storage）
 * - Token 由统一 request 层读写，页面代码不得直接操作
 * - 小程序端自己保存双 Token，不依赖 cookie
 */

const KEYS = {
  accessToken: 'miniapp.accessToken',
  refreshToken: 'miniapp.refreshToken',
  expiresIn: 'miniapp.expiresIn',
  userInfo: 'miniapp.userInfo',
} as const;

// 开发期预览用：在 .env 配置 TARO_APP_DEV_TOKEN 后，未登录（storage 无 token）时
// 回退使用该 dev token，使小程序走真实接口预览（真实天气 + 库里课表数据），
// 绕过微信登录。生产构建不配置该变量即可，不影响真实登录流程。
const DEV_TOKEN = (process.env.TARO_APP_DEV_TOKEN as string | undefined) || '';

export function getAccessToken(): string {
  return Taro.getStorageSync(KEYS.accessToken) || DEV_TOKEN;
}

export function getRefreshToken(): string {
  return Taro.getStorageSync(KEYS.refreshToken) || '';
}

export function setTokens(accessToken: string, refreshToken: string, expiresIn?: number): void {
  Taro.setStorageSync(KEYS.accessToken, accessToken);
  Taro.setStorageSync(KEYS.refreshToken, refreshToken);
  if (expiresIn) {
    Taro.setStorageSync(KEYS.expiresIn, expiresIn);
  }
}

export function clearTokens(): void {
  Taro.removeStorageSync(KEYS.accessToken);
  Taro.removeStorageSync(KEYS.refreshToken);
  Taro.removeStorageSync(KEYS.expiresIn);
}

export function getUserInfo<T = Record<string, unknown>>(): T | null {
  return Taro.getStorageSync(KEYS.userInfo) || null;
}

export function setUserInfo<T = Record<string, unknown>>(user: T): void {
  Taro.setStorageSync(KEYS.userInfo, user);
}

export function clearUserInfo(): void {
  Taro.removeStorageSync(KEYS.userInfo);
}
