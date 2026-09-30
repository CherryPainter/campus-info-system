import { View } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';
import FeaturePlaceholder from '@/components/FeaturePlaceholder';
import './index.scss';

/**
 * 校园卡（宫格入口，独立占位页）
 *
 * 校园卡在线服务（余额查询/流水/支付）学校侧尚未接入后端接口，
 * 进入本页仅作空态提示，避免首页宫格出现"点了没反应"的假功能。
 * 后端有支撑后在此页填充真实业务。
 */
export default function CampusCardPage() {
  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '校园卡' });
  });

  return (
    <View className="campus-card-page">
      <FeaturePlaceholder
        title="校园卡 · 筹备中"
        text="校园卡在线服务（余额、流水、支付）学校侧暂未开放接口，接入后在这里提供。"
      />
    </View>
  );
}

export const config = {
  navigationBarTitleText: '校园卡',
};
