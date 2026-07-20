/**
 * 假期模式 / 非教学周 课程页视图
 *
 * 联动管理员在「假期模式」中配置的区间（权威来源）。
 * 未配置时显示简洁的「非教学周」提示。
 */
import { Tag } from "antd";
import { CalendarOutlined } from "@ant-design/icons";
import { WEEK_DAY_MAP } from "@/api/course";
import type { HolidayPeriod } from "@/api/holiday";

interface HolidayCourseViewProps {
  today: Date;
  semesterName?: string;
  /** 命中的假期区间（来自 GET /api/holiday/status）；未传或 null 则按非教学周展示 */
  holidayPeriod?: HolidayPeriod;
}

const HOLIDAY_TYPE_LABEL: Record<string, string> = {
  winter: "寒假",
  summer: "暑假",
  custom: "自定义假期",
};

function formatToday(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const weekday = WEEK_DAY_MAP[d.getDay() === 0 ? 7 : d.getDay()] || "";
  return `${y}年${m}月${day}日 ${weekday}`;
}

export default function HolidayCourseView({
  today,
  semesterName,
  holidayPeriod,
}: HolidayCourseViewProps) {
  const isHolidayMode = !!holidayPeriod;

  return (
    <div
      style={{
        background: "linear-gradient(135deg, #e6f7ff 0%, #f9f0ff 55%, #fff7e6 100%)",
        borderRadius: 12,
        padding: "40px 24px",
        textAlign: "center",
        boxShadow: "0 2px 12px rgba(0, 0, 0, 0.05)",
        marginBottom: 8,
      }}
    >
      <div
        style={{
          width: 68,
          height: 68,
          borderRadius: "50%",
          background: "#ffffff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          margin: "0 auto 18px",
          boxShadow: "0 4px 14px rgba(24, 144, 255, 0.18)",
        }}
      >
        <CalendarOutlined style={{ fontSize: 30, color: "#1890ff" }} />
      </div>

      <div style={{ fontSize: 24, fontWeight: 600, color: "#1f1f1f", letterSpacing: 1 }}>
        {isHolidayMode ? "推送静默" : "非教学周"}
      </div>

      <div style={{ marginTop: 10, color: "#595959", fontSize: 15 }}>
        {isHolidayMode ? `${holidayPeriod!.name} · ${formatToday(today)}` : formatToday(today)}
      </div>

      <div style={{ marginTop: 6, color: "#8c8c8c", fontSize: 13 }}>
        {isHolidayMode
          ? `当前为「${holidayPeriod!.name}」，课程表暂不更新`
          : "当前不在本学期教学周内，课程表暂不更新"}
      </div>

      {isHolidayMode && (
        <div style={{ marginTop: 12 }}>
          <Tag color="blue">{HOLIDAY_TYPE_LABEL[holidayPeriod!.holiday_type] ?? "假期"}</Tag>
          <span style={{ color: "#595959", fontSize: 14 }}>
            {holidayPeriod!.start_date} ~ {holidayPeriod!.end_date}
          </span>
        </div>
      )}

      {semesterName && (
        <div style={{ marginTop: 18, color: "#595959", fontSize: 14 }}>
          学期：<span style={{ fontWeight: 600 }}>{semesterName}</span>
        </div>
      )}

      <div style={{ marginTop: 16, color: "#bfbfbf", fontSize: 12 }}>
        可在右上角「周次」中选择任意周次浏览历史课表
      </div>
    </div>
  );
}
