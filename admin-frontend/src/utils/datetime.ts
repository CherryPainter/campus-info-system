import dayjs from "dayjs";

/** 格式化日期时间为 YYYY-MM-DD HH:mm:ss（无效值返回 '-'） */
export function formatDateTime(v: unknown): string {
  if (v === null || v === undefined || v === "") return "-";
  const d = dayjs(v as any);
  return d.isValid() ? d.format("YYYY-MM-DD HH:mm:ss") : "-";
}

/** 格式化日期为 YYYY-MM-DD（无效值返回 '-'） */
export function formatDate(v: unknown): string {
  if (v === null || v === undefined || v === "") return "-";
  const d = dayjs(v as any);
  return d.isValid() ? d.format("YYYY-MM-DD") : "-";
}

/** 格式化紧凑日期时间为 MM-DD HH:mm（无效值返回 '-'） */
export function formatTimeShort(v: unknown): string {
  if (v === null || v === undefined || v === "") return "-";
  const d = dayjs(v as any);
  return d.isValid() ? d.format("MM-DD HH:mm") : "-";
}
