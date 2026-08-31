import { get } from '@/utils/request';
import type {
  ScheduleCurrentResult,
  ScheduleTodayResult,
  ScheduleWeekResult,
} from '@/types/api';

/**
 * 课表 API（/api/miniapp/schedule）
 * - 返回系统唯一课表（Course 表为全校/单账号爬取数据，无学生身份维度）
 */

/** 指定日期课程（缺省今天） */
export function getToday(date?: string): Promise<ScheduleTodayResult> {
  return get<ScheduleTodayResult>('/api/miniapp/schedule/today', date ? { date } : {});
}

/** 指定周课表（缺省当前教学周） */
export function getWeek(weekNumber?: number): Promise<ScheduleWeekResult> {
  return get<ScheduleWeekResult>('/api/miniapp/schedule/week', weekNumber ? { week_number: weekNumber } : {});
}

/** 当前教学周信息 */
export function getCurrent(): Promise<ScheduleCurrentResult> {
  return get<ScheduleCurrentResult>('/api/miniapp/schedule/current');
}
