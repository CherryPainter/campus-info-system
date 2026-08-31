import { View, Text } from '@tarojs/components';

import type { ElectricityCurrent } from '@/types/api';
import './index.scss';

interface ElectricityCardProps {
  electricity: ElectricityCurrent | null;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
}

/**
 * 宿舍电量卡片
 * - 展示字段严格以后端 electricity/current 返回为准（remaining/percentage/is_low_power）
 * - 后端无宿舍号/本月已用维度 → 不虚构；电量数据属于当前用户/宿舍范围（后端单电表）
 */
export default function ElectricityCard({
  electricity,
  loading,
  error,
  onRetry,
}: ElectricityCardProps) {
  if (loading) {
    return (
      <View className="card electricity-card">
        <Text className="electricity-title">宿舍电量</Text>
        <Text className="electricity-sub">加载中…</Text>
      </View>
    );
  }

  if (error || !electricity) {
    return (
      <View className="card electricity-card" onClick={onRetry}>
        <Text className="electricity-title">宿舍电量</Text>
        <Text className="electricity-sub">暂时无法获取，点击重试</Text>
      </View>
    );
  }

  const pct = Math.max(0, Math.min(100, electricity.percentage || 0));

  return (
    <View className="card electricity-card">
      <View className="electricity-head">
        <Text className="electricity-title">宿舍电量</Text>
        <Text className={`tag ${electricity.is_low_power ? 'tag-warning' : 'tag-success'}`}>
          {electricity.is_low_power ? '电量偏低' : '剩余正常'}
        </Text>
      </View>
      <View className="electricity-main">
        <Text className="electricity-value">{electricity.remaining ?? '--'}</Text>
        <Text className="electricity-unit">kWh</Text>
      </View>
      <View className="electricity-bar">
        <View className="electricity-bar-inner" style={{ width: `${pct}%` }} />
      </View>
      <Text className="electricity-sub">剩余 {Math.round(pct)}%</Text>
    </View>
  );
}
