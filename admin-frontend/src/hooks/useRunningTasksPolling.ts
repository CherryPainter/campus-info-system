import { useEffect, useRef, useState } from "react";
import type { TaskProcess } from "../api/admin";

export interface RunningTasksResponse {
  status: string;
  data?: { data: TaskProcess[]; count: number };
}

export interface RunningTasksOptions {
  /** 拉取运行中任务列表的接口调用 */
  fetcher: () => Promise<RunningTasksResponse>;
  /** 按任务类型等条件过滤 */
  filter?: (t: TaskProcess) => boolean;
  /** 轮询间隔（毫秒），默认 2000 */
  intervalMs?: number;
  /** 是否启用，默认 true */
  enabled?: boolean;
  /** 运行中列表为空（即全部结束）回调，通常用于刷新数据并停止轮询 */
  onIdle?: () => void;
  /** 仍有运行中任务时回调 */
  onRunning?: (tasks: TaskProcess[]) => void;
}

/**
 * 轮询“运行中任务列表”，列表为空则视为全部结束并触发 onIdle。
 * 合并 Course/Weather/Electricity 三处同质的“查运行中列表 -> 空则刷新”逻辑。
 */
export function useRunningTasksPolling(options: RunningTasksOptions) {
  const [running, setRunning] = useState<TaskProcess[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const optsRef = useRef(options);
  optsRef.current = options;

  useEffect(() => {
    if (!options.enabled) {
      setIsPolling(false);
      return;
    }
    let alive = true;
    const interval = options.intervalMs ?? 2000;

    const stop = () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      if (alive) setIsPolling(false);
    };

    const tick = async () => {
      try {
        const resp = await optsRef.current.fetcher();
        if (!alive) return;
        let tasks = resp.data?.data ?? [];
        if (optsRef.current.filter) tasks = tasks.filter(optsRef.current.filter);
        setRunning(tasks);
        if (tasks.length === 0) {
          stop();
          optsRef.current.onIdle?.();
        } else {
          optsRef.current.onRunning?.(tasks);
        }
      } catch (e) {
        if (!alive) return;
        console.error("[useRunningTasksPolling] 轮询异常", e);
      }
    };

    setIsPolling(true);
    tick();
    timerRef.current = setInterval(tick, interval);
    return () => {
      alive = false;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [options.enabled]);

  return { running, isPolling };
}
