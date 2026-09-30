/**
 * 校园通知（公告）管理端 API 模块
 */
import request from "./request";
import type { ApiResponse } from "@/types/api";

/** 公告分类 */
export type AnnouncementCategory = "notice" | "activity" | "urgent" | "system";

/** 公告状态 */
export type AnnouncementStatus = "draft" | "published" | "withdrawn";

/** 附件 */
export interface AnnouncementAttachment {
  id: number;
  announcement_id: number;
  file_name: string;
  file_size: number;
  file_size_label: string;
  file_url: string;
  /** 完整下载路径（已自带 /api 前缀），前端直接用 <a href> 触发下载 */
  download_url: string;
  created_at: string | null;
}

/** 列表项 */
export interface AnnouncementListItem {
  id: number;
  title: string;
  category: AnnouncementCategory;
  category_label: string;
  summary: string | null;
  department: string | null;
  channel?: string | null;
  audience_type: string;
  is_top: boolean;
  status: AnnouncementStatus;
  published_at: string | null;
  published_label: string | null;
  expired_at: string | null;
  view_count: number;
  created_at: string | null;
  updated_at: string | null;
  /** 封面图 URL（消息推送卡片 / 详情页展示，无图则不显示） */
  cover_url?: string | null;
  /** 管理端列表额外附加 */
  attachment_count: number;
  read_count: number;
}

/** 详情（含正文与附件列表） */
export interface AnnouncementDetail extends AnnouncementListItem {
  content: string;
  attachments: AnnouncementAttachment[];
}

/** 受管频道（管理端 CRUD 用） */
export interface AnnouncementChannelAdmin {
  id: number;
  name: string;
  sort_order: number;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** 新建 / 更新提交体 */
export interface AnnouncementPayload {
  title: string;
  category?: AnnouncementCategory;
  content?: string;
  summary?: string;
  department?: string;
  /** 频道/栏目（学校要闻/学院动态/媒体聚焦…），用于小程序列表顶部频道标签 */
  channel?: string;
  is_top?: boolean;
  /** 过期时间，字符串或 null（长期有效） */
  expired_at?: string | null;
  /** 封面图 URL（详情页 / 消息推送卡片展示，无图则不显示） */
  cover_url?: string | null;
  /** 仅创建时有效：true 则直接发布 */
  publish?: boolean;
}

/** 分类中文与色标（与后端 CATEGORY_LABELS 对齐） */
export const CATEGORY_OPTIONS: { value: AnnouncementCategory; label: string; color: string }[] = [
  { value: "notice", label: "通知", color: "blue" },
  { value: "activity", label: "活动", color: "purple" },
  { value: "urgent", label: "紧急", color: "red" },
  { value: "system", label: "系统", color: "cyan" },
];

/** 频道（与后端 CHANNEL_OPTIONS 对齐；用于小程序列表顶部频道标签） */
export const CHANNEL_OPTIONS: { value: string; label: string }[] = [
  { value: "学校要闻", label: "学校要闻" },
  { value: "学院动态", label: "学院动态" },
  { value: "媒体聚焦", label: "媒体聚焦" },
];

/** 状态中文与色标 */
export const STATUS_OPTIONS: { value: AnnouncementStatus; label: string; color: string }[] = [
  { value: "draft", label: "草稿", color: "default" },
  { value: "published", label: "已发布", color: "green" },
  { value: "withdrawn", label: "已撤回", color: "orange" },
];

export const announcementApi = {
  /** 管理端列表（分页/状态/分类/关键词）
   * 后端返回结构：{ status, data: AnnouncementListItem[], pagination: { total, page, page_size, pages } }
   */
  list: (params: {
    page?: number;
    page_size?: number;
    status?: AnnouncementStatus | "";
    category?: AnnouncementCategory | "";
    keyword?: string;
  }) =>
    request.get<any, ApiResponse<AnnouncementListItem[]> & {
      pagination: { total: number; page: number; page_size: number; pages: number };
    }>("/admin/announcements", { params }),

  /** 详情（含附件） */
  detail: (id: number) =>
    request.get<any, ApiResponse<AnnouncementDetail>>(`/admin/announcements/${id}`),

  /** 创建（publish=true 直接发布） */
  create: (data: AnnouncementPayload) =>
    request.post<any, ApiResponse<AnnouncementDetail>>("/admin/announcements", data),

  /** 更新内容（不改变发布状态） */
  update: (id: number, data: Partial<AnnouncementPayload>) =>
    request.put<any, ApiResponse<AnnouncementDetail>>(`/admin/announcements/${id}`, data),

  /** 发布 */
  publish: (id: number) =>
    request.post<any, ApiResponse<AnnouncementDetail>>(`/admin/announcements/${id}/publish`),

  /** 撤回 */
  withdraw: (id: number) =>
    request.post<any, ApiResponse<AnnouncementDetail>>(`/admin/announcements/${id}/withdraw`),

  /** 删除（软删） */
  remove: (id: number) => request.delete<any, ApiResponse>(`/admin/announcements/${id}`),

  /** 上传附件（multipart，字段名 file） */
  uploadAttachment: (id: number, formData: FormData) =>
    request.post<any, ApiResponse<AnnouncementAttachment>>(
      `/admin/announcements/${id}/attachments`,
      formData
    ),

  /** 删除附件 */
  deleteAttachment: (attachmentId: number) =>
    request.delete<any, ApiResponse>(`/admin/announcements/attachment/${attachmentId}`),

  /** 上传封面图（multipart，字段名 file；独立上传，不依赖公告 id，返回 { url }） */
  uploadCover: (formData: FormData) =>
    request.post<any, ApiResponse<{ url: string }>>(
      `/admin/announcements/upload-cover`,
      formData
    ),

  /** 受管频道 CRUD（管理端「频道管理」页 + 编辑器下拉共用） */
  channelAdmin: {
    /** 列表：默认全部；active_only=true 只返回启用中的频道（编辑器下拉用） */
    list: (params?: { active_only?: boolean }) =>
      request.get<any, ApiResponse<AnnouncementChannelAdmin[]>>(
        `/admin/announcements/channels`,
        { params }
      ),
    /** 新建：{ name, sort_order?, is_active? } */
    create: (data: {
      name: string;
      sort_order?: number;
      is_active?: boolean;
    }) =>
      request.post<any, ApiResponse<AnnouncementChannelAdmin>>(
        `/admin/announcements/channels`,
        data
      ),
    /** 更新：可部分更新 name / sort_order / is_active */
    update: (
      id: number,
      data: Partial<{ name: string; sort_order: number; is_active: boolean }>
    ) =>
      request.put<any, ApiResponse<AnnouncementChannelAdmin>>(
        `/admin/announcements/channels/${id}`,
        data
      ),
    /** 删除 */
    remove: (id: number) =>
      request.delete<any, ApiResponse>(`/admin/announcements/channels/${id}`),
  },
};
