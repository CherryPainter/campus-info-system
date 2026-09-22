import { useState, useCallback } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, {
  useLoad,
  usePullDownRefresh,
  useReachBottom,
  stopPullDownRefresh,
} from '@tarojs/taro';

import * as feedbackApi from '@/api/feedback';
import { API_BASE_URL } from '@/utils/request';
import { previewImages } from '@/utils/imagePreview';
import type { FeedbackItem } from '@/types/api';
import './index.scss';

/**
 * 我的反馈列表（学生侧）
 *
 * 调用 /api/miniapp/feedback 拉取当前用户提交过的反馈，
 * 展示类型、状态、内容预览、截图与提交时间；点击进入详情看管理员回复。
 */

const PAGE_SIZE = 20;

function statusClass(status: string): string {
  switch (status) {
    case 'resolved':
      return 'fb-st-resolved';
    case 'processing':
      return 'fb-st-processing';
    default:
      return 'fb-st-pending';
  }
}

export default function FeedbackListPage() {
  const [list, setList] = useState<FeedbackItem[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [highlightId, setHighlightId] = useState<number | null>(null);

  const loadData = useCallback(async (targetPage: number, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    try {
      const res = await feedbackApi.getList({ page: targetPage, page_size: PAGE_SIZE });
      const items: FeedbackItem[] = res?.data?.items || [];
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

  useLoad((opts) => {
    Taro.setNavigationBarTitle({ title: '我的反馈' });
    if (opts?.highlight) setHighlightId(Number(opts.highlight));
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

  const goDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/feedback/detail/index?id=${id}` });
  };

  return (
    <View className="fb-list-page">
      {!loading && loaded && list.length === 0 ? (
        <View className="fb-empty">
          <Text className="iconfont icon-yijianyufankui fb-empty-icon" />
          <Text className="fb-empty-title">还没有提交过反馈</Text>
          <Text className="fb-empty-tip">遇到问题或有建议？点击右下角「意见反馈」告诉我们</Text>
        </View>
      ) : (
        <View className="fb-list">
          {list.map((item) => (
            <View
              key={item.id}
              className={`fb-item ${highlightId === item.id ? 'fb-item-highlight' : ''}`}
              onClick={() => goDetail(item.id)}
            >
              <View className="fb-item-head">
                <Text className="fb-item-type">{item.type_label}</Text>
                <Text className={`fb-item-status ${statusClass(item.status)}`}>{item.status_label}</Text>
              </View>
              <Text className="fb-item-content">{item.content}</Text>

              {item.images && item.images.length ? (
                <View className="fb-item-images">
                  {item.images.slice(0, 3).map((url, i) => (
                    <Image
                      key={url + i}
                      className="fb-item-img"
                      src={`${API_BASE_URL}${url}`}
                      mode="aspectFill"
                      onClick={(e) => {
                        // 阻止冒泡，避免点图误进详情页
                        e.stopPropagation();
                        previewImages(url, item.images);
                      }}
                    />
                  ))}
                </View>
              ) : null}

              <View className="fb-item-foot">
                <Text className="fb-item-time">{item.created_at}</Text>
                <Text className="fb-item-arrow">›</Text>
              </View>
            </View>
          ))}

          {loadingMore ? (
            <View className="fb-loading-more">
              <Text>加载中...</Text>
            </View>
          ) : list.length > 0 && list.length >= total ? (
            <View className="fb-no-more">
              <Text>没有更多了</Text>
            </View>
          ) : null}
        </View>
      )}

      {/* 悬浮提交入口 */}
      <View
        className="fb-fab"
        onClick={() => Taro.navigateTo({ url: '/pages/feedback/submit/index' })}
      >
        <View className="fb-fab-plus" />
      </View>
    </View>
  );
}

export const config = {
  navigationBarTitleText: '我的反馈',
  enablePullDownRefresh: true,
  backgroundTextStyle: 'dark',
};
