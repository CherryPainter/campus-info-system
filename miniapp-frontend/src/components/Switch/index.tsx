import { View } from '@tarojs/components';

import './index.scss';

interface Props {
  /** 是否开启 */
  checked: boolean;
  /** 切换回调，返回新值 */
  onChange?: (value: boolean) => void;
  /** 是否禁用 */
  disabled?: boolean;
}

/**
 * 自绘 iOS 风格胶囊滑动开关（不依赖 NutUI 全量样式）
 *
 * 背景：本项目 NutUI 全量 style.css 未被 Taro 打包进小程序产物，导致 NutUI Switch
 * 没有外观（只渲染裸节点）。这里用纯 CSS 画一个胶囊 + 滑块的开关，
 * 点击切换，开启为绿色填充 + 滑块右移，关闭为灰色 + 滑块左移。
 */
export default function Switch({ checked, onChange, disabled }: Props) {
  const handleClick = () => {
    if (disabled) return;
    onChange?.(!checked);
  };

  return (
    <View
      className={`app-switch${checked ? ' is-on' : ' is-off'}${disabled ? ' is-disabled' : ''}`}
      onClick={handleClick}
      hoverClass={disabled ? '' : 'app-switch-hover'}
    >
      <View className="app-switch-knob" />
    </View>
  );
}
