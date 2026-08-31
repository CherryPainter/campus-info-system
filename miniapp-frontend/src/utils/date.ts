import dayjs from 'dayjs';

/**
 * 日期 / 时间辅助函数
 */

const WEEKDAY_CN = ['', '一', '二', '三', '四', '五', '六', '日'];

/** 星期几数字(1-7) → 中文「星期四」 */
export function weekdayCN(weekday: number): string {
  const idx = weekday >= 1 && weekday <= 7 ? weekday : 0;
  return `星期${WEEKDAY_CN[idx] || ''}`;
}

/** 按小时返回问候语（5-11 上午 / 11-13 中午 / 13-18 下午 / 其余 晚上） */
export function greeting(): string {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 11) return '上午好';
  if (hour >= 11 && hour < 13) return '中午好';
  if (hour >= 13 && hour < 18) return '下午好';
  return '晚上好';
}

/** 今日文案：「8月27日 · 星期四」 */
export function todayText(): string {
  const d = dayjs();
  return `${d.format('M月D日')} · ${weekdayCN(d.day() === 0 ? 7 : d.day())}`;
}

/** HH:mm */
export function hm(time: string): string {
  return dayjs(time, 'HH:mm').format('HH:mm');
}

/** 秒时间戳 → HH:mm */
export function tsToHm(ts: number): string {
  return dayjs(ts * 1000).format('HH:mm');
}
