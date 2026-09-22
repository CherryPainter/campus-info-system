import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import type { NotificationEvent } from '@/types/api';
import IconArrow from '@/components/IconArrow';

import './index.scss';

interface ReminderCardProps {
  events: NotificationEvent[];
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
}

/** 圆点/胶囊配色（按 category 映射） */
function getCategoryColor(category: NotificationEvent['category']): string {
  switch (category) {
    case 'exam':
      return '#ff8f1f'; // 橙
    case 'holiday':
      return '#1a73e8'; // 蓝
    case 'activity':
      return '#34c759'; // 绿
    default:
      return '#8a8f99'; // 灰
  }
}

/**
 * 近期提醒卡片
 *
 * 结构（对齐原型图）：
 * ┌────────────────────────────────────┐
 * │ 近期提醒              更多 ›       │
 * │ 08-31 ● 计算机等级考试报名截止  [还剩2天] │
 * │ 09-07 ● 中秋节放假          [还剩9天] │
 * │ 09-12 ● 校运动会开幕式       [还剩14天]│
 * │ 09-19 ● 英语四级考试          [还剩21天]│
 * │ 09-30 ● 国庆节放假通知        [还剩32天]│
 * └────────────────────────────────────┘
 */
export default function ReminderCard({
  events,
  loading = false,
  error = false,
  onRetry,
}: ReminderCardProps) {
  if (loading) {
    return (
      <View className="card reminder-card">
        <Text className="reminder-title">近期提醒</Text>
        <Text className="reminder-loading">正在加载…</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View className="card reminder-card">
        <Text className="reminder-title">近期提醒</Text>
        <View className="reminder-error" onClick={onRetry}>
          <Text className="reminder-error-text">加载失败，点击重试</Text>
        </View>
      </View>
    );
  }

  if (events.length === 0) {
    return (
      <View className="card reminder-card">
        <Text className="reminder-title">近期提醒</Text>
        <Text className="reminder-empty">近期没有重要安排</Text>
      </View>
    );
  }

  return (
    <View className="card reminder-card">
      <View className="reminder-header">
        <Text className="reminder-title">近期提醒</Text>
        <View
          className="reminder-more"
          onClick={() => Taro.showToast({ title: '等待学校开放接口', icon: 'none' })}
        >
          <Text>更多</Text>
          <IconArrow size="sm" />
        </View>
      </View>

      <View className="reminder-list">
        {events.map((e, idx) => {
          const color = getCategoryColor(e.category);
          return (
            <View
              key={e.id}
              className={`reminder-item ${idx === events.length - 1 ? 'reminder-item-last' : ''}`}
            >
              <Text className="reminder-date">{e.event_date_label}</Text>
              <View
                className="reminder-dot"
                style={{ background: color }}
              />
              <Text className="reminder-event-title">{e.title}</Text>
              <View
                className="reminder-days-tag"
                style={{ background: `${color}1a`, color }}
              >
                <Text className="reminder-days-text" style={{ color }}>
                  {e.days_left === 0 ? '今天' : `还剩${e.days_left}天`}
                </Text>
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}