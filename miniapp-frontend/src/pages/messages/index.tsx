import { useState, useRef } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useLoad, useDidShow, usePullDownRefresh, useReachBottom, stopPullDownRefresh } from '@tarojs/taro';
import dayjs from 'dayjs';

import * as notificationsApi from '@/api/notifications';
import type { AnnouncementItem, UserNotificationItem } from '@/types/api';
import { API_BASE_URL } from '@/utils/request';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import IconArrow from '@/components/IconArrow';
import { useNotificationSettingsStore } from '@/stores/notificationSettingsStore';
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
  announcement: '新公告',
};

/** 公告标签：置顶显示「置顶」，否则显示分类名 */
function getAnnounceTag(item: AnnouncementItem): { text: string; isTop: boolean } {
  if (item.is_top) return { text: '置顶', isTop: true };
  return { text: item.category_label || '通知', isTop: false };
}

/**
 * 相邻两条消息间隔超过该分钟数，视为进入新时间段，
 * 后发（较旧）一组的上方插入一个居中时间胶囊（仿微信消息列表）。
 */
const GROUP_GAP_MINUTES = 10;

/** 把后端 "YYYY-MM-DD HH:mm:ss" 转成可被 dayjs 可靠解析的本地时间（空格换 T 规避非 ISO 解析歧义） */
function toDay(ts: string | null): dayjs.Dayjs | null {
  if (!ts) return null;
  const d = dayjs(ts.replace(' ', 'T'));
  return d.isValid() ? d : null;
}

/** 智能时间文案：今天→HH:mm；昨天→"昨天 HH:mm"；今年→MM-DD HH:mm；更早→YYYY-MM-DD HH:mm */
function smartTimeLabel(ts: string | null): string {
  const t = toDay(ts);
  if (!t) return '';
  const now = dayjs();
  const today = now.format('YYYY-MM-DD');
  const yesterday = now.subtract(1, 'day').format('YYYY-MM-DD');
  const d = t.format('YYYY-MM-DD');
  const hm = t.format('HH:mm');
  if (d === today) return hm;
  if (d === yesterday) return `昨天 ${hm}`;
  if (t.year() === now.year()) return t.format('MM-DD HH:mm');
  return t.format('YYYY-MM-DD HH:mm');
}

/**
 * 判断列表第 i 条（列表为时间倒序，i 越小越新）上方是否需要时间胶囊：
 * 首条固定显示（给列表顶部一个时间锚点）；与相邻上一条（更新的那条）间隔 ≥ 阈值则新起胶囊。
 */
function needTimeCapsule(items: UserNotificationItem[], i: number): boolean {
  if (i === 0) return true;
  const cur = toDay(items[i].created_at);
  const prev = toDay(items[i - 1].created_at);
  if (!cur || !prev) return true;
  return prev.diff(cur, 'minute', true) >= GROUP_GAP_MINUTES;
}

export default function MessagesPage() {
  const [items, setItems] = useState<UserNotificationItem[]>([]);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [announcementUnread, setAnnouncementUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const { masterEnabled } = useNotificationSettingsStore();

  // 消息提醒总开关关闭时，不再显示任何未读统计与红点，但列表仍可查看历史。
  const totalUnread = masterEnabled ? unreadCount + announcementUnread : 0;

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

  /** 跳消息详情页（进入详情即自动记已读，返回后再刷新列表已读态） */
  const goDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/message-detail/index?id=${id}` });
  };

  /**
   * 标记全部已读（清外部气泡，不动 is_viewed）：
   * - 手动「全部已读」按钮调用（带 toast）
   * - 进入列表时静默调用（清「我的」页角标，不打扰）
   * 两层已读：这里只清 is_read（外部气泡），卡片红点（is_viewed）需点进详情才清。
   */
  const markAllReadApi = async (): Promise<void> => {
    try {
      const res = await notificationsApi.markRead();
      setUnreadCount(res?.data?.unread_count ?? 0);
      setAnnouncementUnread(res?.data?.announcement_unread ?? 0);
      setItems((prev) => prev.map((i) => ({ ...i, is_read: true })));
      setAnnouncements([]);
    } catch {
      /* 静默失败：返回「我的」页时会重新拉取未读 */
    }
  };

  /** 全部已读：站内通知 + 新公告一次清空（带 toast 反馈） */
  const markAllRead = async () => {
    if (totalUnread === 0) return;
    await markAllReadApi();
    Taro.showToast({ title: '已全部标记已读', icon: 'success' });
  };

  /** 点击公告 → 详情页（自动记已读），返回时刷新 */
  const goAnnouncement = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  /** 点击公告类站内信：标记该条已读 + 已看（清卡片红点），再跳公告详情 */
  const openAnnouncementNotification = async (item: UserNotificationItem) => {
    try {
      const res = await notificationsApi.markRead(item.id);
      // 乐观更新：清掉该条未读态与未读计数
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_read: true } : i)));
      setUnreadCount(res?.data?.unread_count ?? 0);
      // 公告类通知点开的是公告详情页（非消息详情），显式标记 is_viewed 清卡片红点
      await notificationsApi.markViewed(item.id);
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_viewed: true } : i)));
    } catch {
      /* 标记失败不阻断跳转 */
    }
    goAnnouncement(item.ref_id as number);
  };

  useLoad(async () => {
    Taro.setNavigationBarTitle({ title: '我的消息' });
    // 进入列表即全部已读：清掉「我的」页外部气泡角标（is_read 维度），
    // 但保留 is_viewed（卡片红点），让想细看的人知道哪些还没点进详情。
    await markAllReadApi();
    await loadFirst();
  });

  // 非首次显示（从公告/消息详情返回）时刷新：公告已读态、消息已读态、未读数
  const firstShowRef = useRef(true);
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false;
      return;
    }
    // 从消息详情返回时，那条消息已在后端记为已读 → 重拉第一页刷新已读态与未读数
    loadFirst();
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
          {items.map((item, i) => (
            <View key={item.id} className="msg-item-group">
              {needTimeCapsule(items, i) && (
                <View className="msg-time-pill">
                  <Text className="msg-time-pill-text">{smartTimeLabel(item.created_at)}</Text>
                </View>
              )}
              <View
                className={`msg-item${item.is_viewed ? ' is-seen' : ' is-unseen'}`}
                onClick={() =>
                  item.ref_type === 'announcement' && item.ref_id
                    ? openAnnouncementNotification(item)
                    : goDetail(item.id)
                }
              >
                {masterEnabled && !item.is_viewed && <View className="msg-item-dot" />}
                {item.cover_url ? (
                  <Image
                    className="msg-item-cover"
                    src={`${API_BASE_URL}${item.cover_url}`}
                    mode="aspectFill"
                  />
                ) : null}
                <View className="msg-item-main">
                  <View className="msg-item-head">
                    <Text className="msg-item-cat">{categoryText(item.category)}</Text>
                  </View>
                  <Text className="msg-item-title">{item.title}</Text>
                  {item.content ? (
                    // 列表只放摘要（最多 2 行省略），完整正文在消息详情页看
                    <Text className="msg-item-content">{item.content}</Text>
                  ) : null}
                </View>
                <IconArrow className="msg-item-arrow" size="lg" />
              </View>
            </View>
          ))}
          {loadingMore ? (
            <View className="msg-more">
              <Text className="msg-more-text">加载中…</Text>
            </View>
          ) : hasMore ? (
            <View className="msg-more" onClick={loadMore}>
              <Text className="msg-more-text">查看更多</Text>
              <IconArrow size="sm" />
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
