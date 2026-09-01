import { useMemo, useState, useRef, useCallback, useEffect } from 'react';
import { View, Text, Swiper, SwiperItem, ScrollView, PickerView, PickerViewColumn } from '@tarojs/components';
import { useLoad, useDidShow, usePullDownRefresh, stopPullDownRefresh, getWindowInfo } from '@tarojs/taro';
import dayjs from 'dayjs';

import { setTabIndex } from '@/utils/tabBarState';

import * as scheduleApi from '@/api/schedule';
import * as notificationApi from '@/api/notification';
import type { NotificationEvent, ScheduleCourse } from '@/types/api';
import { tsToHm } from '@/utils/date';
import TimelineItem, { type CourseColorKey, type TimelineStatus } from '@/components/TimelineItem';
import { courseStatus } from '@/components/CourseCard';
import ReminderCard from '@/components/ReminderCard';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 课表页（时间轴样式，按用户确认的原型图）
 * - 顶部：日期 + 周信息
 * - 周历：本周 7 天（今天高亮）
 * - 时间轴：今日课程按时间排序（圆点竖线 + 状态标签）
 * - 数据只组合后端真实事件（schedule/today + schedule/current），不虚构
 */

const WEEK_LABELS = ['日', '一', '二', '三', '四', '五', '六'];

export default function SchedulePage() {
  const [loading, setLoading] = useState(true);
  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [courses, setCourses] = useState<ScheduleCourse[]>([]);
  const [weekNumber, setWeekNumber] = useState(0);
  const [isTeachingWeek, setIsTeachingWeek] = useState(false);
  // 周历选中的日期（默认今天）
  const [selectedDate, setSelectedDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  // 周次选择面板（展开/收起）
  const [showWeekPicker, setShowWeekPicker] = useState(false);
  // picker-view 内部选中的周次索引（0-based）
  const [pickerSelected, setPickerSelected] = useState<number>(0);
  // 用户手动选择的显示周次（初始=后端当前周，选周后跟随更新）
  const [displayWeekNumber, setDisplayWeekNumber] = useState<number>(0);
  // 后端返回的学期周次面板数据
  const [availableWeeks, setAvailableWeeks] = useState<{ week_number: number; start_date?: string | null; end_date?: string | null }[]>([]);
  const [semesterName, setSemesterName] = useState('');
  // 整周课程数据（用于点击其他日期时按 day_of_week 过滤）
  const [weekCourses, setWeekCourses] = useState<ScheduleCourse[]>([]);
  // 本周每天有课的星期几（dayjs day()：0=周日，1-6=周一至周六；后端 day_of_week 1-7）
  const [hasCourseByDow, setHasCourseByDow] = useState<Set<number>>(new Set());
  // 近期提醒（独立错误状态，避免与课程加载耦合）
  const [reminders, setReminders] = useState<NotificationEvent[]>([]);
  const [remindersLoading, setRemindersLoading] = useState(true);
  const [remindersError, setRemindersError] = useState(false);

  // 近期提醒独立加载（不影响时间轴主流程，互不阻塞）
  const loadReminders = async () => {
    setRemindersLoading(true);
    setRemindersError(false);
    try {
      const r = await notificationApi.getUpcoming({ limit: 5 });
      setReminders(r.data.events);
    } catch {
      setRemindersError(true);
    } finally {
      setRemindersLoading(false);
    }
  };

  // 按日期加载课程：
  //   - 优先从已加载的 weekCourses 按 day_of_week 过滤（与圆点标记同源，保证一致）
  //   - 降级调 getToday(date) 接口（用于"今天"或非当前教学周的日期）
  const fetchDayCourses = useCallback(async (date: string) => {
    setLoading(true);
    try {
      // 从选中日期反推 day_of_week（dayjs: 0=周日 → 后端 7）
      const clickedDow = dayjs(date).day();
      const backendDow = clickedDow === 0 ? 7 : clickedDow;

      // 优先从 weekCourses（当前教学周数据）按 day_of_week 过滤，与圆点标记完全同源
      const fromWeek = weekCourses.filter((c) => c.day_of_week === backendDow);
      if (fromWeek.length > 0) {
        setCourses(fromWeek);
        return;
      }

      // weekCourses 无匹配 → 降级走 getToday 日接口（今天/跨周场景）
      const r = await scheduleApi.getToday(date);
      setCourses(r.data.courses);
    } catch {
      setCourses([]);
    } finally {
      setLoading(false);
    }
  }, [weekCourses]);

  // 选中日期变化 → 加载该日课程（初次 selectedDate=今天，自动加载）
  useEffect(() => {
    if (selectedDate) {
      fetchDayCourses(selectedDate);
    }
  }, [selectedDate, fetchDayCourses]);

  // 加载周信息 + 周历有课标记 + 学期周次面板数据（与选中日期无关，一次性拉取）
  const loadAll = async () => {
    const cRes = await scheduleApi
      .getCurrent()
      .then((r) => ({ ok: true as const, d: r.data }))
      .catch(() => ({ ok: false as const, d: null }));
    const rawWk = cRes.ok && cRes.d ? cRes.d.week_number : 0;
    const availWeeks = (cRes.ok && cRes.d ? cRes.d.available_weeks : []) || [];
    // 非教学周时回退到第 1 周（与 coursetable 一致），避免 displayWeekNumber=0
    // 导致 getStartDateForWeek(0) 算出上周日期、今天不显示
    const wkNum = rawWk > 0 ? rawWk : (availWeeks.length > 0 ? availWeeks[0].week_number : 0);
    const isTW = cRes.ok && cRes.d ? cRes.d.is_teaching_week : false;
    setWeekNumber(rawWk);
    setIsTeachingWeek(isTW);
    setDisplayWeekNumber(wkNum);
    if (cRes.ok && cRes.d) {
      setAvailableWeeks(availWeeks);
      setSemesterName(cRes.d.semester_name || '');
    }

    // 周历有课标记 + 整周课程数据：仅在 weekNumber>=1 时调 week 接口
    if (rawWk >= 1) {
      try {
        const weekRes = await scheduleApi.getWeek(wkNum);
        const wc = weekRes.data.courses as ScheduleCourse[];
        setWeekCourses(wc);
        const set = new Set<number>();
        wc.forEach((c) => {
          if (c.day_of_week) set.add(c.day_of_week);
        });
        setHasCourseByDow(set);
      } catch {
        // 周课表查询失败不影响时间轴主流程
      }
    } else {
      setHasCourseByDow(new Set());
      setWeekCourses([]);
    }
  };

  useLoad(() => {
    // custom 导航栏：读取状态栏高度，避免内容被遮挡
    try {
      const info = getWindowInfo();
      if (info.statusBarHeight) setStatusBarHeight(info.statusBarHeight);
    } catch {
      // 兜底 20
    }
    loadAll();
    loadReminders();
  });

  usePullDownRefresh(async () => {
    await Promise.all([loadAll(), fetchDayCourses(selectedDate)]);
    stopPullDownRefresh();
  });

  // 时间轴是 TabBar 第 1 项：每次显示广播自身下标，保证 TabBar 选中态与任意进入路径一致
  useDidShow(() => {
    setTabIndex(1);
  });

  // 时间轴是 TabBar 页：切 Tab 离开再回来时页面常驻内存、state 不会自动重置。
  // 在非首次显示（onShow）时重置到"今天 + 当前教学周"，满足"退出时间轴页面要重置到今天的数据"。
  const firstShowRef = useRef(true);
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false;
      return; // 首次进入走 useLoad 的 loadAll，不额外处理
    }
    const today = dayjs().format('YYYY-MM-DD');
    const targetWk = weekNumber > 0 ? weekNumber : (availableWeeks.length > 0 ? availableWeeks[0].week_number : 1);
    if (selectedDate !== today || displayWeekNumber !== targetWk) {
      setSelectedDate(today);
      setDisplayWeekNumber(targetWk);
      // 周次/日期变化后，下面的 useEffect 会自动重新拉取该周数据与当天课程
    }
  });

  // 根据周次推算该周周一日期：以「当前真实日历周一」为基准，按 (wn − 当前教学周) 相对偏移。
  // 这样切换周只是"围绕当前时间查看那个周的课程"，不会把日期跳到教学周真实日历（如第2周跳到 03-09），
  // 且与后端 _calculate_date 口径一致（前后端都围绕当前附近 ±N 周）。
  const getStartDateForWeek = useCallback((wn: number): string => {
    const today = dayjs();
    const dow = today.day(); // 0=周日
    const thisMonday = today.add(dow === 0 ? -6 : 1 - dow, 'day');
    const baseWk = weekNumber >= 1 ? weekNumber : 1;
    return thisMonday.add((wn - baseWk) * 7, 'day').format('YYYY-MM-DD');
  }, [weekNumber]);

  // 周历锚定：基于教学周 start_date（非真实日历），选周/滑动后日期对齐
  const currentMonday = useMemo(() => {
    const sd = getStartDateForWeek(displayWeekNumber);
    return dayjs(sd);
  }, [displayWeekNumber, getStartDateForWeek]);

  // 本周 7 天（基于 currentMonday，联动星期标签）
  const weekDays = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => currentMonday.add(i, 'day'));
  }, [currentMonday]);

  // 本周 7 天（周一 ~ 周日），基于 currentMonday 联动
  // (已上移为基于 displayWeekNumber + availableWeeks start_date 的 useMemo)

  const todayStr = dayjs().format('YYYY-MM-DD');

  // Swiper 切换周：切换教学周次（带边界，不超出 availableWeeks 范围）
  const onSwiperChange = useCallback((e: any) => {
    const cur = e.detail.current; // 0=左滑(上一周) 1=中间 2=右滑(下一周)
    if (availableWeeks.length === 0) return;
    const minWk = Math.min(...availableWeeks.map((w) => w.week_number));
    const maxWk = Math.max(...availableWeeks.map((w) => w.week_number));
    if (cur === 2 && displayWeekNumber < maxWk) {
      setDisplayWeekNumber((prev) => prev + 1);
    } else if (cur === 0 && displayWeekNumber > minWk) {
      setDisplayWeekNumber((prev) => prev - 1);
    }
    // Swiper key 随 displayWeekNumber 变化而重建，current 自动回 1
  }, [availableWeeks, displayWeekNumber]);

  // 教学周次变化 → 重新拉取该周的课表数据（有课标记 + 时间轴）
  useEffect(() => {
    if (displayWeekNumber >= 1) {
      scheduleApi.getWeek(displayWeekNumber).then((res) => {
        const wc = res.data.courses as ScheduleCourse[];
        setWeekCourses(wc);
        const set = new Set<number>();
        wc.forEach((c) => { if (c.day_of_week) set.add(c.day_of_week); });
        setHasCourseByDow(set);
      }).catch(() => { /* 周数据加载失败不影响时间轴 */ });
      // 同时刷新选中日期的时间轴（日期可能因教学周锚定而变）
      fetchDayCourses(selectedDate);
    } else {
      setHasCourseByDow(new Set());
      setWeekCourses([]);
    }
  }, [displayWeekNumber]); // eslint-disable-line react-hooks/exhaustive-deps

  // 点击周次：切换到该教学周（用 start_date 锚定日期，与课表页一致）
  const pickWeek = useCallback((wn: number) => {
    setDisplayWeekNumber(wn);
    setShowWeekPicker(false);
    // 选中日期：如果今天在该周内则选今天，否则选周一（不用 isBetween 插件，避免额外依赖）
    const sd = getStartDateForWeek(wn);
    const sundayStr = dayjs(sd).add(6, 'day').format('YYYY-MM-DD');
    const todayStr2 = dayjs().format('YYYY-MM-DD');
    setSelectedDate(todayStr2 >= sd && todayStr2 <= sundayStr ? todayStr2 : sd);
  }, [getStartDateForWeek]);

  // 打开 picker 时自动滚动到当前显示的周次
  const openWeekPicker = useCallback(() => {
    if (availableWeeks.length > 0 && displayWeekNumber > 0) {
      const idx = availableWeeks.findIndex((w) => w.week_number === displayWeekNumber);
      setPickerSelected(idx >= 0 ? idx : 0);
    } else {
      setPickerSelected(0);
    }
    setShowWeekPicker(true);
  }, [availableWeeks, displayWeekNumber]);

  // picker-view 滚动选中变化
  const onPickerChange = useCallback((e: any) => {
    setPickerSelected(e.detail.value);
  }, []);

  // picker 确认选择
  const confirmPicker = useCallback(() => {
    if (availableWeeks.length > 0) {
      const wn = availableWeeks[pickerSelected]?.week_number;
      if (wn) pickWeek(wn);
    }
    setShowWeekPicker(false);
  }, [availableWeeks, pickerSelected, pickWeek]);

  // 显示课程：courses 已是选中日期按 full_date 查询的结果，仅按时间排序
  const displayCourses = useMemo(() => {
    const sorted = [...courses].sort(
      (a, b) => (a._timeInfo?.start_ts || 0) - (b._timeInfo?.start_ts || 0),
    );
    // 合并同名相邻课程（数据库可能按单节存储：periods=[5]、[6] 分两条，
    // 合并后 periods=[5,6]，显示为"5-6节"而非两行单节）
    const merged: typeof sorted = [];
    for (const c of sorted) {
      const last = merged[merged.length - 1];
      if (last && last.course_name === c.course_name && last.day_of_week === c.day_of_week) {
        // 同名同天 → 合并 periods
        const pLast = Array.isArray(last.periods) ? last.periods : [];
        const pCur = Array.isArray(c.periods) ? c.periods : [];
        const combined = [...new Set([...pLast, ...pCur])].sort((a, b) => a - b);
        merged[merged.length - 1] = { ...last, periods: combined };
      } else {
        merged.push({ ...c });
      }
    }
    return merged;
  }, [courses]);

  const weekText = displayWeekNumber > 0 ? `第 ${displayWeekNumber} 周` : '非教学周';
  // 胶囊显示教学状态
  const badgeText = displayWeekNumber > 0 ? '教学周' : '假期';

  return (
    <View className="page schedule-page" style={{ paddingTop: `${statusBarHeight}px` }}>
      {/* 自定义导航栏标题：左对齐粗体大字（与首页"校园宜知行"同款） */}
      <Text className="schedule-nav-title">时间轴</Text>

      {/* 白色圆角矩形卡：头部（年月 + 教学周胶囊 + 下箭头 | 今天）+ 周历 7 天 */}
      <View className="card week-calendar">
        {/* 头部行：第 X 周 + 教学周胶囊 + 旋转箭头（左），今天（右） */}
        <View className="week-calendar-head">
          <View
            className="schedule-week-picker"
            onClick={openWeekPicker}
          >
            <Text className="schedule-month-text">{displayWeekNumber > 0 ? `第 ${displayWeekNumber} 周` : '非教学周'}</Text>
            <View className="week-calendar-badge">
              <Text className="week-calendar-badge-text">{badgeText}</Text>
            </View>
            <Text className={`iconfont icon-a-xiala2 schedule-month-arrow${showWeekPicker ? ' rotated' : ''}`} />
          </View>
          <Text
            className="schedule-today-btn"
            onClick={() => {
              setSelectedDate(todayStr);
              setDisplayWeekNumber(weekNumber);
            }}
          >
            今天
          </Text>
        </View>


        {/* 周历行：Swiper 左右滑动切换教学周（key 随周次重建），每页 7 天横排 */}
        <Swiper
          className="week-swiper"
          key={displayWeekNumber}
          current={1}
          onChange={onSwiperChange}
          duration={200}
        >
          {[-1, 0, 1].map((offset) => {
            const wn = displayWeekNumber + offset;
            const sd = getStartDateForWeek(wn);
            const monday = dayjs(sd);
            const days = Array.from({ length: 7 }, (_, i) => monday.add(i, 'day'));
            return (
              <SwiperItem key={wn}>
                <View className="week-calendar-days">
                  {days.map((d) => {
                    const dateStr = d.format('YYYY-MM-DD');
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
                          <Text className={isToday ? 'week-cell-day-text-active' : isSelected ? 'week-cell-day-text-selected' : ''}>{d.date()}</Text>
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

      {/* 选中日期的课程时间轴 */}
      {loading ? (
        <LoadingState text="正在加载课程…" />
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
            const st = courseStatus(c);
            const statusMap: Record<string, TimelineStatus> = {
              upcoming: 'upcoming',
              ongoing: 'ongoing',
              finished: 'finished',
            };
            const statusTextMap: Record<string, string> = {
              upcoming: '未开始',
              ongoing: '进行中',
              finished: '已结束',
            };
            // 节次文本：periods 可能是数组或 JSON 字符串，统一转字符串数组
            let periodsArr: number[] = [];
            const p = c.periods;
            if (Array.isArray(p)) {
              periodsArr = p;
            } else if (typeof p === 'string') {
              try {
                periodsArr = JSON.parse(p);
              } catch {
                // 兼容 "1-2" 区间字符串
                const m = p.match(/(\d+)\s*[-~]\s*(\d+)/);
                if (m) periodsArr = [Number(m[1]), Number(m[2])];
              }
            }
            const periodsText =
              periodsArr.length >= 2
                ? `${periodsArr[0]}-${periodsArr[periodsArr.length - 1]}节`
                : periodsArr.length === 1
                ? `${periodsArr[0]}节`
                : '';
            // 课程颜色：基于课程名加权 hash 选固定颜色（分布更均匀，每门课视觉不同且稳定）
            const colorKeys: CourseColorKey[] = ['green', 'blue', 'orange', 'purple', 'pink'];
            const hash = (c.course_name || '').split('').reduce(
              (acc, ch, i) => (acc + ch.charCodeAt(0) * (i + 1)) % 997,
              0,
            );
            const courseColorKey: CourseColorKey = colorKeys[hash % colorKeys.length];
            return (
              <TimelineItem
                key={c.schedule_id}
                time={tsToHm(c._timeInfo?.start_ts || 0)}
                periodsText={periodsText}
                courseName={c.course_name}
                building={c.extra_info?.building}
                classroom={c.extra_info?.classroom}
                teacher={c.extra_info?.teacher}
                status={statusMap[st] || 'info'}
                statusText={statusTextMap[st]}
                courseColorKey={courseColorKey}
                isLast={idx === displayCourses.length - 1}
              />
            );
          })}
        </View>
      )}

      {/* 近期提醒（时间轴下方） */}
      <ReminderCard
        events={reminders}
        loading={remindersLoading}
        error={remindersError}
        onRetry={loadReminders}
      />

      {/* 底部弹出周次选择器：半透明遮罩 + 从底部滑入 + 纵向滚轮选周次 */}
      {showWeekPicker && (
        <View className="week-picker-mask" onClick={() => setShowWeekPicker(false)}>
          <View className="week-picker-modal" onClick={(e) => e.stopPropagation()}>
            {/* 标题栏：学期名 + 取消/确认 */}
            <View className="week-picker-header">
              <Text className="week-picker-cancel" onClick={() => setShowWeekPicker(false)}>取消</Text>
              {semesterName ? (
                <Text className="week-picker-title">{semesterName}</Text>
              ) : (
                <View />
              )}
              <Text className="week-picker-confirm" onClick={confirmPicker}>确定</Text>
            </View>
            {/* 分隔线 */}
            <View className="week-picker-divider" />
            {/* PickerView 纵向滚动 */}
            <View className="week-picker-body">
              <PickerView
                className="week-picker-view"
                value={[pickerSelected]}
                onChange={onPickerChange}
              >
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
