import { View } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';
import FeaturePlaceholder from '@/components/FeaturePlaceholder';
import './index.scss';

/**
 * 校历查询（宫格入口，独立占位页）
 *
 * 整学期校历（开学/放假/考试安排）数据后端尚未接入，
 * 进入本页仅作空态提示。后端有支撑后在此页填充真实校历。
 */
export default function CalendarPage() {
  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '校历查询' });
  });

  return (
    <View className="calendar-page">
      <FeaturePlaceholder
        title="校历查询 · 筹备中"
        text="校历（开学、放假、考试安排）校方暂未开放数据接口，接入后第一时间在这里更新。"
      />
    </View>
  );
}

export const config = {
  navigationBarTitleText: '校历查询',
};
