import { useState, useRef } from 'react';
import { View, Text } from '@tarojs/components';
import Taro, { useLoad, useDidShow, usePullDownRefresh, useReachBottom, stopPullDownRefresh } from '@tarojs/taro';

import * as notificationsApi from '@/api/notifications';
import type { AnnouncementItem, UserNotificationItem } from '@/types/api';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 我的消息（个人站内通知 + 新公告提醒）
 *
 * 内容由后端定时任务按用户生成：电量日报/周报/月报、低电量提醒、Cookie 失效提醒等；
 * 顶部「新公告」区块展示未读的校园公告（点进详情自动记已读，返回后自动刷新）。
 * - 列表时间倒序，未读消息带圆点标识
 * - 点击单条标记已读（乐观更新，失败回滚）
 * - 顶部「全部已读」一次清空未读（站内通知 + 新公告）
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

/** 公告标签：置顶显示「置顶」，否则显示分类名 */
function getAnnounceTag(item: AnnouncementItem): { text: string; isTop: boolean } {
  if (item.is_top) return { text: '置顶', isTop: true };
  return { text: item.category_label || '通知', isTop: false };
}

export default function MessagesPage() {
  const [items, setItems] = useState<UserNotificationItem[]>([]);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [announcementUnread, setAnnouncementUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const totalUnread = unreadCount + announcementUnread;

  const loadFirst = async () => {
    setLoading(true);
    try {
      const res = await notificationsApi.getMessages(PAGE_SIZE, 0);
      const list = res?.data?.notifications ?? [];
      setItems(list);
      setAnnouncements(res?.data?.announcements ?? []);
      setUnreadCount(res?.data?.unread_count ?? 0);
      setAnnouncementUnread(res?.data?.announcement_unread ?? 0);
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

  /** 刷新未读公告（从公告详情返回后调用：详情页已自动记已读） */
  const refreshAnnouncements = async () => {
    try {
      const res = await notificationsApi.getMessages(1, 0);
      setAnnouncements(res?.data?.announcements ?? []);
      setAnnouncementUnread(res?.data?.announcement_unread ?? 0);
    } catch {
      /* 静默失败 */
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

  /** 全部已读：站内通知 + 新公告一次清空 */
  const markAllRead = async () => {
    if (totalUnread === 0) return;
    try {
      const res = await notificationsApi.markRead();
      setUnreadCount(res?.data?.unread_count ?? 0);
      setAnnouncementUnread(res?.data?.announcement_unread ?? 0);
      setItems((prev) => prev.map((i) => ({ ...i, is_read: true })));
      setAnnouncements([]);
      Taro.showToast({ title: '已全部标记已读', icon: 'success' });
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '操作失败', icon: 'none' });
    }
  };

  /** 点击公告 → 详情页（自动记已读），返回时刷新 */
  const goAnnouncement = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '我的消息' });
    loadFirst();
  });

  // 非首次显示（从公告详情返回）时刷新未读公告
  const firstShowRef = useRef(true);
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false;
      return;
    }
    refreshAnnouncements();
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
      {/* 新公告：未读公告提醒（点进详情自动已读） */}
      {announcements.length > 0 && (
        <View className="msg-announce">
          <View className="msg-announce-head">
            <Text className="msg-announce-title">新公告</Text>
            <Text className="msg-announce-count">{announcementUnread} 条未读</Text>
          </View>
          {announcements.map((item) => {
            const tag = getAnnounceTag(item);
            return (
              <View
                key={item.id}
                className="msg-announce-item"
                onClick={() => goAnnouncement(item.id)}
              >
                <View className="msg-announce-main">
                  <Text className={`msg-announce-tag ${tag.isTop ? 'tag-top' : 'tag-cat'}`}>
                    {tag.text}
                  </Text>
                  <Text className="msg-announce-title-text">{item.title || '无标题'}</Text>
                </View>
                <View className="msg-announce-meta">
                  <Text className="msg-announce-dept">{item.department || ''}</Text>
                  <Text className="msg-announce-time">{item.published_label || ''}</Text>
                </View>
              </View>
            );
          })}
        </View>
      )}

      {/* 未读统计 + 全部已读 */}
      <View className="msg-head">
        <View className="msg-head-left">
          <Text className="msg-head-count">
            未读消息<Text className="msg-head-num">{totalUnread}</Text>
          </Text>
        </View>
        <View className="msg-head-action" onClick={markAllRead}>
          <Text className={`msg-head-btn${totalUnread === 0 ? ' disabled' : ''}`}>全部已读</Text>
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
