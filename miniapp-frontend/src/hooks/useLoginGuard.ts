import { useCallback, useState } from 'react';
import Taro from '@tarojs/taro';

import LoginModal from '@/components/LoginModal';
import { useAuthStore } from '@/stores/authStore';

/**
 * 私有模块点击累计次数（模块级，冷启动归零）
 *
 * 用途：游客点私有模块时先给气泡提示，累计到阈值才弹一次登录弹窗，
 * 避免"点一下就弹窗"被微信审核判定为「反复弹窗 / 强制用户登录才能体验」。
 */
let privateClickCount = 0;

/** 弹窗阈值：累计点击 N 次后弹一次登录弹窗（弹完归零，下一轮重新累计） */
export const PRIVATE_CLICK_THRESHOLD = 3;

/** 登录成功 / 用户主动进入登录流程后清零累计次数 */
export function resetPrivateClickCount(): void {
  privateClickCount = 0;
}

/**
 * 非 hook 场景（如首页宫格回调、卡片"更多"等不方便挂 hook 的地方）复用同一套逻辑：
 * 未登录时前 N-1 次气泡提示，第 N 次执行 onThreshold（通常是打开登录弹窗）。
 */
export function runPrivateClick(onThreshold: () => void): void {
  privateClickCount += 1;
  if (privateClickCount >= PRIVATE_CLICK_THRESHOLD) {
    privateClickCount = 0;
    onThreshold();
    return;
  }
  Taro.showToast({ title: '该功能需登录后使用', icon: 'none', duration: 1500 });
}

/**
 * 登录守卫：包装一个需要登录的操作。
 * - 已登录 → 直接执行 action
 * - 未登录 → 前 N-1 次只出气泡提示（toast，不打断浏览）；第 N 次才弹 LoginModal，
 *   弹完立即归零重新累计（即「累计弹窗」：普通点击用气泡，够次数才弹窗）
 *
 * 设计取舍：点"确定"只跳登录页，**不**自动重放 action。
 * 原因：被守卫的动作多为路由跳转/状态切换，重放容易触发副作用重复。
 * 登录成功后用户重新点击即可——这是"先体验后授权"合规下的常规交互。
 *
 * 用法：
 *   const { guard, modalProps } = useLoginGuard();
 *   const handleClick = () => guard(() => Taro.navigateTo({ url: '/pages/xxx/index' }));
 *   <View onClick={handleClick}>点我</View>
 *   <LoginModal {...modalProps} />
 */
export function useLoginGuard() {
  const { isLoggedIn } = useAuthStore();
  const [visible, setVisible] = useState(false);

  const guard = useCallback(
    (action: () => void) => {
      if (isLoggedIn) {
        action();
        return;
      }
      privateClickCount += 1;
      if (privateClickCount >= PRIVATE_CLICK_THRESHOLD) {
        // 够次数 → 弹一次并归零，下一轮又是 N-1 次气泡
        privateClickCount = 0;
        setVisible(true);
        return;
      }
      // 普通点击 → 气泡提示，不弹窗、不打断浏览
      Taro.showToast({ title: '该功能需登录后使用', icon: 'none', duration: 1500 });
    },
    [isLoggedIn],
  );

  return {
    guard,
    modalProps: {
      visible,
      onCancel: () => setVisible(false),
    },
  };
}
