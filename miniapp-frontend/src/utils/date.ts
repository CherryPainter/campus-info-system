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

/** 日期字符串（YYYY-MM-DD）→ 中文「星期四」；无效日期返回空串 */
export function weekdayCNFromDate(date: string): string {
  const d = dayjs(date);
  if (!d.isValid()) return '';
  return weekdayCN(d.day() === 0 ? 7 : d.day());
}

/**
 * 相对今天的口语化标签：今天 / 昨天 / 前天，更早的日期返回空串
 *
 * 注意（用电场景）：用电记录里的日期是【用电日】，用电日是次日 00 点后才结算入库的，
 * 所以最新一条通常是「昨天」而不是「今天」——由结算机制决定，不是数据缺失。
 */
export function relativeDayLabel(date: string): string {
  const d = dayjs(date);
  if (!d.isValid()) return '';
  const diff = d.startOf('day').diff(dayjs().startOf('day'), 'day');
  if (diff === 0) return '今天';
  if (diff === -1) return '昨天';
  if (diff === -2) return '前天';
  return '';
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
