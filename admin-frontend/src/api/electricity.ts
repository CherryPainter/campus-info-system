/**
 * 电量相关 API 模块
 *
 * 用户化说明（2026-09-01）：
 * - 电量数据按用户隔离后，全局视图查询方法（getRemaining/getRecords/getStatistics）
 *   已随管理端改版删除，学生维度查询统一走 adminApi.getElectricityStudents 系列。
 * - 保留 triggerFetchAll：进程管理页（Tasks.tsx）仍以「全量爬取」作为运维入口。
 */

import request from "./request";
import type { ApiResponse } from "@/types/api";

/** 时间范围类型 */
export type RangeType = "week" | "last_week" | "month" | "last_month" | "custom";

/**
 * 电量 API
 * 所有端点需要 JWT Bearer Token 认证（由 request 拦截器自动添加）
 */
export const electricityApi = {
  /** 全量爬取（需管理员权限）：遍历所有已配置 Cookie 的学生，逐人强制全量采集 */
  triggerFetchAll: () =>
    request.post<any, ApiResponse<{ task_id?: number }>>("/electricity/trigger/fetch_all"),
};
