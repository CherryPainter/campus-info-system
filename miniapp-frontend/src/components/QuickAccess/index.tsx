import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import './index.scss';

export interface QuickItem {
  key: string;
  label: string;
  icon: string;
  /** 点击行为：'tab' + pagePath → 跳 TabBar 页；'page' + pagePath → 跳普通页（需在 pages 注册）；否则弹"等待学校开放接口" */
  action?: 'tab' | 'page';
  pagePath?: string;
}

export const DEFAULT_ITEMS: QuickItem[] = [
  { key: 'schedule', label: '课表查询', icon: 'kechengbiao', action: 'page', pagePath: '/pages/coursetable/index' },
  { key: 'electricity', label: '电量查询', icon: 'dianchi', action: 'page', pagePath: '/pages/electricity/index' },
  { key: 'card', label: '校园卡', icon: 'xiaoyuanqia-', action: 'page', pagePath: '/pages/campus-card/index' },
  { key: 'notice', label: '通知公告', icon: 'tongzhi', action: 'page', pagePath: '/pages/announcement/index/index' },
  { key: 'classroom', label: '空闲教室', icon: 'kongxianjiaoshi', action: 'page', pagePath: '/pages/classroom/index' },
  { key: 'weather', label: '天气预报', icon: 'tianqi', action: 'page', pagePath: '/pages/weather/index' },
  { key: 'calendar2', label: '校历查询', icon: 'rili', action: 'page', pagePath: '/pages/calendar/index' },
];

interface QuickAccessProps {
  items?: QuickItem[];
  title?: string;
  /**
   * 是否需要登录才能使用：true 时，非公开功能项点击会触发 onLogin 引导，
   * 不直接跳转。用于「先体验后授权」——游客可点公开项，受限项弹登录。
   */
  requireLogin?: boolean;
  /** 免登录的公开功能 key（requireLogin=true 时白名单） */
  publicKeys?: string[];
  /** 受限功能点击回调（弹登录引导） */
  onLogin?: () => void;
}

const HANDLE_PAGE: Record<string, (path: string) => void> = {
  tab: (path) => Taro.switchTab({ url: path }),
  page: (path) => Taro.navigateTo({ url: path }),
};

function handleClick(item: QuickItem, ctx?: QuickAccessProps): void {
  // 需登录且当前项不在公开白名单 → 引导登录，不直接跳转
  if (ctx?.requireLogin && !(ctx.publicKeys || []).includes(item.key)) {
    ctx.onLogin?.();
    return;
  }
  if (item.action && item.pagePath && HANDLE_PAGE[item.action]) {
    HANDLE_PAGE[item.action](item.pagePath);
    return;
  }
  // 后端尚无支撑的能力：明确提示"等待学校开放接口"，不假装有数据
  Taro.showToast({ title: '等待学校开放接口', icon: 'none' });
}

/**
 * 常用功能宫格（原型图核心模块）
 * - 点击有真实业务的（课表/电量/通知公告/天气）跳对应页面
 * - 学校侧尚未接入的（校园卡/空闲教室/校历查询）跳各自占位页，页面空态提示"暂无最新数据"
 * - 原「更多功能」为无落地页的占位项（点击仅 toast 提示），已移除
 */
export default function QuickAccess({ items = DEFAULT_ITEMS, title = '常用功能', requireLogin, publicKeys, onLogin }: QuickAccessProps) {
  const ctx: QuickAccessProps = { requireLogin, publicKeys, onLogin };
  return (
    <View className="card quick-access">
      <View className="card-header">
        <Text className="card-title">{title}</Text>
      </View>
      <View className="quick-grid">
        {items.map((item) => (
          <View key={item.key} className="quick-cell" onClick={() => handleClick(item, ctx)}>
            <View className="quick-icon-wrap">
              <Text className={`iconfont icon-${item.icon}`} />
            </View>
            <Text className="quick-label">{item.label}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}