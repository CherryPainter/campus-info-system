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
 * 后端目前没有任何校园卡接口（充值/积分明细/交易记录/卡片挂失）。
 * 为避免审核涉"充值/余额"等金融观感，卡面不展示余额金额：
 * - 右侧原"余额（元）"改为"积分"占位 "--"
 * - 原"充值"按钮文案改为"明细"（去金融字眼，仍保留"查看卡内情况"的意会）
 * 三个操作按钮点击均 toast"等待学校开放接口"，不虚构数据。
 * 后端就绪后替换为真实数据与路由。
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
          <Text className="campus-balance-label">积分</Text>
          <Text className="campus-balance-value">--</Text>
        </View>
      </View>
      <View className="campus-actions">
        <View
          className="campus-action"
          onClick={() => Taro.showToast({ title: '等待学校开放接口', icon: 'none' })}
        >
          <Text className="iconfont icon-RectangleCopy campus-action-icon" />
          <Text className="campus-action-text">明细</Text>
        </View>
        <View
          className="campus-action"
          onClick={() => Taro.showToast({ title: '等待学校开放接口', icon: 'none' })}
        >
          <Text className="iconfont icon-RectangleCopy1 campus-action-icon" />
          <Text className="campus-action-text">交易记录</Text>
        </View>
        <View
          className="campus-action"
          onClick={() => Taro.showToast({ title: '等待学校开放接口', icon: 'none' })}
        >
          <Text className="iconfont icon-zhanghuguashi campus-action-icon" />
          <Text className="campus-action-text">卡片挂失</Text>
        </View>
      </View>
    </View>
  );
}
