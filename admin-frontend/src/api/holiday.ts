/**
 * 假期模式 API 模块
 */
import request from './request';
import type { ApiResponse } from '@/types/api';

/** 假期区间 */
export interface HolidayPeriod {
  id: number;
  name: string;
  holiday_type: 'winter' | 'summer' | 'custom';
  start_date: string;
  end_date: string;
  enabled: boolean;
  note: string | null;
  created_at: string;
  updated_at: string;
}

/** 假期模式当前状态 */
export interface HolidayStatus {
  enabled: boolean;
  active: boolean;
  period: HolidayPeriod | null;
  now: string;
}

/** 假期模式 API */
export const holidayApi = {
  /** 获取当前状态（总开关 / 是否静默中 / 命中区间） */
  getStatus: () => request.get<any, ApiResponse<HolidayStatus>>('/holiday/status'),
  /** 切换总开关 */
  setMaster: (enabled: boolean) =>
    request.put<any, ApiResponse<{ enabled: boolean }>>('/holiday/master', { enabled }),
  /** 区间列表 */
  list: () => request.get<any, ApiResponse<HolidayPeriod[]>>('/holiday/periods'),
  /** 新建区间 */
  create: (data: Partial<HolidayPeriod>) =>
    request.post<any, ApiResponse<HolidayPeriod>>('/holiday/periods', data),
  /** 更新区间 */
  update: (id: number, data: Partial<HolidayPeriod>) =>
    request.put<any, ApiResponse<HolidayPeriod>>(`/holiday/periods/${id}`, data),
  /** 删除区间 */
  remove: (id: number) => request.delete<any, ApiResponse>(`/holiday/periods/${id}`),
};
