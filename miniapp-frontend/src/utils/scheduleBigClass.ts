/**
 * 课表「两节为一节大课」拆分工具
 *
 * 背景：
 * - 教务爬虫按单节写入课程（如 5-8 节存成 periods=[5]/[6]/[7]/[8] 多条），
 *   后端 _merge_split_courses 会把同天同名同教室的记录合并成 periods=[5,6,7,8] 一条，
 *   于是前端拿到的是「四节课合成为一块」的整段区间（14:10-18:10）。
 * - 但真实上课是「两节两节上」，每 2 节 = 1 门大课。本工具把合并后的课程按每 2 节一组
 *   拆回多条，并用课表权威时间填充每块的 start_time / end_time / _timeInfo，
 *   与后端 app/utils/course_helpers.py 的 split_course_to_big_classes 口径完全一致
 *   （含两套时间表 + 按楼栋选择），保证小程序端展示与提醒时间准确。
 *
 * 注意：仅用于「首页今日课程」与「时间轴页」的展示拆分，不影响课表 grid 页（其合并逻辑独立）。
 */

import type { ScheduleCourse } from '@/types/api';

/** 节次 -> [开始, 结束]（第一套时间表：启智楼等楼栋） */
const FIRST_SCHEDULE: Record<number, [string, string]> = {
  1: ['08:10', '08:55'],
  2: ['09:05', '09:50'],
  3: ['10:10', '10:55'],
  4: ['11:05', '11:50'],
  5: ['14:10', '14:55'],
  6: ['15:05', '15:50'],
  7: ['16:10', '16:55'],
  8: ['17:05', '17:50'],
  9: ['18:50', '19:35'],
  10: ['19:35', '20:20'],
  11: ['20:30', '21:15'],
  12: ['21:15', '22:00'],
};

/** 节次 -> [开始, 结束]（第二套时间表：艺教楼等楼栋，默认） */
const SECOND_SCHEDULE: Record<number, [string, string]> = {
  1: ['08:10', '08:55'],
  2: ['09:05', '09:50'],
  3: ['10:30', '11:15'],
  4: ['11:25', '12:10'],
  5: ['14:10', '14:55'],
  6: ['15:05', '15:50'],
  7: ['16:30', '17:15'],
  8: ['17:25', '18:10'],
  9: ['18:50', '19:35'],
  10: ['19:35', '20:20'],
  11: ['20:30', '21:15'],
  12: ['21:15', '22:00'],
};

/** 使用第一套时间表的楼栋（其余楼栋用第二套） */
const FIRST_SCHEDULE_BUILDINGS = [
  '启智楼',
  '雏鹰楼',
  '语慧楼',
  '思源楼',
  '讯达楼',
  '盛德楼',
  'S01',
  'S02',
  'J01',
  'J04',
  'J14',
  'J15',
];

/** 按楼栋选择时间表（与后端 get_schedule_by_building 一致） */
function getScheduleByBuilding(building?: string): Record<number, [string, string]> {
  if (building && FIRST_SCHEDULE_BUILDINGS.includes(building)) return FIRST_SCHEDULE;
  return SECOND_SCHEDULE;
}

/** 把 periods 字段统一成 number[]（兼容 list / JSON 字符串 / 单数字 / undefined） */
function normalizePeriods(periods: number[] | string | undefined | null): number[] {
  if (periods == null) return [];
  let arr: unknown;
  if (Array.isArray(periods)) {
    arr = periods;
  } else if (typeof periods === 'string') {
    if (!periods.trim()) return [];
    try {
      const parsed = JSON.parse(periods);
      if (Array.isArray(parsed)) {
        arr = parsed;
      } else {
        // "1-2" 区间字符串兜底
        const m = periods.match(/(\d+)\s*[-~]\s*(\d+)/);
        arr = m ? [Number(m[1]), Number(m[2])] : periods.split(',').map((s) => s.trim());
      }
    } catch {
      const m = periods.match(/(\d+)\s*[-~]\s*(\d+)/);
      arr = m ? [Number(m[1]), Number(m[2])] : periods.split(',').map((s) => s.trim());
    }
  } else {
    arr = [periods];
  }
  if (!Array.isArray(arr)) return [];
  return arr
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n >= 1 && n <= 12);
}

/** 由 full_date + HH:mm 计算本地秒级时间戳（与后端 datetime(...).timestamp() 口径一致） */
function toTimestamp(fullDate: string, hhmm: string): number {
  const d = new Date(`${fullDate}T${hhmm}:00`);
  return Math.floor(d.getTime() / 1000);
}

/**
 * 把一门（可能跨多节）课程按「每 2 节 = 1 门大课」拆成多条。
 * 返回至少 1 条；只有单组（≤2 节）时原样返回。
 */
export function splitCourseToBigClasses(course: ScheduleCourse): ScheduleCourse[] {
  const periods = normalizePeriods(course.periods as number[] | string | undefined);
  if (periods.length === 0) {
    // 无 periods 兜底：用 period_idx
    if (course.period_idx && course.period_idx >= 1) {
      periods.push(course.period_idx);
    } else {
      return [course];
    }
  }
  const sorted = [...new Set(periods)].sort((a, b) => a - b);
  // 按每 2 节一组切分（与后端 chunks = [periods[i:i+2] for i in range(0, len, 2)] 一致）
  const chunks: number[][] = [];
  for (let i = 0; i < sorted.length; i += 2) {
    chunks.push(sorted.slice(i, i + 2));
  }
  if (chunks.length <= 1) return [course];

  const building = course.extra_info?.building || '';
  const sch = getScheduleByBuilding(building);
  const fullDate = course.extra_info?.full_date;

  return chunks.map((chunk) => {
    const lo = chunk[0];
    const hi = chunk[chunk.length - 1];
    const start_time = sch[lo]?.[0] ?? course.start_time;
    const end_time = sch[hi]?.[1] ?? course.end_time;
    const newCourse: ScheduleCourse = {
      ...course,
      period_idx: lo,
      periods: chunk,
      start_time,
      end_time,
      schedule_id: `${course.schedule_id}#p${lo}-${hi}`,
    };
    if (fullDate) {
      newCourse._timeInfo = {
        ...course._timeInfo,
        start_ts: toTimestamp(fullDate, start_time),
        end_ts: toTimestamp(fullDate, end_time),
      };
    }
    return newCourse;
  });
}

/** 批量拆分：把一整天/一周的课程列表按大课展开（顺序保持输入顺序，调用方自行排序） */
export function splitCoursesToBigClasses(courses: ScheduleCourse[]): ScheduleCourse[] {
  return courses.flatMap((c) => splitCourseToBigClasses(c));
}
