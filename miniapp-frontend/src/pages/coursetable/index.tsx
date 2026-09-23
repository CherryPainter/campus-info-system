import { useMemo, useState, useCallback } from 'react';
import { View, Text, PickerView, PickerViewColumn } from '@tarojs/components';
import { useLoad, usePullDownRefresh, stopPullDownRefresh, navigateTo } from '@tarojs/taro';
import dayjs from 'dayjs';

import * as scheduleApi from '@/api/schedule';
import type { ScheduleCourse, ScheduleSemester } from '@/types/api';
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

// 周次选择器右列的候选周（覆盖到 25 周；各学期真实周由后端 available_weeks 决定，
// 选中某周后仍以该学期实际可用周为准回退到第 1 周，避免右列与后端周上限脱节）
const PICKER_WEEKS = Array.from({ length: 25 }, (_, i) => i + 1);

/** 把后端学期名（如 2026-2027-1）格式化为中文展示文本 */
function formatSemesterLabel(name: string): string {
  const m = name.match(/^(\d{4})-(\d{4})-(\d)$/);
  if (!m) return name;
  const [, start, end, term] = m;
  const termText = term === '1' ? '一' : term === '2' ? '二' : term;
  return `${start}-${end}年 第${termText}学期`;
}

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
  isCurrentSemester: boolean,
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

  // 是否为「真实当前周」：
  // 必须同时满足「展示周次 == 真实教学周」且「展示的学期就是当前学期」，
  // 否则历史学期（上学期）即使选了与本周相同的周次，也不应出现"进行中/已结束"实时态。
  const isRealCurrentWeek =
    isCurrentSemester && currentWeekNumber > 0 && displayWeekNumber === currentWeekNumber;

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

  // 整周课程（课程表版式用）
  const [weekCourses, setWeekCourses] = useState<ScheduleCourse[]>([]);

  const [weekNumber, setWeekNumber] = useState(0);
  const [showWeekPicker, setShowWeekPicker] = useState(false);
  const [pickerSelected, setPickerSelected] = useState<number>(0);
  // 周次选择器左列：当前选中的学期索引（对应 semesters 下标）
  const [pickerSemSelected, setPickerSemSelected] = useState<number>(0);
  // 周次选择器左列：当前展示的学年/学期
  const [semesters, setSemesters] = useState<ScheduleSemester[]>([]);
  // 当前选中的学期 id（缺省当前学期）
  const [selectedSemesterId, setSelectedSemesterId] = useState<number>(0);
  const [displayWeekNumber, setDisplayWeekNumber] = useState<number>(0);
  const [availableWeeks, setAvailableWeeks] = useState<{ week_number: number; start_date?: string | null; end_date?: string | null }[]>([]);
  const [semesterName, setSemesterName] = useState('');
  const [hasCourseByDow, setHasCourseByDow] = useState<Set<number>>(new Set());
  // 当前显示周该周的周一日期（用于列头日期；当前学期按真实日历，历史学期用该学期开学日）
  const [weekStartDate, setWeekStartDate] = useState<string | null>(null);

  // 加载某学期的整周课程（随选中周次/学期刷新）
  const loadWeekCourses = useCallback(async (wn: number, semId?: number) => {
    if (wn < 1) {
      setWeekCourses([]);
      setHasCourseByDow(new Set());
      return;
    }
    try {
      const weekRes = await scheduleApi.getWeek(wn, semId || undefined);
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

  // 判断给定学期是否为「当前学期」（用于决定周次日期锚定口径）
  const isCurrentSemester = useCallback(
    (semId?: number): boolean => {
      if (!semId || semId === 0) return true; // 未选 = 当前
      const cur = semesters.find((s) => s.is_current);
      return Boolean(cur && cur.id === semId);
    },
    [semesters],
  );

  // 由某个学期 id 解析其展示名（如 "2026-2027-1"）
  const semesterNameById = useCallback(
    (semId: number): string => {
      const s = semesters.find((x) => x.id === semId);
      return s ? s.name : semesterName;
    },
    [semesters, semesterName],
  );

  // 计算某周在表格列头的锚定周一日期：
  // - 当前学期：沿用「以当前真实日历周一为基准按周差偏移」的既有口径（与 schedule 页一致），
  //   保证"本周=这周"、今天的列高亮正确。
  // - 历史学期：直接用该学期真实周历（available_weeks[wn-1].start_date，后端按开学日推算），
  //   让列头日期反映当年真实几月几号。
  const getWeekStartDate = useCallback(
    (wn: number, semId?: number, weeks?: { week_number: number; start_date?: string | null }[]): string | null => {
      if (wn < 1) return null;
      if (!isCurrentSemester(semId)) {
        const w = (weeks || []).find((x) => x.week_number === wn);
        if (w?.start_date) return w.start_date;
        // 无真实日期的极端回退：仍按当前周偏移
      }
      const today = dayjs();
      const dow = today.day();
      const thisMonday = today.add(dow === 0 ? -6 : 1 - dow, 'day');
      const base = weekNumber >= 1 ? weekNumber : 1;
      return thisMonday.add((wn - base) * 7, 'day').format('YYYY-MM-DD');
    },
    [weekNumber, isCurrentSemester],
  );

  // 初始化
  const loadAll = useCallback(async () => {
    setLoading(true);
    const cRes = await scheduleApi
      .getCurrent()
      .then((r) => ({ ok: true as const, d: r.data }))
      .catch(() => ({ ok: false as const, d: null }));
    const rawWk = cRes.ok && cRes.d ? cRes.d.week_number : 0;
    const availWeeks = (cRes.ok && cRes.d ? cRes.d.available_weeks : []) || [];
    const semList: ScheduleSemester[] = (cRes.ok && cRes.d ? cRes.d.semesters : []) || [];
    const wkNum = rawWk > 0 ? rawWk : (availWeeks.length > 0 ? availWeeks[0].week_number : 0);
    setWeekNumber(rawWk);
    setDisplayWeekNumber(wkNum);
    if (cRes.ok && cRes.d) {
      setAvailableWeeks(availWeeks);
      setSemesterName(cRes.d.semester_name || '');
    }
    if (semList.length > 0) {
      setSemesters(semList);
      setSelectedSemesterId(cRes.ok && cRes.d ? cRes.d.semester_id : semList[0].id);
    }
    // 周历锚定到相对当前真实周的周一（wkNum 即当前周，偏移 0；不跳教学周真实日历）
    setWeekStartDate(getWeekStartDate(wkNum));
    await loadWeekCourses(wkNum);
    setLoading(false);
  }, [loadWeekCourses, getWeekStartDate]);

  useLoad(() => {
    loadAll();
  });

  usePullDownRefresh(async () => {
    await loadAll();
    stopPullDownRefresh();
  });

  // 周历：基于选中的锚定周一
  const currentMonday = useMemo(() => {
    if (!weekStartDate) return dayjs(); // 兜底：无数据时回退今天
    const d = dayjs(weekStartDate);
    const dow = d.day();
    const monday = dow === 1 ? d : (dow === 0 ? d.add(-6, 'day') : d.add(1 - dow, 'day'));
    return monday;
  }, [weekStartDate]);

  const todayStr = dayjs().format('YYYY-MM-DD');

  // 应用「指定学期 + 周次」到表格：拉取该学期该周课程 + 锚定列头周一 + 更新周次展示名
  const applyWeek = useCallback(
    async (wn: number, semId?: number, weeksOverride?: { week_number: number; start_date?: string | null }[]) => {
      setDisplayWeekNumber(wn);
      const effectiveSem = semId || selectedSemesterId || 0;
      // 优先用调用方给定的周历（切学期后 state 里的 availableWeeks 可能还是旧学期，故可显式传入）
      setWeekStartDate(getWeekStartDate(wn, effectiveSem, weeksOverride || availableWeeks));
      if (effectiveSem && semesters.length > 0) {
        const s = semesters.find((x) => x.id === effectiveSem);
        if (s) setSemesterName(s.name);
      }
      await loadWeekCourses(wn, effectiveSem || undefined);
    },
    [selectedSemesterId, availableWeeks, getWeekStartDate, semesters, loadWeekCourses],
  );

  const pickWeek = useCallback(
    async (wn: number) => {
      await applyWeek(wn, selectedSemesterId);
      setShowWeekPicker(false);
    },
    [applyWeek, selectedSemesterId],
  );

  // 周次选择器左列：可选学期（后端按当前学年向前候选生成），用可读学年文案展示
  const semesterList = useMemo(
    () => semesters.map((s) => formatSemesterLabel(s.name)).filter(Boolean),
    [semesters],
  );

  const openWeekPicker = useCallback(() => {
    // 右列用扁平周次 1..25，索引 = 周次-1
    const wkIdx = Math.max(0, Math.min(PICKER_WEEKS.length - 1, (displayWeekNumber || 1) - 1));
    setPickerSelected(wkIdx);
    // 左列定位到当前所选学期
    const semIdx = semesters.findIndex((s) => s.id === selectedSemesterId);
    setPickerSemSelected(semIdx >= 0 ? semIdx : 0);
    setShowWeekPicker(true);
  }, [displayWeekNumber, semesters, selectedSemesterId]);

  // Picker 双列：value 是 [semIdx, weekIdx]
  const onPickerChange = useCallback(
    (e: any) => {
      const value = e.detail.value;
      if (!Array.isArray(value)) return;
      const [semIdx, weekIdx] = value;
      if (typeof semIdx === 'number' && semIdx !== pickerSemSelected) {
        setPickerSemSelected(semIdx);
        // 切学期：右边周次先复位（确认后再拉取该学期周列表）
        setPickerSelected(0);
      }
      if (typeof weekIdx === 'number' && weekIdx !== pickerSelected) {
        setPickerSelected(weekIdx);
      }
    },
    [pickerSelected, pickerSemSelected],
  );

  // 从可选学期列表生成某学期的周选项（左列联动右列）
  const confirmPicker = useCallback(async () => {
    const sem = semesters[pickerSemSelected];
    // 右列扁平周次：选中周 = pickerSelected + 1
    const targetWeek = pickerSelected + 1;
    if (sem && sem.id !== selectedSemesterId) {
      // 切换学期：先切后端数据，再应用周次（周次若超出该学期实际周数，由后端/加载层兜底回退）
      setSelectedSemesterId(sem.id);
      setSemesterName(sem.name);
      let weeks: { week_number: number; start_date?: string | null }[] = [];
      try {
        const res = await scheduleApi.getWeek(targetWeek, sem.id);
        weeks = (res.data.available_weeks || []) as { week_number: number; start_date?: string | null }[];
      } catch {
        weeks = [];
      }
      setAvailableWeeks(weeks);
      setSelectedSemesterId(sem.id);
      setSemesterName(sem.name);
      await applyWeek(targetWeek, sem.id, weeks);
    } else {
      // 同学期：直接切周
      await applyWeek(targetWeek, selectedSemesterId);
    }
    setShowWeekPicker(false);
  }, [semesters, pickerSemSelected, selectedSemesterId, pickerSelected, applyWeek]);

  // 回到当前教学周（顶部"本周"按钮）
  const goToCurrentWeek = useCallback(async () => {
    // 先切回当前学期
    const cur = semesters.find((s) => s.is_current);
    const curId = cur ? cur.id : 0;
    if (selectedSemesterId !== curId && cur) {
      setSelectedSemesterId(curId);
      setSemesterName(cur.name);
      try {
        const res = await scheduleApi.getWeek(1, cur.id);
        setAvailableWeeks((res.data.available_weeks || []) as { week_number: number; start_date?: string | null }[]);
      } catch {
        /* 忽略 */
      }
    }
    const targetWk = weekNumber > 0 ? weekNumber : (availableWeeks.length > 0 ? availableWeeks[0].week_number : 1);
    await applyWeek(targetWk, curId);
  }, [semesters, selectedSemesterId, weekNumber, availableWeeks, applyWeek]);

  // ====== 课程表版式数据 ======
  const { map, maxPeriod } = useMemo(
    () => buildCellMap(weekCourses, weekNumber, displayWeekNumber, isCurrentSemester(selectedSemesterId)),
    [weekCourses, weekNumber, displayWeekNumber, selectedSemesterId, semesters],
  );
  // 表格行数：按实际数据最大节次动态截断，避免无课空行把页面拉长；
  // 至少保留 8 行，保证常见课表（1-8节）视觉完整。
  const periodList = useMemo(() => {
    const minRows = 8;
    const rows = Math.max(minRows, maxPeriod);
    return Array.from({ length: rows }, (_, i) => i + 1);
  }, [maxPeriod]);
  // 列：周一~周五固定，周末有课才追加（对齐网页端移动端列策略）
  const dayList = useMemo(() => {
    const list = [1, 2, 3, 4, 5];
    if (hasCourseByDow.has(6)) list.push(6);
    if (hasCourseByDow.has(7)) list.push(7);
    return list;
  }, [hasCourseByDow]);

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

  /** 渲染单个课程卡片（对齐网页端 renderCourseCell 移动端分支） */
  const renderCourseCard = (cell: Cell, day: number) => {
    const c = cell.course;
    const colorIdx = getCourseColorIndex(c.course_name);
    const baseColor = COURSE_COLORS[colorIdx];
    const isOngoing = cell.isOngoing;
    const isPast = cell.isPast;
    const isFinished = isPast;

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
          // 带上当前查看的周次与学期，详情页按该学期该周拉数据，
          // 避免上学期课程在详情页被当成当前学期课程而查不到（"课程信息不存在"）
          const semParam = selectedSemesterId ? `&semester_id=${selectedSemesterId}` : '';
          navigateTo({ url: `/pages/coursedetail/index?id=${c.schedule_id}&week_number=${displayWeekNumber || 1}${semParam}` });
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
      {/* 顶部周次选择栏：本周（左） | 学期周次（中） */}
      <View className="card week-calendar ct-week-header-grid">
        <View className="week-calendar-head">
          <Text className="schedule-today-btn" onClick={goToCurrentWeek}>本周</Text>
          <View className="schedule-week-picker" onClick={openWeekPicker}>
            <Text className="schedule-semester-text">
              {formatSemesterLabel(semesterName)} 第{displayWeekNumber}周
            </Text>
            <Text className={`iconfont icon-a-xiala2 schedule-month-arrow${showWeekPicker ? ' rotated' : ''}`} />
          </View>
          <View className="week-header-spacer" />
        </View>
      </View>

      {/* ====== 课程表版式：始终渲染完整表格（有/无课都显示网格，空格子占位） ====== */}
      {loading ? (
        renderGridSkeleton()
      ) : (
        <View className="ct-table">
          <View className="ct-table-inner">
            {/* 固定节次列 */}
            <View className="ct-col-period">
              <View className="ct-cell ct-corner">
                <Text className="ct-corner-text">节</Text>
              </View>
              {periodList.map((p) => {
                const periodGroupClass = p <= 4 ? 'ct-period-cell-light' : p <= 8 ? 'ct-period-cell-gray' : 'ct-period-cell-light';
                return (
                  <View className={`ct-cell ct-period-cell ${periodGroupClass}`} key={p}>
                    <Text className="ct-period-num">{p}</Text>
                  </View>
                );
              })}
            </View>

            {/* 课程区：等分铺满屏幕 */}
            <View className="ct-cols">
            {dayList.map((day) => {
              const dayDate = currentMonday.add(day - 1, 'day');
              const dateLabel = dayDate.format('MM/DD');
              const isToday = dayDate.format('YYYY-MM-DD') === todayStr;
              return (
                <View className={`ct-col ${isToday ? 'ct-col-today' : ''}`} key={day}>
                  <View className={`ct-cell ct-day-head ${isToday ? 'ct-day-head-today' : ''}`}>
                    <Text className="ct-day-week">{WEEK_LABELS[day % 7]}</Text>
                    <Text className="ct-day-date">{dateLabel}</Text>
                  </View>
                    {periodList.map((p) => {
                      const cell = map[day]?.[p];
                      if (!cell) {
                        // 空节占位：保持表格行高与垂直位置对齐
                        return <View className="ct-cell ct-cell-empty" key={p} />;
                      }
                      if (!cell.render) return null;
                        return renderCourseCard(cell, day);
                      })}
                    </View>
                  );
                })}
              </View>
            </View>
          </View>
        )}

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
              <PickerView
                className="week-picker-view"
                value={[pickerSemSelected, pickerSelected]}
                onChange={onPickerChange}
              >
                {/* 左列：学年/学期 */}
                <PickerViewColumn>
                  {(semesterList.length > 0 ? semesterList : [semesterName].filter(Boolean)).map((s, i) => (
                    <View className="week-picker-item" key={`${s}-${i}`}>
                      <Text className="week-picker-item-text">{s}</Text>
                    </View>
                  ))}
                </PickerViewColumn>
                {/* 右列：周次 */}
                <PickerViewColumn>
                  {PICKER_WEEKS.map((w) => (
                    <View className="week-picker-item" key={w}>
                      <Text className="week-picker-item-text">第{w}周</Text>
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
