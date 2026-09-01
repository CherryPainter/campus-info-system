import Taro from '@tarojs/taro';
import type { FeedbackItem } from '@/types/api';

/**
 * 反馈「状态更新未读」红点计数工具
 *
 * 规则（前端本地追踪，零后端改动）：
 * - 红点代表「管理员更新了你反馈的状态，而你还没看过这个新状态」；
 *   需提醒的状态为 processing（处理中）与 resolved（已处理/已解决）。
 * - 用「id → 上次查看时的状态(status)」的映射记录已读，而非简单 id 集合：
 *   这样每一次状态流转（pending→processing→resolved）都能重新提醒，
 *   且用户看过后即消，避免「已看过 pending 就不再提醒后续状态」或
 *   「处理中永远消不掉」等缺陷。
 * - 用户在详情页查看后，记录该反馈当前的 status → 若状态未再变化则红点 -1。
 * - 计数为 0 时不显示红点。
 *
 * 之所以用本地存储而非后端字段：本功能是纯展示性的「提醒」，
 * 不涉及业务正确性，且与现有架构（无 per-viewer 已读状态）解耦。
 * 仅统计「我的反馈」中当前登录用户自己的反馈，天然隔离其他用户。
 */

const VIEWED_KEY = 'feedback.viewedStatus';

/** 读取「已读状态映射」：{ [反馈id]: 查看时的status }（容错：损坏/旧格式数据回退空对象） */
export function getViewedStatusMap(): Record<number, string> {
  try {
    const raw = Taro.getStorageSync(VIEWED_KEY);
    if (typeof raw === 'string' && raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<number, string>;
      }
    } else if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      return raw as Record<number, string>;
    }
  } catch {
    /* 解析失败回退空 */
  }
  return {};
}

/** 记录某条反馈「当前查看时的状态」，用于判断是否已见过该状态 */
export function markViewed(id: number, status: string): void {
  const map = getViewedStatusMap();
  if (map[id] === status) return;
  map[id] = status;
  try {
    Taro.setStorageSync(VIEWED_KEY, map);
  } catch {
    /* 忽略写入失败（不影响主流程） */
  }
}

/** 需要提醒的状态集合 */
const NOTIFY_STATUSES = new Set(['processing', 'resolved']);

/** 计算未读红点数：状态处于「需提醒」且 上次查看的状态 ≠ 当前状态 */
export function computeUnread(
  items: FeedbackItem[],
  viewedMap?: Record<number, string>,
): number {
  const map = viewedMap || getViewedStatusMap();
  return items.filter(
    (i) => NOTIFY_STATUSES.has(i.status) && map[i.id] !== i.status,
  ).length;
}

// ============ 模块级共享计数（供 CustomTabBar 直接读取）============

let _sharedCount = 0;

/** 读取当前共享的未读数（CustomTabBar 等非 hook 消费方用） */
export function getSharedBadgeCount(): number {
  return _sharedCount;
}

/** 更新共享未读数（由 useFeedbackBadge / profile 页在刷新后调用） */
export function setSharedBadgeCount(n: number): void {
  _sharedCount = n;
  // 通知 CustomTabBar（框架级组件）实时更新角标
  try {
    Taro.eventCenter.trigger('feedback:badge', n);
  } catch {
    /* eventCenter 未就绪时忽略（首帧） */
  }
}
