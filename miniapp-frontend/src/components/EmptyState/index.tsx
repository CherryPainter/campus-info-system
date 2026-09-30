import { View, Text } from '@tarojs/components';

interface EmptyStateProps {
  title: string;
  desc?: string;
}

/**
 * 空数据状态（复用全局 .state-wrap 样式，文案从简不花哨）
 *
 * 图标用纯 CSS 矢量绘制（.state-icon，定义见 styles/theme.scss），
 * 不再使用 NutUI <Icon>：NutUI Icon 内部以 createElement('i', ...) 渲染一个
 * 运行时才确定的 <i> 标签，Taro 静态分析无法为其生成模板，会触发
 * 「Template tmpl_0_i not found」运行时报错（灰点无法渲染）。
 */
export default function EmptyState({ title, desc }: EmptyStateProps) {
  return (
    <View className="state-wrap">
      <View className="state-icon" />
      <Text className="state-title">{title}</Text>
      {desc ? <Text className="state-desc">{desc}</Text> : null}
    </View>
  );
}
