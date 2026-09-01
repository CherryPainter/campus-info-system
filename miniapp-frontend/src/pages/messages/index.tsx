import { useState } from 'react';
import { View, Text } from '@tarojs/components';
import Taro, { useLoad, usePullDownRefresh, useReachBottom, stopPullDownRefresh } from '@tarojs/taro';

import * as notificationsApi from '@/api/notifications';
import type { UserNotificationItem } from '@/types/api';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 我的消息（个人站内通知）
 *
 * 内容由后端定时任务按用户生成：电量日报/周报/月报、低电量提醒、Cookie 失效提醒等。
 * - 列表时间倒序，未读消息带圆点标识
 * - 点击单条标记已读（乐观更新，失败回滚）
 * - 顶部「全部已读」一次清空未读
 * - 触底加载下一页（后端按 limit/offset 分页）
 */

const PAGE_SIZE = 20;

const CATEGORY_LABEL: Record<string, string> = {
  electricity_daily: '电量日报',
  electricity_weekly: '电量周报',
  electricity_monthly: '电量月报',
  low_power: '低电量提醒',
  cookie_invalid: '配置失效',
  fetch_error: '采集异常',
};

export default function MessagesPage() {
  const [items, setItems] = useState<UserNotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const loadFirst = async () => {
    setLoading(true);
    try {
      const res = await notificationsApi.getMessages(PAGE_SIZE, 0);
      const list = res?.data?.notifications ?? [];
      setItems(list);
      setUnreadCount(res?.data?.unread_count ?? 0);
      // 后端不返回 total，以"本页条数 == limit"判断可能还有下一页
      setHasMore(list.length >= PAGE_SIZE);
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '加载失败', icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await notificationsApi.getMessages(PAGE_SIZE, items.length);
      const more = res?.data?.notifications ?? [];
      if (more.length > 0) {
        setItems((prev) => [...prev, ...more]);
        setUnreadCount(res?.data?.unread_count ?? 0);
      }
      setHasMore(more.length >= PAGE_SIZE);
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      setLoadingMore(false);
    }
  };

  /** 单条标记已读（乐观更新，失败回滚） */
  const markOneRead = async (item: UserNotificationItem) => {
    if (item.is_read) return;
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_read: true } : i)));
    setUnreadCount((c) => Math.max(0, c - 1));
    try {
      await notificationsApi.markRead(item.id);
    } catch {
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_read: false } : i)));
      setUnreadCount((c) => c + 1);
    }
  };

  const markAllRead = async () => {
    if (unreadCount === 0) return;
    try {
      const res = await notificationsApi.markRead();
      setUnreadCount(res?.data?.unread_count ?? 0);
      setItems((prev) => prev.map((i) => ({ ...i, is_read: true })));
      Taro.showToast({ title: '已全部标记已读', icon: 'success' });
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '操作失败', icon: 'none' });
    }
  };

  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '我的消息' });
    loadFirst();
  });

  usePullDownRefresh(async () => {
    await loadFirst();
    stopPullDownRefresh();
  });

  useReachBottom(() => {
    loadMore();
  });

  const categoryText = (c: string) => CATEGORY_LABEL[c] || '系统通知';

  if (loading) {
    return (
      <View className="msg-page">
        <LoadingState text="加载中…" />
      </View>
    );
  }

  return (
    <View className="msg-page">
      {/* 未读统计 + 全部已读 */}
      <View className="msg-head">
        <View className="msg-head-left">
          <Text className="msg-head-count">
            未读消息<Text className="msg-head-num">{unreadCount}</Text>
          </Text>
        </View>
        <View className="msg-head-action" onClick={markAllRead}>
          <Text className={`msg-head-btn${unreadCount === 0 ? ' disabled' : ''}`}>全部已读</Text>
        </View>
      </View>

      {items.length === 0 ? (
        <View className="msg-empty-wrap">
          <EmptyState title="暂无消息" desc="电量日报、低电量提醒等将在这里展示" />
        </View>
      ) : (
        <>
          {items.map((item) => (
            <View
              key={item.id}
              className={`msg-item${item.is_read ? '' : ' unread'}`}
              onClick={() => markOneRead(item)}
            >
              <View className="msg-item-head">
                <Text className="msg-item-cat">{categoryText(item.category)}</Text>
                {!item.is_read && <Text className="msg-item-dot" />}
              </View>
              <Text className="msg-item-title">{item.title}</Text>
              {item.content ? (
                <Text className="msg-item-content">{item.content}</Text>
              ) : null}
              <Text className="msg-item-time">{item.created_at || ''}</Text>
            </View>
          ))}
          {loadingMore ? (
            <View className="msg-more">
              <Text className="msg-more-text">加载中…</Text>
            </View>
          ) : hasMore ? (
            <View className="msg-more" onClick={loadMore}>
              <Text className="msg-more-text">查看更多 ›</Text>
            </View>
          ) : (
            <View className="msg-more">
              <Text className="msg-more-text">没有更多了</Text>
            </View>
          )}
        </>
      )}
    </View>
  );
}

export const config = {
  navigationBarTitleText: '我的消息',
  enablePullDownRefresh: true,
};
