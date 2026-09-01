/**
 * 意见与反馈 管理端 API 模块
 *
 * 与学生端 /api/miniapp/feedback 是不同的业务方向（反向通道），
 * 这里只读 + 处理（标记状态 / 回复），不参与消息中心的推送逻辑。
 */
import request from "./request";
import type { ApiResponse } from "@/types/api";

/** 反馈类型 */
export type FeedbackType = "bug" | "suggest" | "consult" | "other";

/** 处理状态 */
export type FeedbackStatus = "pending" | "processing" | "resolved";

/** 列表项 */
export interface FeedbackItem {
  id: number;
  user_id: number;
  type: FeedbackType;
  type_label: string;
  content: string;
  contact: string;
  images: string[];
  status: FeedbackStatus;
  status_label: string;
  created_at: string;
  updated_at: string;
}

/** 详情（含管理员回复） */
export interface FeedbackDetail extends FeedbackItem {
  reply: string;
  replied_at: string;
}

/** 列表分页返回 */
export interface FeedbackListResult {
  items: FeedbackItem[];
  total: number;
  page: number;
  page_size: number;
}

/** 类型中文与色标（与后端 FEEDBACK_TYPES 对齐） */
export const FEEDBACK_TYPE_OPTIONS: { value: FeedbackType; label: string; color: string }[] = [
  { value: "bug", label: "功能异常", color: "red" },
  { value: "suggest", label: "功能建议", color: "blue" },
  { value: "consult", label: "咨询求助", color: "cyan" },
  { value: "other", label: "其他", color: "default" },
];

/** 状态中文与色标（与后端 STATUS_* 对齐） */
export const FEEDBACK_STATUS_OPTIONS: { value: FeedbackStatus; label: string; color: string }[] = [
  { value: "pending", label: "待处理", color: "orange" },
  { value: "processing", label: "处理中", color: "blue" },
  { value: "resolved", label: "已解决", color: "green" },
];

export const feedbackApi = {
  /** 管理端列表（分页 / 按状态筛选） */
  list: (params: { page?: number; page_size?: number; status?: FeedbackStatus | "" }) =>
    request.get<any, ApiResponse<FeedbackListResult>>("/admin/feedback", { params }),

  /** 详情（含回复） */
  detail: (id: number) =>
    request.get<any, ApiResponse<{ feedback: FeedbackDetail }>>(`/admin/feedback/${id}`),

  /** 标记处理状态（pending / processing / resolved） */
  resolve: (id: number, status: FeedbackStatus) =>
    request.post<any, ApiResponse<{ feedback: FeedbackDetail }>>(
      `/admin/feedback/${id}/resolve`,
      { status }
    ),

  /** 回复（并置为已解决） */
  reply: (id: number, reply: string) =>
    request.post<any, ApiResponse<{ feedback: FeedbackDetail }>>(
      `/admin/feedback/${id}/reply`,
      { reply }
    ),
};
