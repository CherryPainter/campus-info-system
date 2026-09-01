import { useCallback, useState } from 'react';

import * as feedbackApi from '@/api/feedback';
import { computeUnread, getViewedStatusMap, setSharedBadgeCount } from '@/utils/feedbackBadge';

/**
 * 反馈未读计数 hook
 *
 * refresh() 拉取「我的反馈」全量（page_size 上限 50），
 * 去掉「已看过当前状态」的 processing / resolved 反馈后即为红点数字。
 * 返回 count（红点数字，0 表示不显示）与 refresh（用于页面 show/load 时刷新）。
 */
export function useFeedbackBadge() {
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
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
  }, []);

  return { count, loading, refresh };
}
