import { useState } from 'react';
import { View, Text, Image, ScrollView } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';

import * as feedbackApi from '@/api/feedback';
import { API_BASE_URL } from '@/utils/request';
import { markViewed } from '@/utils/feedbackBadge';
import type { FeedbackDetail } from '@/types/api';
import './index.scss';

/**
 * 反馈详情（学生侧）
 *
 * 展示反馈类型 / 状态 / 内容 / 截图 / 提交时间，
 * 以及管理员回复（处理完成后显示）。
 */

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

export default function FeedbackDetailPage() {
  const [detail, setDetail] = useState<FeedbackDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useLoad((opts) => {
    Taro.setNavigationBarTitle({ title: '反馈详情' });
    const id = Number(opts?.id);
    if (!id) {
      setError('缺少反馈 id');
      setLoading(false);
      return;
    }
    feedbackApi
      .getDetail(id)
      .then((res) => {
        const fb = res?.data?.feedback || null;
        setDetail(fb);
        // 进入详情即视为「看过当前状态」→ 若该状态未再变化则红点 -1
        if (fb) {
          markViewed(fb.id, fb.status);
        }
      })
      .catch((e) => {
        setError((e as Error).message || '加载失败');
      })
      .finally(() => setLoading(false));
  });

  if (loading) {
    return (
      <View className="fb-detail-page">
        <View className="fb-detail-loading">
          <Text>加载中...</Text>
        </View>
      </View>
    );
  }

  if (error || !detail) {
    return (
      <View className="fb-detail-page">
        <View className="fb-detail-error">
          <Text>{error || '反馈不存在'}</Text>
        </View>
      </View>
    );
  }

  return (
    <View className="fb-detail-page">
      <ScrollView className="fb-detail-scroll" scrollY>
        <View className="fb-detail-card">
          <View className="fb-detail-head">
            <Text className="fb-detail-type">{detail.type_label}</Text>
            <Text className={`fb-detail-status ${statusClass(detail.status)}`}>
              {detail.status_label}
            </Text>
          </View>

          <Text className="fb-detail-content">{detail.content}</Text>

          {detail.images && detail.images.length ? (
            <View className="fb-detail-images">
              {detail.images.map((url, i) => (
                <Image
                  key={url + i}
                  className="fb-detail-img"
                  src={`${API_BASE_URL}${url}`}
                  mode="widthFix"
                />
              ))}
            </View>
          ) : null}

          <View className="fb-detail-row">
            <Text className="fb-detail-key">提交时间</Text>
            <Text className="fb-detail-val">{detail.created_at}</Text>
          </View>
        </View>

        {/* 管理员回复 */}
        {detail.reply ? (
          <View className="fb-reply-card">
            <View className="fb-reply-title">
              <Text className="fb-reply-dot" />
              <Text className="fb-reply-title-text">管理员回复</Text>
            </View>
            <Text className="fb-reply-content">{detail.reply}</Text>
            {detail.replied_at ? (
              <Text className="fb-reply-time">{detail.replied_at}</Text>
            ) : null}
          </View>
        ) : (
          <View className="fb-pending-tip">
            <Text>管理员正在处理中，请耐心等待回复</Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

export const config = {
  navigationBarTitleText: '反馈详情',
  enablePullDownRefresh: false,
};
