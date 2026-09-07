import { View } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';
import FeaturePlaceholder from '@/components/FeaturePlaceholder';
import './index.scss';

/**
 * 空闲教室（宫格入口，独立占位页）
 *
 * 空闲教室查询依赖教务实时课室占用数据，后端尚未接入，
 * 进入本页仅作空态提示。后端有支撑后在此页填充真实查询。
 */
export default function ClassroomPage() {
  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '空闲教室' });
  });

  return (
    <View className="classroom-page">
      <FeaturePlaceholder />
    </View>
  );
}

export const config = {
  navigationBarTitleText: '空闲教室',
};
