import { View, Text } from '@tarojs/components';
import { Popup } from '@nutui/nutui-react-taro';

import type { ScheduleCourse } from '@/types/api';
import { weekdayCN } from '@/utils/date';
import './index.scss';

interface CourseDetailProps {
  course: ScheduleCourse | null;
  visible: boolean;
  onClose: () => void;
}

/**
 * 课程详情弹层（§12.1）
 * - 只展示后端 API 实际存在的数据：名称/教师/教室/时间/节次/周次
 * - 后端无 remark（备注）字段 → 不虚构展示
 */
export default function CourseDetail({ course, visible, onClose }: CourseDetailProps) {
  if (!course) return null;

  const weeks = course.extra_info?.weeks;
  const weeksText = Array.isArray(weeks) ? weeks.join('、') : weeks ? String(weeks) : '';
  const periodText = Array.isArray(course.periods)
    ? course.periods.join('-')
    : course.periods
      ? String(course.periods)
      : '';

  const rows: Array<[string, string]> = [
    ['课程', course.course_name],
    ['教师', course.extra_info?.teacher || '—'],
    ['教室', `${course.extra_info?.building || ''}${course.extra_info?.classroom || ''}` || '—'],
    ['时间', `${course.start_time || '--'} - ${course.end_time || '--'}`],
  ];
  if (periodText) rows.push(['节次', periodText]);
  rows.push(['星期', weekdayCN(course.day_of_week)]);
  if (weeksText) rows.push(['周次', weeksText]);

  return (
    <Popup
      visible={visible}
      onClose={onClose}
      position="bottom"
      round
      closeable
      closeIconPosition="top-right"
    >
      <View className="course-detail">
        <Text className="detail-title">{course.course_name}</Text>
        <View className="detail-rows">
          {rows.map(([label, value]) => (
            <View className="detail-row" key={label}>
              <Text className="detail-label">{label}</Text>
              <Text className="detail-value">{value}</Text>
            </View>
          ))}
        </View>
      </View>
    </Popup>
  );
}
