import { useState } from 'react';
import { View, Text, ScrollView, Image } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';

import * as notificationsApi from '@/api/notifications';
import type { UserNotificationItem } from '@/types/api';
import { API_BASE_URL } from '@/utils/request';
import './index.scss';

/**
 * 消息详情（个人站内通知）
 *
 * 消息列表只展示摘要（电量日报/周报/月报正文较长，全部铺开会让列表很臃肿），
 * 点进来看完整内容；后端在进入详情时已自动标记已读。
 */

const CATEGORY_LABEL: Record<string, string> = {
  electricity_daily: '电量日报',
  electricity_weekly: '电量周报',
  electricity_monthly: '电量月报',
  low_power: '低电量提醒',
  cookie_invalid: '配置失效',
  fetch_error: '采集异常',
};

/** 完整时间：YYYY-MM-DD HH:mm（后端 created_at 为 "YYYY-MM-DD HH:mm:ss"） */
function fullTime(ts: string | null): string {
  if (!ts) return '';
  return ts.slice(0, 16);
}

export default function MessageDetailPage() {
  const [detail, setDetail] = useState<UserNotificationItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useLoad((opts) => {
    Taro.setNavigationBarTitle({ title: '消息详情' });
    const id = Number(opts?.id);
    if (!id) {
      setError('缺少消息 id');
      setLoading(false);
      return;
    }
    notificationsApi
      .getNotificationDetail(id)
      .then((res) => {
        setDetail(res?.data?.notification || null);
      })
      .catch((e) => {
        setError((e as Error).message || '加载失败');
      })
      .finally(() => setLoading(false));
  });

  if (loading) {
    return (
      <View className="msgd-page">
        <View className="msgd-tip">
          <Text>加载中...</Text>
        </View>
      </View>
    );
  }

  if (error || !detail) {
    return (
      <View className="msgd-page">
        <View className="msgd-tip">
          <Text>{error || '消息不存在'}</Text>
        </View>
      </View>
    );
  }

  return (
    <ScrollView scrollY className="msgd-page">
      <View className="msgd-head">
        <Text className="msgd-cat">{CATEGORY_LABEL[detail.category] || '系统通知'}</Text>
        <Text className="msgd-time">{fullTime(detail.created_at)}</Text>
      </View>
      <Text className="msgd-title">{detail.title}</Text>
      {/* 封面图：标题之下、正文之上，有图才渲染（无图不占位） */}
      {detail.cover_url ? (
        <Image className="msgd-cover" src={`${API_BASE_URL}${detail.cover_url}`} mode="widthFix" />
      ) : null}
      <View className="msgd-divider" />
      {/* 正文为纯文本、\n 换行，用 pre-wrap 保留原始排版 */}
      <Text className="msgd-content">{detail.content || '（无正文）'}</Text>
    </ScrollView>
  );
}
