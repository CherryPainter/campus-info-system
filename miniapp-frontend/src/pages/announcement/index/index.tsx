import { useCallback, useRef, useState } from 'react';
import { View, Text, ScrollView, Input } from '@tarojs/components';
import Taro, { useLoad, usePullDownRefresh, useReachBottom, stopPullDownRefresh } from '@tarojs/taro';

import * as announcementsApi from '@/api/announcements';
import type { AnnouncementChannel, AnnouncementItem } from '@/types/api';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 通知公告总览页（首页「通知公告」入口）—— 2026-09-30 改版 v2（校园新闻门户样式）
 *
 * 后端：
 * - GET /api/miniapp/announcements?page=&page_size=&channel=&keyword=&only_favorite=
 * - GET /api/miniapp/announcements/channels → {items:[{key,name,count}], total}
 *
 * 页面结构：
 * 1. 顶部搜索栏（页内联即时筛选，不新开搜索页）：输入即按 keyword 重新拉取当前列表
 * 2. 频道标签行：全部（默认）+ 我的关注 + 各频道（横滑，选中短下划线）；右侧「更多频道」汉堡打开频道选择器
 * 3. 列表卡片：纯文字上下结构（标题两行 + 来源/日期），不配图；已读/未读视觉一致，不做阅读后变灰
 */

const PAGE_SIZE = 10;

/** 「全部」：不按频道过滤的默认 Tab，保证任何情况下都能看到全部可见公告 */
const TAB_ALL = '全部';
/** 「我的关注」：固定特殊 Tab（等价「我的收藏」），不来自后端频道聚合 */
const TAB_FOLLOW = '我的关注';

export default function AnnouncementListPage() {
  const [items, setItems] = useState<AnnouncementItem[]>([]);
  const [channels, setChannels] = useState<AnnouncementChannel[]>([]);
  const [activeTab, setActiveTab] = useState<string>(TAB_ALL);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [keyword, setKeyword] = useState('');

  // 搜索关键词：用 ref 让 loadFirst/loadMore 始终读到最新值，避免闭包陷阱
  const keywordRef = useRef('');
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 请求序号：切换频道时丢弃过期响应，避免串数据
  const reqIdRef = useRef(0);

  /** 拉第一页（首屏 / 下拉刷新 / 切换频道 / 选频道 / 搜索共用） */
  const loadFirst = useCallback(async (tab: string) => {
    const reqId = ++reqIdRef.current;
    setLoading(true);
    setItems([]);
    setPage(1);
    try {
      const isFollow = tab === TAB_FOLLOW;
      const isAll = tab === TAB_ALL;
      const kw = keywordRef.current.trim();
      const res = await announcementsApi.getList({
        page: 1,
        page_size: PAGE_SIZE,
        only_favorite: isFollow || undefined,
        channel: isFollow || isAll ? undefined : tab,
        keyword: kw || undefined,
      });
      if (reqId !== reqIdRef.current) return;
      const list = res?.data?.items ?? [];
      const t = res?.data?.total ?? list.length;
      setItems(list);
      setTotal(t);
      setHasMore(list.length < t && list.length > 0);
    } catch (e) {
      if (reqId !== reqIdRef.current) return;
      Taro.showToast({ title: (e as Error).message || '加载失败', icon: 'none' });
    } finally {
      if (reqId === reqIdRef.current) setLoading(false);
    }
  }, []);

  /** 频道清单（全量口径，不随筛选变化；失败不阻断列表） */
  const loadChannels = useCallback(async () => {
    try {
      const res = await announcementsApi.getChannels();
      setChannels(res?.data?.items ?? []);
    } catch {
      setChannels([]);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (loadingMore || loading || !hasMore) return;
    const reqId = reqIdRef.current;
    setLoadingMore(true);
    const nextPage = page + 1;
    try {
      const isFollow = activeTab === TAB_FOLLOW;
      const isAll = activeTab === TAB_ALL;
      const kw = keywordRef.current.trim();
      const res = await announcementsApi.getList({
        page: nextPage,
        page_size: PAGE_SIZE,
        only_favorite: isFollow || undefined,
        channel: isFollow || isAll ? undefined : activeTab,
        keyword: kw || undefined,
      });
      if (reqId !== reqIdRef.current) return;
      const more = res?.data?.items ?? [];
      if (more.length > 0) {
        setItems((prev) => [...prev, ...more]);
        setPage(nextPage);
      }
      setHasMore(more.length > 0 && nextPage * PAGE_SIZE < total);
    } catch {
      if (reqId === reqIdRef.current) {
        Taro.showToast({ title: '加载失败', icon: 'none' });
      }
    } finally {
      if (reqId === reqIdRef.current) setLoadingMore(false);
    }
  }, [activeTab, hasMore, loading, loadingMore, page, total]);

  const goDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  // 搜索：页内联即时筛选（防抖 350ms 后重新拉第一页），不新开搜索页
  const handleSearchInput = (value: string) => {
    setKeyword(value);
    keywordRef.current = value;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      loadFirst(activeTab);
    }, 350);
  };

  const clearSearch = () => {
    setKeyword('');
    keywordRef.current = '';
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    loadFirst(activeTab);
  };

  const selectTab = (tab: string) => {
    setShowPicker(false);
    if (tab === activeTab) return;
    setActiveTab(tab);
    loadFirst(tab);
  };

  useLoad(() => {
    loadFirst(TAB_ALL);
    loadChannels();
  });

  usePullDownRefresh(async () => {
    await Promise.all([loadFirst(activeTab), loadChannels()]);
    stopPullDownRefresh();
  });

  useReachBottom(() => {
    loadMore();
  });

  const tabs = [TAB_ALL, TAB_FOLLOW, ...channels.map((c) => c.key)];

  // 空态文案：优先判断搜索关键词（筛选无结果），其次按频道
  let emptyTitle = '该频道暂无通知';
  let emptyDesc = '换个频道，或下拉刷新看看';
  if (keyword.trim()) {
    emptyTitle = '没有找到相关通知';
    emptyDesc = '换个关键词试试';
  } else if (activeTab === TAB_ALL) {
    emptyTitle = '暂无通知';
    emptyDesc = '下拉刷新试试';
  } else if (activeTab === TAB_FOLLOW) {
    emptyTitle = '你还没有关注的通知';
    emptyDesc = '在详情页收藏通知，会出现在这里';
  }

  return (
    <View className="alist-page">
      {/* ====== 搜索栏（页内联筛选，不新开页面） ====== */}
      <View className="alist-search">
        <View className="alist-search-icon" />
        <Input
          className="alist-search-input"
          value={keyword}
          placeholder="搜索资讯"
          placeholderClass="alist-search-ph"
          confirmType="search"
          onInput={(e) => handleSearchInput(e.detail.value)}
        />
        {keyword ? <View className="alist-search-clear" onClick={clearSearch} /> : null}
      </View>

      {/* ====== 频道标签行 ====== */}
      <View className="alist-channel-bar">
        <ScrollView className="alist-channel-scroll" scrollX scrollWithAnimation showScrollbar={false}>
          <View className="alist-channel-inner">
            {tabs.map((tab) => (
              <View
                key={tab}
                className={`alist-channel-item ${activeTab === tab ? 'is-active' : ''}`}
                onClick={() => selectTab(tab)}
              >
                <Text className="alist-channel-text">{tab}</Text>
                {activeTab === tab ? <View className="alist-channel-underline" /> : null}
              </View>
            ))}
          </View>
        </ScrollView>
        <View className="alist-channel-more" onClick={() => setShowPicker(true)}>
          <View className="alist-hamburger">
            <View className="alist-hb-bar" />
            <View className="alist-hb-bar" />
            <View className="alist-hb-bar" />
          </View>
        </View>
      </View>

      {/* ====== 列表 ====== */}
      {loading ? (
        <LoadingState text="加载中…" />
      ) : items.length === 0 ? (
        <View className="alist-empty-wrap">
          <EmptyState title={emptyTitle} desc={emptyDesc} />
        </View>
      ) : (
        <View className="alist-card-list">
          {items.map((item) => (
            <View
              key={item.id}
              className="alist-card"
              onClick={() => goDetail(item.id)}
            >
              <Text className="alist-card-title">{item.title || '无标题'}</Text>
              <View className="alist-card-meta">
                {item.department ? <Text className="alist-card-dept">{item.department}</Text> : null}
                {item.published_label ? (
                  <Text className="alist-card-time">{item.published_label}</Text>
                ) : null}
              </View>
            </View>
          ))}

          {loadingMore ? (
            <View className="alist-more">
              <Text className="alist-more-text">加载中…</Text>
            </View>
          ) : hasMore ? (
            <View className="alist-more" onClick={loadMore}>
              <Text className="alist-more-text">查看更多</Text>
            </View>
          ) : (
            <View className="alist-more">
              <Text className="alist-more-text">没有更多了</Text>
            </View>
          )}
        </View>
      )}

      {/* ====== 频道选择器（汉堡按钮触发） ====== */}
      {showPicker ? (
        <View className="alist-picker-mask" onClick={() => setShowPicker(false)}>
          <View className="alist-picker-panel" onClick={(e) => e.stopPropagation()}>
            <Text className="alist-picker-title">选择频道</Text>
            <View className="alist-picker-list">
              {tabs.map((tab) => (
                <View
                  key={tab}
                  className={`alist-picker-item ${activeTab === tab ? 'is-active' : ''}`}
                  onClick={() => selectTab(tab)}
                >
                  <Text className="alist-picker-text">{tab}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>
      ) : null}
    </View>
  );
}
