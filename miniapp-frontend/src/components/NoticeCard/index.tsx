import { useState, useEffect } from 'react';
import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { Icon } from '@nutui/nutui-react-taro';
import * as notificationApi from '@/api/notification';

import './index.scss';

/** 通知条目（兼容公告和日历事件两种响应结构）*/
interface NoticeItem {
  id?: number;
  title: string;
  summary?: string | null;
  content?: string | null;
  published_at?: string;
  event_date?: string;
  event_date_label?: string;
  description?: string | null;
}

/**
 * 校园通知卡片（首页）
 *
 * 调用后端 /api/miniapp/notifications/upcoming?limit=3 获取真实数据，
 * 展示最近 3 条通知（标题+摘要+时间），点击跳转通知列表页。
 */
export default function NoticeCard() {
  const [list, setList] = useState<NoticeItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    notificationApi.getUpcoming({ limit: 3 })
      .then((res) => {
        const data = (res as any)?.data;
        // 兼容两种响应结构：{ list: [...] } 或 { events: [...] } 或直接数组
        let items: any[] = [];
        if (Array.isArray(data?.list)) items = data.list;
        else if (Array.isArray(data?.events)) items = data.events;
        else if (Array.isArray(data)) items = data;
        setList(items.slice(0, 3).map(normalizeItem));
      })
      .catch(() => {
        /* 静默失败，显示空态 */
      })
      .finally(() => setLoading(false));
  }, []);

  const goToList = () => {
    Taro.showToast({ title: '通知列表开发中', icon: 'none' });
  };

  return (
    <View className="card notice-card" onClick={goToList}>
      <View className="card-header">
        <Text className="card-title">校园通知</Text>
        <Text className="card-more">查看更多 ›</Text>
      </View>

      {loading ? (
        <View className="notice-loading">
          <Icon name="loading" size={20} color="#c8ccd4" />
        </View>
      ) : list.length === 0 ? (
        <View className="notice-empty">
          <Icon name="notice" size={32} color="#c8ccd4" />
          <Text className="notice-text">暂无通知</Text>
        </View>
      ) : (
        <View className="notice-list">
          {list.map((item, idx) => (
            <View key={item.id || idx} className="notice-item">
              <View className="notice-item-dot" />
              <View className="notice-item-body">
                <Text className="notice-item-title">{item.title || '无标题'}</Text>
                {(item.summary || item.content || item.description) && (
                  <Text className="notice-item-desc" numberOfLines={2}>
                    {item.summary || item.description ||
                      stripHtml(item.content || '').slice(0, 60)}
                  </Text>
                )}
              </View>
              {(item.published_at || item.event_date_label) && (
                <Text className="notice-item-time">
                  {formatRelativeTime(item.published_at || item.event_date || '')}
                </Text>
              )}
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

/** 统一不同来源的字段为 NoticeItem */
function normalizeItem(raw: any): NoticeItem {
  return {
    id: raw.id,
    title: raw.title || '',
    summary: raw.summary ?? null,
    content: raw.content ?? null,
    published_at: raw.published_at ?? raw.event_date ?? null,
    event_date_label: raw.event_date_label ?? null,
    description: raw.description ?? null,
  };
}

/** 去除 HTML 标签 */
function stripHtml(html: string): string {
  return html.replace(/<[^>]+>/g, '');
}

/** 简易相对时间格式化 */
function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return '';
  const now = Date.now();
  const target = new Date(dateStr).getTime();
  const diff = now - target;
  if (Number.isNaN(diff)) return dateStr.slice(0, 10);

  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return `${min}分钟前`;

  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;

  const day = Math.floor(hr / 24);
  if (day === 1) return '昨天';
  if (day < 7) return `${day}天前`;

  return dateStr.slice(0, 10);
}
