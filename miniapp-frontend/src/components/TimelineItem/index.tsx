import { View, Text } from '@tarojs/components';

import './index.scss';

export type TimelineStatus = 'upcoming' | 'ongoing' | 'finished' | 'info';
export type CourseColorKey = 'green' | 'blue' | 'orange' | 'purple' | 'pink';

interface TimelineItemProps {
  /** 左侧时间文本（HH:mm），大字号显示 */
  time: string;
  /** 节次文本，如 "1-2节"，小灰字显示在时间下方 */
  periodsText?: string;
  /** 课程名（粗体大字） */
  courseName: string;
  /** 教室（如 "B201"） */
  building?: string;
  /** 教室详细（楼栋+教室号，如 "理工楼501软件开发实训室"） */
  classroom?: string;
  /** 教师 */
  teacher?: string;
  /** 状态（决定状态标签颜色） */
  status?: TimelineStatus;
  /** 状态文本（如 进行中/未开始/已结束） */
  statusText?: string;
  /** 课程颜色 key（决定卡片底色 + 圆点双层颜色，同一课程名稳定不变） */
  courseColorKey?: CourseColorKey;
  /** 是否为时间轴最后一项（不画底部竖线） */
  isLast?: boolean;
}

const STATUS_TAG_CLASS: Record<TimelineStatus, string> = {
  upcoming: 'tag-upcoming',
  ongoing: 'tag-ongoing',
  finished: 'tag-finished',
  info: 'tag-info',
};
// 注：状态标签类已改为跟随卡片色（tag-color-*），STATUS_TAG_CLASS 保留备用

/**
 * 时间轴条目（圆点 + 竖线 + 时间 + 课程卡片）
 * 结构（对齐原型图）：
 * ┌─────────────────────────────────────────────┐
 * │  08:10    ⬤        软件工程实践（1-2节）  [未开始] │
 * │  1-2节    │        理工楼501软件开发实训室 · 王老师 │
 * │           ↓                                    │
 * │  10:30    ⬤        数据库应用（3-4节）      │
 * │           │        ...                         │
 * └─────────────────────────────────────────────┘
 * 圆点双层结构：外层淡色环 + 内层空心圆（颜色按 courseColorKey）
 * 状态标签颜色跟随卡片色（courseColorKey）
 */
export default function TimelineItem({
  time,
  periodsText,
  courseName,
  building,
  classroom,
  teacher,
  status = 'info',
  statusText,
  courseColorKey = 'blue',
  isLast,
}: TimelineItemProps) {
  const location = [building, classroom].filter(Boolean).join('');
  return (
    <View className={`timeline-item ${status === 'finished' ? 'timeline-item-finished' : ''}`}>
      {/* 左列：时间 + 节次 */}
      <View className="timeline-time-col">
        <Text className="timeline-time">{time}</Text>
        {periodsText ? <Text className="timeline-periods">{periodsText}</Text> : null}
      </View>

      {/* 中列：圆点（双层）+ 竖线 */}
      <View className="timeline-rail">
        <View className={`timeline-dot-outer dot-color-${courseColorKey}`}>
          <View className={`timeline-dot-inner dot-color-${courseColorKey}`} />
        </View>
        {!isLast ? <View className="timeline-line" /> : null}
      </View>

      {/* 右列：课程卡片（颜色按 courseColorKey） */}
      <View className="timeline-body">
        <View className={`timeline-card card-color-${courseColorKey}`}>
          <View className="timeline-card-head">
            <Text className="timeline-title">
              {courseName}
              {periodsText ? <Text className="timeline-title-periods">（{periodsText}）</Text> : null}
            </Text>
            {statusText ? (
              <Text className={`timeline-tag tag-color-${courseColorKey}`}>{statusText}</Text>
            ) : null}
          </View>
          {location || teacher ? (
            <Text className="timeline-location">
              {[location, teacher].filter(Boolean).join(' · ')}
            </Text>
          ) : null}
        </View>
      </View>
    </View>
  );
}