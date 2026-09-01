import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import './index.scss';

interface CampusCardProps {
  /** 校园卡号（一卡通号，与学号不同；未填写则不显示编号） */
  cardNumber?: string | null;
}

/**
 * 校园卡（蓝色卡，§14 + 原型图）
 * 卡片编号展示 campus_card_number（校园卡号），不再误用学号。
 * 后端目前没有任何校园卡接口（余额/充值/交易记录/卡片挂失），
 * 按"不虚构数据"原则：余额显示"--"+提示"未开通/敬请期待"，三个操作按钮点击 toast"敬请期待"。
 * 后端就绪后只需替换余额展示逻辑，三个按钮再接真实路由。
 */
export default function CampusCard({ cardNumber }: CampusCardProps) {
  return (
    <View className="campus-card">
      <View className="campus-top">
        <View>
          <Text className="campus-title">校园卡</Text>
          {cardNumber ? (
            <Text className="campus-no">No. {cardNumber}</Text>
          ) : (
            <Text className="campus-no campus-no-empty">未绑定校园卡号</Text>
          )}
        </View>
        <View className="campus-balance">
          <Text className="campus-balance-label">余额（元）</Text>
          <Text className="campus-balance-value">--</Text>
        </View>
      </View>
      <View className="campus-actions">
        <View
          className="campus-action"
          onClick={() => Taro.showToast({ title: '功能开发中', icon: 'none' })}
        >
          <Text className="iconfont icon-RectangleCopy campus-action-icon" />
          <Text className="campus-action-text">充值</Text>
        </View>
        <View
          className="campus-action"
          onClick={() => Taro.showToast({ title: '功能开发中', icon: 'none' })}
        >
          <Text className="iconfont icon-RectangleCopy1 campus-action-icon" />
          <Text className="campus-action-text">交易记录</Text>
        </View>
        <View
          className="campus-action"
          onClick={() => Taro.showToast({ title: '功能开发中', icon: 'none' })}
        >
          <Text className="iconfont icon-zhanghuguashi campus-action-icon" />
          <Text className="campus-action-text">卡片挂失</Text>
        </View>
      </View>
    </View>
  );
}
