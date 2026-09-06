import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import './index.scss';

export interface QuickItem {
  key: string;
  label: string;
  icon: string;
  /** 点击行为：'tab' + pagePath → 跳 TabBar 页；'page' + pagePath → 跳普通页（需在 pages 注册）；否则弹"敬请期待" */
  action?: 'tab' | 'page';
  pagePath?: string;
}

export const DEFAULT_ITEMS: QuickItem[] = [
  { key: 'schedule', label: '课表查询', icon: 'kechengbiao', action: 'page', pagePath: '/pages/coursetable/index' },
  { key: 'electricity', label: '电量查询', icon: 'dianchi', action: 'page', pagePath: '/pages/electricity/index' },
  { key: 'card', label: '校园卡', icon: 'xiaoyuanqia-' },
  { key: 'notice', label: '通知公告', icon: 'tongzhi', action: 'page', pagePath: '/pages/announcement/index/index' },
  { key: 'classroom', label: '空闲教室', icon: 'kongxianjiaoshi' },
  { key: 'weather', label: '天气预报', icon: 'tianqi', action: 'page', pagePath: '/pages/weather/index' },
  { key: 'calendar2', label: '校历查询', icon: 'rili' },
  { key: 'more', label: '更多功能', icon: 'gengduogongneng_24' },
];

interface QuickAccessProps {
  items?: QuickItem[];
  title?: string;
}

const HANDLE_PAGE: Record<string, (path: string) => void> = {
  tab: (path) => Taro.switchTab({ url: path }),
  page: (path) => Taro.navigateTo({ url: path }),
};

function handleClick(item: QuickItem): void {
  if (item.action && item.pagePath && HANDLE_PAGE[item.action]) {
    HANDLE_PAGE[item.action](item.pagePath);
    return;
  }
  // 后端尚无支撑的能力：明确提示"敬请期待"，不假装有数据
  Taro.showToast({ title: '敬请期待', icon: 'none' });
}

/**
 * 常用功能 8 宫格（原型图核心模块）
 * - 点击有真实跳转目标的（如课表）走 Taro 路由
 * - 后端尚无对应能力的功能（校园卡/通知/空闲教室等）展示图标但不虚构数据，点击 toast"敬请期待"
 */
export default function QuickAccess({ items = DEFAULT_ITEMS, title = '常用功能' }: QuickAccessProps) {
  return (
    <View className="card quick-access">
      <View className="card-header">
        <Text className="card-title">{title}</Text>
        <Text className="card-more">自定义</Text>
      </View>
      <View className="quick-grid">
        {items.map((item) => (
          <View key={item.key} className="quick-cell" onClick={() => handleClick(item)}>
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