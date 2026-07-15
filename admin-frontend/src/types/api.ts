/**
 * 前端共享 API 响应类型
 * 所有 api 模块统一从这里导入 ApiResponse / Paginated，避免重复定义。
 */

/** 通用 API 响应包装（后端统一返回结构） */
export interface ApiResponse<T = unknown> {
  status: string;
  message?: string;
  data?: T;
}

/** 统一分页结构（对外暴露的分页方法最终返回此形态） */
export interface Paginated<T> {
  data: T[];
  pagination: {
    total: number;
    page: number;
    per_page: number;
    pages: number;
  };
}
