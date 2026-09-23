import { useState, useEffect, useMemo } from 'react';
import { View, Text } from '@tarojs/components';
import { useRouter, useLoad } from '@tarojs/taro';

import * as scheduleApi from '@/api/schedule';
import type { ScheduleCourse } from '@/types/api';
import { weekdayCN } from '@/utils/date';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/** 与课表页完全一致的 10 色哈希 */
const COURSE_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1',
  '#13c2c2', '#eb2f96', '#f5222d', '#fa541c', '#fa8c16',
];

function getCourseColorIndex(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % COURSE_COLORS.length;
}

/** 格式化 periods 数组为 "1-2节" 文本 */
function formatPeriods(course: ScheduleCourse): string {
  const p = course.periods;
  if (!p) return '';
  if (Array.isArray(p)) return `${p[0]}-${p[p.length - 1]}节`;
  return String(p);
}

/**
 * 汇总同一天同一门课的多段节次：
 * - 收集当天所有节次编号并排序
 * - 合并连续区间（1-2 + 3-4 => "1-4节"；1-2 + 5-6 => "1-2节、5-6节"）
 */
function buildPeriodSummary(courses: ScheduleCourse[]): string {
  const nums = new Set<number>();
  for (const c of courses) {
    const p = c.periods;
    if (Array.isArray(p)) {
      p.forEach((n) => {
        const v = Number(n);
        if (!Number.isNaN(v)) nums.add(v);
      });
    } else if (typeof p === 'number') {
      nums.add(p);
    }
  }
  const sorted = Array.from(nums).sort((a, b) => a - b);
  if (sorted.length === 0) return '';
  const ranges: [number, number][] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === prev + 1) {
      prev = sorted[i];
    } else {
      ranges.push([start, prev]);
      start = sorted[i];
      prev = sorted[i];
    }
  }
  ranges.push([start, prev]);
  return ranges.map(([a, b]) => (a === b ? `${a}节` : `${a}-${b}节`)).join('、');
}

export default function CourseDetailPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [weekCourses, setWeekCourses] = useState<ScheduleCourse[]>([]);
  const [currentCourseId, setCurrentCourseId] = useState<string>('');

  useLoad(() => {
    const id = (router.params?.id || '') as string;
    // 课表页跳转时携带当前查看的周次与学期；缺省时后端按当前教学周/当前学期
    const wkParam = Number(router.params?.week_number);
    const wkNum = Number.isInteger(wkParam) && wkParam >= 1 ? wkParam : undefined;
    const semParam = Number(router.params?.semester_id);
    const semId = Number.isInteger(semParam) && semParam >= 1 ? semParam : undefined;
    setCurrentCourseId(id);
    if (id) loadDetail(id, wkNum, semId);
  });

  async function loadDetail(scheduleId: string, weekNumber?: number, semesterId?: number) {
    setLoading(true);
    try {
      // 获取指定学期指定周课程（用于"本周课程安排" + 定位当前课程），
      // 与课表页当前查看的学期/周次保持一致，避免上学期课程被当成当前学期而查不到
      const res = await scheduleApi.getWeek(weekNumber, semesterId);
      setWeekCourses(res.data.courses || []);
    } catch {
      // 静默失败，显示空态
    }
    setLoading(false);
  }

  /** 从周课表中找到当前点击的课程 */
  const currentCourse = useMemo(
    () => weekCourses.find((c) => c.schedule_id === currentCourseId) || null,
    [weekCourses, currentCourseId],
  );

  if (loading) return <LoadingState />;
  if (!currentCourse) return <EmptyState title="课程信息不存在" />;

  const colorIdx = getCourseColorIndex(currentCourse.course_name);
  const baseColor = COURSE_COLORS[colorIdx];
  const location = `${currentCourse.extra_info?.building || ''}${currentCourse.extra_info?.classroom || ''}`;
  const periodText = formatPeriods(currentCourse);

  return (
    <View className="cd-page">
      {/* ====== 浅色头部卡片（半透淡彩） ======
          原先用 baseColor 全饱和渐变 + 白字，整体过艳；现在改为低透明度淡彩渐变 +
          文字用基色自身（深）以保证可读性；通过 .cd-header 下的类名区分两个主题。 */}
      <View className="cd-header" style={{ background: `linear-gradient(135deg, ${baseColor}1a, ${baseColor}0d)` }}>
        <Text className="cd-header-title" style={{ color: baseColor }}>
          {currentCourse.course_name}
          {periodText ? ` (${periodText})` : ''}
        </Text>
        <Text className="cd-header-sub" style={{ color: `${baseColor}b3` }}>
          {location || '—'}
          {' · '}
          {currentCourse.extra_info?.teacher || '—'}
        </Text>

        <View className="cd-header-meta">
          <View className="cd-header-meta-item">
            <Text className="iconfont icon-rili cd-header-icon" />
            <Text className="cd-header-meta-text">
              {weekdayCN(currentCourse.day_of_week)} 第{periodText.replace('节', '')}
            </Text>
          </View>
          <View className="cd-header-meta-item">
            <Text className="iconfont icon-shijianzhou cd-header-icon" />
            <Text className="cd-header-meta-text">
              {currentCourse.start_time || '--'}-{currentCourse.end_time || '--'}
            </Text>
          </View>
        </View>

        <View className="cd-header-location">
          <Text className="iconfont icon-jinru cd-header-icon" />
          <Text className="cd-header-meta-text">{location || '—'}</Text>
        </View>
      </View>

      {/* ====== 课程信息 ====== */}
      <View className="cd-section">
        <Text className="cd-section-title">课程信息</Text>
        <Text className="cd-desc">
          {currentCourse.course_name}是本学期重要课程之一，请按时上课。
          如有调课或补课安排，请以教务系统通知为准。
        </Text>
      </View>

      {/* ====== 课表信息 ====== */}
      <View className="cd-section">
        <Text className="cd-section-title">课表信息</Text>
        <View className="cd-info-list">
          {renderInfoRow('课程名称', currentCourse.course_name)}
          {renderInfoRow('课程编号', currentCourse.course_code || '—')}
          {renderInfoRow('授课教师', currentCourse.extra_info?.teacher || '—')}
          {renderInfoRow(
            '上课时间',
            `${weekdayCN(currentCourse.day_of_week)} ${periodText} (${currentCourse.start_time || '--'}-${currentCourse.end_time || '--'})`,
          )}
          {renderInfoRow('上课地点', location || '—')}
          {renderInfoRow('课程类型', currentCourse.extra_info?.credits ? '必修课' : '—')}
          {renderInfoRow('学分', currentCourse.extra_info?.credits || '—')}
        </View>
      </View>

      {/* ====== 课程安排（本周周几有课） ====== */}
      <View className="cd-section">
        <Text className="cd-section-title">课程安排</Text>
        <View className="cd-week-list">
          {(() => {
            // 判断两个 classroom 是否"兼容"（空值互相兼容 + 完全匹配）
            const classroomMatch = (a?: string, b?: string): boolean => {
              const ae = !a || !a.trim();
              const be = !b || !b.trim();
              return ae || be || a === b;
            };
            // 从整周数据中找出同课名、同教室的所有课程记录
            // （教室为空时兼容任意教室，避免爬虫/旧数据缺 classroom 时丢失关联）
            const sameClassroom = currentCourse.extra_info?.classroom;
            const sameCourses = weekCourses.filter(
              (c) =>
                c.course_name === currentCourse.course_name &&
                classroomMatch(c.extra_info?.classroom, sameClassroom) &&
                c.schedule_id !== currentCourse.schedule_id,
            );
            // 当前课程 + 同名课程 → 按 week_day 索引
            const byDay: Record<number, ScheduleCourse[]> = { 1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [] };
            byDay[currentCourse.day_of_week] = [currentCourse];
            for (const c of sameCourses) {
              const dow = c.day_of_week;
              if (dow >= 1 && dow <= 7) byDay[dow].push(c);
            }

            return [1, 2, 3, 4, 5, 6, 7].map((dow) => {
              const courses = byDay[dow];
              const hasClass = courses.length > 0;
              // 同一天多段课 → 汇总节次，地点/教师取该天第一条
              const periodSummary = hasClass ? buildPeriodSummary(courses) : '';
              const first = hasClass ? courses[0] : null;
              const loc = first
                ? `${first.extra_info?.building || ''}${first.extra_info?.classroom || ''}`
                : '';
              const teacher = first?.extra_info?.teacher || '';
              return (
                <View key={dow} className={`cd-week-item ${hasClass ? 'cd-week-item-active' : ''}`}>
                  <Text className={`cd-week-dow ${hasClass ? 'cd-week-dow-active' : ''}`}>
                    {weekdayCN(dow)}
                  </Text>
                  {hasClass ? (
                    <View className="cd-week-course-info">
                      <Text className="cd-week-name" style={{ color: baseColor }}>
                        {currentCourse.course_name} ({periodSummary})
                      </Text>
                      {/* 授课地点在课程名下面一行，教师同行右侧 */}
                      <View className="cd-week-sub">
                        <Text className="cd-week-loc">{loc || '—'}</Text>
                        {teacher ? <Text className="cd-week-meta">{teacher}</Text> : null}
                      </View>
                    </View>
                  ) : (
                    <Text className="cd-week-empty">无课</Text>
                  )}
                </View>
              );
            });
          })()}
        </View>
      </View>
    </View>
  );
}

function renderInfoRow(label: string, value: string) {
  return (
    <View className="cd-info-row" key={label}>
      <Text className="cd-info-label">{label}</Text>
      <Text className="cd-info-value">{value}</Text>
    </View>
  );
}
