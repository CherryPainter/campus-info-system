import { App } from 'antd';

/**
 * 统一消息提示（阶段 2 #6）
 * 通过 antd 的 App 上下文获取 message 实例，替代各页面直接 import 静态 message，
 * 确保 message 能正确读取 ConfigProvider 的主题/语言配置。
 */
export function useMessage() {
  const { message } = App.useApp();
  return message;
}

/**
 * 从 axios/fetch 错误中提取后端返回的可读错误信息。
 * 兼容形态：e.response.data.message / e.message / 兜底文案。
 */
export function showApiError(e: unknown, fallback = '操作失败'): string {
  const err = e as {
    response?: { data?: { message?: string } };
    message?: string;
  };
  return err?.response?.data?.message || err?.message || fallback;
}
