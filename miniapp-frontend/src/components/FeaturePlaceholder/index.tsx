import { View, Text } from '@tarojs/components';

import './index.scss';

interface FeaturePlaceholderProps {
  /** 居中的一句提示文字 */
  text?: string;
}

/**
 * 未开放功能的占位页组件
 *
 * 用于宫格中点击暂无可支撑接口的单项：进入真实页面，主体仅居中一句灰字提示，
 * 避免首页宫格出现"点了没反应"的假功能。无接口能力，故不做图标/多行说明等冗余。
 */
export default function FeaturePlaceholder({ text = '暂时没有最新数据' }: FeaturePlaceholderProps) {
  return (
    <View className="fp-wrap">
      <Text className="fp-text">{text}</Text>
    </View>
  );
}
