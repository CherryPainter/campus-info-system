import { useEffect, useRef, useState } from "react";

/** 通用 API 响应结构（各 api 模块内部 ApiResponse 的结构子集） */
export interface ApiDataResponse<T> {
  status: string;
  data?: T;
  message?: string;
}

export interface TaskPollingOptions<T> {
  /** 拉取任务详情的接口调用，需返回含 data 的响应 */
  fetcher: (id: number) => Promise<ApiDataResponse<T>>;
  /** 从响应数据中提取状态与提示信息 */
  resolve: (data: T) => { status: string; message?: string };
  /** 视为“已结束”的状态集合，命中即停止轮询；默认覆盖常见终态 */
  terminalStatuses?: string[];
  /** 轮询间隔（毫秒），默认 2000 */
  intervalMs?: number;
  /** 是否启用轮询，默认 true */
  enabled?: boolean;
  /** 任意状态更新时回调（用于实时刷新 UI） */
  onUpdate?: (data: T) => void;
  /** 任务成功结束（completed / completed_empty / success）回调 */
  onDone?: (data: T) => void;
  /** 任务失败结束（failed / cancelled）回调 */
  onFailed?: (data: T) => void;
}

const DEFAULT_TERMINAL = ["completed", "completed_empty", "success", "failed", "cancelled"];

/**
 * 按任务 ID 跟踪异步任务的完整生命周期（pending -> running -> 终态）。
 * 统一消除各页面重复实现的“按 ID 轮询”逻辑，集中处理定时器清理与终态判定。
 */
export function useTaskPolling<T>(taskId: number | null, options: TaskPollingOptions<T>) {
  const [task, setTask] = useState<T | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const optsRef = useRef(options);
  optsRef.current = options;

  useEffect(() => {
    if (taskId == null || options.enabled === false) {
      setIsPolling(false);
      return;
    }
    let alive = true;
    const terminal = options.terminalStatuses ?? DEFAULT_TERMINAL;
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
        const resp = await optsRef.current.fetcher(taskId);
        if (!alive) return;
        const data = resp.data;
        if (!data) return;
        setTask(data);
        const { status, message } = optsRef.current.resolve(data);
        optsRef.current.onUpdate?.(data);
        if (terminal.includes(status)) {
          stop();
          if (status === "failed" || status === "cancelled") {
            optsRef.current.onFailed?.(data);
          } else {
            optsRef.current.onDone?.(data);
          }
        }
      } catch (e) {
        if (!alive) return;
        // 单次网络错误不终止轮询，下一周期重试
        console.error("[useTaskPolling] 轮询异常", e);
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
  }, [taskId, options.enabled]);

  return { task, isPolling };
}
