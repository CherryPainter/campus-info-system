import { useState } from 'react';
import { View, Text, ScrollView } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';

import * as electricityApi from '@/api/electricity';
import type { ElectricityDailyDetailResult } from '@/types/api';
import './index.scss';

/**
 * 用电详情（某一个用电日）
 *
 * 头部沿用「消息详情」页的排版（分类标签 + 时间 / 标题 / 分隔线），
 * 正文则改成结构化卡片，而不是照搬站内信的纯文本：
 *   - 用电概况：当日总用电量 + 较前一日 + 较近期日均
 *   - 各电表用电详情：每块分表一行，带占比条
 *   - 结算信息：统计日期 / 结算时间 / 当时剩余电量
 *
 * 为什么要做这一页：
 *   一个宿舍有【两块分表】（如 31栋512 与 310512），后端用电记录表里一天会有两条。
 *   列表页已按用电日合并成一条（显示合计），"合计是怎么来的"就在这一页交代清楚。
 *
 * 口径：后端返回的 date 是**用电日**；记录表的 record_time 是「用电日 + 1 天」的
 * 00:0x 结算时刻，所以这里能同时看到"用电日"和"结算时间"两个不同的日期，不是 bug。
 *
 * 路由参数：date（用电日，YYYY-MM-DD）
 */

type Detail = ElectricityDailyDetailResult['data'];

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
function shortTime(ts: string | null): string {
  return ts ? ts.slice(0, 16) : '';
}

export default function ElectricityDailyPage() {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useLoad((opts) => {
    Taro.setNavigationBarTitle({ title: '用电详情' });
    const date = String(opts?.date || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      setError('缺少有效的用电日期');
      setLoading(false);
      return;
    }
    electricityApi
      .getDailyDetail(date)
      .then((res) => {
        setDetail(res?.data ?? null);
      })
      .catch((e) => {
        setError((e as Error).message || '加载失败');
      })
      .finally(() => setLoading(false));
  });

  if (loading) {
    return (
      <View className="elecd-page">
        <View className="elecd-tip">
          <Text>加载中...</Text>
        </View>
      </View>
    );
  }

  if (error || !detail) {
    return (
      <View className="elecd-page">
        <View className="elecd-tip">
          <Text>{error || '该日期暂无用电记录'}</Text>
        </View>
      </View>
    );
  }

  const {
    date,
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
    <ScrollView scrollY className="elecd-page">
      {/* 头部：与「消息详情」一致（分类标签 + 时间 / 标题 / 分隔线） */}
      <View className="elecd-head">
        <Text className="elecd-cat">用电日报</Text>
        <Text className="elecd-head-time">{shortTime(settle_time) || date}</Text>
      </View>
      <Text className="elecd-title">每日用电报告（{date}）</Text>
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
          <Text className="elecd-info-val">{date}</Text>
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
    </ScrollView>
  );
}
