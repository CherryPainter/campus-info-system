import { useState, useEffect } from 'react';
import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { Icon } from '@nutui/nutui-react-taro';
import * as announcementsApi from '@/api/announcements';

import './index.scss';

/**
 * 校园通知卡片（首页）
 *
 * 调用后端 /api/miniapp/announcements?page_size=3 获取公告列表，
 * 展示最近 3 条（置顶优先）。
 *
 * 布局（对齐原型，与详情页标签统一）：
 * ┌──────────────────────────────────────┐
 * │ 校园通知                    更多 ›    │
 * │ [置顶] 关于2025年暑假放假安排的通知     │
 * │        教务处   05-19 10:30           │
 * │ ──────────────────────────────────── │
 * │ [通知] 图书馆端午节开放时间调整通知      │
 * │        图书馆   05-19 09:15           │
 * └──────────────────────────────────────┘
 *
 * 标签样式与详情页统一：
 *   置顶 → 红字 + 浅红底圆角「置顶」
 *   非置顶 → 蓝字 + 浅蓝底圆角（分类名，如「通知」「返校」）
 */

/** 取标签信息：置顶显示「置顶」，否则取分类全称 */
function getTagInfo(item: any): { text: string; isTop: boolean } {
  if (item.is_top) return { text: '置顶', isTop: true };
  const label = item.category_label || item.category || '通知';
  return { text: label, isTop: false };
}

export default function NoticeCard() {
  const [list, setList] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    announcementsApi
      .getList({ page_size: 3 })
      .then((res) => {
        const items = (res as any)?.data?.items || [];
        setList(items.slice(0, 3));
      })
      .catch(() => {
        /* 静默失败 */
      })
      .finally(() => setLoading(false));
  }, []);

  /** 点击条目跳详情 */
  const goToDetail = (id: number) => {
    Taro.navigateTo({ url: `/pages/announcement/detail/index?id=${id}` });
  };

  /** 点击"更多"进入通知公告列表页 */
  const goToList = () => {
    Taro.navigateTo({ url: '/pages/announcement/index/index' });
  };

  return (
    <View className="card notice-card">
      <View className="notice-header">
        <Text className="notice-title">校园通知</Text>
        <Text className="notice-more" onClick={goToList}>更多 ›</Text>
      </View>

      {loading ? (
        <View className="notice-loading">
          <Icon name="loading" size={20} color="#c8ccd4" />
        </View>
      ) : list.length === 0 ? (
        <View className="notice-empty">
          <Text className="notice-empty-text">暂无通知</Text>
        </View>
      ) : (
        <View className="notice-list">
          {list.map((item) => {
            const tag = getTagInfo(item);
            return (
              <View key={item.id} className="notice-item" onClick={() => goToDetail(item.id)}>
                <View className="notice-item-main">
                  <Text className={`notice-tag ${tag.isTop ? 'tag-top' : 'tag-cat'}`}>
                    {tag.text}
                  </Text>
                  <Text className="notice-item-title">{item.title || '无标题'}</Text>
                </View>
                <View className="notice-item-meta">
                  <Text className="notice-dept">{item.department || ''}</Text>
                  {item.published_label && (
                    <Text className="notice-time">{item.published_label}</Text>
                  )}
                </View>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}
