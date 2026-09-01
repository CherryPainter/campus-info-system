import type { ReactNode } from 'react';
import { useLaunch } from '@tarojs/taro';

// 全局样式
import './styles/common.scss';
import './styles/theme.scss';
// 全局图标字体（iconfont：校园宜知行）
import './styles/iconfont.scss';
// NutUI React Taro 全量样式（按需加载可在 nutui 配置中开启）
import '@nutui/nutui-react-taro/dist/style.css';

import { useFeedbackBadge } from '@/hooks/useFeedbackBadge';

function App({ children }: { children: ReactNode }) {
  const { refresh: refreshFeedbackBadge } = useFeedbackBadge();

  useLaunch(() => {
    console.log('[miniapp] 校园宜知行小程序启动');
    // 预取反馈未读数并写入模块级共享状态：冷启动时 TabBar「我的」角标即可显示，
    // 无需先进入「我的」页。未登录（登录页）时拉取失败会被 hook 吞掉，不影响主流程。
    refreshFeedbackBadge();
  });

  return <>{children}</>;
}

export default App;
