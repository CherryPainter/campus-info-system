import { useCallback, useRef, useState } from 'react';
import { View, Text, Input } from '@tarojs/components';
import Taro, { useReachBottom } from '@tarojs/taro';

import * as announcementsApi from '@/api/announcements';
import type { AnnouncementItem } from '@/types/api';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 通知公告独立搜索页（2026-09-30 新增）
 *
 * 后端：GET /api/miniapp/announcements?keyword=<kw>&page=&page_size=
 * - keyword 匹配标题 + 摘要（LIKE）
 * - 输入防抖 350ms，空关键词清空结果
 * - 触底加载更多
 */

const PAGE_SIZE = 10;

export default function AnnouncementSearchPage() {
  const [keyword, setKeyword] = useState('');
  const [items, setItems] = useState<AnnouncementItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [searched, setSearched] = useState(false);
  const reqIdRef = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(async (kw: string, pageNum = 1, append = false) => {
    const trimmed = kw.trim();
    if (!trimmed) {
      setItems([]);
      setTotal(0);
      setSearched(false);
      setHasMore(false);
      return;
    }
    const reqId = ++reqIdRef.current;
    if (pageNum === 1) setLoading(true);
    else setLoadingMore(true);
    try {
      const res = await announcementsApi.getList({
        page: pageNum,
        page_size: PAGE_SIZE,
        keyword: trimmed,
      });
      if (reqId !== reqIdRef.current) return;
      const list = res?.data?.items ?? [];
      const t = res?.data?.total ?? list.length;
      if (append) setItems((prev) => [...prev, ...list]);
      else setItems(list);
      setTotal(t);
      setPage(pageNum);
      setHasMore(list.length < t && list.length > 0);
      setSearched(true);
    } catch (e) {
      if (reqId !== reqIdRef.current) return;
      Taro.showToast({ title: (e as Error).message || '搜索失败', icon: 'none' });
    } finally {
      if (reqId === reqIdRef.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, []);

  const onInput = (e: { detail: { value: string } }) => {
    const v = e.detail.value;
    setKeyword(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(v, 1), 350);
  };

  const onClear = () => {
    setKeyword('');
    setItems([]);
    setTotal(0);
    setSearched(false);
    setHasMore(false);
  };

  const loadMore = useCallback(() => {
    if (loadingMore || loading || !hasMore || !keyword.trim()) return;
    search(keyword, page + 1, true);
  }, [keyword, page, hasMore, loading, loadingMore, search]);

  useReachBottom(loadMore);

  const goDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  return (
    <View className="asearch-page">
      <View className="asearch-bar">
        <View className="asearch-icon" />
        <Input
          className="asearch-input"
          placeholder="搜索资讯"
          value={keyword}
          onInput={onInput}
          focus
          confirmType="search"
        />
        {keyword ? (
          <Text className="asearch-clear" onClick={onClear}>
            取消
          </Text>
        ) : null}
      </View>

      {!searched ? (
        <View className="asearch-tip">
          <Text className="asearch-tip-text">输入关键词，搜索标题与摘要</Text>
        </View>
      ) : loading ? (
        <LoadingState text="搜索中…" />
      ) : items.length === 0 ? (
        <EmptyState title="没有找到相关通知" desc="换个关键词试试" />
      ) : (
        <View className="asearch-list">
          {items.map((item) => (
            <View
              key={item.id}
              className={`asearch-card ${item.is_read ? 'is-read' : ''}`}
              onClick={() => goDetail(item.id)}
            >
              <Text className="asearch-card-title">{item.title || '无标题'}</Text>
              <View className="asearch-card-meta">
                {item.department ? <Text className="asearch-card-dept">{item.department}</Text> : null}
                {item.published_label ? (
                  <Text className="asearch-card-time">{item.published_label}</Text>
                ) : null}
              </View>
            </View>
          ))}
          {loadingMore ? (
            <View className="asearch-more">
              <Text className="asearch-more-text">加载中…</Text>
            </View>
          ) : hasMore ? (
            <View className="asearch-more" onClick={loadMore}>
              <Text className="asearch-more-text">查看更多</Text>
            </View>
          ) : (
            <View className="asearch-more">
              <Text className="asearch-more-text">没有更多了</Text>
            </View>
          )}
        </View>
      )}
    </View>
  );
}
