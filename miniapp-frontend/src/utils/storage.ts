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
  // access token 签发时间戳（毫秒）：配合 expiresIn 计算剩余有效期，供请求层"预刷新"避免过期后首请求 401 噪音
  tokenIssuedAt: 'miniapp.tokenIssuedAt',
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
  // 记录签发时刻，用于判断剩余有效期
  Taro.setStorageSync(KEYS.tokenIssuedAt, Date.now());
}

export function clearTokens(): void {
  Taro.removeStorageSync(KEYS.accessToken);
  Taro.removeStorageSync(KEYS.refreshToken);
  Taro.removeStorageSync(KEYS.expiresIn);
  Taro.removeStorageSync(KEYS.tokenIssuedAt);
}

/**
 * access token 是否即将过期（剩余不足 leewayMs）
 * - 需要签发时间 + 有效秒数齐备才可判断（微信登录/刷新写入）
 * - storage 无 token（回退 DEV_TOKEN 的预览场景）或信息缺失 → false，不触发预刷新
 * - 返回值仅供请求层"提前刷新"参考，非过期判断的权威依据（后端 401 才是）
 */
export function isAccessTokenExpiringSoon(leewayMs = 60_000): boolean {
  const issuedAt = Taro.getStorageSync(KEYS.tokenIssuedAt);
  const expiresIn = Taro.getStorageSync(KEYS.expiresIn);
  if (typeof issuedAt !== 'number' || typeof expiresIn !== 'number') {
    return false;
  }
  const remainingMs = issuedAt + expiresIn * 1000 - Date.now();
  return remainingMs < leewayMs;
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
