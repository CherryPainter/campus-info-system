import { useState, useCallback } from 'react';
import { View, Text } from '@tarojs/components';
import Taro, {
  useLoad,
  usePullDownRefresh,
  useReachBottom,
  stopPullDownRefresh,
} from '@tarojs/taro';
import * as announcementsApi from '@/api/announcements';
import type { AnnouncementItem } from '@/types/api';
import './index.scss';

/** 前端兜底：剥除 HTML 标签，防止脏数据显示 */
const stripHtml = (s: string | null): string =>
  (s || '').replace(/<[^>]+>/g, '').trim();

/**
 * 我的收藏
 *
 * 调用后端 /api/miniapp/announcements?only_favorite=1，
 * 仅返回当前用户收藏过的通知。支持下拉刷新、触底加载更多。
 *
 * 标签样式与首页 NoticeCard / 详情页统一：
 *   置顶 → 红字 + 浅红底圆角「置顶」
 *   非置顶 → 蓝字 + 浅蓝底圆角（分类名，如「通知」）
 */

const PAGE_SIZE = 20;

/** 取标签信息：置顶显示「置顶」，否则取分类全称 */
function getTagInfo(item: AnnouncementItem): { text: string; isTop: boolean } {
  if (item.is_top) return { text: '置顶', isTop: true };
  const label = item.category_label || item.category || '通知';
  return { text: label, isTop: false };
}

export default function FavoritesPage() {
  const [list, setList] = useState<AnnouncementItem[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const loadData = useCallback(async (targetPage: number, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    try {
      const res = await announcementsApi.getFavorites({
        page: targetPage,
        page_size: PAGE_SIZE,
      });
      const items: AnnouncementItem[] = res?.data?.items || [];
      const t: number = res?.data?.total || 0;
      setTotal(t);
      setList((prev) => (append ? [...prev, ...items] : items));
      setPage(targetPage);
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      setLoading(false);
      setLoadingMore(false);
      setLoaded(true);
      stopPullDownRefresh();
    }
  }, []);

  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '我的收藏' });
    loadData(1, false);
  });

  usePullDownRefresh(() => {
    loadData(1, false);
  });

  useReachBottom(() => {
    if (loadingMore || loading) return;
    if (list.length >= total) return;
    loadData(page + 1, true);
  });

  const goToDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  return (
    <View className="favorites-page">
      {!loading && loaded && list.length === 0 ? (
        <View className="favorites-empty">
          <Text className="iconfont icon-a-rongqi2231x favorites-empty-icon" />
          <Text className="favorites-empty-title">还没有收藏任何通知</Text>
          <Text className="favorites-empty-tip">
            在通知详情页点击五角星即可收藏，这里会显示你收藏的内容
          </Text>
        </View>
      ) : (
        <View className="favorites-list">
          {list.map((item) => {
            const tag = getTagInfo(item);
            return (
              <View
                key={item.id}
                className="fav-item"
                onClick={() => goToDetail(item.id)}
              >
                <View className="fav-item-main">
                  <Text className={`fav-tag ${tag.isTop ? 'tag-top' : 'tag-cat'}`}>
                    {tag.text}
                  </Text>
                  <Text className="fav-item-title">{item.title || '无标题'}</Text>
                </View>

                {item.summary && stripHtml(item.summary) ? (
                  <Text className="fav-item-summary">{stripHtml(item.summary)}</Text>
                ) : null}

                <View className="fav-item-meta">
                  {item.published_label ? (
                    <Text className="fav-time">{item.published_label}</Text>
                  ) : null}
                </View>
              </View>
            );
          })}

          {loadingMore ? (
            <View className="favorites-loading-more">
              <Text>加载中...</Text>
            </View>
          ) : list.length > 0 && list.length >= total ? (
            <View className="favorites-no-more">
              <Text>没有更多了</Text>
            </View>
          ) : null}
        </View>
      )}
    </View>
  );
}

// 页面级配置：开启下拉刷新
export const config = {
  navigationBarTitleText: '我的收藏',
  enablePullDownRefresh: true,
  backgroundTextStyle: 'dark',
};
