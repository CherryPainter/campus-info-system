/**
 * 会话失效统一处理工具
 *
 * 当用户会话因以下原因失效时，由 request 拦截器（401）或首页心跳（/auth/session/status）
 * 调用本模块，直接将页面跳转到登录页（无需用户手动点击确认、也无需手动刷新浏览器）：
 *  - new_login    ：账号已在其他设备登录（附带踢人设备 IP）
 *  - expired      ：会话自然过期
 *  - admin_revoke ：被管理员强制下线
 *  - logout       ：在其他位置主动登出
 *  - unknown      ：其他原因
 *
 * 用模块级 shown 标志保证同一页面生命周期内只触发一次跳转，避免 401 / 心跳 / 多请求并发重复跳转。
 * 失效原因写入 sessionStorage，供登录页挂载时兜底再提示一次“为何被登出”。
 *
 * 提示形式：上视口气泡（antd message.warning，自动 1.5s 后消失），不再用居中 Modal 阻塞视线，
 * 也不再塞到登录卡片里——跳转后到 /login 页时由 LoginPage 的 useEffect 再读 sessionStorage
 * 用 message 兜底弹一次，让用户知道"为什么被登出"。
 */
import { message } from "antd";

export type SessionRevokeReason =
  | "new_login"
  | "expired"
  | "admin_revoke"
  | "logout"
  | "unknown"
  | "no_session"
  | string;

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
 * 触发会话失效跳转：直接 replace 到登录页，停留不超 1.8s 让用户看清原因。
 * 跳转每次都执行（不依赖 shown 标志），确保任何一次 401 / 心跳失效都能落地跳登录页；
 * 提示仅展示一次，避免并发请求重复气泡。失效原因写入 sessionStorage，供登录页兜底提示。
 *
 * 注意：此处使用 antd **静态** message（不通过 App.useApp()）——因为调用方在 axios 拦截器与
 * 心跳钩子中，经常在 React 上下文之外触发，拿不到 useApp 实例；静态 message 不带 ConfigProvider
 * 主题，但对"会话失效"这种强一致提示影响很小。
 */
export function notifySessionExpired(detail?: SessionExpiryDetail): void {
  const msg = buildMessage(detail);

  // 兜底：写入 sessionStorage，供登录页挂载时再提示一次"为何被登出"
  try {
    sessionStorage.setItem("session_expired_reason", msg);
  } catch {
    /* 隐私模式等不可用时忽略 */
  }

  // 跳转每次都执行：即使用户不点"重新登录"，也定时回到登录页，
  // 避免停留在已失效会话页面、点啥都无反应（无需手动刷新感知）。
  window.setTimeout(() => {
    window.location.replace("/login");
  }, 1800);

  // 气泡仅展示一次（shown 只控制气泡，不控制跳转）
  if (shown) return;
  shown = true;
  // 顶部气泡，1.5s 自动消失（在 1.8s 跳转之前让用户能看到）
  message.warning({
    content: msg,
    duration: 1.5,
  });
}
