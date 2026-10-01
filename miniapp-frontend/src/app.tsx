import type { ReactNode } from 'react';
import { useLaunch } from '@tarojs/taro';

// 全局样式
import './styles/common.scss';
import './styles/theme.scss';
// 全局图标字体（iconfont：校园宜知行）
import './styles/iconfont.scss';
// NutUI React Taro 全量样式（按需加载可在 nutui 配置中开启）
import '@nutui/nutui-react-taro/dist/style.css';

import * as notificationsApi from '@/api/notifications';
import { useAuthStore } from '@/stores/authStore';
import { useNotificationSettingsStore } from '@/stores/notificationSettingsStore';
import { setSharedBadgeCount } from '@/utils/feedbackBadge';

function App({ children }: { children: ReactNode }) {
  useLaunch(() => {
    console.log('[miniapp] 校园宜知行小程序启动');
    // 预取消息未读总数写入模块级共享状态：冷启动时 TabBar「我的」角标即可显示，
    // 无需先进入「我的」页。口径即消息未读（站内通知 + 公告）——反馈状态变更
    // 也会作为站内消息下发，故角标就是「消息未读总数」。
    // 未登录 / 未绑定 / 关闭提醒开关时不请求（失败静默，不影响启动）。
    const { isLoggedIn } = useAuthStore.getState();
    const { masterEnabled, announcement } = useNotificationSettingsStore.getState();
    if (!isLoggedIn || !masterEnabled || !announcement) return;
    notificationsApi
      .getUnreadCount()
      .then((res) => setSharedBadgeCount(res?.data?.total ?? 0))
      .catch(() => {
        /* 静默失败：进入「我的」页时会重新拉取 */
      });
  });

  return <>{children}</>;
}

export default App;
