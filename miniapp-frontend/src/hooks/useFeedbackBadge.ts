import { useCallback, useState } from 'react';

import * as feedbackApi from '@/api/feedback';
import { useAuthStore } from '@/stores/authStore';
import { useNotificationSettingsStore } from '@/stores/notificationSettingsStore';
import { computeUnread, getViewedStatusMap, setSharedBadgeCount } from '@/utils/feedbackBadge';

/**
 * 反馈未读计数 hook
 *
 * refresh() 拉取「我的反馈」全量（page_size 上限 50），
 * 去掉「已看过当前状态」的 processing / resolved 反馈后即为红点数字。
 * 返回 count（红点数字，0 表示不显示）与 refresh（用于页面 show/load 时刷新）。
 *
 * 游客态保护：未登录时 refresh() 直接 no-op，避免触发 401 噪音
 * （feedback 接口需登录，但游客也可能通过 tabBar 预加载或他处被动调到此 hook）。
 *
 * 消息设置保护：用户在设置页关闭「反馈回复」或总开关后，不再显示红点，也不再发请求。
 */
export function useFeedbackBadge() {
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const { isLoggedIn } = useAuthStore();
  const { masterEnabled, feedback: feedbackEnabled } = useNotificationSettingsStore();

  const refresh = useCallback(async () => {
    if (!isLoggedIn) return; // 游客态：no-op，不发请求
    if (!masterEnabled || !feedbackEnabled) {
      // 用户已静默反馈提醒：清空红点并同步到 TabBar
      setCount(0);
      setSharedBadgeCount(0);
      return;
    }
    setLoading(true);
    try {
      const viewed = getViewedStatusMap();
      const res = await feedbackApi.getList({ page: 1, page_size: 50 });
      const items = res?.data?.items || [];
      const c = computeUnread(items, viewed);
      setCount(c);
      setSharedBadgeCount(c); // 同步到模块级共享状态，供 CustomTabBar 读取
    } catch {
      // 拉取失败保留上一次计数（不闪烁归零）
    } finally {
      setLoading(false);
    }
  }, [isLoggedIn, masterEnabled, feedbackEnabled]);

  return { count, loading, refresh };
}
