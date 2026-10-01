import { useState, useEffect } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import { getSharedBadgeCount } from '@/utils/feedbackBadge';
import {
  getTabIndex,
  setTabIndex,
  TAB_INDEX_EVENT,
  getTabBarHidden,
  TABBAR_HIDDEN_EVENT,
} from '@/utils/tabBarState';
import homeIcon from '@/assets/tabbar/home.png';
import homeActiveIcon from '@/assets/tabbar/home-active.png';
import timelineIcon from '@/assets/tabbar/timeline.png';
import timelineActiveIcon from '@/assets/tabbar/timeline-active.png';
import profileIcon from '@/assets/tabbar/profile.png';
import profileActiveIcon from '@/assets/tabbar/profile-active.png';
import './index.scss';

/**
 * 自定义底部 TabBar（框架级组件，替换原生 TabBar）
 *
 * app.config.ts 设置 tabBar.custom=true 后，微信自动渲染本组件为底部导航栏。
 * 不需要在各 tab 页手动引入（框架自动挂载）。
 *
 * 选中态策略（修复「点一下短暂选中又跳回首页 / 要两次才选中」）：
 * - 选中的 tab 下标存在模块级共享状态（tabBarState），不依赖组件 useState 生命周期；
 * - 切换时 update 模块态并广播，组件订阅事件实时同步 setCurrent；
 * - 每个 tab 页在 useDidShow 时广播自己的下标，保证任何进入路径（含其它页 switchTab 直达）都一致；
 * - 因此即使组件被框架重建、useState 回到初值，也会立刻被事件/挂载初值修正。
 */

interface TabItem {
  pagePath: string;
  text: string;
  icon: string;
  activeIcon: string;
}

const TAB_LIST: TabItem[] = [
  { pagePath: '/pages/home/index', text: '首页', icon: homeIcon, activeIcon: homeActiveIcon },
  { pagePath: '/pages/schedule/index', text: '时间轴', icon: timelineIcon, activeIcon: timelineActiveIcon },
  { pagePath: '/pages/profile/index', text: '我的', icon: profileIcon, activeIcon: profileActiveIcon },
];

const BADGE_EVENT = 'feedback:badge';

export default function CustomTabBar() {
  // 初值取模块级选中态（而非硬编码 0），避免重建后闪烁回首页
  const [current, setCurrent] = useState<number>(() => getTabIndex());
  const [badge, setBadge] = useState<number>(() => getSharedBadgeCount());
  // 是否隐藏：用于"全屏弹窗/抽屉"等场景临时藏起（custom tabBar 不能用 wx.hideTabBar 控制）
  const [hidden, setHidden] = useState<boolean>(() => getTabBarHidden());

  // 挂载：订阅选中态广播 + 角标广播 + 显隐广播；卸载时解绑
  useEffect(() => {
    const onTabIndex = (idx: number) => setCurrent(idx);
    const onBadge = (n: number) => setBadge(n);
    const onHidden = (h: boolean) => setHidden(h);
    Taro.eventCenter.on(TAB_INDEX_EVENT, onTabIndex);
    Taro.eventCenter.on(BADGE_EVENT, onBadge);
    Taro.eventCenter.on(TABBAR_HIDDEN_EVENT, onHidden);
    return () => {
      Taro.eventCenter.off(TAB_INDEX_EVENT, onTabIndex);
      Taro.eventCenter.off(BADGE_EVENT, onBadge);
      Taro.eventCenter.off(TABBAR_HIDDEN_EVENT, onHidden);
    };
  }, []);

  // 每次本组件随 tab 显示时（pageLifetimes.show），刷新角标 + 用模块态兜底修正选中
  // （不在此处依据路由回写 current，路由在切换过渡期会读到旧页面导致回退，已移除）
  useDidShow(() => {
    setBadge(getSharedBadgeCount());
    setCurrent(getTabIndex());
  });

  const switchTab = (idx: number) => {
    if (idx === current) return;
    setTabIndex(idx); // 更新模块态 + 广播 → setCurrent，跨重建也一致
    setCurrent(idx); // 乐观即时高亮
    Taro.switchTab({ url: TAB_LIST[idx].pagePath });
  };

  // 隐藏态：return null 即可不渲染。custom tabBar 不能靠 wx.hideTabBar 控，
  // 必须由组件自身 return null；外部通过 setTabBarHidden(true/false) 触发。
  if (hidden) return null;

  return (
    <View className="custom-tabbar">
      {TAB_LIST.map((tab, idx) => (
        <View
          key={tab.pagePath}
          className={`custom-tabbar-item ${idx === current ? 'custom-tabbar-active' : ''}`}
          onClick={() => switchTab(idx)}
        >
          <Image
            className="custom-tabbar-icon"
            src={idx === current ? tab.activeIcon : tab.icon}
            mode="aspectFit"
          />
          {/* 「我的」tab 角标：消息未读总数（站内通知 + 公告；反馈状态通知也在其中） */}
          {idx === 2 && badge > 0 && (
            <View className="custom-tabbar-badge">
              <Text className="custom-tabbar-badge-text">{badge > 99 ? '99+' : badge}</Text>
            </View>
          )}
          <Text className={`custom-tabbar-text ${idx === current ? 'custom-tabbar-text-active' : ''}`}>
            {tab.text}
          </Text>
        </View>
      ))}
    </View>
  );
}
