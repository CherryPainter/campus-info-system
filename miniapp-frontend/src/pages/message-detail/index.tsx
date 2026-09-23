import { useState } from 'react';
import { View, Text, ScrollView, Image } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';

import * as notificationsApi from '@/api/notifications';
import type { ElectricityReportPayload, UserNotificationItem } from '@/types/api';
import { API_BASE_URL } from '@/utils/request';
import { relativeDayLabel, weekdayCNFromDate } from '@/utils/date';
import IconArrow from '@/components/IconArrow';
import './index.scss';

/**
 * 消息详情（个人站内通知）
 *
 * 消息列表只展示摘要（电量日报/周报/月报正文较长，全部铺开会让列表很臃肿），
 * 点进来看完整内容；后端在进入详情时已自动标记已读。
 *
 * 电量报告类通知额外带了结构化 payload：正文 content 是给人读的纯文本（保持兼容），
 * payload 则用于渲染「每日用电」可点击列表（点某天进那天的用电详情）。
 * 没有 payload 的老消息、以及其它类型通知，仍按纯文本渲染。
 */

const CATEGORY_LABEL: Record<string, string> = {
  electricity_daily: '电量日报',
  electricity_weekly: '电量周报',
  electricity_monthly: '电量月报',
  low_power: '低电量提醒',
  cookie_invalid: '配置失效',
  fetch_error: '采集异常',
};

/** 完整时间：YYYY-MM-DD HH:mm（后端 created_at 为 "YYYY-MM-DD HH:mm:ss"） */
function fullTime(ts: string | null): string {
  if (!ts) return '';
  return ts.slice(0, 16);
}

/** 用电日格式（YYYY-MM-DD）；不匹配则不生成跳转，避免拼出无效路由 */
const USAGE_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** 跳转某个用电日的用电详情（与用电记录列表点击进入的是同一个页面） */
function openDailyDetail(date: string) {
  if (!USAGE_DATE_RE.test(date)) return;
  Taro.navigateTo({ url: `/pages/electricity-daily/index?date=${date}` });
}

/**
 * payload 运行时收窄
 *
 * payload 是 JSON 列：老消息没有该字段，其它类型通知也可能带 payload，
 * 因此不能直接当电量报告用；结构不符时返回 null，退回纯文本渲染。
 */
function asReportPayload(raw: unknown): ElectricityReportPayload | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  if (obj.kind !== 'electricity_report') return null;
  return obj as unknown as ElectricityReportPayload;
}

/** 数字展示：非法值按 0 处理，保留两位小数 */
function num2(v: unknown): string {
  const n = Number(v);
  return (Number.isFinite(n) ? n : 0).toFixed(2);
}

/**
 * 电量报告的结构化正文（日报 / 周报 / 月报共用）
 *
 * 为什么不直接渲染 content：纯文本里的「每日用电详情」是一行行死文本，点不动。
 * 这里用同一份数据的结构化形态渲染，让每一天都可点进当日明细。
 */
function ElectricityReportBody({ payload }: { payload: ElectricityReportPayload }) {
  const meters = Array.isArray(payload.meters) ? payload.meters : [];
  const daily = Array.isArray(payload.daily) ? payload.daily : [];
  const daysCount = Number(payload.days_count) || 0;
  // 日报只有一个用电日，period_label 就是那天的日期，可直达当日详情
  const singleDay = USAGE_DATE_RE.test(String(payload.period_label || ''));

  return (
    <>
      {/* ---- 用电概况 ---- */}
      <Text className="msgd-section-title">用电概况</Text>
      <View className="msgd-total-row">
        <Text className="msgd-total-num">{num2(payload.total_usage)}</Text>
        <Text className="msgd-total-unit">度</Text>
      </View>
      <Text className="msgd-period">{payload.period_label}</Text>

      <View className="msgd-stat-row">
        <View className="msgd-stat-item">
          <Text className="msgd-stat-val">{daysCount} 天</Text>
          <Text className="msgd-stat-label">统计天数</Text>
        </View>
        <View className="msgd-stat-divider" />
        <View className="msgd-stat-item">
          <Text className="msgd-stat-val">{num2(payload.avg_daily)} 度</Text>
          <Text className="msgd-stat-label">日均用电</Text>
        </View>
        {payload.remaining != null ? (
          <>
            <View className="msgd-stat-divider" />
            <View className="msgd-stat-item">
              <Text className="msgd-stat-val">{num2(payload.remaining)} 度</Text>
              <Text className="msgd-stat-label">剩余电量</Text>
            </View>
          </>
        ) : null}
      </View>

      {/* ---- 各电表用电 ---- */}
      {meters.length > 0 ? (
        <>
          <Text className="msgd-section-title">各电表用电</Text>
          {meters.map((m, idx) => (
            <View
              className={`msgd-row ${idx === meters.length - 1 ? 'last' : ''}`}
              key={m.meter || idx}
            >
              <Text className="msgd-row-label">{m.meter}</Text>
              <Text className="msgd-row-value">{num2(m.usage)} 度</Text>
            </View>
          ))}
        </>
      ) : null}

      {/* ---- 每日用电（可点击进当日详情） ---- */}
      {daily.length > 0 ? (
        <>
          <Text className="msgd-section-title">每日用电</Text>
          <Text className="msgd-section-tip">点击某天可查看当日各分表明细</Text>
          {daily.map((d, idx) => {
            const rel = relativeDayLabel(d.date);
            const wk = weekdayCNFromDate(d.date);
            return (
              <View
                className={`msgd-row msgd-row--link ${idx === daily.length - 1 ? 'last' : ''}`}
                key={d.date}
                hoverClass="msgd-row-hover"
                hoverStayTime={50}
                onClick={() => openDailyDetail(d.date)}
              >
                <View className="msgd-row-left">
                  <View className="msgd-row-label-row">
                    <Text className="msgd-row-label">{d.date}</Text>
                    {rel ? <Text className="msgd-row-tag">{rel}</Text> : null}
                  </View>
                  {wk ? <Text className="msgd-row-sub">{wk}</Text> : null}
                </View>
                <View className="msgd-row-right">
                  <Text className="msgd-row-value">{num2(d.usage)}</Text>
                  <Text className="msgd-row-unit">度</Text>
                  <IconArrow size="sm" className="msgd-row-arrow" />
                </View>
              </View>
            );
          })}
        </>
      ) : null}

      {/* ---- 日报无每日列表，给一条直达当日详情的入口 ---- */}
      {daily.length === 0 && singleDay ? (
        <View
          className="msgd-row msgd-row--link last"
          hoverClass="msgd-row-hover"
          hoverStayTime={50}
          onClick={() => openDailyDetail(String(payload.period_label))}
        >
          <Text className="msgd-row-label">查看当日各分表明细</Text>
          <IconArrow size="sm" className="msgd-row-arrow" />
        </View>
      ) : null}
    </>
  );
}

export default function MessageDetailPage() {
  const [detail, setDetail] = useState<UserNotificationItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useLoad((opts) => {
    Taro.setNavigationBarTitle({ title: '消息详情' });
    const id = Number(opts?.id);
    if (!id) {
      setError('缺少消息 id');
      setLoading(false);
      return;
    }
    notificationsApi
      .getNotificationDetail(id)
      .then((res) => {
        setDetail(res?.data?.notification || null);
      })
      .catch((e) => {
        setError((e as Error).message || '加载失败');
      })
      .finally(() => setLoading(false));
  });

  if (loading) {
    return (
      <View className="msgd-page">
        <View className="msgd-tip">
          <Text>加载中...</Text>
        </View>
      </View>
    );
  }

  if (error || !detail) {
    return (
      <View className="msgd-page">
        <View className="msgd-tip">
          <Text>{error || '消息不存在'}</Text>
        </View>
      </View>
    );
  }

  // 电量报告且 payload 结构合法 → 结构化渲染；否则退回纯文本
  const report = asReportPayload(detail.payload);

  return (
    <ScrollView scrollY className="msgd-page">
      <View className="msgd-head">
        <Text className="msgd-cat">{CATEGORY_LABEL[detail.category] || '系统通知'}</Text>
        <Text className="msgd-time">{fullTime(detail.created_at)}</Text>
      </View>
      <Text className="msgd-title">{detail.title}</Text>
      {/* 封面图：标题之下、正文之上，有图才渲染（无图不占位） */}
      {detail.cover_url ? (
        <Image className="msgd-cover" src={`${API_BASE_URL}${detail.cover_url}`} mode="widthFix" />
      ) : null}
      <View className="msgd-divider" />
      {report ? (
        <ElectricityReportBody payload={report} />
      ) : (
        /* 正文为纯文本、\n 换行，用 pre-wrap 保留原始排版 */
        <Text className="msgd-content">{detail.content || '（无正文）'}</Text>
      )}
    </ScrollView>
  );
}
