import { View, Text } from '@tarojs/components';

interface LoadingStateProps {
  text?: string;
}

/** 加载中状态（复用全局 .state-wrap 样式） */
export default function LoadingState({ text = '加载中…' }: LoadingStateProps) {
  return (
    <View className="state-wrap">
      <View className="loading-dot" />
      <Text className="state-title">{text}</Text>
    </View>
  );
}
