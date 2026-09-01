import Taro from '@tarojs/taro';
import type { FeedbackItem } from '@/types/api';

/**
 * 反馈「已受理未读」红点计数工具
 *
 * 规则（前端本地追踪，零后端改动）：
 * - 「已受理」= 反馈被管理员回复且状态置为 resolved（对应后端 detail 中 reply 非空）。
 * - 未读 = 该 resolved 反馈的 id 尚未被用户查看过。
 * - 用户在详情页查看（且确有回复）后，将 id 写入本地已读集合 → 计数 -1。
 * - 计数为 0 时不显示红点。
 *
 * 之所以用本地存储而非后端字段：本功能是纯展示性的「提醒」，
 * 不涉及业务正确性，且与现有架构（无 per-viewer 已读状态）解耦。
 * 仅统计「我的反馈」中当前登录用户自己的反馈，天然隔离其他用户。
 */

const VIEWED_KEY = 'feedback.viewedIds';

/** 读取已读反馈 id 列表（容错：损坏数据回退空数组） */
export function getViewedIds(): number[] {
  try {
    const raw = Taro.getStorageSync(VIEWED_KEY);
    let arr: unknown = raw;
    if (typeof raw === 'string' && raw) {
      arr = JSON.parse(raw);
    }
    if (Array.isArray(arr)) {
      return arr.filter((x) => typeof x === 'number') as number[];
    }
  } catch {
    /* 解析失败回退空 */
  }
  return [];
}

/** 将某条反馈标记为已读（写入本地集合，去重） */
export function markViewed(id: number): void {
  const set = new Set<number>(getViewedIds());
  if (set.has(id)) return;
  set.add(id);
  try {
    Taro.setStorageSync(VIEWED_KEY, Array.from(set));
  } catch {
    /* 忽略写入失败（不影响主流程） */
  }
}

/** 计算未读红点数：已受理(resolved) 且 未读 */
export function computeUnread(items: FeedbackItem[], viewed?: number[]): number {
  const viewedSet = new Set<number>(viewed || getViewedIds());
  return items.filter((i) => i.status === 'resolved' && !viewedSet.has(i.id)).length;
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
