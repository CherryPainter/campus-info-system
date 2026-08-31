import type { ReactNode } from 'react';
import { useLaunch } from '@tarojs/taro';

// 全局样式
import './styles/common.scss';
import './styles/theme.scss';
// 全局图标字体（iconfont：校园宜知行）
import './styles/iconfont.scss';
// NutUI React Taro 全量样式（按需加载可在 nutui 配置中开启）
import '@nutui/nutui-react-taro/dist/style.css';

function App({ children }: { children: ReactNode }) {
  useLaunch(() => {
    console.log('[miniapp] 校园宜知行小程序启动');
  });

  return <>{children}</>;
}

export default App;
