import { useMemo, useState, useRef, useEffect, useCallback } from 'react';
import { View, Text, ScrollView, Canvas } from '@tarojs/components';
import { useLoad, usePullDownRefresh, stopPullDownRefresh, getWindowInfo } from '@tarojs/taro';
import Taro from '@tarojs/taro';
import dayjs from 'dayjs';

import * as electricityApi from '@/api/electricity';
import type { ElectricityCurrent, ElectricityRecord, ElectricityTrendPoint } from '@/types/api';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

/**
 * 宿舍电量详情页
 *
 * 布局（按原型图）：
 *   - Hero 白底卡片：左侧电表名+大数字+状态 / 右侧细线圆环
 *   - 统计行：总容量 | 剩余百分比
 *   - 更新时间
 *   - 趋势图：Canvas 2D 折线图
 *   - 用电记录列表
 */

// 清洗电表名："31栋512照明" → "31栋512"（用于统计等辅助展示）
interface DayTrend {
  label: string;
  date: string;
  usage: number;
}

type TrendTab = 'day' | 'week' | 'month';

// 圆角矩形路径（兼容微信小程序 Canvas 2D，ctx.roundRect 在部分基础库版本缺失）
function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export default function ElectricityPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [current, setCurrent] = useState<ElectricityCurrent | null>(null);
  // 是否已配置电表 Cookie（false = 未配置，需引导去设置；null = 接口未返回/未知）
  const [cookieConfigured, setCookieConfigured] = useState<boolean | null>(null);
  const [records, setRecords] = useState<ElectricityRecord[]>([]);
  const [trendTab, setTrendTab] = useState<TrendTab>('week');

  // 用电记录按需分页：首屏拉一页，点「查看更多记录」再向后端请求下一页追加
  const RECORD_PAGE = 20;
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [trendData, setTrendData] = useState<ElectricityTrendPoint[]>([]);
  // 本月已用度数：从首屏拉到的用电记录里按本月累加
  const [monthUsed, setMonthUsed] = useState<number | null>(null);

  // 折线图点击高亮
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const activeIdxRef = useRef<number | null>(null);
  const chartRef = useRef<{
    ctx: CanvasRenderingContext2D;
    W: number;
    H: number;
    pad: { top: number; right: number; bottom: number; left: number };
    cW: number;
    cH: number;
    stepX: number;
    pts: { x: number; y: number }[];
    maxVal: number;
  } | null>(null);

  const loadAll = async () => {
    setLoading(true);
    setError(false);
    try {
      const [cRes, hRes, tRes, mRes] = await Promise.all([
        electricityApi.getCurrent().catch(() => null),
        electricityApi.getHistory(RECORD_PAGE, 0).catch(() => null),
        electricityApi.getTrend(trendTab).catch(() => null),
        // 本月已用：改由后端按自然月聚合返回。
        // 此前只把首屏 20 条记录里属于本月的 usage 相加，导致详情页 74.04、
        // 我的页 162.93 两个口径（我的页拉 1000 条），统一走后端后一致
        electricityApi.getMonthlyUsage().catch(() => null),
      ]);
      setCookieConfigured(cRes?.data?.cookie_configured ?? null);
      setCurrent(cRes?.data?.electricity ?? null);
      // 更新时间统一显示"访问这一刻"（本次请求已确认数据），覆盖后端爬取时间戳
      if (cRes?.data?.electricity) {
        setCurrent({ ...cRes.data.electricity, recorded_at: dayjs().format('YYYY-MM-DD HH:mm:ss') });
      } else {
        setCurrent(null);
      }
      const recs = hRes?.data?.records ?? [];
      setRecords(recs);
      setTotal(hRes?.data?.total ?? recs.length);
      setTrendData(tRes?.data?.points ?? []);
      // 后端懒采集：该学生首次进入（无任何记录）且已配置 Cookie 时已自动触发全量爬取，
      // 本次仍返回空数据，提示稍后下拉刷新查看
      if (hRes?.data?.fetch_triggered) {
        Taro.showToast({ title: '正在首次采集电量数据，请稍后下拉刷新查看', icon: 'none', duration: 2500 });
      }
      // 本月已用：直接用后端聚合结果（month_used），不再用首屏记录本地累加
      setMonthUsed(mRes?.data?.month_used ?? 0);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  // 加载更多记录：向后端请求下一页并追加
  const loadMore = async () => {
    if (loadingMore) return;
    if (records.length >= total) return;
    setLoadingMore(true);
    try {
      const hRes = await electricityApi.getHistory(RECORD_PAGE, records.length).catch(() => null);
      const more = hRes?.data?.records ?? [];
      if (more.length > 0) {
        setRecords((prev) => [...prev, ...more]);
        setTotal(hRes?.data?.total ?? records.length + more.length);
      } else {
        // 没有更多了，以已加载数量为准
        setTotal(records.length);
      }
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      setLoadingMore(false);
    }
  };

  // 切换趋势区间：仅重新拉取趋势点（轻量）
  const changeTrendTab = (tab: TrendTab) => {
    setTrendTab(tab);
    electricityApi.getTrend(tab).then((tRes) => {
      setTrendData(tRes?.data?.points ?? []);
    }).catch(() => { /* 保留旧数据 */ });
  };

  useLoad(() => {
    try {
      const info = getWindowInfo();
      if (info.statusBarHeight) setStatusBarHeight(info.statusBarHeight);
    } catch { /* 兜底 */ }
    loadAll();
    // 打开电量页即触发一次轻量刷新（后端 60s 冷却），完成后更新最新值；
    // 更新时间显示"访问这一刻"的时间（本次请求确认了数据真实性），而非后端爬取时间戳
    electricityApi.refresh().then((r) => {
      // 刷新返回的 cookie_configured 与 current 一致，一并同步（未配置时为 false）
      if (r?.data?.cookie_configured != null) {
        setCookieConfigured(r.data.cookie_configured);
      }
      if (r?.data?.electricity) {
        const e = r.data.electricity;
        // 用客户端当前时间覆盖 recorded_at，作为"更新时间"
        setCurrent({ ...e, recorded_at: dayjs().format('YYYY-MM-DD HH:mm:ss') });
      }
    }).catch(() => { /* 刷新失败保留缓存 */ });
  });

  usePullDownRefresh(async () => {
    await loadAll();
    stopPullDownRefresh();
  });

  // 电表名：清洗展示（去掉"电表:"前缀 + "照明"后缀，统一为"31栋512"格式）
  // 优先用 current.meter；若其为占位值 "default" 或空，则从历史用电记录里解析真实楼栋
  const resolveMeter = (): string => {
    const raw = (() => {
      if (current?.meter && current.meter.trim() !== 'default') return current.meter.trim();
      const fromHistory = records.find((r) => r.meter && r.meter.trim() !== 'default');
      return fromHistory?.meter ? fromHistory.meter.trim() : '';
    })();
    return raw.replace(/^电表[:：]\s*/, '').replace(/照明$/, '').trim();
  };
  const roomText = resolveMeter() || '楼栋未配置';

  const updateTime = current?.recorded_at || '';

  // 总容量兜底计算
  const totalCapacity = current?.total_capacity != null
    ? current.total_capacity
    : (current?.remaining && current?.percentage ? (current.remaining / current.percentage) * 100 : null);

  // 百分比钳制 0-100
  const pct = current ? Math.max(0, Math.min(100, current.percentage || 0)) : 0;

  // 趋势数据：直接来自后端 /electricity/trend 的日聚合点（已按所选区间返回）
  const trend = useMemo<DayTrend[]>(() => {
    const showToday = trendTab !== 'week'; // day/month 末点标「今天」，week 标 MM/DD
    return trendData.map((p, i) => {
      const isLast = i === trendData.length - 1;
      return {
        date: p.date,
        label: isLast && showToday ? '今天' : dayjs(p.date).format('M/D'),
        usage: p.usage,
      };
    });
  }, [trendData, trendTab]);

  // 折线图绘制（highlight 为点击高亮的点索引，绘制电量气泡 tooltip）
  const drawChart = useCallback((highlight: number | null) => {
    const c = chartRef.current;
    if (!c) return;
    const { ctx, W, H, pad, cW, cH, stepX, pts, maxVal } = c;
    ctx.clearRect(0, 0, W, H);

    // Y 轴刻度 + 网格
    ctx.fillStyle = '#999';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const ySteps = 4;
    for (let i = 0; i <= ySteps; i++) {
      const v = (maxVal / ySteps) * i;
      const y = pad.top + cH - (i / ySteps) * cH;
      ctx.fillText(v.toFixed(1), pad.left - 6, y);
      ctx.strokeStyle = '#f0f0f0';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + cW, y);
      ctx.stroke();
    }

    // X 轴标签（月隔 5 日标一个，日/周全标；折线/数据点始终全部绘制）
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const labelStep = trendTab === 'month' ? 5 : 1;
    trend.forEach((d, idx) => {
      if (idx % labelStep !== 0 && idx !== trend.length - 1) return; // 末点(今天)始终标
      const x = pad.left + idx * stepX;
      ctx.fillStyle = '#999';
      ctx.font = '9px sans-serif';
      ctx.fillText(d.label, x, pad.bottom + cH + 8);
    });

    // 渐变填充区域
    const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + cH);
    gradient.addColorStop(0, 'rgba(26,115,232,0.15)');
    gradient.addColorStop(1, 'rgba(26,115,232,0)');
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pad.top + cH);
    pts.forEach((p) => ctx.lineTo(p.x, p.y));
    ctx.lineTo(pts[pts.length - 1].x, pad.top + cH);
    ctx.closePath();
    ctx.fill();

    // 折线
    ctx.strokeStyle = '#1a73e8';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    pts.forEach((p, i) => { i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y); });
    ctx.stroke();

    // 数据点（白底蓝边圆圈）
    pts.forEach((p) => {
      ctx.fillStyle = '#fff';
      ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#1a73e8';
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2); ctx.stroke();
    });

    // 点击高亮点 + 电量气泡
    if (highlight != null && pts[highlight]) {
      const p = pts[highlight];
      const d = trend[highlight];

      // 强调圆点（实心蓝 + 白边）
      ctx.fillStyle = '#1a73e8';
      ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, Math.PI * 2); ctx.stroke();

      // 气泡
      const text1 = d.label;
      const text2 = `${d.usage.toFixed(2)} 度`;
      const bw = 72;
      const bh = 36;
      let bx = p.x - bw / 2;
      let by = p.y - bh - 12;
      bx = Math.max(pad.left, Math.min(bx, W - pad.right - bw));
      if (by < pad.top) by = p.y + 12; // 点太靠顶则气泡画在下方

      ctx.fillStyle = '#1a73e8';
      roundRect(ctx, bx, by, bw, bh, 6);
      ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text1, bx + bw / 2, by + bh / 2 - 8);
      ctx.fillText(text2, bx + bw / 2, by + bh / 2 + 8);
    }
  }, [trend, trendTab]);

  // Canvas 绘制折线图（useEffect + 延迟查询确保节点就绪）
  useEffect(() => {
    if (trend.every((x) => x.usage === 0)) return;
    const timer = setTimeout(() => {
      Taro.createSelectorQuery()
        .select('#elec-line-canvas')
        .fields({ node: true, size: true })
        .exec((res) => {
          if (!res[0] || !res[0].node) return;
          const canvas = res[0].node as unknown as HTMLCanvasElement;
          const ctx = canvas.getContext('2d')!;
          const dpr = Taro.getSystemInfoSync().pixelRatio;
          canvas.width = (res[0].width as number) * dpr;
          canvas.height = (res[0].height as number) * dpr;
          ctx.scale(dpr, dpr);

          const W = res[0].width as number;
          const H = res[0].height as number;
          const pad = { top: 20, right: 10, bottom: 30, left: 36 };
          const cW = W - pad.left - pad.right;
          const cH = H - pad.top - pad.bottom;

          const vals = trend.map((x) => x.usage);
          const maxVal = Math.max(1, ...vals);

          const stepX = cW / Math.max(1, trend.length - 1);
          const pts = trend.map((d, i) => ({
            x: pad.left + i * stepX,
            y: pad.top + cH - ((d.usage) / (maxVal || 1)) * cH,
          }));

          chartRef.current = { ctx, W, H, pad, cW, cH, stepX, pts, maxVal };
          drawChart(activeIdxRef.current);
        });
    }, 300);
    return () => clearTimeout(timer);
  }, [trend, trendTab, drawChart]);

  // 点击/触摸折线图：定位最近点并显示电量气泡
  const handleTouch = (e: any) => {
    const c = chartRef.current;
    if (!c) return;
    const touch = e.touches?.[0] ?? e.changedTouches?.[0];
    if (!touch) return;
    const x = touch.x;
    let idx = Math.round((x - c.pad.left) / c.stepX);
    idx = Math.max(0, Math.min(c.pts.length - 1, idx));
    activeIdxRef.current = idx;
    setActiveIdx(idx);
    drawChart(idx); // 同步重绘，点击即时反馈
  };

  if (loading) {
    return (
      <View className="page electricity-page" style={{ paddingTop: `${statusBarHeight}px` }}>
      <View className="elec-navbar" style={{ paddingTop: `${statusBarHeight}px` }}>
        <View className="elec-navbar-inner">
          <View className="elec-navbar-left" onClick={() => Taro.navigateBack()}>
            <Text className="elec-navbar-back">‹</Text>
          </View>
          <Text className="elec-navbar-title">电量详情</Text>
          <View className="elec-navbar-right" />
        </View>
      </View>
      </View>
    );
  }

  // 未配置电表 Cookie：引导去设置（每个宿舍有独立电表，需学生自配 Cookie 后端才会采集）
  if (cookieConfigured === false) {
    return (
      <View className="page electricity-page" style={{ paddingTop: `${statusBarHeight}px` }}>
        <View className="elec-navbar" style={{ paddingTop: `${statusBarHeight}px` }}>
          <View className="elec-navbar-inner">
            <View className="elec-navbar-left" onClick={() => Taro.navigateBack()}>
              <Text className="elec-navbar-back">‹</Text>
            </View>
            <Text className="elec-navbar-title">电量详情</Text>
            <View className="elec-navbar-right" />
          </View>
        </View>
        <View className="state-wrap" style={{ paddingTop: '160rpx' }}>
          <Text className="state-title">未配置电表接入信息</Text>
          <Text className="state-desc">每个宿舍有独立的电表，配置后即可自动采集电量数据</Text>
          <View
            className="state-retry"
            onClick={() => Taro.navigateTo({ url: '/pages/electricity-config/index' })}
          >
            <Text className="state-retry-text">去设置</Text>
          </View>
        </View>
      </View>
    );
  }

  if (error) {
    return (
      <View className="page electricity-page" style={{ paddingTop: `${statusBarHeight}px` }}>
      <View className="elec-navbar" style={{ paddingTop: `${statusBarHeight}px` }}>
        <View className="elec-navbar-inner">
          <View className="elec-navbar-left" onClick={() => Taro.navigateBack()}>
            <Text className="elec-navbar-back">‹</Text>
          </View>
          <Text className="elec-navbar-title">电量详情</Text>
          <View className="elec-navbar-right" />
        </View>
      </View>
      <View className="state-wrap">
          <Text className="state-title">暂时无法获取电量数据</Text>
          <View className="state-retry" onClick={loadAll}>
            <Text className="state-retry-text">重新加载</Text>
          </View>
        </View>
      </View>
    );
  }

  const isEmpty = !current && records.length === 0;

  return (
    <ScrollView scrollY className="page electricity-page">
      <View className="elec-navbar" style={{ paddingTop: `${statusBarHeight}px` }}>
        <View className="elec-navbar-inner">
          <View className="elec-navbar-left" onClick={() => Taro.navigateBack()}>
            <Text className="elec-navbar-back">‹</Text>
          </View>
          <Text className="elec-navbar-title">电量详情</Text>
          <View className="elec-navbar-right" />
        </View>
      </View>

      {isEmpty ? (
        <View className="card">
          <EmptyState title="暂无电量数据" desc="学校尚未采集宿舍电量" />
        </View>
      ) : (
        <>
          {/* ===== 电量信息卡片（全部内容合在一个 card 内） ===== */}
          <View className="card elec-hero-card">
            {/* 上半：左侧文字 + 右侧圆环 */}
            <View className="elec-hero-top">
              <View className="elec-hero-left">
                <View className="elec-meter-row">
                  <Text className="elec-meter-name">{roomText || '--'}</Text>
                  <Text className="iconfont icon-bianji elec-edit-icon" />
                </View>

                <View className="elec-value-row">
                  <Text className="elec-value-num">
                    {current?.remaining != null ? current.remaining.toFixed(2) : '--'}
                  </Text>
                  <Text className="elec-value-unit">度</Text>
                </View>
                <Text className="elec-value-label">剩余电量</Text>

                <Text className={`elec-status-text ${current?.is_low_power ? 'low' : 'normal'}`}>
                  {current?.is_low_power ? '电量偏低' : '剩余正常'}
                </Text>
              </View>

              <View className="elec-ring-wrap">
                <View
                  className="elec-ring-bg"
                  style={{
                    background: `conic-gradient(from -90deg, #1a73e8 0%, #1a73e8 ${pct}%, #d0d5dd ${pct}%, #d0d5dd 100%)`,
                  }}
                />
                <View className="elec-ring-hole" />
              </View>
            </View>

            {/* 分割线 */}
            <View className="elec-card-divider" />

            {/* 统计行：总容量 | 本月已用 */}
            <View className="elec-stats-row">
              <View className="elec-stat-item">
                <Text className="elec-stat-label">总容量</Text>
                <Text className="elec-stat-val">
                  {totalCapacity != null ? totalCapacity.toFixed(1) : '--'}
                  <Text className="elec-stat-unit-inline">度</Text>
                </Text>
              </View>
              <View className="elec-stat-divider" />
              <View className="elec-stat-item">
                <Text className="elec-stat-label">本月已用</Text>
                <Text className="elec-stat-val">
                  {monthUsed != null ? monthUsed.toFixed(2) : '--'}
                  <Text className="elec-stat-unit-inline">度</Text>
                </Text>
              </View>
            </View>

            {/* 更新时间 */}
            {updateTime ? (
              <Text className="elec-update-time">更新时间：{updateTime}</Text>
            ) : null}
          </View>

          {/* ===== 用电趋势（Canvas 折线图） ===== */}
          <View className="card elec-trend-card">
            <View className="elec-trend-head">
              <Text className="elec-trend-title">用电趋势</Text>
              <View className="elec-trend-tabs">
                {(['day', 'week', 'month'] as TrendTab[]).map((tab) => (
                  <Text
                    key={tab}
                    className={`elec-tab ${trendTab === tab ? 'active' : ''}`}
                    onClick={() => changeTrendTab(tab)}
                  >
                    {{ day: '日', week: '周', month: '月' }[tab]}
                  </Text>
                ))}
              </View>
            </View>
            <Text className="elec-trend-sub">用电量(度)</Text>

            {trend.every((x) => x.usage === 0) ? (
              <Text className="elec-trend-empty">暂无用电记录</Text>
            ) : (
              <View className="elec-canvas-wrap">
                <Canvas
                  id="elec-line-canvas"
                  type="2d"
                  className="elec-line-canvas"
                  onTouchStart={handleTouch}
                />
              </View>
            )}
          </View>

          {/* ===== 用电记录（按需分页） ===== */}
          <View className="card elec-records-card">
            <View className="elec-records-head">
              <View className="elec-records-head-row">
                <Text className="elec-records-title">用电记录</Text>
                {total > 0 && (
                  <Text className="elec-records-count">共 {total} 条</Text>
                )}
              </View>
              {/* 用电记录由学校系统每日 00 点后结算前一天，故与"剩余电量"（实时）会有差异 */}
              <Text className="elec-records-tip">每日 00 点后结算前一天的用电</Text>
            </View>
            {records.length === 0 ? (
              <Text className="elec-records-empty">暂无记录</Text>
            ) : (
              <>
                {records.map((r, idx) => {
                  const t = r.record_time || r.time || '';
                  const d = t ? dayjs(t) : null;
                  const dateText = d && d.isValid() ? d.format('YYYY-MM-DD HH:mm') : '--';
                  const isLast = idx >= records.length - 1;
                  return (
                    <View
                      className={`elec-record ${isLast ? 'last' : ''}`}
                      key={r.id ?? idx}
                    >
                      <Text className="elec-record-date">{dateText}</Text>
                      <Text className="elec-record-usage">{Number(r.usage || 0).toFixed(2)}度</Text>
                    </View>
                  );
                })}
                {records.length < total ? (
                  <View className="elec-more-btn" onClick={loadMore}>
                    <Text className="elec-more-text">
                      {loadingMore
                        ? '加载中…'
                        : `查看更多记录（${total - records.length}） ›`}
                    </Text>
                  </View>
                ) : (
                  <View className="elec-more-btn" onClick={loadAll}>
                    <Text className="elec-more-text">收起 ∧</Text>
                  </View>
                )}
              </>
            )}
          </View>
        </>
      )}
    </ScrollView>
  );
}
