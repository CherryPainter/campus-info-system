import { useCallback } from 'react';
import Taro from '@tarojs/taro';

import { useAuthStore } from '@/stores/authStore';

/**
 * 游客点击受限功能的统一气泡提示。
 *
 * 只提示、不弹窗、不累计计数（曾按「累计 3 次弹登录窗」设计，已按需求移除）：
 * 微信审核要求不得「反复弹窗或强制登录才能体验」，气泡提示属于最轻量的引导。
 */
export function toastLoginRequired(): void {
  Taro.showToast({ title: '该功能需登录后使用', icon: 'none', duration: 1500 });
}

/**
 * 登录守卫：包装一个需要登录的操作。
 * - 已登录 → 直接执行 action
 * - 未登录 → 气泡提示（登录入口由页面自身的显式登录按钮/卡片承担）
 *
 * 设计取舍：守卫只提示、**不**自动跳登录页，也**不**自动重放 action。
 * 原因：被守卫的动作多为路由跳转/状态切换，重放容易触发副作用重复；
 * 自动跳转登录页又会打断浏览（强制登录体验）。
 * 登录成功后用户重新点击即可。
 *
 * 用法：
 *   const { guard } = useLoginGuard();
 *   const handleClick = () => guard(() => Taro.navigateTo({ url: '/pages/xxx/index' }));
 */
export function useLoginGuard() {
  const { isLoggedIn } = useAuthStore();

  const guard = useCallback(
    (action: () => void) => {
      if (isLoggedIn) {
        action();
        return;
      }
      toastLoginRequired();
    },
    [isLoggedIn],
  );

  return { guard };
}
