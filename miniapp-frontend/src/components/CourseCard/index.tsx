import { View, Text } from '@tarojs/components';

import type { ScheduleCourse } from '@/types/api';
import './index.scss';

interface CourseCardProps {
  course: ScheduleCourse;
  /** 点击跳转课程详情（首页今日课程条目用） */
  onClick?: () => void;
}

/** 课程状态：未开始 / 进行中 / 已结束（仅前端展示态，不改后端数据）
 *
 * 重要：后端返回的 ``_timeInfo.start_ts`` 是按**课程在 DB 里存的 ``week_number`` 字段**
 * （一般是这门课第一次开课的周）算的，**不是**前端当前选中的周。
 * 当用户在时间轴页切换到别的周、但课程被 ``weeks`` 字段匹配选中时，``start_ts``
 * 对应的日期和"选中的那一天"对不上——直接用 ``now`` 比较会把将来的课判为
 * 「已结束」。这时必须传 ``targetDate``（YYYY-MM-DD，**选中那一天**），按
 * 课程的 ``start_time``/``end_time`` 在那一天重算时间戳。
 *
 * @param course 课程
 * @param targetDate 可选。YYYY-MM-DD；提供时按"该日期 + start_time/end_time"
 *   重算有效时间戳；不提供则退回 ``_timeInfo`` 里的值（适用于"今天"接口，
 *   后端已按今天过滤、``start_ts`` 就是今天的）。
 */
export function courseStatus(
  course: ScheduleCourse,
  targetDate?: string
): 'upcoming' | 'ongoing' | 'finished' {
  const now = Date.now() / 1000;
  const { start_ts, end_ts } = course._timeInfo || {};
  let effectiveStart: number | undefined = start_ts;
  let effectiveEnd: number | undefined = end_ts;
  if (targetDate && course.start_time && course.end_time) {
    const m = targetDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (m) {
      const [, y, mo, d] = m;
      const [sh, sm] = course.start_time.split(':').map(Number);
      const [eh, em] = course.end_time.split(':').map(Number);
      if (!Number.isNaN(sh) && !Number.isNaN(eh)) {
        effectiveStart = new Date(+y, +mo - 1, +d, sh, sm).getTime() / 1000;
        effectiveEnd = new Date(+y, +mo - 1, +d, eh, em).getTime() / 1000;
      }
    }
  }
  if (effectiveStart && now < effectiveStart) return 'upcoming';
  if (effectiveEnd && now > effectiveEnd) return 'finished';
  return 'ongoing';
}

/** 节次文本（periods 可能是数组或 JSON 字符串） */
export function formatPeriods(periods: number[] | string | undefined | null): string {
  if (!periods) return '';
  let arr: number[] = [];
  if (Array.isArray(periods)) {
    arr = periods;
  } else if (typeof periods === 'string') {
    try {
      arr = JSON.parse(periods);
    } catch {
      const m = periods.match(/(\d+)\s*[-~]\s*(\d+)/);
      if (m) arr = [Number(m[1]), Number(m[2])];
    }
  }
  if (arr.length >= 2) return `${arr[0]}-${arr[arr.length - 1]}节`;
  if (arr.length === 1) return `${arr[0]}节`;
  return '';
}

/** 课程颜色：基于课程名加权 hash 选固定颜色（5 选 1）
 *  与 TimelineItem 同算法，保证首页/时间轴同门课同色 */
export function courseColorKey(name: string): 'green' | 'blue' | 'orange' | 'purple' | 'pink' {
  const keys: ('green' | 'blue' | 'orange' | 'purple' | 'pink')[] = [
    'green',
    'blue',
    'orange',
    'purple',
    'pink',
  ];
  const hash = (name || '').split('').reduce((acc, ch, i) => (acc + ch.charCodeAt(0) * (i + 1)) % 997, 0);
  return keys[hash % keys.length];
}

const COLOR_HEX: Record<'green' | 'blue' | 'orange' | 'purple' | 'pink', string> = {
  green: '#34c759',
  blue: '#1a73e8',
  orange: '#ff8f1f',
  purple: '#a055dc',
  pink: '#e63c82',
};

/**
 * 今日课程卡片（首页用，对齐原型图）
 * 结构：节次 + 圆点 + 课程名 + 教室 + 时间（全部一行水平）
 */
export default function CourseCard({ course, onClick }: CourseCardProps) {
  const status = courseStatus(course);
  const teacher = course.extra_info?.teacher || '';
  const building = course.extra_info?.building || '';
  const classroom = course.extra_info?.classroom || '';
  // 教室 = 楼栋 + 教室（无楼栋则只显示教室号）
  const location = building + classroom;
  const periodsText = formatPeriods(course.periods as number[] | string | undefined);
  // 颜色：已结束课程整体变灰，否则按课程名 hash
  const colorKey = courseColorKey(course.course_name);
  const dotColor = status === 'finished' ? '#c8c9cc' : COLOR_HEX[colorKey];
  const textColor = status === 'finished' ? '#c8c9cc' : '';
  const periodText = periodsText;

  return (
    <View
      className={`course-card ${status === 'finished' ? 'course-card-finished' : ''}`}
      onClick={onClick}
      hoverClass={onClick ? 'course-card-hover' : undefined}
    >
      <Text className={`course-period ${status === 'finished' ? 'course-finished' : ''}`}>
        {periodText}
      </Text>
      <View className="course-dot" style={{ background: dotColor }} />
      <Text
        className="course-name"
        style={status === 'finished' ? { color: '#c8c9cc' } : {}}
      >
        {course.course_name}
      </Text>
      <Text
        className="course-location"
        style={status === 'finished' ? { color: '#c8c9cc' } : {}}
      >
        {location || teacher}
      </Text>
      <Text
        className="course-time-range"
        style={status === 'finished' ? { color: '#c8c9cc' } : {}}
      >
        {course.start_time}-{course.end_time}
      </Text>
    </View>
  );
}