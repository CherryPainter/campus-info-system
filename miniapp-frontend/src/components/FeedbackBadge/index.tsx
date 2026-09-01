import { View, Text } from '@tarojs/components';
import './index.scss';

interface Props {
  /** 未读数量；<=0 时不渲染 */
  count: number;
}

/**
 * 红色圆形未读计数红点
 * - count <= 0：不渲染（满足"没有不显示"）
 * - count > 99：显示 99+
 */
export default function FeedbackBadge({ count }: Props) {
  if (!count || count < 1) return null;
  return (
    <View className="fb-badge">
      <Text className="fb-badge-num">{count > 99 ? '99+' : count}</Text>
    </View>
  );
}
