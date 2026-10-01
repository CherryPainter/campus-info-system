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

// ============ 反馈「详情已看」集合（卡片右上角红点用）============
//
// 与上方「状态更新未读」(viewedStatus) 是两个独立维度（两层已读模型）：
// - viewedStatus：管理员更新了状态且我没看过该状态 → 驱动「我的」页外部气泡；
// - viewedIds：  我是否点进过这条反馈的详情页 → 驱动卡片右上角红点。
// 进入「我的反馈」列表即把所有当前反馈 markViewed(状态)，外部气泡清 0；
// 但「已读 ≠ 看过」，卡片红点仍按 viewedIds 显示，直到用户真正点进某条详情。
// 两者都为零后端改动，纯本地存储。

const VIEWED_IDS_KEY = 'feedback.viewedIds';

/** 读取「已点进详情看过」的反馈 id 集合（容错：损坏数据回退空集合） */
export function getViewedIds(): Set<number> {
  try {
    const raw = Taro.getStorageSync(VIEWED_IDS_KEY);
    if (Array.isArray(raw)) return new Set(raw as number[]);
    if (typeof raw === 'string' && raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return new Set(parsed as number[]);
    }
  } catch {
    /* 解析失败回退空 */
  }
  return new Set();
}

/** 记录某条反馈「已点进详情看过」 */
export function markFeedbackViewed(id: number): void {
  const set = getViewedIds();
  if (set.has(id)) return;
  set.add(id);
  try {
    Taro.setStorageSync(VIEWED_IDS_KEY, Array.from(set));
  } catch {
    /* 忽略写入失败（不影响主流程） */
  }
}

/** 是否已点进详情看过（用于卡片红点：未看才显示红点） */
export function isFeedbackViewed(id: number): boolean {
  return getViewedIds().has(id);
}

// ============ 模块级共享计数（供 CustomTabBar 直接读取）============

let _sharedCount = 0;

/** 读取当前共享的未读数（CustomTabBar 等非 hook 消费方用） */
export function getSharedBadgeCount(): number {
  return _sharedCount;
}

/**
 * 更新共享未读数（TabBar「我的」角标）
 *
 * 口径：消息未读总数（站内通知 + 公告），由「我的」页 / app.tsx 拉到未读数后写入。
 * 2026-10-01 起反馈状态变更改为后端站内通知下发，反馈不再单独占用 TabBar 角标，
 * 原先的反馈角标 hook（useFeedbackBadge）已删除。
 */
export function setSharedBadgeCount(n: number): void {
  _sharedCount = n;
  // 通知 CustomTabBar（框架级组件）实时更新角标
  try {
    Taro.eventCenter.trigger('feedback:badge', n);
  } catch {
    /* eventCenter 未就绪时忽略（首帧） */
  }
}
