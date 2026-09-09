import { useCallback, useState } from 'react';

import LoginModal from '@/components/LoginModal';
import { useAuthStore } from '@/stores/authStore';

/**
 * 登录守卫：包装一个需要登录的操作。
 * - 已登录 → 直接执行 action
 * - 未登录 → 弹出 LoginModal（点"确定"跳登录页，点"取消"放弃）
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
      } else {
        setVisible(true);
      }
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
