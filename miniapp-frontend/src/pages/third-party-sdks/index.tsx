import { View, Text } from '@tarojs/components';

import './index.scss';

/**
 * 第三方 SDK 列表
 * 列出本小程序接入的第三方 SDK 及其用途，供用户查阅。
 */

interface SdkItem {
  name: string;
  desc: string;
  provider: string;
}

const SDKS: SdkItem[] = [
  {
    name: '微信原生 SDK',
    desc: '用于微信小程序登录、用户信息授权、页面导航、消息订阅、扫码等基础能力。',
    provider: '腾讯',
  },
  {
    name: 'Taro',
    desc: '跨端开发框架，用于将 React 代码编译为微信小程序运行时代码。',
    provider: '京东凹凸实验室',
  },
  {
    name: 'NutUI React for Taro',
    desc: 'UI 组件库，用于弹窗、图标、开关等交互组件。',
    provider: '京东',
  },
  {
    name: 'dayjs',
    desc: '日期处理库，用于课表、消息时间等日期格式化与计算。',
    provider: 'iamkun',
  },
  {
    name: 'zustand',
    desc: '状态管理库，用于登录态、用户资料、消息提醒设置等全局状态。',
    provider: 'poimandres',
  },
];

export default function ThirdPartySdksPage() {
  return (
    <View className="sdks-page">
      <View className="sdks-card">
        <Text className="sdks-intro">
          为保障小程序基础功能与体验，我们接入了以下第三方 SDK。各 SDK 仅收集实现其功能所必需的信息，我们不会向任何第三方共享您的个人身份信息。
        </Text>
        {SDKS.map((sdk) => (
          <View key={sdk.name} className="sdks-item">
            <Text className="sdks-name">{sdk.name}</Text>
            <Text className="sdks-desc">{sdk.desc}</Text>
            <Text className="sdks-link">提供方：{sdk.provider}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}
