import { useMemo, useState, useCallback, useEffect } from 'react';
import { View, Text, Swiper, SwiperItem, PickerView, PickerViewColumn } from '@tarojs/components';
import { useLoad, usePullDownRefresh, stopPullDownRefresh, navigateTo } from '@tarojs/taro';
import dayjs from 'dayjs';

import * as scheduleApi from '@/api/schedule';
import type { ScheduleCourse } from '@/types/api';
import TimelineItem, { type TimelineStatus } from '@/components/TimelineItem';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 课表详情页（双版式）
 *
 * 渲染逻辑完全对齐网页端 Course.tsx 移动端 renderCourseCell：
 * - 同 10 色哈希（与网页端同课程同色）
 * - 合并条件：同名 + 教师空值兼容 + 教室空值兼容 + 严格相邻
 * - 进行中：渐变背景 + 红色左边框 + "正在上课"徽章
 * - 已结束：灰底 + 灰字 + 灰色边框
 * - 节数标签：优先 periods → period_name → period_idx 兜底
 */

const WEEK_LABELS = ['日', '一', '二', '三', '四', '五', '六'];

/* ====== 颜色体系：与网页端 Course.tsx 完全一致的 10 色哈希 ====== */
const COURSE_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1',
  '#13c2c2', '#eb2f96', '#f5222d', '#fa541c', '#fa8c16',
];

/** 与网页端 getCourseColorIndex 完全相同的哈希函数 */
function getCourseColorIndex(courseName: string): number {
  let hash = 0;
  for (let i = 0; i < courseName.length; i++) {
    hash = courseName.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % COURSE_COLORS.length;
}

/** 中文数字映射（对齐网页端 CN_NUM） */
const CN_NUM: Record<string, number> = {
  一: 1, 二: 2, 三: 3, 四: 4, 五: 5,
  六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
  十一: 11, 十二: 12,
};

/** 将 period_name 中的中文数字转阿拉伯数字（对齐网页端 normalizePeriodName） */
function normalizePeriodName(name: string): string {
  return name.replace(/[一二三四五六七八九十]+/g, (m) => String(CN_NUM[m] ?? m));
}

/**
 * 解析节数——与网页端 Course.tsx parsePeriods 完全一致的优先级链：
 * 1. period_name 字段（支持 "第7-10节" / "第7、8节" / "第七、八节" / "第2节" / "第二节"）
 * 2. periods 字段（JSON 数组 / 逗号分隔字符串）
 * 3. period_idx 兜底
 */
function parsePeriods(course: ScheduleCourse): number[] {
  const norm = (n: number) => (n >= 1 && n <= 12 ? n : NaN);
  const clean = (arr: number[]) => arr.map(norm).filter((n) => !isNaN(n));

  // 1. period_name 字段（对齐网页端完整解析链，优先级最高）
  const pn = (course as any).period_name;
  if (pn) {
    const name = normalizePeriodName(String(pn));
    // "第7-10节"
    let m = name.match(/第(\d+)[-~～](\d+)节/);
    if (m) {
      const f = Number(m[1]), e = Number(m[2]);
      if (f <= e) return clean(Array.from({ length: e - f + 1 }, (_, i) => f + i));
    }
    // "第7、8节"
    m = name.match(/第(\d+)、(\d+)节/);
    if (m) {
      const f = Number(m[1]), e = Number(m[2]);
      if (f <= e) return clean(Array.from({ length: e - f + 1 }, (_, i) => f + i));
    }
    // "第2节"
    m = name.match(/第(\d+)节/);
    if (m) return clean([Number(m[1])]);
  }

  // 2. periods 字段
  const pd = course.periods;
  if (Array.isArray(pd)) return clean(pd.map(Number));
  if (typeof pd === 'string' && pd) {
    try {
      const a = JSON.parse(pd);
      if (Array.isArray(a)) return clean(a.map(Number));
    } catch { /* 继续 */ }
    return clean(pd.split(',').map(Number));
  }

  // 3. period_idx 兜底
  const pi = course.period_idx;
  return pi && pi >= 1 && pi <= 12 ? [pi] : [];
}

/** 格式化节数标签文本（对齐网页端 renderCourseCell 节数显示） */
function formatPeriodLabel(course: ScheduleCourse): string {
  const ps = parsePeriods(course);
  if (ps.length === 0) return `第${course.period_idx}节`;
  if (ps.length === 1) return `第${ps[0]}节`;
  return `第${ps[0]}-${ps[ps.length - 1]}节`;
}

// 课程格行高（rpx），跨节课程高度 = rowSpan * ROW_H
const ROW_H = 130;

interface Cell {
  course: ScheduleCourse;
  rowSpan: number;
  render: boolean;
  isOngoing: boolean;
  isPast: boolean;
}

/**
 * 构建 cellMap —— 完全对齐网页端 Course.tsx 的 cellMap useMemo 逻辑：
 * 1. 按 day_of_week 分组
 * 2. 解析每条课程的节数，按首节排序
 * 3. 合并相邻同名同教师(空兼容)同教室(空兼容)课程
 * 4. 写入 map[day][startPeriod] 并标记合并占位
 * 5. 进行中判断：仅「当前学期 + 当前周 + 今天 + 当前时段」才标 isOngoing
 */
function buildCellMap(
  courses: ScheduleCourse[],
  currentWeekNumber: number,
  displayWeekNumber: number,
): { map: Record<number, Record<number, Cell>>; maxPeriod: number } {
  const map: Record<number, Record<number, Cell>> = {};
  for (let d = 1; d <= 7; d++) map[d] = {};
  let maxPeriod = 0;

  // 按天分组
  const byDay: Record<number, ScheduleCourse[]> = {};
  for (const c of courses) {
    const d = c.day_of_week;
    if (d < 1 || d > 7) continue;
    if (!byDay[d]) byDay[d] = [];
    byDay[d].push(c);
  }

  // 字段匹配辅助（空值兼容——对齐网页端 fieldsMatch）
  const fieldsMatch = (a?: string, b?: string): boolean => {
    const ae = a === null || a === undefined || a === '';
    const be = b === null || b === undefined || b === '';
    return ae || be || a === b;
  };

  // 合并相邻同名课程（对齐网页端 mergeAdjacentCourses）
  function merge(dayCourses: ScheduleCourse[]) {
    const withP = dayCourses
      .map((c) => ({ c, ps: parsePeriods(c) }))
      .filter((x) => x.ps.length > 0);
    withP.sort((a, b) => a.ps[0] - b.ps[0]);

    const merged: { course: ScheduleCourse; allPeriods: number[] }[] = [];
    for (const { c, ps } of withP) {
      const last = merged[merged.length - 1];
      const lastEnd = last ? last.allPeriods[last.allPeriods.length - 1] : -999;

      // 合并条件：同名 + 教师(空兼容) + 教室(空兼容) + 严格相邻
      const canMerge =
        last &&
        last.course.course_name === c.course_name &&
        fieldsMatch(last.course.extra_info?.teacher, c.extra_info?.teacher) &&
        fieldsMatch(last.course.extra_info?.classroom, c.extra_info?.classroom) &&
        ps[0] === lastEnd + 1;

      if (canMerge) {
        last.allPeriods = [...last.allPeriods, ...ps];
        last.course = {
          ...last.course,
          end_time: c.end_time,
          periods: last.allPeriods.join(','),
        } as ScheduleCourse;
      } else {
        merged.push({ course: { ...c }, allPeriods: [...ps] });
      }
    }
    return merged;
  }

  // 实时时钟（对齐网页端 "new Date()" 判断进行中）
  const now = new Date();
  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  const todayDow = now.getDay() || 7; // 日=7

  // 是否为「真实当前周」（避免非当前周的课程被误标"进行中"）
  const isRealCurrentWeek = currentWeekNumber > 0 && displayWeekNumber === currentWeekNumber;

  for (let day = 1; day <= 7; day++) {
    const merged = merge(byDay[day] || []);
    for (const { course, allPeriods } of merged) {
      const startPeriod = allPeriods[0];
      const endPeriod = allPeriods[allPeriods.length - 1];
      const rowSpan = endPeriod - startPeriod + 1;

      // 进行中 / 已结束 判断（对齐网页端实时时间比较）
      let courseIsOngoing = false;
      let courseIsPast = false;
      if (
        isRealCurrentWeek &&
        day === todayDow &&
        course.start_time &&
        course.end_time
      ) {
        const [sh, sm] = course.start_time.split(':').map(Number);
        const [eh, em] = course.end_time.split(':').map(Number);
        if (!isNaN(sh) && !isNaN(eh)) {
          const startMin = sh * 60 + sm;
          const endMin = eh * 60 + em;
          courseIsOngoing = currentMinutes >= startMin && currentMinutes <= endMin;
          courseIsPast = currentMinutes > endMin;
        }
      }

      map[day][startPeriod] = {
        course,
        rowSpan,
        render: true,
        isOngoing: courseIsOngoing,
        isPast: courseIsPast,
      };
      for (let p = startPeriod + 1; p <= endPeriod; p++) {
        map[day][p] = { course, rowSpan: 1, render: false, isOngoing: false, isPast: false };
      }
      maxPeriod = Math.max(maxPeriod, endPeriod);
    }
  }
  return { map, maxPeriod };
}

export default function CourseTablePage() {
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'grid' | 'timeline'>('grid');

  // 整周课程（课程表版式用）
  const [weekCourses, setWeekCourses] = useState<ScheduleCourse[]>([]);
  // 选中日课程（时间轴版式用）
  const [courses, setCourses] = useState<ScheduleCourse[]>([]);

  const [weekNumber, setWeekNumber] = useState(0);
  const [isTeachingWeek, setIsTeachingWeek] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  const [showWeekPicker, setShowWeekPicker] = useState(false);
  const [pickerSelected, setPickerSelected] = useState<number>(0);
  const [displayWeekNumber, setDisplayWeekNumber] = useState<number>(0);
  const [availableWeeks, setAvailableWeeks] = useState<{ week_number: number; start_date?: string | null; end_date?: string | null }[]>([]);
  const [semesterName, setSemesterName] = useState('');
  const [hasCourseByDow, setHasCourseByDow] = useState<Set<number>>(new Set());
  // 周历锚定：当前显示周历的周一日期（来自后端 available_weeks.start_date）
  const [weekStartDate, setWeekStartDate] = useState<string | null>(null);

  // 加载整周课程（随选中周次刷新）
  const loadWeekCourses = useCallback(async (wn: number) => {
    if (wn < 1) {
      setWeekCourses([]);
      setHasCourseByDow(new Set());
      return;
    }
    try {
      const weekRes = await scheduleApi.getWeek(wn);
      const wc = (weekRes.data.courses as ScheduleCourse[]) || [];
      setWeekCourses(wc);
      const set = new Set<number>();
      wc.forEach((c) => {
        if (c.day_of_week) set.add(c.day_of_week);
      });
      setHasCourseByDow(set);
    } catch {
      setWeekCourses([]);
      setHasCourseByDow(new Set());
    }
  }, []);

  // 加载选中日课程
  const fetchDayCourses = useCallback(async (date: string) => {
    try {
      const r = await scheduleApi.getToday(date);
      setCourses(r.data.courses);
    } catch {
      setCourses([]);
    }
  }, []);

  // 根据周次推算该周周一日期：以「当前真实日历周一」为基准，按 (wn − baseWk) 相对偏移。
  // 与 schedule 页 + 后端 _calculate_date 口径一致：切换周只是围绕当前时间查看那个周的课程，
  // 不会把日期跳到教学周真实日历（如第2周跳到 03-09）。
  // baseWk 缺省取当前教学周 weekNumber（交互时已就绪）；loadAll 初始化需显式传 wkNum，
  // 避免 setWeekNumber 异步未生效时读到旧值导致偏移错误。
  const getStartDateForWeek = useCallback((wn: number, baseWk?: number): string | null => {
    if (wn < 1) return null;
    const today = dayjs();
    const dow = today.day();
    const thisMonday = today.add(dow === 0 ? -6 : 1 - dow, 'day');
    const base = baseWk && baseWk >= 1 ? baseWk : (weekNumber >= 1 ? weekNumber : 1);
    return thisMonday.add((wn - base) * 7, 'day').format('YYYY-MM-DD');
  }, [weekNumber]);

  // 初始化
  const loadAll = useCallback(async () => {
    setLoading(true);
    const cRes = await scheduleApi
      .getCurrent()
      .then((r) => ({ ok: true as const, d: r.data }))
      .catch(() => ({ ok: false as const, d: null }));
    const rawWk = cRes.ok && cRes.d ? cRes.d.week_number : 0;
    const availWeeks = (cRes.ok && cRes.d ? cRes.d.available_weeks : []) || [];
    const wkNum = rawWk > 0 ? rawWk : (availWeeks.length > 0 ? availWeeks[0].week_number : 0);
    setWeekNumber(rawWk);
    setIsTeachingWeek(cRes.ok && cRes.d ? cRes.d.is_teaching_week : false);
    setDisplayWeekNumber(wkNum);
    if (cRes.ok && cRes.d) {
      setAvailableWeeks(availWeeks);
      setSemesterName(cRes.d.semester_name || '');
    }
    // 周历锚定到相对当前真实周的周一（wkNum 即当前周，偏移 0；不跳教学周真实日历）
    setWeekStartDate(getStartDateForWeek(wkNum, wkNum));
    await loadWeekCourses(wkNum);
    setLoading(false);
  }, [loadWeekCourses, getStartDateForWeek]);

  useLoad(() => {
    loadAll();
    fetchDayCourses(selectedDate);
  });

  useEffect(() => {
    if (selectedDate) fetchDayCourses(selectedDate);
  }, [selectedDate, fetchDayCourses]);

  usePullDownRefresh(async () => {
    await Promise.all([loadAll(), fetchDayCourses(selectedDate)]);
    stopPullDownRefresh();
  });

  // 周历：基于相对当前真实周的 weekStartDate 锚定（不跳教学周真实日历）
  const currentMonday = useMemo(() => {
    if (!weekStartDate) return dayjs(); // 兜底：无数据时回退今天
    const d = dayjs(weekStartDate);
    // 确保 start_date 是周一（后端已保证，防御性校验）
    const dow = d.day();
    const monday = dow === 1 ? d : (dow === 0 ? d.add(-6, 'day') : d.add(1 - dow, 'day'));
    return monday;
  }, [weekStartDate]);

  const todayStr = dayjs().format('YYYY-MM-DD');
  const todayDow = dayjs().day() === 0 ? 7 : dayjs().day();

  // Swiper 左右滑动切换周次：基于 available_weeks 相邻周
  const onSwiperChange = useCallback((e: any) => {
    const cur = e.detail.current;
    if (cur === 2) {
      // 往后（周次+1）
      setDisplayWeekNumber((prev) => {
        const next = prev + 1;
        setWeekStartDate(getStartDateForWeek(next));
        loadWeekCourses(next);
        return next;
      });
    } else if (cur === 0) {
      // 往前（周次-1）
      setDisplayWeekNumber((prev) => {
        const prevW = prev - 1;
        if (prevW < 1) return prev; // 不允许小于第1周
        setWeekStartDate(getStartDateForWeek(prevW));
        loadWeekCourses(prevW);
        return prevW;
      });
    }
  }, [availableWeeks, loadWeekCourses, getStartDateForWeek]);

  const pickWeek = useCallback(
    (wn: number) => {
      setDisplayWeekNumber(wn);
      setWeekStartDate(getStartDateForWeek(wn));
      // selectedDate 设为该周对应的今天所在位置（若今天在该周内则用今天，否则用该周周一）
      if (weekStartDate) {
        const monday = dayjs(weekStartDate);
        const today = dayjs();
        // 检查今天是否在该周范围内
        const weekEnd = monday.add(6, 'day');
        if ((today.isAfter(monday) || today.isSame(monday, 'day')) &&
            (today.isBefore(weekEnd) || today.isSame(weekEnd, 'day'))) {
          setSelectedDate(today.format('YYYY-MM-DD'));
        } else {
          setSelectedDate(monday.format('YYYY-MM-DD'));
        }
      }
      setShowWeekPicker(false);
      loadWeekCourses(wn);
    },
    [availableWeeks, loadWeekCourses, getStartDateForWeek],
  );

  const openWeekPicker = useCallback(() => {
    if (availableWeeks.length > 0 && displayWeekNumber > 0) {
      const idx = availableWeeks.findIndex((w) => w.week_number === displayWeekNumber);
      setPickerSelected(idx >= 0 ? idx : 0);
    } else {
      setPickerSelected(0);
    }
    setShowWeekPicker(true);
  }, [availableWeeks, displayWeekNumber]);

  const onPickerChange = useCallback((e: any) => setPickerSelected(e.detail.value), []);
  const confirmPicker = useCallback(() => {
    if (availableWeeks.length > 0) {
      const wn = availableWeeks[pickerSelected]?.week_number;
      if (wn) pickWeek(wn);
    }
    setShowWeekPicker(false);
  }, [availableWeeks, pickerSelected, pickWeek]);

  // ====== 课程表版式数据 ======
  const { map, maxPeriod } = useMemo(
    () => buildCellMap(weekCourses, weekNumber, displayWeekNumber),
    [weekCourses, weekNumber, displayWeekNumber],
  );
  // 固定12行（对齐网页端 Course.tsx），不依赖实际数据的 maxPeriod
  const periodList = useMemo(() => Array.from({ length: 12 }, (_, i) => i + 1), []);
  // 列：周一~周五固定，周末有课才追加（对齐网页端移动端列策略）
  const dayList = useMemo(() => {
    const list = [1, 2, 3, 4, 5];
    if (hasCourseByDow.has(6)) list.push(6);
    if (hasCourseByDow.has(7)) list.push(7);
    return list;
  }, [hasCourseByDow]);

  // ====== 时间轴版式数据 ======
  const displayCourses = useMemo(
    () => [...courses].sort((a, b) => (a._timeInfo?.start_ts || 0) - (b._timeInfo?.start_ts || 0)),
    [courses],
  );

  const weekText = displayWeekNumber > 0 ? `第 ${displayWeekNumber} 周` : '非教学周';
  const badgeText = isTeachingWeek ? '教学周' : '假期';

  /** 课表网格骨架屏：进入页面立即渲染网格结构，数据到达后填充真实卡片（消除"导航先出、页面后出"的白屏等待） */
  const renderGridSkeleton = () => (
    <View className="ct-table ct-skeleton">
      <View className="ct-table-inner">
        {/* 固定节次列 */}
        <View className="ct-col-period">
          <View className="ct-cell ct-corner">
            <Text className="ct-corner-text">节</Text>
          </View>
          {periodList.map((p) => (
            <View className="ct-cell ct-period-cell" key={p}>
              <Text className="ct-period-num">{p}</Text>
            </View>
          ))}
        </View>
        {/* 课程区骨架占位（固定周一~周五 5 列，周末列等数据到达后追加） */}
        <View className="ct-cols">
          {[1, 2, 3, 4, 5].map((day) => (
            <View className="ct-col" key={day}>
              <View className="ct-cell ct-day-head">
                <View className="ct-skeleton-block ct-skeleton-day" />
              </View>
              {periodList.map((p) => (
                <View className="ct-cell" key={p}>
                  <View className="ct-skeleton-block" />
                </View>
              ))}
            </View>
          ))}
        </View>
      </View>
    </View>
  );

  /** 时间轴版式骨架：几条圆点竖线 + 卡片占位 */
  const renderTimelineSkeleton = () => (
    <View className="timeline-list ct-skeleton-timeline">
      {[1, 2, 3, 4].map((i) => (
        <View className="ct-skeleton-tl-item" key={i}>
          <View className="ct-skeleton-tl-time">
            <View className="ct-skeleton-block" />
          </View>
          <View className="ct-skeleton-tl-body">
            <View className="ct-skeleton-block" />
          </View>
        </View>
      ))}
    </View>
  );

  /** 渲染单个课程卡片（对齐网页端 renderCourseCell 移动端分支） */
  const renderCourseCard = (cell: Cell, day: number) => {
    const c = cell.course;
    const colorIdx = getCourseColorIndex(c.course_name);
    const baseColor = COURSE_COLORS[colorIdx];
    const isOngoing = cell.isOngoing;
    const isPast = cell.isPast;
    const isFinished = isPast;
    const isTodayCol = day === todayDow;

    // 计算上课进度（用于渐进式高亮，对齐网页端 classProgress）
    let classProgress = 0;
    if (isOngoing && c.start_time && c.end_time) {
      const now = new Date();
      const [sh, sm] = c.start_time.split(':').map(Number);
      const [eh, em] = c.end_time.split(':').map(Number);
      const startMin = sh * 60 + sm;
      const endMin = eh * 60 + em;
      const nowMin = now.getHours() * 60 + now.getMinutes();
      const total = endMin - startMin;
      if (total > 0) classProgress = Math.min(1, Math.max(0, (nowMin - startMin) / total));
    }

    // 背景：进行中时渐变（对齐网页端 activeBgColor）
    const activeBgColor = isOngoing
      ? `linear-gradient(to bottom, #fff1f0 ${classProgress * 100}%, ${baseColor}15 ${classProgress * 100}%)`
      : `${baseColor}15`;
    const activeBorderColor = isOngoing ? '#ff4d4f' : baseColor;

    const location = `${c.extra_info?.building || ''}${c.extra_info?.classroom || ''}`;
    const periodsText = formatPeriodLabel(c);

    return (
      <View
        className={`ct-cell ct-course-cell ${isOngoing ? 'ct-course-ongoing' : ''} ${isFinished ? 'ct-course-finished' : ''}`}
        style={{
          height: `${cell.rowSpan * ROW_H}rpx`,
          background: isFinished ? '#f5f5f5' : activeBgColor,
          borderLeftColor: isFinished ? '#d9d9d9' : activeBorderColor,
        }}
        onClick={() => {
          // 带上当前查看的周次，详情页按该周拉数据，避免"有课显示没课"
          navigateTo({ url: `/pages/coursedetail/index?id=${c.schedule_id}&week_number=${displayWeekNumber || 1}` });
        }}
      >
        {/* 进行中徽章（对齐网页端移动端 "正在上课" 标签） */}
        {isOngoing && (
          <View className="ct-ongoing-badge">
            <Text className="ct-ongoing-badge-text">正在上课</Text>
          </View>
        )}

        {/* 课程名 */}
        <Text
          className="ct-course-name"
          style={{ color: isFinished ? '#999' : isOngoing ? '#ff4d4f' : baseColor }}
        >
          {c.course_name}
        </Text>

        {/* 教师行 */}
        {c.extra_info?.teacher ? (
          <View className="ct-course-row">
            <Text className="iconfont icon-kongxianjiaoshi ct-course-icon" />
            <Text className="ct-course-info">{c.extra_info.teacher}</Text>
          </View>
        ) : null}

        {/* 地点行（对齐网页端三段式：building+classroom / 仅classroom） */}
        {c.extra_info?.building && c.extra_info?.classroom ? (
          <View className="ct-course-row">
            <Text className="iconfont icon-jinru ct-course-icon" />
            <Text className="ct-course-info">{c.extra_info.building} {c.extra_info.classroom}</Text>
          </View>
        ) : !c.extra_info?.building && c.extra_info?.classroom ? (
          <View className="ct-course-row">
            <Text className="iconfont icon-jinru ct-course-icon" />
            <Text className="ct-course-info">{c.extra_info.classroom}</Text>
          </View>
        ) : null}

        {/* 时间段（底部自动顶推） */}
        {c.start_time && c.end_time ? (
          <Text className="ct-course-time">{c.start_time} - {c.end_time}</Text>
        ) : null}

        {/* 节数标签 */}
        {periodsText ? (
          <Text className="ct-course-periods">{periodsText}</Text>
        ) : null}
      </View>
    );
  };

  return (
    <View className="page ct-page">
      {/* 视图切换 Tab */}
      <View className="ct-tabs">
        <View
          className={`ct-tab ${viewMode === 'grid' ? 'ct-tab-active' : ''}`}
          onClick={() => setViewMode('grid')}
        >
          课表
        </View>
        <View
          className={`ct-tab ${viewMode === 'timeline' ? 'ct-tab-active' : ''}`}
          onClick={() => setViewMode('timeline')}
        >
          日程
        </View>
      </View>

      {/* 周历卡片 */}
      <View className="card week-calendar">
        <View className="week-calendar-head">
          <View className="schedule-week-picker" onClick={openWeekPicker}>
            <Text className="schedule-month-text">{weekText}</Text>
            <View className="week-calendar-badge">
              <Text className="week-calendar-badge-text">{badgeText}</Text>
            </View>
            <Text className={`iconfont icon-a-xiala2 schedule-month-arrow${showWeekPicker ? ' rotated' : ''}`} />
        </View>
        <Text
          className="schedule-today-btn"
          onClick={() => {
            // 回到当前教学周：若在教学周则用真实当前周，否则回退第1周
            const targetWk = weekNumber > 0 ? weekNumber : (availableWeeks.length > 0 ? availableWeeks[0].week_number : 1);
            setDisplayWeekNumber(targetWk);
            setWeekStartDate(getStartDateForWeek(targetWk));
            setSelectedDate(todayStr);
            loadWeekCourses(targetWk);
          }}
        >
          今天
        </Text>
        </View>

        <Swiper className="week-swiper" key={displayWeekNumber} current={1} onChange={onSwiperChange} duration={200}>
          {[-1, 0, 1].map((offset) => {
            // 基于当前教学周次查找相邻周的 start_date
            const targetWk = displayWeekNumber + offset;
            const targetStart = getStartDateForWeek(targetWk);
            const baseMonday = targetStart
              ? (() => { const d = dayjs(targetStart); const dow = d.day(); return dow === 1 ? d : (dow === 0 ? d.add(-6, 'day') : d.add(1 - dow, 'day')); })()
              : currentMonday; // 无数据时回退到当前锚定周一
            const days = Array.from({ length: 7 }, (_, i) => baseMonday.add(i, 'day'));
            return (
              <SwiperItem key={targetWk}>
                <View className="week-calendar-days">
                  {days.map((d) => {
                    const dateStr = d.format('YYYY-MM-DD');
                    // 今天始终标记（与时间轴页一致）：蓝色实心圆 + 白字；选中其他日期为蓝色字体
                    const isToday = dateStr === todayStr;
                    const isSelected = dateStr === selectedDate;
                    const dDow = d.day();
                    const backendDow = dDow === 0 ? 7 : dDow;
                    const hasCourse = hasCourseByDow.has(backendDow);
                    return (
                      <View
                        className={`week-cell ${isToday ? 'week-cell-today' : ''} ${isSelected && !isToday ? 'week-cell-selected' : ''}`}
                        key={dateStr}
                        onClick={() => setSelectedDate(dateStr)}
                      >
                        <Text className={`week-cell-label ${isToday || isSelected ? 'week-cell-active' : ''}`}>
                          {WEEK_LABELS[dDow]}
                        </Text>
                        <View className={`week-cell-day ${isToday ? 'week-cell-day-today' : ''} ${isSelected && !isToday ? 'week-cell-day-selected' : ''}`}>
                          <Text className={isToday ? 'week-cell-day-text-active' : isSelected ? 'week-cell-day-text-selected' : ''}>
                            {d.date()}
                          </Text>
                        </View>
                        <View className="week-cell-dot-row">
                          {hasCourse ? <View className="week-cell-dot" /> : <View className="week-cell-dot week-cell-dot-empty" />}
                        </View>
                      </View>
                    );
                  })}
                </View>
              </SwiperItem>
            );
          })}
        </Swiper>
      </View>

      {/* ====== 课程表版式 ====== */}
      {viewMode === 'grid' &&
        (loading ? (
          renderGridSkeleton()
        ) : maxPeriod === 0 ? (
          <View className="card ct-empty-card">
            <EmptyState title="本周没有课程" desc="换一周看看吧" />
          </View>
        ) : (
          <View className="ct-table">
            <View className="ct-table-inner">
              {/* 固定节次列 */}
              <View className="ct-col-period">
                <View className="ct-cell ct-corner">
                  <Text className="ct-corner-text">节</Text>
                </View>
                {periodList.map((p) => (
                  <View className="ct-cell ct-period-cell" key={p}>
                    <Text className="ct-period-num">{p}</Text>
                  </View>
                ))}
              </View>

              {/* 课程区：等分铺满屏幕 */}
              <View className="ct-cols">
                {dayList.map((day) => {
                  const isToday = day === todayDow;
                  return (
                    <View className={`ct-col ${isToday ? 'ct-col-today' : ''}`} key={day}>
                      <View className="ct-cell ct-day-head">
                        <Text className="ct-day-text">{WEEK_LABELS[day % 7]}</Text>
                      </View>
                      {periodList.map((p) => {
                        const cell = map[day]?.[p];
                        if (!cell || !cell.render) return null;
                        return renderCourseCard(cell, day);
                      })}
                    </View>
                  );
                })}
              </View>
            </View>
          </View>
        ))}

      {/* ====== 时间轴版式 ====== */}
      {viewMode === 'timeline' &&
        (loading ? (
          renderTimelineSkeleton()
        ) : displayCourses.length === 0 ? (
          <View className="card schedule-empty-card">
            <EmptyState
              title={selectedDate === todayStr ? '今天没有课程' : '当天没有课程'}
              desc={selectedDate === todayStr ? '好好休息一下吧' : '换一天看看吧'}
            />
          </View>
        ) : (
          <View className="timeline-list">
            {displayCourses.map((c, idx) => {
              // 简单状态判断（时间轴不需要 isRealCurrentWeek 守卫，因为只展示当天）
              const now = Date.now() / 1000;
              const { start_ts, end_ts } = c._timeInfo || {};
              let st: TimelineStatus = 'info';
              if (start_ts && now < start_ts) st = 'upcoming';
              else if (end_ts && now > end_ts) st = 'finished';
              else if (start_ts && end_ts) st = 'ongoing';
              const statusTextMap: Record<TimelineStatus, string> = {
                upcoming: '未开始', ongoing: '进行中', finished: '已结束', info: '',
              };
              const ps = Array.isArray(c.periods) ? c.periods : [];
              const periodsText = ps.length >= 2
                ? `${ps[0]}-${ps[ps.length - 1]}节`
                : ps.length === 1 ? `${ps[0]}节` : '';
              // 颜色索引：用网页端同款哈希
              const colorIdx = getCourseColorIndex(c.course_name);
              const colorKeyMap: Record<number, 'green' | 'blue' | 'orange' | 'purple' | 'pink'> = {
                0: 'blue', 1: 'green', 2: 'orange', 3: 'purple', 4: 'pink',
                5: 'blue', 6: 'green', 7: 'orange', 8: 'purple', 9: 'pink',
              };
              return (
                <TimelineItem
                  key={c.schedule_id}
                  time={c.start_time}
                  periodsText={periodsText}
                  courseName={c.course_name}
                  building={c.extra_info?.building}
                  classroom={c.extra_info?.classroom}
                  teacher={c.extra_info?.teacher}
                  status={st}
                  statusText={statusTextMap[st]}
                  courseColorKey={colorKeyMap[colorIdx] || 'blue'}
                  isLast={idx === displayCourses.length - 1}
                />
              );
            })}
          </View>
        ))}

      {/* 周次选择器 */}
      {showWeekPicker && (
        <View className="week-picker-mask" onClick={() => setShowWeekPicker(false)}>
          <View className="week-picker-modal" onClick={(e) => e.stopPropagation()}>
            <View className="week-picker-header">
              <Text className="week-picker-cancel" onClick={() => setShowWeekPicker(false)}>取消</Text>
              {semesterName ? <Text className="week-picker-title">{semesterName}</Text> : <View />}
              <Text className="week-picker-confirm" onClick={confirmPicker}>确定</Text>
            </View>
            <View className="week-picker-divider" />
            <View className="week-picker-body">
              <PickerView className="week-picker-view" value={[pickerSelected]} onChange={onPickerChange}>
                <PickerViewColumn>
                  {availableWeeks.map((w) => (
                    <View className="week-picker-item" key={w.week_number}>
                      <Text className="week-picker-item-text">第{w.week_number}周</Text>
                    </View>
                  ))}
                </PickerViewColumn>
              </PickerView>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
