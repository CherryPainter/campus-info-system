/**
 * 反馈待处理角标 共享状态
 *
 * 作用：管理端「意见与反馈」侧边栏菜单项的红点/数字角标。
 * - 管理员登录后每 30s 轮询一次 /admin/feedback/count，拿到「未解决=待处理+处理中」总数；
 * - 在 Feedback 列表页标记处理/回复后调用 refresh() 立即刷新，无需等下一轮轮询；
 * - 非管理员（普通用户/未登录）不轮询、计数归零（普通用户菜单本就没有「意见与反馈」入口）。
 *
 * 与小程序端 feedbackBadge 思路一致（模块级共享计数 + 事件/轮询刷新），
 * 但管理端用 React Context + 定时轮询，因为管理端是常驻后台，实时性靠轮询即可。
 */
import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { feedbackApi } from "@/api/feedback";
import { useUser } from "@/contexts/UserContext";

interface FeedbackBadgeContextType {
  /** 未解决（待处理 + 处理中）总数，用于角标 */
  unresolved: number;
  /** 待处理数 */
  pending: number;
  /** 处理中数 */
  processing: number;
  /** 手动刷新（处理/回复后调用，立即更新角标） */
  refresh: () => void;
}

const FeedbackBadgeContext = createContext<FeedbackBadgeContextType | undefined>(undefined);

const POLL_INTERVAL = 30_000;

const ZERO = { pending: 0, processing: 0, unresolved: 0 };

export function FeedbackBadgeProvider({ children }: { children: ReactNode }) {
  const { isAdmin, authenticated } = useUser();
  const [state, setState] = useState(ZERO);

  const refresh = useCallback(async () => {
    if (!isAdmin) {
      setState(ZERO);
      return;
    }
    try {
      const res = await feedbackApi.count();
      if (res.status === "success" && res.data) {
        setState({
          pending: res.data.pending,
          processing: res.data.processing,
          unresolved: res.data.unresolved,
        });
      }
    } catch {
      // 轮询失败静默保留上一次计数，不闪烁归零
    }
  }, [isAdmin]);

  useEffect(() => {
    // 仅管理员已登录才轮询；其余情况清零
    if (!isAdmin || authenticated !== true) {
      setState(ZERO);
      return;
    }
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [isAdmin, authenticated, refresh]);

  return (
    <FeedbackBadgeContext.Provider value={{ ...state, refresh }}>
      {children}
    </FeedbackBadgeContext.Provider>
  );
}

export function useFeedbackBadge() {
  const ctx = useContext(FeedbackBadgeContext);
  if (!ctx) {
    throw new Error("useFeedbackBadge 必须在 FeedbackBadgeProvider 内使用");
  }
  return ctx;
}
