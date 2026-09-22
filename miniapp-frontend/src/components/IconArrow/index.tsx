import { View } from '@tarojs/components';

import './index.scss';

export type ArrowDirection = 'right' | 'left' | 'up' | 'down';
export type ArrowSize = 'sm' | 'md' | 'lg';

interface IconArrowProps {
  /** 指向方向，默认 right */
  direction?: ArrowDirection;
  /** 尺寸档：sm 配 22-24rpx 文字 / md（默认）配 28-32rpx / lg 配 36-40rpx */
  size?: ArrowSize;
  /** 追加类名：颜色（color）与外边距（margin）由调用方在自己的 scss 里设置 */
  className?: string;
}

/**
 * 箭头图标（纯 CSS 矢量，不依赖任何字体）
 *
 * 为什么不用文本字符（› / ‹ / >）：
 * 用户可自定义字体（font-family）与字号，文本字符的字形、粗细、基线会被
 * 一并改写，观感不稳定。本组件用 border-top + border-right + rotate 画线，
 * 显示效果只由 CSS 决定，与用户字体完全无关。
 *
 * - 颜色：描边用 currentColor，继承所在元素的 color，页面只需设 color 即可。
 * - 尺寸：sm / md / lg 三档，见 index.scss。
 */
export default function IconArrow({
  direction = 'right',
  size = 'md',
  className = '',
}: IconArrowProps) {
  const cls = ['icon-arrow', `icon-arrow--${size}`, `is-${direction}`, className]
    .filter(Boolean)
    .join(' ');

  return <View className={cls} />;
}
