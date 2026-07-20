/**
 * 会话失效统一弹框工具
 *
 * 当用户会话因以下原因失效时，由 request 拦截器（401）或首页心跳（/auth/session/status）
 * 调用本模块，弹出“仅确认”警告框，并在用户点确认后跳登录页：
 *  - new_login    ：账号已在其他设备登录（附带踢人设备 IP）
 *  - expired      ：会话自然过期
 *  - admin_revoke ：被管理员强制下线
 *  - logout       ：在其他位置主动登出
 *  - unknown      ：其他原因
 *
 * 用模块级 shown 标志保证同一页面生命周期内只弹一次，避免 401 / 心跳 / 多请求并发重复弹框。
 */
import { Modal } from "antd";

export type SessionRevokeReason =
  "new_login" | "expired" | "admin_revoke" | "logout" | "unknown" | "no_session" | string;

export interface SessionExpiryDetail {
  reason?: SessionRevokeReason;
  ip?: string;
  time?: string;
}

let shown = false;

function buildMessage(detail?: SessionExpiryDetail): string {
  const ip = detail?.ip;
  switch (detail?.reason) {
    case "new_login":
      return ip
        ? `您的账号已在其他设备登录（设备 IP：${ip}），当前会话已被强制下线，请重新登录。`
        : "您的账号已在其他设备登录，当前会话已被强制下线，请重新登录。";
    case "expired":
      return "登录会话已过期，请重新登录。";
    case "admin_revoke":
      return "您的会话已被管理员强制下线，请重新登录。";
    case "logout":
      return "您已在其他位置登出，请重新登录。";
    default:
      return "您的登录会话已失效，请重新登录。";
  }
}

/**
 * 弹出会话失效警告框（仅“确认”按钮），点确认后跳登录页。
 * 同时把最终文案写入 sessionStorage，供登录页挂载时兜底再提示一次。
 */
export function notifySessionExpired(detail?: SessionExpiryDetail): void {
  if (shown) return;
  shown = true;

  const msg = buildMessage(detail);

  Modal.warning({
    title: "登录会话已失效",
    content: msg,
    okText: "确认",
    centered: true,
    closable: false,
    onOk: () => {
      window.location.href = "/login";
    },
  });
}
