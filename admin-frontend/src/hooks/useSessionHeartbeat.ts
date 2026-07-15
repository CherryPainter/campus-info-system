/**
 * 会话心跳检测 Hook
 *
 * 周期性调用 GET /api/auth/session/status 探测当前会话是否仍有效，
 * 弥补“只有发 API 请求返回 401 才发现被踢”的延迟 —— 即便页面空闲，
 * 也能在数秒内通过弹框及时告知用户“已在其他设备登录 / 会话过期”。
 *
 * 端点始终返回 200（valid 标志区分），不会触发响应拦截器的 401 逻辑。
 */
import { useCallback } from 'react';
import request from '@/api/request';
import { useIntervalPolling } from '@/hooks/useIntervalPolling';
import { POLL_NORMAL } from '@/hooks/pollIntervals';
import { notifySessionExpired } from '@/utils/sessionExpiry';

export function useSessionHeartbeat(enabled: boolean, intervalMs: number = POLL_NORMAL): void {
  const check = useCallback(async () => {
    try {
      // request 拦截器已解包一层，res 即 { valid, reason, ip, time }
      const res: any = await request.get('/auth/session/status');
      if (res && res.valid === false) {
        notifySessionExpired({ reason: res.reason, ip: res.ip, time: res.time });
      }
    } catch {
      // 网络抖动忽略，不因一次探测失败就把用户踢出
    }
  }, []);

  useIntervalPolling(check, intervalMs, enabled, true);
}
