import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { View, Text, ScrollView, Canvas } from '@tarojs/components';
import { useLoad, getWindowInfo, stopPullDownRefresh, usePullDownRefresh } from '@tarojs/taro';
import Taro from '@tarojs/taro';

import * as weatherApi from '@/api/weather';
import type {
  WeatherNow,
  WeatherHourlyItem,
  WeatherAlert,
  WeatherDailyItem,
  WeatherIndexItem,
  WeatherAir,
  WeatherMinutelyItem,
} from '@/types/api';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

// 解析 hourly 项的时间戳（兼容 "2026-08-29T20:00+08:00" 与 "2026-08-29 20:00"）
function parseHourTs(h: any): number {
  const t = h?.fxTime || h?.fx_time || h?.time || '';
  if (!t) return 0;
  const iso = t.includes('+') ? t : t.replace(' ', 'T');
  const ms = Date.parse(iso);
  return isNaN(ms) ? 0 : ms;
}

// 把 hourly 重排为「以"现在"附近为起始的序列」
// 和风 24h 接口返回「当前时刻往后 24h」，跨零点时旧缓存会把 00:00 排到末尾。
// 策略：先升序 → 按日期旋转（今天数据排前）→ 兜底按"距现在最近"旋转。
function reorderHourly(arr: any[]): any[] {
  if (!arr || arr.length < 2) return arr;
  const sorted = [...arr].sort((a, b) => parseHourTs(a) - parseHourTs(b));
  const now = new Date();
  const pad2 = (n: number) => (n < 10 ? '0' + n : '' + n);
  const todayStr = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;

  // 策略1：按日期旋转 — 找到今天第一条数据，转到最前
  let rot = -1;
  for (let i = 0; i < sorted.length; i++) {
    const t = sorted[i]?.fxTime || sorted[i]?.fx_time || sorted[i]?.time || '';
    if (t.slice(0, 10) === todayStr) { rot = i; break; }
  }
  if (rot > 0) return [...sorted.slice(rot), ...sorted.slice(0, rot)];

  // 策略2：凌晨宽窗口（0:00-4:59）— 数据可能全是昨天的，找"明天"锚点
  if (now.getHours() < 5) {
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const tomStr = `${tomorrow.getFullYear()}-${pad2(tomorrow.getMonth() + 1)}-${pad2(tomorrow.getDate())}`;
    for (let i = 0; i < sorted.length; i++) {
      const t = sorted[i]?.fxTime || sorted[i]?.fx_time || sorted[i]?.time || '';
      if (t.slice(0, 10) === tomStr) { rot = i; break; }
    }
    if (rot > 0) return [...sorted.slice(rot), ...sorted.slice(0, rot)];
  }

  // 策略3：终极兜底 — 找距"现在"时间最近的点，旋转到索引 2（留 2 个历史点）
  let closestIdx = 0;
  let minDiff = Infinity;
  sorted.forEach((h, i) => {
    const diff = Math.abs(parseHourTs(h) - now.getTime());
    if (diff < minDiff) { minDiff = diff; closestIdx = i; }
  });
  if (closestIdx > 2) {
    const targetIdx = Math.min(closestIdx, 2); // 旋转后让最近点落在位置 0~2
    return [...sorted.slice(targetIdx), ...sorted.slice(0, targetIdx)];
  }

  return sorted;
}

// 天气状况到渐变色映射（顶部亮、底部加深，保证白字对比度）
const WEATHER_GRADIENTS: Record<string, { from: string; via: string; to: string }> = {
  '晴':     { from: '#3a8fd4', via: '#6bb3f0', to: '#3d5a73' },
  '少云':   { from: '#4a93d6', via: '#74b8f0', to: '#3f5e76' },
  '多云':   { from: '#5a9bd9', via: '#7abbe8', to: '#42566b' },
  '阴':     { from: '#6a8aaa', via: '#8fa3b8', to: '#414b56' },
  '雷':     { from: '#3a5070', via: '#556a8a', to: '#2c3340' },
  '暴雨':   { from: '#274a6b', via: '#3d6890', to: '#1e2a38' },
  '大雨':   { from: '#2d5678', via: '#486c8c', to: '#222e3c' },
  '中雨':   { from: '#3d6890', via: '#5880a8', to: '#28323f' },
  '阵雨':   { from: '#4e7a9e', via: '#6a94b4', to: '#2c3a47' },
  '小雨':   { from: '#4e7a9e', via: '#6a94b4', to: '#2e3b48' },
  '雪':     { from: '#8fa4bc', via: '#b8c8d8', to: '#4a5563' },
  '雨夹雪': { from: '#7a8fa8', via: '#a0b4c8', to: '#3c4654' },
  '雾':     { from: '#8a9aa8', via: '#abb8c4', to: '#4a535c' },
  '霾':     { from: '#8a8a7a', via: '#a8a890', to: '#4a4a3e' },
  '沙尘':   { from: '#9a8a5a', via: '#b8a878', to: '#4e4630' },
  '冰雹':   { from: '#5a6a8a', via: '#7a8aa8', to: '#333b4a' },
};

// 天气特效类型：雨天/雾天/晴天（其余无特效）
type FxType = '' | 'rainy' | 'foggy' | 'sunny';
function getFxType(text?: string | null): FxType {
  if (!text) return '';
  if (text.includes('雨') || text.includes('雪') || text.includes('冰雹')) return 'rainy';
  if (text.includes('雾') || text.includes('霾') || text.includes('沙尘')) return 'foggy';
  if (text.includes('晴') || text.includes('少云')) return 'sunny';
  return '';
}

// 按优先级匹配天气文字（更具体的先匹配）
function getGradient(text?: string | null) {
  if (!text) return WEATHER_GRADIENTS['晴'];
  const order = [
    '雷', '暴雨', '大雨', '中雨', '阵雨', '小雨', '雨夹雪', '雪',
    '雾', '霾', '沙尘', '冰雹', '多云', '少云', '阴', '晴',
  ];
  for (const key of order) {
    if (text.includes(key)) return WEATHER_GRADIENTS[key];
  }
  if (text.includes('雨')) return WEATHER_GRADIENTS['小雨'];
  if (text.includes('云')) return WEATHER_GRADIENTS['多云'];
  if (text.includes('雪')) return WEATHER_GRADIENTS['雪'];
  return WEATHER_GRADIENTS['阴'];
}

/**
 * 温度 → 颜色（冷蓝 → 暖红色阶）
 */
const TEMP_STOPS: { t: number; c: [number, number, number] }[] = [
  { t: -10, c: [59, 130, 246] },
  { t: 0,   c: [96, 165, 250] },
  { t: 10,  c: [34, 211, 238] },
  { t: 18,  c: [74, 222, 128] },
  { t: 24,  c: [250, 204, 21] },
  { t: 30,  c: [251, 146, 60] },
  { t: 38,  c: [239, 68, 68] },
];

function tempToColor(temp: number): string {
  const stops = TEMP_STOPS;
  if (temp <= stops[0].t) return `rgb(${stops[0].c.join(',')})`;
  if (temp >= stops[stops.length - 1].t) return `rgb(${stops[stops.length - 1].c.join(',')})`;
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (temp >= a.t && temp <= b.t) {
      const r = (temp - a.t) / (b.t - a.t);
      const cr = Math.round(a.c[0] + (b.c[0] - a.c[0]) * r);
      const cg = Math.round(a.c[1] + (b.c[1] - a.c[1]) * r);
      const cb = Math.round(a.c[2] + (b.c[2] - a.c[2]) * r);
      return `rgb(${cr},${cg},${cb})`;
    }
  }
  return '#fff';
}

/**
 * Catmull-Rom 样条 → 平滑曲线控制点
 */
function getCurvePoints(pts: { x: number; y: number }[]): { x: number; y: number }[] {
  if (pts.length < 2) return pts;
  const result: { x: number; y: number }[] = [];
  for (let i = 0; i < pts.length; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[Math.min(pts.length - 1, i + 1)];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    result.push(p1);
    if (i < pts.length - 1) {
      const t = 0.5;
      const t2 = t * t;
      const t3 = t2 * t;
      result.push({
        x: 0.5 * ((2 * p1.x) + (-p0.x + p2.x) * t + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3),
        y: 0.5 * ((2 * p1.y) + (-p0.y + p2.y) * t + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 + (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3),
      });
    }
  }
  return result;
}

/**
 * 天气文字 → emoji 图标（Canvas 内绘制用）
 */
function getWeatherIconEmoji(text?: string | null): string {
  if (!text) return '🌤';
  if (text.includes('晴')) return text.includes('多云') ? '⛅' : '☀';
  if (text.includes('云')) return '☁';
  if (text.includes('雨')) return text.includes('大雨') || text.includes('暴雨') ? '🌧' : '🌦';
  if (text.includes('雪')) return '❄';
  if (text.includes('雷')) return '⛈';
  if (text.includes('雾') || text.includes('霾')) return '🌫';
  return '🌤';
}

// 星期中文
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
function getWeekdayLabel(fxDate?: string, index = 0): string {
  if (!fxDate) return '';
  if (index === 0) return '今天';
  const d = new Date(fxDate.replace(/-/g, '/'));
  if (isNaN(d.getTime())) return fxDate.slice(5);
  return WEEKDAYS[d.getDay()];
}

// AQI 数值 → 颜色（与国标等级一致）
function aqiToColor(aqi: number | string | undefined): string {
  const v = Number(aqi);
  if (!v) return '#9aa7b3';
  if (v <= 50) return '#52c41a';   // 优
  if (v <= 100) return '#eab308';  // 良
  if (v <= 150) return '#fa8c16';  // 轻度污染
  if (v <= 200) return '#f5222d';  // 中度污染
  if (v <= 300) return '#a8327d';  // 重度污染
  return '#7e0023';                // 严重污染
}

/**
 * 生活指数 type/name → iconfont class 名（不含 icon- 前缀，调用方加 iconfont 基类）
 */
function getIndexIconClass(type?: string, name?: string): string {
  const t = type || '';
  // 优先按官方 type 精确匹配（和风数字编号）
  const map: Record<string, string> = {
    '1': 'paobu',              // 运动
    '2': 'xiche-cuxiantiao',   // 洗车
    '3': 'tubiao-',            // 穿衣(衣服)
    '4': 'diaoyugan',          // 钓鱼
    '5': 'ziwaixian',          // 紫外线
    '6': 'lvyoufabu',          // 旅游
    '7': '-breathbreathinghealthrespiratory', // 花粉过敏
    '8': 'shushiduwendu',      // 舒适度
    '9': 'ganmaoyaowu',        // 感冒
    '14': 'liangyifu',         // 晾晒
    '15': 'jiaotongdeng',      // 交通
    '16': 'fangshai',          // 防晒
  };
  if (map[t]) return map[t];
  // 兜底按 name 匹配
  const n = name || '';
  if (n.includes('运动')) return 'paobu';
  if (n.includes('洗车')) return 'xiche-cuxiantiao';
  if (n.includes('穿衣') || n.includes('衣服')) return 'tubiao-';
  if (n.includes('钓鱼')) return 'diaoyugan';
  if (n.includes('紫外线')) return 'ziwaixian';
  if (n.includes('旅游')) return 'lvyoufabu';
  if (n.includes('过敏')) return '-breathbreathinghealthrespiratory';
  if (n.includes('舒适')) return 'shushiduwendu';
  if (n.includes('感冒')) return 'ganmaoyaowu';
  if (n.includes('晾晒')) return 'liangyifu';
  if (n.includes('交通')) return 'jiaotongdeng';
  if (n.includes('防晒')) return 'fangshai';
  if (n.includes('化妆') || n.includes('口红')) return 'kouhong';
  if (n.includes('太阳镜')) return 'taiyangjing';
  if (n.includes('空调')) return 'kongdiao';
  return 'tianqi';  // 默认天气图标
}

// 每个数据点在 Canvas 中的水平间距（px）
const POINT_STEP = 68;

// ==================== 降雨提醒卡片（摘要 + 雨滴 + 降水强度折线图） ====================
function MinutelyRainCard({ data }: { data: { summary?: string; minutely: WeatherMinutelyItem[] } }) {
  const items = data.minutely || [];

  // 绘制降水强度折线图（Canvas 2D）
  const drawRainChart = useCallback((list: WeatherMinutelyItem[]) => {
    if (list.length < 2) return;

    // 获取 Canvas 实际尺寸
    const query = Taro.createSelectorQuery();
    query.select('#minutelyRainChart')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res?.[0]?.node) return;
        const canvas = res[0].node;
        const dpr = Taro.getSystemInfoSync().pixelRatio;
        const W = res[0].width;
        const H = res[0].height;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        const c = canvas.getContext('2d');
        c.scale(dpr, dpr);

        const padL = 4;   // 左边距（雨滴区右侧留空）
        const padR = 6;   // 右边距
        const padT = 8;   // 上边距
        const padB = 4;   // 下边距（时间轴上方）
        const cw = W - padL - padR;
        const ch = H - padT - padB;

        // 解析降水量
        const vals = list.map(m => Math.max(0, Number(m.precip) || 0));
        const maxV = Math.max(...vals, 0.5); // 至少 0.5 避免全零时折线贴底

        // 计算坐标点
        const stepX = cw / Math.max(list.length - 1, 1);
        const pts = vals.map((v, i) => ({
          x: padL + i * stepX,
          y: padT + ch - (v / maxV) * ch * 0.85, // 留顶部 15% 余量
        }));

        // 清空
        c.clearRect(0, 0, W, H);

        // ====== 三条淡灰水平参考线 ======
        c.strokeStyle = 'rgba(180,190,200,0.35)';
        c.lineWidth = 1;
        [0.25, 0.5, 0.75].forEach(ratio => {
          const ly = padT + ch * ratio;
          c.beginPath();
          c.moveTo(padL, ly);
          c.lineTo(padL + cw, ly);
          c.stroke();
        });

        // ====== 填充区域（浅蓝渐变）======
        c.beginPath();
        c.moveTo(pts[0].x, padT + ch);
        pts.forEach(p => c.lineTo(p.x, p.y));
        c.lineTo(pts[pts.length - 1].x, padT + ch);
        c.closePath();
        const fillGrad = c.createLinearGradient(0, padT, 0, padT + ch);
        fillGrad.addColorStop(0, 'rgba(96,165,250,0.35)');
        fillGrad.addColorStop(1, 'rgba(96,165,250,0.06)');
        c.fillStyle = fillGrad;
        c.fill();

        // ====== 折线（蓝色，2px 圆头）======
        c.beginPath();
        c.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) {
          c.lineTo(pts[i].x, pts[i].y);
        }
        c.strokeStyle = '#60a5fa';
        c.lineWidth = 2;
        c.lineCap = 'round';
        c.lineJoin = 'round';
        c.stroke();
      });
  }, []);

  // 数据就绪后绘制
  useEffect(() => {
    if (items.length >= 2) {
      // 延迟等 DOM 渲染完成
      const t = setTimeout(() => drawRainChart(items), 300);
      return () => clearTimeout(t);
    }
  }, [items, drawRainChart]);

  // 生成时间轴标签（取首/中/尾三个点）
  const timeLabels = useMemo(() => {
    if (items.length === 0) return ['现在', '', ''];
    const fmt = (fxTime?: string) => {
      if (!fxTime) return '';
      const d = new Date(fxTime.replace(' ', 'T').includes('+') ? fxTime : fxTime.replace(' ', 'T'));
      if (isNaN(d.getTime())) return '';
      const now = new Date();
      const diffMin = Math.round((d.getTime() - now.getTime()) / 60000);
      if (diffMin <= 5) return '现在';
      if (diffMin <= 65) return '一小时';
      if (diffMin <= 125) return '两小时';
      return `${Math.floor(diffMin / 60)}小时`;
    };
    const n = items.length;
    return [
      fmt(items[0]?.fx_time),
      n > 1 ? fmt(items[Math.floor(n / 2)]?.fx_time) : '',
      n > 2 ? fmt(items[n - 1]?.fx_time) : '',
    ];
  }, [items]);

  return (
    <View className="minutely-card-wrap">
      <View className="minutely-card">
        {/* 摘要文字 */}
        <Text className="minutely-summary">{data.summary || ''}</Text>

        {/* 图表区域：左侧雨滴 + 右侧折线 */}
        <View className="minutely-chart-area">
          {/* 雨滴图标列 */}
          <View className="minutely-raindrops">
            <Text className="raindrop raindrop-lg">💧</Text>
            <Text className="raindrop raindrop-md">💧</Text>
            <Text className="raindrop raindrop-sm">💧</Text>
          </View>

          {/* 降水强度折线图 */}
          <View className="minutely-line-wrap">
            <Canvas id="minutelyRainChart" type="2d" className="minutely-line-canvas" />
          </View>
        </View>

        {/* 时间轴标签 */}
        <View className="minutely-time-axis">
          {timeLabels.map((label, i) => (
            <Text key={i} className={`minutely-time-label ${i === 0 ? 'is-now' : ''}`}>
              {label}
            </Text>
          ))}
        </View>
      </View>
    </View>
  );
}


export default function WeatherPage() {
  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [loading, setLoading] = useState(true);
  const [weather, setWeather] = useState<WeatherNow | null>(null);
  const [hourly, setHourly] = useState<WeatherHourlyItem[]>([]);
  const [alerts, setAlerts] = useState<WeatherAlert[]>([]);
  const [daily, setDaily] = useState<WeatherDailyItem[]>([]);
  const [indices, setIndices] = useState<WeatherIndexItem[]>([]);
  const [air, setAir] = useState<WeatherAir | null>(null);
  const [minutely, setMinutely] = useState<{ summary?: string; minutely: WeatherMinutelyItem[] } | null>(null);
  const [error, setError] = useState(false);
  // 生活指数长按状态：记录当前长按的卡片 key（type 或 name），null 表示未长按
  const [pressedIndex, setPressedIndex] = useState<string | null>(null);
  // 页面背景渐变（以当前实时天气为准，固定不变，不随折线滑动切换）
  const [bgGradient, setBgGradient] = useState<{ from: string; via: string; to: string }>(() => getGradient(weather?.text));
  // 天气特效类型（以当前实时天气为准，固定不变）
  const [fxType, setFxType] = useState<FxType>('');
  // 背景图层就绪：数据到达后再淡入，避免进入页面时背景"硬切"
  const [bgReady, setBgReady] = useState(false);

  // 雨滴（随机参数，仅生成一次；必须放在所有条件 return 之前，遵守 Hooks 规则）
  const [raindrops] = useState(() =>
    Array.from({ length: 50 }, () => ({
      left: Math.random() * 100,
      delay: Math.random() * 1.5,
      dur: 0.5 + Math.random() * 0.8,
      len: 12 + Math.random() * 16,
      op: 0.12 + Math.random() * 0.22,
    })),
  );
  // 雾团（缓慢飘动）
  const [fogBanks] = useState(() =>
    Array.from({ length: 5 }, () => ({
      top: 12 + Math.random() * 60,
      left: Math.random() * 40,
      dur: 16 + Math.random() * 12,
      delay: Math.random() * 8,
      op: 0.10 + Math.random() * 0.14,
    })),
  );

  // Canvas 节点缓存（避免每次绘制都异步查询 SelectorQuery）
  const canvasRef = useRef<any>(null);
  const ctxRef = useRef<any>(null);
  const canvasWRef = useRef(0);   // Canvas 实际渲染宽度（px）
  const canvasHRef = useRef(0);

  // 横向平移状态（自接管触摸，不依赖 ScrollView 原生滚动）
  const offsetRef = useRef(0);     // 当前向左滚动的像素数（可为负：让"现在"右移）
  const minOffsetRef = useRef(0);  // 最小 offset（负数，允许"现在"移到屏幕中间区域）
  const maxOffsetRef = useRef(0);  // 最大可滚动像素
  const scrollRangeRef = useRef(0); // maxOffset - minOffset（高亮线性映射用）
  const activeIdxRef = useRef(0);  // 当前高亮的数据点（由滚动距离驱动）
  const touchStartX = useRef(0);
  const touchStartOffset = useRef(0);
  const lastTouchTimeRef = useRef(0);  // 最后触摸时间戳，用于判断是否进入实时自动模式
  const realtimeTempRef = useRef<number | null>(null);  // 实况温度（独立气泡源，与顶部数字一致）

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [curRes, hrRes, alRes, dailyRes, indRes, airRes, minRes] = await Promise.allSettled([
        weatherApi.getCurrent(),
        weatherApi.getHourly(),
        weatherApi.getAlerts(),
        weatherApi.getDaily(),
        weatherApi.getIndices(),
        weatherApi.getAir(),
        weatherApi.getMinutely(),
      ]);
      if (curRes.status === 'fulfilled') {
        const w = curRes.value.data.weather;
        setWeather(w);
        realtimeTempRef.current = w?.temp ?? null;  // 同步实况温度给独立气泡
        // 背景与特效以"当前实时天气"为准，固定不变（不随折线滑动切换，避免夜间滑动时背景忽闪刺眼）
        setBgGradient(getGradient(w?.text));
        setFxType(getFxType(w?.text));
        setBgReady(true);
      }
      if (hrRes.status === 'fulfilled') setHourly(reorderHourly(hrRes.value.data.hourly || []));
      if (alRes.status === 'fulfilled') setAlerts(alRes.value.data.warnings || []);
      if (dailyRes.status === 'fulfilled') setDaily(dailyRes.value.data.daily || []);
      if (indRes.status === 'fulfilled') setIndices(indRes.value.data.indices || []);
      if (airRes.status === 'fulfilled') setAir(airRes.value.data.air || null);
      if (minRes.status === 'fulfilled') setMinutely(minRes.value.data.minutely || null);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useLoad(() => {
    try {
      const info = getWindowInfo();
      if (info.statusBarHeight) setStatusBarHeight(info.statusBarHeight);
    } catch { /* 兜底 */ }
    loadAll();
  });

  usePullDownRefresh(async () => {
    await loadAll();
    stopPullDownRefresh();
  });

  // 计算某数据点（含 offset）的屏幕 x 坐标
  const pointX = (i: number) => {
    const W = canvasWRef.current;
    const padX = 4;   // 等宽布局，仅保留极小边距防止圆点/气泡贴边裁切
    return padX + i * POINT_STEP - offsetRef.current;
  };

  /**
   * 同步绘制（直接用缓存的 ctx，不异步查询）
   * 整个曲线 + 时间轴 + 图标 在同一坐标系下平移，对齐天然一致
   */
  const drawChart = useCallback((data: WeatherHourlyItem[]) => {
    const ctx = ctxRef.current;
    const W = canvasWRef.current;
    const H = canvasHRef.current;
    if (!ctx || !W || !H || data.length < 2) return;

    const padX = 4;   // 等宽布局，仅保留极小边距防止圆点/气泡贴边裁切
    const curveTop = 46;   // 顶部预留空间，容纳最高温标注 + 节点圆，避免溢出
    const curveBottom = H - 110;
    const timeY = curveBottom + 40;   // 天气图标+时间文字块与折线间距 40px（从 60 减回 20）
    const textY = timeY + 46;
    const nodeR = 14;       // 圆形节点半径（外层作用域，供高亮块与最高温标注共用）

    const temps = data.map((h) => Number(h.temp) || 0);
    const minT = Math.min(...temps);
    const maxT = Math.max(...temps);
    const range = maxT - minT || 1;

    // 高亮 = 线性映射 offset → [0, N-1]
    //   在 minOffset 时 idx=0（首点高亮），在 maxOffset 时 idx=N-1（尾点高亮）
    //   滑动全程均匀分配，不会跳跃，一定能到达首尾
    const totalRange = scrollRangeRef.current || 1;
    const t = (offsetRef.current - minOffsetRef.current) / totalRange;  // [0, 1]
    activeIdxRef.current = Math.min(data.length - 1, Math.max(0, Math.round(t * (data.length - 1))));
    const idx = activeIdxRef.current;

    // 所有点坐标（含 offset 平移）
    const pts = temps.map((t, i) => ({
      x: pointX(i),
      y: curveBottom - ((t - minT) / range) * (curveBottom - curveTop - 10),
      temp: t,
    }));

    ctx.clearRect(0, 0, W, H);

    // 只保留可见范围内的点用于绘制曲线/填充，避免左右越界
    const visPts = pts.filter((p) => p.x >= -60 && p.x <= W + 60);
    if (visPts.length >= 2) {
      // ====== 1. 渐变填充 ======
      const curvePts = getCurvePoints(visPts);
      ctx.beginPath();
      ctx.moveTo(curvePts[0].x, curveBottom);
      curvePts.forEach((p) => ctx.lineTo(p.x, p.y));
      ctx.lineTo(curvePts[curvePts.length - 1].x, curveBottom);
      ctx.closePath();
      const gradFill = ctx.createLinearGradient(0, curveTop, 0, curveBottom);
      gradFill.addColorStop(0, 'rgba(255,255,255,0.35)');
      gradFill.addColorStop(1, 'rgba(255,255,255,0.04)');
      ctx.fillStyle = gradFill;
      ctx.fill();

      // ====== 2. 平滑曲线（温度渐变色，逐段） ======
      const curveTemp: number[] = curvePts.map((_, k) => {
        const i = Math.floor(k / 2);
        if (k % 2 === 0) return visPts[i].temp;
        return (visPts[i].temp + visPts[Math.min(visPts.length - 1, i + 1)].temp) / 2;
      });
      for (let j = 0; j < curvePts.length - 1; j++) {
        const p1 = curvePts[j];
        const p2 = curvePts[j + 1];
        const grad = ctx.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
        grad.addColorStop(0, tempToColor(curveTemp[j]));
        grad.addColorStop(1, tempToColor(curveTemp[j + 1]));
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';
        ctx.stroke();
      }

      // ====== 3. 数据点小圆 ======
      visPts.forEach((p, vi) => {
        // 找到原始索引需要在 pts 里的位置，这里用坐标近似：跳过即可
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.fill();
      });
    }

    // ====== 4. 高亮点 + 圆形节点气泡 ======
    // 统一逻辑：高亮点永远贴在折线上（X/Y 均来自曲线插值）
    //   - 交互模式（触摸后 10s 内）：精确落在某个 hourly 整点上
    //   - 实时模式（闲置 >10s）：基于当前分钟数在相邻两点间插值，自动跟随时钟
    //   - 圆圈内数字："现在"附近优先显示实况温度（与顶部一致），其他点显示预报温度
    const isRealtimeMode = Date.now() - lastTouchTimeRef.current > 10000;

    // 「现在」锚点：距当前时刻最近的整点 hourly 索引。
    // 气泡高亮与时间轴"现在"标签共用同一索引，从根本上保证两者永远对齐，杜绝首开错位。
    const _nowForLabel = new Date();
    let _nowIdx = 0;
    let _nowMinDiff = Infinity;
    data.forEach((h, i) => {
      const ts = parseHourTs(h);
      const diff = Math.abs(ts - _nowForLabel.getTime());
      if (diff < _nowMinDiff) { _nowMinDiff = diff; _nowIdx = i; }
    });

    // 全局最高温点（用于最高温标注）
    let maxTempIdx = 0;
    let maxTempVal = temps[0] || 0;
    temps.forEach((t, i) => { if (t > maxTempVal) { maxTempVal = t; maxTempIdx = i; } });

    // 确定目标索引（整数）和子像素偏移
    let targetIdx = idx;       // 交互模式：来自滑动 offset（手指滑动查看其它点）
    let subPixelRatio = 0;     // 实时模式：气泡锚定"现在"整点（与时间轴标签一致），不插值

    if (isRealtimeMode) {
      // 实时模式：气泡直接落在"现在"整点（_nowIdx），与下方时间轴"现在"标签同一位置，
      // 不再按分钟在两点间插值，避免气泡与"现在"标签错开导致首开错位。
      targetIdx = _nowIdx;
      subPixelRatio = 0;
    }

    // 从曲线上取坐标（保证永远贴在折线上）
    const highlightX = pointX(targetIdx) + (isRealtimeMode ? (pointX(targetIdx + 1) - pointX(targetIdx)) * subPixelRatio : 0);
    const highlightY = isRealtimeMode
      ? pts[targetIdx].y + (pts[Math.min(targetIdx + 1, pts.length - 1)].y - pts[targetIdx].y) * subPixelRatio
      : (pts[targetIdx]?.y ?? curveBottom);

    // 圆圈内温度：
    //   - 实时模式（即显示"现在"）：取实况温度（独立来源，与顶部数字一致），不随曲线插值漂移
    //   - 交互模式（手指触摸某点）：取该点曲线预报温度
    const curveTemp = isRealtimeMode
      ? temps[targetIdx] + (temps[Math.min(targetIdx + 1, temps.length - 1)] - temps[targetIdx]) * subPixelRatio
      : (pts[targetIdx]?.temp ?? 0);
    const realtimeTemp = realtimeTempRef.current;
    const highlightTemp = (isRealtimeMode && realtimeTemp != null) ? realtimeTemp : curveTemp;

    if (highlightX >= -40 && highlightX <= W + 40) {
      // 垂直虚线（节点底 → 时间轴）
      ctx.beginPath();
      ctx.setLineDash([3, 3]);
      ctx.moveTo(highlightX, highlightY + 14);
      ctx.lineTo(highlightX, textY + 16);
      ctx.strokeStyle = 'rgba(255,255,255,0.2)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.setLineDash([]);

      // 圆形节点：白底 + 温度色粗边框
      const borderW = 2.5;
      ctx.beginPath();
      ctx.arc(highlightX, highlightY, nodeR, 0, Math.PI * 2);
      ctx.fillStyle = '#fff';
      ctx.fill();
      ctx.strokeStyle = tempToColor(highlightTemp);
      ctx.lineWidth = borderW;
      ctx.stroke();

      // 节点内数字（黑色粗体，不带°）
      const nodeTxt = `${Math.round(highlightTemp)}`;
      ctx.fillStyle = '#222';
      ctx.font = '600 13px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(nodeTxt, highlightX, highlightY);
    }

    // ====== 最高温标注（温度色 + 粗体，不与当前节点重叠时绘制）======
    {
      const mp = pts[maxTempIdx];
      if (mp && mp.x >= -40 && mp.x <= W + 40 && maxTempIdx !== idx) {
        const lab = `${Math.round(maxTempVal)}`;
        ctx.fillStyle = tempToColor(maxTempVal);   // 温度色
        ctx.font = '700 14px sans-serif';           // 粗体
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        // 始终画在点上方；canvas 顶部已预留 curveTop 空间，正常不会再溢出
        const ly = Math.max(14, mp.y - 22);
        ctx.fillText(lab, mp.x, ly);
      }
    }

    // ====== 5. 时间轴（图标 + 时间文字，随曲线一起平移） ======
    ctx.textAlign = 'center';
    // 「现在」锚点 _nowIdx 已在上方统一计算（气泡与时间轴标签共用），此处直接复用，避免分歧
    data.forEach((h, i) => {
      const px = pointX(i);
      if (px < -40 || px > W + 40) return;   // 不可见跳过
      const isNow = i === _nowIdx;   // 唯一匹配：距当前时间最近的点
      const isActive = i === idx;

      // 天气图标 emoji
      ctx.fillStyle = '#fff';
      ctx.font = isActive ? `600 ${40}px sans-serif` : `500 ${36}px sans-serif`;
      ctx.textBaseline = 'top';
      ctx.fillText(getWeatherIconEmoji(h.text), px, timeY);

      // 时间文字
      const t = h.fxTime || h.fx_time || '';
      const hour = t.includes(' ') ? t.split(' ')[1].slice(0, 5) : t.slice(11, 16);
      const label = isNow ? '现在' : hour;
      ctx.fillStyle = isNow ? '#fff' : isActive ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.5)';
      ctx.font = (isNow || isActive) ? '600 12px sans-serif' : '400 11px sans-serif';
      ctx.textBaseline = 'top';
      ctx.fillText(label, px, textY);

      // ====== 降水概率角标（仅 >=60% 时显示在图标右上角，白字无描边）======
      const popVal = Number(h.pop);
      if (!isNaN(popVal) && popVal >= 60) {
        const bText = `${Math.round(popVal)}%`;
        ctx.font = '700 10px sans-serif';
        const bW = ctx.measureText(bText).width;
        // 紧贴图标右上角：图标字号~36px，右边缘≈px+22；角标定位在图标右上方
        const bx = px + 20;
        const by = timeY - 4;
        if (bx > -bW && bx < W) {
          ctx.textAlign = 'left';
          ctx.textBaseline = 'bottom';
          ctx.fillStyle = '#fff';
          ctx.fillText(bText, bx, by);
        }
      }
    });
  }, []);

  // 首次获取 Canvas 节点并初始化
  const initCanvas = useCallback((data: WeatherHourlyItem[]) => {
    if (data.length < 2) return;
    const query = Taro.createSelectorQuery();
    query.select('#tempChart')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res?.[0]?.node) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const dpr = Taro.getSystemInfoSync().pixelRatio;
        const W = res[0].width;
        const H = res[0].height;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        ctx.scale(dpr, dpr);
        canvasRef.current = canvas;
        ctxRef.current = ctx;
        canvasWRef.current = W;
        canvasHRef.current = H;
        const padX = 4;
        const N = data.length;          // 24 个点
        // 坐标系：pointX(i) = padX + i*STEP - offset
        //   offset 越大 → pointX 越小（内容左移，看后面的点）
        //   offset 越小 → pointX 越大（内容右移，看前面的点）
        //
        // 边界设计：
        //   minOffset：第一个点(i=0)在屏幕 x=24 处（安全避开左裁切），几乎不能往右滑
        //   maxOffset：最后一个点(i=N-1)在屏幕 x=W-24 处（紧贴右边缘）
        //   初始 offset：第一个点在屏幕 x=28 处（清晰展示"现在"）
        const firstPointSafe = 24;     // 首点安全左边界（px，留出圆点半径+气泡余量）
        const lastPointSafe = W - 24;   // 尾点安全右边界（px，紧贴右边缘）
        const initPointX = 28;          // 首点初始位置

        minOffsetRef.current = padX - firstPointSafe;           // ≈ -20：首点不能往右滑
        maxOffsetRef.current = padX + (N - 1) * POINT_STEP - lastPointSafe;  // 尾点贴右边

        // 根据当前实际时钟定位到最近的小时点（而非固定 i=0）
        const now = new Date();
        const currentHour = now.getHours();
        const currentMin = now.getMinutes();
        let nowIdx = 0;
        let minDiff = Infinity;
        data.forEach((h, i) => {
          const t = h.fxTime || h.fx_time || '';
          // 解析时间 "2026-08-29T20:00+08:00" 或 "2026-08-29 20:00"
          const hStr = t.includes(' ') ? t.split(' ')[1].slice(0, 2) : t.slice(11, 13);
          const hNum = parseInt(hStr, 10);
          if (!isNaN(hNum)) {
            let diff = Math.abs(hNum - currentHour);
            if (diff > 12) diff = 24 - diff;   // 跨午夜处理
            if (currentMin >= 30 && hNum === ((currentHour + 1) % 24)) diff -= 0.5;
            if (diff < minDiff) { minDiff = diff; nowIdx = i; }
          }
        });
        activeIdxRef.current = nowIdx;

        // 初始 offset：基于当前时间**分钟数**插值定位（非整点 nowIdx）
        // 让"当前时刻"落在屏幕左侧约 1/3 处
        const _initNow = new Date();
        const _initNowTs = _initNow.getTime();
        let _leftI = -1, _rightI = -1;
        for (let i = 0; i < data.length; i++) {
          const ts = parseHourTs(data[i]);
          if (ts <= _initNowTs) _leftI = i;
          if (ts > _initNowTs && _rightI === -1) _rightI = i;
        }
        if (_leftI === -1) _leftI = 0;
        if (_rightI === -1) { _rightI = data.length - 1; _leftI = Math.max(0, _rightI - 1); }

        const _lTs = parseHourTs(data[_leftI]), _rTs = parseHourTs(data[_rightI]);
        const _tsSpan = _rTs - _lTs || 3600000;
        const _ratio = Math.min(1, Math.max(0, (_initNowTs - _lTs) / _tsSpan));
        // 插值后的"虚拟索引"（含小数）
        const floatIdx = _leftI + (_rightI - _leftI) * _ratio;

        const nowInitX = Math.min(120, W * 0.35);
        let initOffset = padX + floatIdx * POINT_STEP - nowInitX;
        // 若初始 offset 会导致首点被推出太远（>300px off-screen），则回拉
        const firstVisibleX = padX - initOffset;
        if (firstVisibleX < -300) {
          const safeIdx = Math.max(0, floatIdx - 4);
          initOffset = padX + safeIdx * POINT_STEP - nowInitX;
        }
        offsetRef.current = Math.max(minOffsetRef.current, Math.min(maxOffsetRef.current, initOffset));

        // 预计算高亮映射范围（线性映射：offset → [0, N-1]）
        scrollRangeRef.current = maxOffsetRef.current - minOffsetRef.current;
        drawChart(data);
      });
  }, [drawChart]);

  // 数据就绪后多次延迟初始化 Canvas
  useEffect(() => {
    if (!loading && hourly.length >= 2) {
      const timers = [200, 500, 1000].map(
        (delay) => setTimeout(() => initCanvas(hourly), delay),
      );
      return () => timers.forEach(clearTimeout);
    }
  }, [loading, hourly, initCanvas]);

  // 定时刷新折线图（每 60 秒），让"当前时间指示器"跟随时钟移动
  useEffect(() => {
    if (loading || hourly.length < 2) return;
    const timer = setInterval(() => {
      if (ctxRef.current) drawChart(hourly);
    }, 30000); // 每 30 秒重绘，让实时指示器跟随时钟移动
    return () => clearInterval(timer);
  }, [loading, hourly, drawChart]);

  // 触摸：横向平移
  const onTouchStart = (e: any) => {
    if (!e.touches || !e.touches[0]) return;
    touchStartX.current = e.touches[0].clientX;
    touchStartOffset.current = offsetRef.current;
    lastTouchTimeRef.current = Date.now();
  };

  const onTouchMove = (e: any) => {
    if (hourly.length < 2 || !e.touches || !e.touches[0]) return;
    lastTouchTimeRef.current = Date.now();
    const cur = e.touches[0].clientX;
    const delta = touchStartX.current - cur;   // 左滑为正
    const next = Math.min(
      maxOffsetRef.current,
      Math.max(minOffsetRef.current, touchStartOffset.current + delta),
    );
    offsetRef.current = next;
    drawChart(hourly);
  };

  const onTouchEnd = () => {
    // 只 clamp 到边界，不吸附到居中（用户要求：尾点滑入屏幕即可）
    offsetRef.current = Math.min(maxOffsetRef.current, Math.max(minOffsetRef.current, offsetRef.current));
    drawChart(hourly);
  };

  // 点击某个点 → 让该点居中
  const onTap = (e: any) => {
    if (hourly.length < 2) return;
    lastTouchTimeRef.current = Date.now();
    const tapX = e.detail?.x;
    if (tapX == null) return;
    const W = canvasWRef.current;
    const padX = 4;   // 等宽布局，仅保留极小边距防止圆点/气泡贴边裁切
    // 反算点击位置对应的数据点
    const i = Math.round((tapX + offsetRef.current - padX) / POINT_STEP);
    const ci = Math.min(hourly.length - 1, Math.max(0, i));
    // 让该点居中：offset = i*STEP + padX - W/2
    const target = Math.min(
      maxOffsetRef.current,
      Math.max(minOffsetRef.current, ci * POINT_STEP + padX - W / 2),
    );
    offsetRef.current = target;
    drawChart(hourly);
  };

  if (loading) {
    return (
      <View className="weather-page" style={{ paddingTop: `${statusBarHeight}px` }}>
        <LoadingState text="正在获取天气…" />
      </View>
    );
  }

  if (!weather || error) {
    return (
      <View className="weather-page" style={{ paddingTop: `${statusBarHeight}px` }}>
        <EmptyState title="暂无天气数据" desc="下拉重试或稍后再来" />
      </View>
    );
  }

  const temps = hourly.map((h) => Number(h.temp) || 0);
  const minTemp = temps.length > 0 ? Math.min(...temps) : null;
  const maxTemp = temps.length > 0 ? Math.max(...temps) : null;

  // 背景渐变：跟随当前高亮小时的天气实时切换（bgGradient 为 state）
  const gradient = bgGradient;

  return (
    <View className="weather-screen">
      {/* 背景渐变图层：数据就绪后淡入，避免"硬切" */}
      <View
        className="weather-bg"
        style={{
          opacity: bgReady ? 1 : 0,
          background: `linear-gradient(180deg, ${gradient.from} 0%, ${gradient.via} 32%, #6f8499 100%)`,
        }}
      />
      {/* 天气特效层：固定覆盖全屏，不随滚动，不拦截交互 */}
      {fxType === 'sunny' && (
        <View className="weather-fx weather-fx--sunny">
          <View className="fx-sun-glow" />
          <View className="fx-sun-rays" />
        </View>
      )}
      {fxType === 'rainy' && (
        <View className="weather-fx weather-fx--rainy">
          {raindrops.map((d, i) => (
            <View
              key={i}
              className="fx-raindrop"
              style={{
                left: `${d.left}%`,
                animationDelay: `${d.delay}s`,
                animationDuration: `${d.dur}s`,
                height: `${d.len}rpx`,
                opacity: d.op,
              }}
            />
          ))}
        </View>
      )}
      {fxType === 'foggy' && (
        <View className="weather-fx weather-fx--foggy">
          {fogBanks.map((f, i) => (
            <View
              key={i}
              className="fx-fog"
              style={{
                top: `${f.top}%`,
                left: `${f.left}%`,
                animationDelay: `${f.delay}s`,
                animationDuration: `${f.dur}s`,
                opacity: f.op,
              }}
            />
          ))}
        </View>
      )}

      <ScrollView
        scrollY
        className="weather-page"
        style={{
          paddingTop: `${statusBarHeight}px`,
        }}
        enhanced
        showScrollbar={false}
      >
      {/* ====== 顶部栏（返回 + 城市名居中） ====== */}
      <View className="weather-top-bar">
        <View className="weather-back-btn" onClick={() => Taro.navigateBack()}>
          <Text className="iconfont icon-fanhui" />
        </View>
        <Text className="weather-city">{weather.city_name || '永川区'}</Text>
      </View>
      {/* 分割线（不连左右边缘） */}
      <View className="weather-top-divider" />

      {/* ====== 温度区 ====== */}
      <View className="weather-hero">
        {/* PM2.5 / UV 胶囊标签（绝对定位，左对齐贴边） */}
        <View className="weather-temp-badges">
          {air && air.pm2p5 != null && (
            <View className="weather-badge">
              <View className="weather-badge-left">
                <Text className="weather-badge-abbr">PM</Text>
                <View className="weather-badge-line" style={{ background: aqiToColor(Number(air.pm2p5) * 4) }} />
                <Text className="weather-badge-sub">2.5</Text>
              </View>
              <Text className="weather-badge-val">{Math.round(Number(air.pm2p5))}</Text>
            </View>
          )}
          {indices.length > 0 && (() => {
            const uv = indices.find(i => i.type === '5');
            return uv ? (
              <View className="weather-badge">
                <View className="weather-badge-left">
                  <Text className="weather-badge-abbr">UV</Text>
                  <View className="weather-badge-line" style={{ background: uv.category?.includes('强') ? '#f56c6c' : uv.category?.includes('中') ? '#e6a23c' : '#67c23a' }} />
                </View>
                <Text className="weather-badge-val">{uv.category || '-'}</Text>
              </View>
            ) : null;
          })()}
        </View>

        {/* 第一行：大数字 + °C + 体感 */}
        <View className="weather-temp-main">
          <Text className="weather-temp-num">{Math.round(weather.temp ?? 0)}</Text>
          <Text className="weather-temp-unit">°C</Text>
          {weather.feels_like != null && (
            <View className="weather-feels-row">
              <Text className="weather-feels-label">体感</Text>
              <Text className="weather-feels-value">{Math.round(weather.feels_like)}°C</Text>
            </View>
          )}
        </View>
        {/* 第二行：天气文字 + 温度区间 */}
        <View className="weather-desc-row">
          <Text className="weather-desc">{weather.text || '未知'}</Text>
          {minTemp != null && maxTemp != null && (
            <Text className="weather-temp-range">
              {Math.round(minTemp)} ~ {Math.round(maxTemp)}°C
            </Text>
          )}
        </View>
      </View>

      {/* ====== 降雨提醒卡片（有雨时显示，含摘要+雨滴+降水强度折线图+时间轴） ====== */}
      {minutely && minutely.summary && !/无降|无雨|没有降雨|不会下|暂无降水|无降水/.test(minutely.summary) && (
        <MinutelyRainCard data={minutely} />
      )}

      {/* ====== 24小时折线图（自接管触摸平移，曲线+时间轴同步移动） ====== */}
      {hourly.length > 0 && (
        <View className="weather-section" style={{ paddingLeft: 0, paddingRight: 0 }}>
          <View className="chart-container">
            <Canvas
              id="tempChart"
              type="2d"
              className="weather-chart-canvas"
              onTouchStart={onTouchStart}
              onTouchMove={onTouchMove}
              onTouchEnd={onTouchEnd}
              onTap={onTap}
            />
          </View>
        </View>
      )}

      {/* ====== 未来 7 天 ====== */}
      <View className="weather-section">
        <Text className="weather-section-title">未来 7 天</Text>
        {daily.length > 0 ? (
          <ScrollView scrollX className="daily-scroll" showScrollbar={false}>
            {daily.map((d, i) => (
              <View className="daily-card" key={d.fx_date || i}>
                <Text className="daily-week">{getWeekdayLabel(d.fx_date, i)}</Text>
                <Text className="daily-date">{d.fx_date ? d.fx_date.slice(5) : ''}</Text>
                <View className="daily-icon-wrap">
                  <Text className="daily-icon">{getWeatherIconEmoji(d.text_day)}</Text>
                  {d.pop != null && Number(d.pop) >= 60 && (
                    <View className="daily-pop-badge">{Math.round(Number(d.pop))}%</View>
                  )}
                </View>
                <Text className="daily-temp-max">{Math.round(Number(d.temp_max) || 0)}°</Text>
                <Text className="daily-temp-min">{Math.round(Number(d.temp_min) || 0)}°</Text>
                <Text className="daily-text">{d.text_day || ''}</Text>
              </View>
            ))}
          </ScrollView>
        ) : (
          <Text className="weather-placeholder">暂无数据</Text>
        )}
      </View>

      {/* ====== 信息卡（透明底，核心4项横排+次要底行） ====== */}
      <View className="weather-info-card">
        {/* 核心行：湿度 / 风向 / 风力 / 体感 */}
        <View className="weather-info-row">
          <View className="weather-info-item">
            <Text className="iconfont info-icon icon-wenshiduchuanganqi_o" />
            <Text className="weather-info-label">湿度</Text>
            <Text className="weather-info-value">{weather.humidity != null ? `${weather.humidity}%` : '-'}</Text>
          </View>
          <View className="weather-info-item">
            <Text className="iconfont info-icon icon-fengxiang" />
            <Text className="weather-info-label">风向</Text>
            <Text className="weather-info-value">{weather.wind_dir || '-'}</Text>
          </View>
          <View className="weather-info-item">
            <Text className="iconfont info-icon icon-fengli" />
            <Text className="weather-info-label">风力</Text>
            <Text className="weather-info-value">{weather.wind_scale || '-'}</Text>
          </View>
          {weather.feels_like != null && (
            <View className="weather-info-item">
              <Text className="iconfont info-icon icon-tiganwendu" />
              <Text className="weather-info-label">体感</Text>
              <Text className="weather-info-value">{Math.round(weather.feels_like)}°C</Text>
            </View>
          )}
        </View>
        {/* 次要行：能见度 / 气压 */}
        <View className="weather-info-row weather-info-sub-row">
          {weather.vis != null && (
            <View className="weather-info-item">
              <Text className="iconfont info-icon icon-nengjiandu" />
              <Text className="weather-info-label">能见度</Text>
              <Text className="weather-info-value">{weather.vis}km</Text>
            </View>
          )}
          {weather.pressure != null && (
            <View className="weather-info-item">
              <Text className="iconfont info-icon icon-qiya" />
              <Text className="weather-info-label">气压</Text>
              <Text className="weather-info-value">{weather.pressure}hPa</Text>
            </View>
          )}
        </View>
      </View>

      {/* 天气预警（紧凑横条模式） */}
      {alerts.length > 0 && (
        <View className="weather-section">
          <Text className="weather-section-title">天气预警</Text>
          {alerts.map((a) => (
            <View className={`weather-alert-bar severity-bar-${a.severity?.toLowerCase() || 'unknown'}`} key={a.alert_id}>
              <View className="alert-bar-color" />
              <View className="alert-bar-body">
                <Text className="alert-bar-headline">{a.headline}</Text>
                <Text className={`alert-bar-tag tag-${a.severity?.toLowerCase() || 'unknown'}`}>
                  {a.severity || '预警'}
                </Text>
              </View>
              {a.description && <Text className="alert-bar-desc">{a.description}</Text>}
            </View>
          ))}
        </View>
      )}

      {/* 空气质量 AQI（生活指数之上） */}
      <View className="weather-section">
        {air ? (
          <View className="weather-air-card">
            {/* 第一行：AQI 数字 + 等级 */}
            <View className="air-header">
              <View className="air-aqi-block">
                <Text className="air-aqi-num" style={{ color: aqiToColor(air.aqi) }}>
                  {air.aqi != null ? Math.round(Number(air.aqi)) : '-'}
                </Text>
                <Text className="air-aqi-level" style={{ color: aqiToColor(air.aqi) }}>
                  {air.category || '未知'}
                </Text>
              </View>
            </View>
            {/* 色条（优→严重） */}
            <View className="air-bar-wrap">
              <View className="air-bar-track">
                <View className="air-bar-fill" />
              </View>
              {/* 当前值指示线 */}
              <View
                className="air-bar-marker"
                style={{ left: `${Math.min(Math.max((Number(air.aqi) || 0) / 300 * 100, 0), 100)}%` }}
              />
            </View>
            <View className="air-bar-labels">
              <Text className="air-bar-label">优</Text>
              <Text className="air-bar-label">严重</Text>
            </View>
            {/* 污染物指标 */}
            <View className="air-pollutants">
              {[
                { label: 'PM2.5', value: air.pm2p5 },
                { label: 'PM10', value: air.pm10 },
                { label: 'CO', value: (air as Record<string, unknown>).co },
                { label: 'SO2', value: (air as Record<string, unknown>).so2 },
              ].map((p) => (
                <View className="air-pollutant-item" key={p.label}>
                  <Text className="air-pollutant-label">{p.label}</Text>
                  <Text className="air-pollutant-value">{p.value != null ? Math.round(Number(p.value)) : '-'}</Text>
                  <View className="air-pollutant-dot" style={{ background: p.value != null ? aqiToColor(Number(p.value) * 4) : 'rgba(255,255,255,0.2)' }} />
                </View>
              ))}
            </View>
          </View>
        ) : (
          <Text className="weather-placeholder">暂无数据</Text>
        )}
      </View>

      {/* 生活指数 */}
      <View className="weather-section">
        <Text className="weather-section-title">生活指数</Text>
        {indices.length > 0 ? (
          <View className="indices-grid">
            {indices.map((it) => {
              const isPressed = pressedIndex === (it.type || it.name);
              return (
              <View
                className="index-card"
                key={it.type || it.name}
                onLongPress={() => setPressedIndex(it.type || it.name || null)}
                onTouchEnd={() => setPressedIndex(null)}
              >
                {isPressed ? (
                  // 长按时：图标/名字/值全部隐藏，仅显示描述
                  <Text className="index-text index-text--full">{it.text || it.category || ''}</Text>
                ) : (
                  // 默认：图标 + 名字 + 值（等级）
                  <>
                    <Text className={`iconfont index-icon icon-${getIndexIconClass(it.type, it.name)}`} />
                    <Text className="index-name">{it.name || ''}</Text>
                    <Text className="index-category">{it.category || ''}</Text>
                  </>
                )}
              </View>
              );
            })}
          </View>
        ) : (
          <Text className="weather-placeholder">暂无数据</Text>
        )}
      </View>

      <View style={{ height: '60rpx' }} />

      {/* 数据来源标注 */}
      <View className="weather-source">
        <Text className="weather-source-text">数据由和风天气提供</Text>
      </View>

      <View style={{ height: '40rpx' }} />
    </ScrollView>
    </View>
  );
}
