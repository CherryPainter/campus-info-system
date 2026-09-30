import { View, Text } from '@tarojs/components';

import './index.scss';

interface FeaturePlaceholderProps {
  /** 主标题，建议带功能名，如「校历查询 · 筹备中」 */
  title?: string;
  /** 诚实的一句说明：为什么暂无数据 / 何时会有，不编造已实现的能力 */
  text?: string;
}

/**
 * 未开放功能的占位页组件
 *
 * 用于宫格中点击暂无可支撑接口的单项：进入真实页面，主体居中展示
 * 「功能筹备中」空态（纯 CSS 矢量插图，无 emoji）+ 一句诚实说明，
 * 避免首页宫格出现"点了没反应"的假功能，也避免塞假数据糊弄。
 * 后端接入后，直接在本页填充真实业务即可，无需改动宫格入口。
 */
export default function FeaturePlaceholder({
  title = '功能筹备中',
  text = '校方暂未开放相关接口，接入后第一时间在这里更新。',
}: FeaturePlaceholderProps) {
  return (
    <View className="fp-wrap">
      <View className="fp-illust">
        <View className="fp-status-dot" />
      </View>
      <Text className="fp-title">{title}</Text>
      <Text className="fp-text">{text}</Text>
    </View>
  );
}
