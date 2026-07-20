/**
 * 电量相关 API 模块
 */

import request from "./request";
import type { ApiResponse } from "@/types/api";

/** 剩余电量数据 */
export interface ElectricityRemaining {
  /** 剩余电量（度） */
  default: number;
  /** 总量（度） */
  total_capacity: number;
  /** 百分比（0-100） */
  percentage: number;
  /** 是否低电量 */
  is_low_power: boolean;
  /** 记录时间 */
  recorded_at?: string;
}

/** 用电记录 */
export interface ElectricityRecord {
  time: string;
  usage: number;
  meter: string;
}

/** 用电统计 */
export interface ElectricityStatistics {
  daily: { date: string; usage: number; count?: number }[];
  by_meter: { meter: string; usage: number }[];
  summary: {
    total_records: number;
    total_usage: number;
    avg_daily: number;
    max_daily: number;
    min_daily: number;
    meter_count: number;
  };
  range?: {
    type: string;
    start_date: string;
    end_date: string;
  };
}

/** 时间范围类型 */
export type RangeType = "week" | "last_week" | "month" | "last_month" | "custom";

/** 电量配置 */
export interface ElectricityConfig {
  cookie?: string;
  low_power_threshold?: number;
  daily_push_time?: string;
  weekly_push_day?: string;
}

/**
 * 电量 API
 * 所有端点需要 JWT Bearer Token 认证（由 request 拦截器自动添加）
 */
export const electricityApi = {
  /** 获取剩余电量 */
  getRemaining: () => request.get<any, ApiResponse<ElectricityRemaining>>("/electricity/remaining"),

  /** 获取用电记录（支持分页） */
  getRecords: (limit?: number) =>
    request.get<any, ApiResponse<ElectricityRecord[]>>("/electricity/records", {
      params: limit ? { limit } : undefined,
    }),

  /**
   * 获取用电统计（按日聚合 + 按电表聚合）
   * @param range_type 时间范围类型: week-本周, last_week-上周, month-本月, last_month-上月, custom-自定义
   * @param start_date 自定义开始日期 (YYYY-MM-DD)，range_type=custom 时必填
   * @param end_date 自定义结束日期 (YYYY-MM-DD)，range_type=custom 时必填
   */
  getStatistics: (range_type?: string, start_date?: string, end_date?: string) => {
    const params: Record<string, string> = {};
    if (range_type) params.range_type = range_type;
    if (start_date) params.start_date = start_date;
    if (end_date) params.end_date = end_date;
    return request.get<any, ApiResponse<ElectricityStatistics>>("/electricity/statistics", {
      params,
    });
  },

  /** 全量爬取（需管理员权限） */
  triggerFetchAll: () =>
    request.post<any, ApiResponse<{ task_id?: number }>>("/electricity/trigger/fetch_all"),

  /** 删除全部用电记录（需管理员权限） */
  deleteAllRecords: () =>
    request.delete<
      any,
      ApiResponse<{ deleted_records: number; deleted_remaining: number; deleted_capacity: number }>
    >("/electricity/records"),
};
