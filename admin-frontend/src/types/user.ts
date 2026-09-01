/**
 * 前端统一用户类型
 * 合并原 auth.ts 的 UserInfo 与 admin.ts 的 User（id 统一为 number）。
 */

export interface User {
  id: number;
  username: string;
  email?: string;
  nickname?: string;
  bio?: string;
  avatar?: string;
  role: string;
  is_active: boolean;
  is_primary: boolean;
  mfa_enabled: boolean;
  /** 登录来源分流：wechat=微信端小程序（openid 登录，无密码/MFA），web=网页端 */
  source?: "wechat" | "web";
  last_login?: string;
  last_login_ip?: string;
  created_at?: string;
}
