/**
 * 24h 预报 · 横向时间轴组件
 *
 * 替代 Weather.tsx 里旧的竖向逐行时间轴（信息密度低、页面冗长）。
 * 布局参考常见天气 App 的逐时条：温度平滑曲线 + 逐时天气图标 + 降水概率 +
 * 时间轴，横向滚动查看；当前小时用浅色底带 + 强调色标注；跨天处画分隔线。
 *
 * 图标沿用项目既有的 emoji 方案（weatherEmoji），主题强调色沿用 weatherAccent。
 */
import { Spin, Alert } from "antd";
import type { HourlyForecast } from "@/api/weather";

/** 天气文字 → emoji 图标（按常见中文天气描述匹配） */
const WEATHER_EMOJI: [RegExp, string][] = [
  [/雷|暴/, "⛈️"],
  [/雨/, "🌧️"],
  [/雪/, "❄️"],
  [/雾|霾|沙|尘/, "🌫️"],
  [/阴/, "☁️"],
  [/多云/, "⛅"],
  [/晴/, "☀️"],
];
const weatherEmoji = (text: string): string => {
  for (const [re, emoji] of WEATHER_EMOJI) if (re.test(text || "")) return emoji;
  return "🌡️";
};

/** 天气文字 → 主题强调色 */
const weatherAccent = (text: string): string => {
  if (/雨|雪|雷/.test(text || "")) return "#1677ff";
  if (/晴/.test(text || "")) return "#fa8c16";
  if (/多云/.test(text || "")) return "#13c2c2";
  if (/阴|雾|霾/.test(text || "")) return "#8c8c8c";
  return "#1677ff";
};

/** 格式化时间字符串为 HH:mm */
const fmtHour = (t: string): string => {
  if (!t) return "--:--";
  const d = new Date(t);
  if (isNaN(d.getTime())) return t;
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

/** 格式化时间字符串为 M/D（跨天分隔线标注用） */
const fmtDay = (t: string): string => {
  const d = new Date(t);
  if (isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}/${d.getDate()}`;
};

/** Catmull-Rom 转三次贝塞尔：把离散温度点连成平滑曲线 */
const smoothPath = (pts: { x: number; y: number }[]): string => {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`;
  const r1 = (n: number) => Math.round(n * 10) / 10;
  let d = `M ${r1(pts[0].x)} ${r1(pts[0].y)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${r1(c1x)} ${r1(c1y)}, ${r1(c2x)} ${r1(c2y)}, ${r1(p2.x)} ${r1(p2.y)}`;
  }
  return d;
};

/** 每列宽度（px） */
const COL_W = 62;
/** SVG 总高度（px） */
const SVG_H = 216;
/** 温度曲线的纵向映射区间（最高温 y=46，最低温 y=128） */
const CURVE_TOP = 46;
const CURVE_BOTTOM = 128;

interface Props {
  data: HourlyForecast[];
  loading?: boolean;
}

export default function HourlyForecastStrip({ data, loading }: Props) {
  if (loading)
    return (
      <div style={{ textAlign: "center", padding: 40 }}>
        <Spin />
      </div>
    );
  if (!data.length)
    return <Alert message="暂无 24 小时预报数据" type="info" showIcon />;

  const temps = data.map((h) => parseFloat(h.temp) || 0);
  const maxT = Math.max(...temps);
  const minT = Math.min(...temps);
  const span = Math.max(maxT - minT, 1);
  const yFor = (t: number) => CURVE_TOP + (1 - (t - minT) / span) * (CURVE_BOTTOM - CURVE_TOP);
  const pts = temps.map((t, i) => ({ x: i * COL_W + COL_W / 2, y: yFor(t) }));
  const curve = smoothPath(pts);

  // 跨天分隔：与前一小时的日期不同的位置画虚线并标注日期
  const dayMarks: number[] = [];
  for (let i = 1; i < data.length; i++) {
    const d1 = fmtDay(data[i].time);
    const d0 = fmtDay(data[i - 1].time);
    if (d1 && d1 !== d0) dayMarks.push(i);
  }

  return (
    <div
      style={{
        border: "1px solid #f0f0f0",
        borderRadius: 8,
        background: "#fff",
        padding: "14px 16px 10px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "#333" }}>未来 24 小时</span>
        <span style={{ fontSize: 12, color: "#999" }}>
          最高 {maxT}° / 最低 {minT}°
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <svg width={data.length * COL_W} height={SVG_H} style={{ display: "block" }}>
          {/* 当前小时背景带 */}
          <rect x={0} y={0} width={COL_W} height={SVG_H} fill="#f5f9ff" rx={6} />
          {/* 跨天分隔线 + 日期标注 */}
          {dayMarks.map((i) => (
            <g key={`day-${i}`}>
              <line
                x1={i * COL_W}
                y1={30}
                x2={i * COL_W}
                y2={SVG_H - 24}
                stroke="#e8e8e8"
                strokeDasharray="3 3"
              />
              <text x={i * COL_W + 6} y={14} fontSize={10} fill="#bbb">
                {fmtDay(data[i].time)}
              </text>
            </g>
          ))}
          {/* 温度平滑曲线 */}
          <path
            d={curve}
            fill="none"
            stroke="#1677ff"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {data.map((item, i) => {
            const p = pts[i];
            const isCurrent = i === 0;
            const pop = parseFloat(item.pop) || 0;
            return (
              <g key={`${item.time}-${i}`}>
                <title>
                  {`${fmtHour(item.time)} ${item.text} ${item.temp}°C 降水概率 ${item.pop}%`}
                </title>
                {/* 透明热区：悬停可看 title 提示 */}
                <rect x={i * COL_W} y={0} width={COL_W} height={SVG_H} fill="transparent" />
                {/* 温度标签 */}
                <text
                  x={p.x}
                  y={p.y - 12}
                  textAnchor="middle"
                  fontSize={13}
                  fontWeight={isCurrent ? 700 : 600}
                  fill={isCurrent ? "#1677ff" : "#444"}
                >
                  {item.temp}°
                </text>
                {/* 曲线节点 */}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={3.5}
                  fill="#fff"
                  stroke={isCurrent ? weatherAccent(item.text) : "#1677ff"}
                  strokeWidth={2}
                />
                {/* 天气图标 */}
                <text x={p.x} y={p.y + 34} textAnchor="middle" fontSize={17}>
                  {weatherEmoji(item.text)}
                </text>
                {/* 降水概率（0% 不显示，降低噪音） */}
                {pop > 0 && (
                  <text x={p.x} y={p.y + 54} textAnchor="middle" fontSize={11} fill="#1677ff">
                    {item.pop}%
                  </text>
                )}
                {/* 时间轴 */}
                <text
                  x={p.x}
                  y={SVG_H - 8}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={isCurrent ? 600 : 400}
                  fill={isCurrent ? "#1677ff" : "#999"}
                >
                  {isCurrent ? "现在" : fmtHour(item.time)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
