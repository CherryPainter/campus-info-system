import { useState } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useLoad, usePullDownRefresh, useReachBottom, stopPullDownRefresh } from '@tarojs/taro';

import * as announcementsApi from '@/api/announcements';
import type { AnnouncementItem } from '@/types/api';
import { API_BASE_URL } from '@/utils/request';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 通知公告总览页（首页「通知公告」入口）
 *
 * 后端：GET /api/miniapp/announcements?page=&page_size=
 * - 默认 page_size=10；触底加载更多
 * - 后端按 is_top desc, published_at desc 排序 → 置顶自动排前
 *
 * 视觉结构（用户 2026-09-06 要求）：
 * - 上：「置顶公告专区」独立块（含置顶的公告，按发布时间倒序）
 * - 下：「全部公告」列表块（含全部公告；如与置顶重叠也照常展示）
 * 点单条 → 跳详情页（首次访问自动记已读）。
 *
 * 注意：这里的"置顶专区"和"全部公告"会有重叠——用户视觉上更清晰区分两类，
 * 但底层仍走同一接口同一份数据。如需严格去重可后端去重，本页不重复。
 */

const PAGE_SIZE = 10;

/** 标签：置顶显示「置顶」红字红底；其他显示 category_label（如「通知」「活动」） */
function getTagInfo(item: AnnouncementItem): { text: string; isTop: boolean } {
  if (item.is_top) return { text: '置顶', isTop: true };
  return { text: item.category_label || '通知', isTop: false };
}

export default function AnnouncementListPage() {
  const [items, setItems] = useState<AnnouncementItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const loadFirst = async () => {
    setLoading(true);
    setPage(1);
    try {
      const res = await announcementsApi.getList({ page: 1, page_size: PAGE_SIZE });
      const list = res?.data?.items ?? [];
      const t = res?.data?.total ?? list.length;
      setItems(list);
      setTotal(t);
      setHasMore(list.length < t && list.length > 0);
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '加载失败', icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const nextPage = page + 1;
    try {
      const res = await announcementsApi.getList({ page: nextPage, page_size: PAGE_SIZE });
      const more = res?.data?.items ?? [];
      if (more.length > 0) {
        setItems((prev) => [...prev, ...more]);
        setPage(nextPage);
      }
      setHasMore(more.length >= PAGE_SIZE && items.length + more.length < total);
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      setLoadingMore(false);
    }
  };

  const goDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  // 挂载时首次加载（修复 2026-09-06：之前漏 useLoad 导致 loading 恒 true 停在"加载中…"）
  useLoad(() => {
    loadFirst();
  });

  usePullDownRefresh(async () => {
    await loadFirst();
    stopPullDownRefresh();
  });

  useReachBottom(() => {
    loadMore();
  });

  if (loading) {
    return (
      <View className="alist-page">
        <LoadingState text="加载中…" />
      </View>
    );
  }

  if (items.length === 0) {
    return (
      <View className="alist-page">
        <View className="alist-empty-wrap">
          <EmptyState title="暂无通知" desc="学校发布的公告将在这里展示" />
        </View>
      </View>
    );
  }

  // 分组：置顶与全部（去重——同一公告只在「全部」中出现一次）
  const topItems = items.filter((it) => it.is_top);
  const allItems = items; // 全部列表仍展示全部（包含置顶）；如需去重可用 filter 排除
  // const allItems = items.filter((it) => !it.is_top); // 可选：严格去重

  return (
    <View className="alist-page">
      {/* ====== 置顶公告专区 ====== */}
      {topItems.length > 0 && (
        <View className="alist-section">
          <View className="alist-section-head">
            <Text className="alist-section-title">置顶公告</Text>
            <Text className="alist-section-count">{topItems.length} 条</Text>
          </View>
          <View className="alist-card">
            {topItems.map((item) => (
              <View
                key={`top-${item.id}`}
                className="alist-item alist-item-top"
                onClick={() => goDetail(item.id)}
              >
                {item.cover_url ? (
                  <Image className="alist-item-cover" src={`${API_BASE_URL}${item.cover_url}`} mode="widthFix" />
                ) : null}
                <View className="alist-item-main">
                  <Text className={`alist-tag tag-top`}>{getTagInfo(item).text}</Text>
                  <Text className="alist-item-title">{item.title || '无标题'}</Text>
                  {item.summary ? (
                    <Text className="alist-item-summary">{item.summary}</Text>
                  ) : null}
                </View>
                <View className="alist-item-meta">
                  {item.department ? (
                    <Text className="alist-item-dept">{item.department}</Text>
                  ) : null}
                  {item.published_label ? (
                    <Text className="alist-item-time">{item.published_label}</Text>
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        </View>
      )}

      {/* ====== 全部公告 ====== */}
      <View className="alist-section">
        <View className="alist-section-head">
          <Text className="alist-section-title">全部公告</Text>
          <Text className="alist-section-count">共 {total} 条</Text>
        </View>
        <View className="alist-card">
          {allItems.map((item) => {
            const tag = getTagInfo(item);
            return (
              <View
                key={`all-${item.id}`}
                className={`alist-item ${tag.isTop ? 'alist-item-top' : ''}`}
                onClick={() => goDetail(item.id)}
              >
                {item.cover_url ? (
                  <Image className="alist-item-cover" src={`${API_BASE_URL}${item.cover_url}`} mode="widthFix" />
                ) : null}
                <View className="alist-item-main">
                  <Text className={`alist-tag ${tag.isTop ? 'tag-top' : 'tag-cat'}`}>
                    {tag.text}
                  </Text>
                  <Text className="alist-item-title">{item.title || '无标题'}</Text>
                  {item.summary ? (
                    <Text className="alist-item-summary">{item.summary}</Text>
                  ) : null}
                </View>
                <View className="alist-item-meta">
                  {item.department ? (
                    <Text className="alist-item-dept">{item.department}</Text>
                  ) : null}
                  {item.published_label ? (
                    <Text className="alist-item-time">{item.published_label}</Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>

        {loadingMore ? (
          <View className="alist-more">
            <Text className="alist-more-text">加载中…</Text>
          </View>
        ) : hasMore ? (
          <View className="alist-more" onClick={loadMore}>
            <Text className="alist-more-text">查看更多</Text>
            <View className="alist-more-arrow" />
          </View>
        ) : (
          <View className="alist-more">
            <Text className="alist-more-text">没有更多了</Text>
          </View>
        )}
      </View>
    </View>
  );
}