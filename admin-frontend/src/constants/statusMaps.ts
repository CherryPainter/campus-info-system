/**
 * 共享状态映射（阶段 2 #5）
 * 统一各页面散落的状态/来源/事件类型映射，避免重复定义。
 * color 统一使用 Ant Design PresetStatusColor：success / error / processing / warning / default
 * icon 单独保留（ReactNode）。
 */
import { createElement, type ReactNode } from 'react';
import {
  ClockCircleOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleFilled,
  StopOutlined,
  SendOutlined,
} from '@ant-design/icons';

/** Ant Design PresetStatusColor */
export type StatusColor = 'success' | 'error' | 'processing' | 'warning' | 'default';

/** 仅颜色 + 文案 */
export interface StatusMeta {
  color: StatusColor;
  text: string;
}

/** 颜色 + 图标 + 文案 */
export interface StatusMetaWithIcon {
  color: StatusColor;
  icon: ReactNode;
  text: string;
}

/** 推送状态（来源 Push.tsx statusMap） */
export const PUSH_STATUS_MAP: Record<string, StatusMeta> = {
  pending: { color: 'warning', text: '待发送' },
  sent: { color: 'success', text: '已发送' },
  failed: { color: 'error', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
};

/** 任务进程状态（来源 Processes.tsx statusMap） */
export const PROCESS_STATUS_MAP: Record<string, StatusMetaWithIcon> = {
  running: { color: 'processing', icon: createElement(ClockCircleOutlined), text: '运行中' },
  completed: { color: 'success', icon: createElement(CheckCircleOutlined), text: '已完成' },
  completed_empty: { color: 'warning', icon: createElement(ExclamationCircleOutlined), text: '完成·无数据' },
  failed: { color: 'error', icon: createElement(CloseCircleOutlined), text: '失败' },
  cancelled: { color: 'default', icon: createElement(CloseCircleOutlined), text: '已取消' },
};

/** 爬取预约任务状态（来源 Processes.tsx crawlStatusMap） */
export const CRAWL_TASK_STATUS_MAP: Record<string, StatusMeta> = {
  pending: { color: 'default', text: '待执行' },
  running: { color: 'processing', text: '执行中' },
  completed: { color: 'success', text: '已完成' },
  completed_empty: { color: 'warning', text: '完成·无数据' },
  failed: { color: 'error', text: '失败' },
  cancelled: { color: 'warning', text: '已取消' },
};

/** 仪表盘任务状态（来源 Dashboard.tsx TASK_STATUS_MAP） */
export const TASK_STATUS_MAP: Record<string, StatusMetaWithIcon> = {
  completed: { color: 'success', icon: createElement(CheckCircleFilled), text: '完成' },
  failed: { color: 'error', icon: createElement(CloseCircleFilled), text: '失败' },
  running: { color: 'processing', icon: createElement(ClockCircleFilled), text: '运行中' },
  cancelled: { color: 'default', icon: createElement(StopOutlined), text: '已取消' },
  pending: { color: 'warning', icon: createElement(ClockCircleFilled), text: '待执行' },
};

/** Webhook 测试状态（来源 Webhooks.tsx TEST_STATUS_MAP） */
export const WEBHOOK_TEST_STATUS_MAP: Record<string, StatusMetaWithIcon> = {
  success: { icon: createElement(CheckCircleOutlined), color: 'success', text: '成功' },
  failed: { icon: createElement(CloseCircleOutlined), color: 'error', text: '失败' },
  pending: { icon: createElement(SendOutlined, { spin: true }), color: 'processing', text: '测试中' },
};

/** IP 黑名单来源（原 ipBlacklist.ts SOURCE_CN，迁至此） */
export const IP_SOURCE_MAP: Record<string, string> = {
  manual: '手动封禁',
  auto: '自动检测',
  ddos: 'DDoS 攻击检测',
  rate_limit: '限频触发',
  'ddos攻击检测': 'DDoS 攻击检测',
  'rate_limit限频': '限频触发',
  // 登录信号感知分层处置
  auto_ddos_detect: '自动化 DDoS 检测',
  auto_security_violation: '安全违规自动检测',
  login_brute_tier2: '撞库/枚举(临时封禁)',
  login_brute_tier3: '暴力破解(永久封禁)',
  'auto-brute': '暴力破解自动封禁',
  login_enum: '用户名枚举探测',
  login_rate_limit: '登录限流',
  login_account_target: '账号遭多IP围攻(临时封禁)',
};

/** IP 来源视觉样式（颜色 + 图标语义） */
export const IP_SOURCE_STYLE: Record<string, { color: string; icon: string }> = {
  manual: { color: 'blue', icon: 'user' },
  auto: { color: 'default', icon: 'robot' },
  ddos: { color: 'red', icon: 'fire' },
  rate_limit: { color: 'orange', icon: 'clock-circle' },
  'ddos攻击检测': { color: 'red', icon: 'fire' },
  'rate_limit限频': { color: 'orange', icon: 'clock-circle' },
  auto_ddos_detect: { color: 'red', icon: 'fire' },
  auto_security_violation: { color: 'magenta', icon: 'warning' },
  login_brute_tier2: { color: 'volcano', icon: 'key' },
  login_brute_tier3: { color: 'red', icon: 'lock' },
  'auto-brute': { color: 'volcano', icon: 'key' },
  login_enum: { color: 'orange', icon: 'apartment' },
  login_rate_limit: { color: 'gold', icon: 'clock-circle' },
  login_account_target: { color: 'red', icon: 'team' },
};

/** IP 安全事件类型（原 ipBlacklist.ts EVENT_TYPE_CN，迁至此） */
export const IP_EVENT_TYPE_MAP: Record<string, string> = {
  rate_limit_exceeded: '请求频率超限',
  sql_injection: 'SQL 注入尝试',
  xss: 'XSS 攻击尝试',
  suspicious_path: '可疑路径访问',
  large_request: '超大请求',
  ddos: 'DDoS 攻击',
  file_upload_abuse: '文件上传滥用',
  login_brute_force: '登录密码爆破',
  login_security: '登录安全信号',
};
