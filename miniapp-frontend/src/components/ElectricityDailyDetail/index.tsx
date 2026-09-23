import { useEffect, useState } from 'react';
import { View, Text } from '@tarojs/components';

import * as electricityApi from '@/api/electricity';
import type { ElectricityDailyDetailResult } from '@/types/api';
import './index.scss';

/**
 * 某一个用电日的用电详情（正文）
 *
 * 为什么抽成组件：
 *   站内信的「电量日报」与用电记录页的「用电详情」讲的是同一件事（同一个用电日），
 *   若各写一套渲染，同一份数据会长出两副面孔。这里作为唯一定义，
 *   由 pages/electricity-daily 与 pages/message-detail（日报场景整页复用）共用。
 *
 * 数据源：实时接口 /api/miniapp/electricity/daily/<date>，而不是通知里的 payload 快照。
 *   因此历史日报消息点进去看到的是**当前库里的数据**，后续采集纠错会反映出来；
 *   消息自身的时间/标题仍按发出时刻原样展示，两者不一致时以本组件数据为准。
 *
 * 口径：接口返回的 date 是**用电日**；记录表的 record_time 是「用电日 + 1 天」的
 *   00:0x 结算时刻，所以这里能同时看到"用电日"和"结算时间"两个不同的日期，不是 bug。
 *
 * 头部（分类标签 / 时间 / 标题）也由本组件渲染，props 可覆盖文案，
 *   保证两个入口进来的头部规格完全一致。
 */

type Detail = ElectricityDailyDetailResult['data'];

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** 保留两位小数的度数文本 */
function usageText(n: number): string {
  return n.toFixed(2);
}

/** 带符号的增减量：+0.24 / -0.31 / 0.00 */
function signedText(n: number): string {
  if (n > 0) return `+${n.toFixed(2)}`;
  if (n < 0) return `-${Math.abs(n).toFixed(2)}`;
  return '0.00';
}

/** 结算时间去掉秒：YYYY-MM-DD HH:mm（后端为 "YYYY-MM-DD HH:mm:ss"） */
function shortTime(ts: string | null | undefined): string {
  return ts ? ts.slice(0, 16) : '';
}

interface Props {
  /** 用电日，YYYY-MM-DD */
  date: string;
  /** 头部左上角分类标签，默认「用电日报」 */
  categoryLabel?: string;
  /** 头部右侧时间，默认取接口返回的结算时间 */
  headTime?: string;
  /** 头部标题，默认「每日用电报告（用电日）」 */
  title?: string;
}

export default function ElectricityDailyDetail({
  date,
  categoryLabel = '用电日报',
  headTime,
  title,
}: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 本组件可能挂在页面里、也可能挂在列表的详情页里，故用 useEffect 而非页面级的 useLoad
  useEffect(() => {
    const target = String(date || '').trim();
    if (!DATE_RE.test(target)) {
      setDetail(null);
      setError('缺少有效的用电日期');
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError('');
    electricityApi
      .getDailyDetail(target)
      .then((res) => {
        if (alive) setDetail(res?.data ?? null);
      })
      .catch((e) => {
        if (alive) setError((e as Error).message || '加载失败');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [date]);

  if (loading) {
    return (
      <View className="elecd-tip">
        <Text>加载中...</Text>
      </View>
    );
  }

  if (error || !detail) {
    return (
      <View className="elecd-tip">
        <Text>{error || '该日期暂无用电记录'}</Text>
      </View>
    );
  }

  const {
    date: usageDate,
    settle_time,
    total_usage,
    meter_count,
    meters,
    prev,
    diff_prev,
    avg_recent,
    avg_recent_days,
    diff_avg,
    remaining,
    remaining_at,
  } = detail;

  return (
    <>
      {/* ===== 头部 ===== */}
      <View className="elecd-head">
        <Text className="elecd-cat">{categoryLabel}</Text>
        <Text className="elecd-head-time">{headTime || shortTime(settle_time) || usageDate}</Text>
      </View>
      <Text className="elecd-title">{title || `每日用电报告（${usageDate}）`}</Text>
      <View className="elecd-divider" />

      {/* ===== 用电概况 ===== */}
      <View className="card elecd-card">
        <Text className="elecd-card-title">用电概况</Text>

        <View className="elecd-total">
          <Text className="elecd-total-num">{usageText(total_usage)}</Text>
          <Text className="elecd-total-unit">度</Text>
        </View>
        <Text className="elecd-total-label">当日总用电量</Text>

        {(diff_prev != null || diff_avg != null) && (
          <View className="elecd-cmp-row">
            <View className="elecd-cmp-item">
              <Text className="elecd-cmp-label">较前一日</Text>
              <Text className="elecd-cmp-val">
                {diff_prev != null ? `${signedText(diff_prev)} 度` : '--'}
              </Text>
              <Text className="elecd-cmp-sub">
                {prev ? `前一日 ${usageText(prev.total_usage)} 度` : '无前一日数据'}
              </Text>
            </View>
            <View className="elecd-cmp-divider" />
            <View className="elecd-cmp-item">
              <Text className="elecd-cmp-label">
                {avg_recent_days > 0 && avg_recent_days < 7
                  ? `较近 ${avg_recent_days} 日均值`
                  : '较近 7 日均值'}
              </Text>
              <Text className="elecd-cmp-val">
                {diff_avg != null ? `${signedText(diff_avg)} 度` : '--'}
              </Text>
              <Text className="elecd-cmp-sub">
                {avg_recent != null ? `日均 ${usageText(avg_recent)} 度` : '数据不足'}
              </Text>
            </View>
          </View>
        )}
      </View>

      {/* ===== 各电表用电详情 ===== */}
      <View className="card elecd-card">
        <View className="elecd-card-head">
          <Text className="elecd-card-title">各电表用电详情</Text>
          <Text className="elecd-card-count">共 {meter_count} 块分表</Text>
        </View>

        {meters.map((m) => (
          <View className="elecd-meter" key={m.meter}>
            <View className="elecd-meter-row">
              <Text className="elecd-meter-name">{m.meter}</Text>
              <Text className="elecd-meter-usage">{usageText(m.usage)} 度</Text>
            </View>
            <View className="elecd-bar">
              <View
                className="elecd-bar-fill"
                style={{ width: `${Math.max(0, Math.min(100, m.percent))}%` }}
              />
            </View>
            <Text className="elecd-meter-pct">占当日 {m.percent.toFixed(1)}%</Text>
          </View>
        ))}

        <Text className="elecd-note">
          一个宿舍可能有照明、空调等多块分表，各分表抄表口径独立；
          上方「当日总用电量」为各分表之和。
        </Text>
      </View>

      {/* ===== 结算信息 ===== */}
      <View className="card elecd-card">
        <Text className="elecd-card-title">结算信息</Text>
        <View className="elecd-info-row">
          <Text className="elecd-info-label">统计日期</Text>
          <Text className="elecd-info-val">{usageDate}</Text>
        </View>
        <View className="elecd-info-row">
          <Text className="elecd-info-label">结算时间</Text>
          <Text className="elecd-info-val">{shortTime(settle_time) || '--'}</Text>
        </View>
        {remaining != null && (
          <View className="elecd-info-row">
            <Text className="elecd-info-label">当时剩余电量</Text>
            <Text className="elecd-info-val">{usageText(remaining)} 度</Text>
          </View>
        )}
        {remaining_at && (
          <Text className="elecd-note">
            剩余电量取自该次采集（{remaining_at}），与"当日用电量"不是同一时点。
          </Text>
        )}
      </View>
    </>
  );
}
