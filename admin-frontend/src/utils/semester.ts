/**
 * 学期相关日期推算工具（原 Course.tsx 中的模块级函数迁移至此，供 Course 与 CrawlScheduler 共用）
 */

/**
 * 根据学期 ID（DB 格式，如 20251 / 20252）推算开学日期
 * - 第一学期（秋）：起始年份 9 月 1 日
 * - 第二学期（春）：起始年份 +1 年 3 月 2 日
 * 例如 20251 -> 2025-09-01；20252 -> 2026-03-02
 */
export function getSemesterStartDate(semesterId?: number): Date {
  if (!semesterId) {
    // 未指定学期时，按今天所在学期推断（兼容初始状态）
    const today = new Date();
    const year = today.getFullYear();
    const springStart = new Date(year, 2, 2);
    const fallStart = new Date(year, 8, 1);
    if (today >= springStart && today <= new Date(year, 6, 19)) return springStart;
    if (today >= fallStart) return fallStart;
    if (today < springStart) return new Date(year - 1, 8, 1);
    // 7-20 ~ 8-31 为暑假真空期：下一学期是当年秋季（9/1 开学），而非春季
    return fallStart;
  }
  const year = Math.floor(semesterId / 10);
  const term = semesterId % 10;
  if (term === 1) {
    return new Date(year, 8, 1); // 第一学期：9月1日
  }
  return new Date(year + 1, 2, 2); // 第二学期：次年3月2日
}

/** 根据学期日期计算每周的日期（带 semesterId，日期随所选学期变化） */
export function getWeekDate(weekNumber: number, weekDay: number, semesterId?: number): string {
  const semesterStart = getSemesterStartDate(semesterId);

  // 先锚定到「开学日所在周的真实周一」，与后端 build_available_weeks 同一口径。
  // 开学日若不是周一（如 2026-09-01 是周二），直接把开学日当周一会让整周日期
  // 比真实日历整体偏移 (开学日星期几-1) 天，与课表表头/周历显示的「今天」对不齐。
  const weekMonday = new Date(semesterStart);
  const dow = weekMonday.getDay(); // 0=周日,1=周一..6=周六
  const diffToMonday = dow === 0 ? -6 : 1 - dow;
  weekMonday.setDate(weekMonday.getDate() + diffToMonday);

  // 再按周次推算该周的周一
  weekMonday.setDate(weekMonday.getDate() + (weekNumber - 1) * 7);

  // 计算该天的日期（weekDay: 1=周一, 7=周日）
  const targetDate = new Date(weekMonday);
  targetDate.setDate(weekMonday.getDate() + weekDay - 1);

  // 格式化为 MM-DD
  const month = String(targetDate.getMonth() + 1).padStart(2, "0");
  const day = String(targetDate.getDate()).padStart(2, "0");
  return `${month}-${day}`;
}
