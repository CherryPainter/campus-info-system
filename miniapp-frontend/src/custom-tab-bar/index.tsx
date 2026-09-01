import { useState, useEffect } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import { getSharedBadgeCount } from '@/utils/feedbackBadge';
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
 * 特性：
 * - 三个 tab（首页 / 时间轴 / 我的），图标与原生一致
 * - 「我的」tab 右上角显示反馈未读角标（红色圆圈数字，0 时隐藏）
 * - 角标通过 Taro.eventCenter 实时更新（profile 页 useFeedbackBadge 刷新后触发）
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
  const [current, setCurrent] = useState(0);
  const [badge, setBadge] = useState(0);

  // 挂载时读初始 badge + 监听实时更新事件
  useEffect(() => {
    setBadge(getSharedBadgeCount());
    const handler = (n: number) => setBadge(n);
    Taro.eventCenter.on(BADGE_EVENT, handler);
    return () => Taro.eventCenter.off(BADGE_EVENT, handler);
  }, []);

  // 每次 tab 显示（切 tab / 从子页面返回）时刷新高亮和 badge
  useDidShow(() => {
    const pages = Taro.getCurrentPages();
    const curPage = pages[pages.length - 1];
    const route = '/' + (curPage?.route || '');
    const idx = TAB_LIST.findIndex((t) => route === t.pagePath || route.startsWith(t.pagePath + '/'));
    if (idx >= 0) setCurrent(idx);
    setBadge(getSharedBadgeCount());
  });

  const switchTab = (idx: number) => {
    if (idx === current) return;
    setCurrent(idx);
    Taro.switchTab({ url: TAB_LIST[idx].pagePath });
  };

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
          {/* 「我的」tab 角标：反馈未读数 */}
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
