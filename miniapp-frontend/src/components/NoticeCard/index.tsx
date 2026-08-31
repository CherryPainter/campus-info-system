import { View, Text } from '@tarojs/components';
import { Icon } from '@nutui/nutui-react-taro';

import './index.scss';

/**
 * 校园通知占位卡片
 * - 后端 notification 接口尚未实现（勿虚构数据）
 * - 接口就绪后替换为真实列表（最多 3 条，其余进通知页）
 */
export default function NoticeCard() {
  return (
    <View className="card notice-card">
      <View className="card-header">
        <Text className="card-title">校园通知</Text>
      </View>
      <View className="notice-empty">
        <Icon name="notice" size={32} color="#c8ccd4" />
        <Text className="notice-text">通知功能开发中，敬请期待</Text>
      </View>
    </View>
  );
}
