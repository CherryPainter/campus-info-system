import { View, Text } from '@tarojs/components';
import { Icon } from '@nutui/nutui-react-taro';

interface EmptyStateProps {
  title: string;
  desc?: string;
}

/** 空数据状态（复用全局 .state-wrap 样式，文案从简不花哨） */
export default function EmptyState({ title, desc }: EmptyStateProps) {
  return (
    <View className="state-wrap">
      <Icon name="empty" size={40} color="#c8ccd4" />
      <Text className="state-title">{title}</Text>
      {desc ? <Text className="state-desc">{desc}</Text> : null}
    </View>
  );
}
