import { useCallback, useState } from 'react';

import * as feedbackApi from '@/api/feedback';
import { computeUnread, getViewedIds } from '@/utils/feedbackBadge';

/**
 * 反馈未读计数 hook
 *
 * refresh() 拉取「我的反馈」全量（page_size 上限 50），
 * 去掉已读的 resolved 反馈后即为红点数字。
 * 返回 count（红点数字，0 表示不显示）与 refresh（用于页面 show/load 时刷新）。
 */
export function useFeedbackBadge() {
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const viewed = getViewedIds();
      const res = await feedbackApi.getList({ page: 1, page_size: 50 });
      const items = res?.data?.items || [];
      setCount(computeUnread(items, viewed));
    } catch {
      // 拉取失败保留上一次计数（不闪烁归零）
    } finally {
      setLoading(false);
    }
  }, []);

  return { count, loading, refresh };
}
