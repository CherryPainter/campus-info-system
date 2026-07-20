import { useEffect, useRef } from "react";

/**
 * 固定间隔重复执行某个 fetcher（用于页面周期刷新、时钟、存活探测等）。
 * 自动处理定时器清理与组件卸载，避免各页面手写 setInterval 导致的泄漏。
 */
export function useIntervalPolling(
  fetcher: () => void | Promise<any>,
  intervalMs: number,
  enabled = true,
  /** 启用时是否立即执行一次；某些场景需延迟首个周期以避开竞态或避免挂载双拉，可传 false */
  immediate = true
) {
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const tick = () => {
      if (alive) fetcherRef.current();
    };
    if (immediate) tick();
    const timer = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [enabled, intervalMs, immediate]);
}
