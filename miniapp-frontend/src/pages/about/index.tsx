import { View, Text, Image } from '@tarojs/components';
import Taro from '@tarojs/taro';

import IconArrow from '@/components/IconArrow';
import logoPng from '@/assets/images/logo.png';
import { APP_VERSION } from '@/version';
import './index.scss';

/**
 * 关于页
 * 聚合小程序必要的条款与信息入口，不再用 showModal 弹框展示。
 */

interface AboutItem {
  label: string;
  value?: string;
  action?: () => void;
}

export default function AboutPage() {
  const items: AboutItem[] = [
    {
      label: '用户协议',
      action: () => Taro.navigateTo({ url: '/pages/user-agreement/index' }),
    },
    {
      label: '隐私政策',
      action: () => Taro.navigateTo({ url: '/pages/privacy-policy/index' }),
    },
    {
      label: '第三方 SDK 列表',
      action: () => Taro.navigateTo({ url: '/pages/third-party-sdks/index' }),
    },
    {
      label: '开源声明',
      action: () => Taro.navigateTo({ url: '/pages/open-source/index' }),
    },
    {
      label: '意见反馈',
      action: () => Taro.navigateTo({ url: '/pages/feedback/submit/index' }),
    },
  ];

  const infoItems: AboutItem[] = [
    { label: '版本号', value: APP_VERSION },
    { label: '客服邮箱', value: 'support@gelsomino.cn' },
    { label: '开发者', value: '校园信息聚合与智能推送系统团队' },
  ];

  return (
    <View className="about-page">
      <View className="about-header">
        <View className="about-logo">
          <Image className="about-logo-img" src={logoPng} mode="aspectFit" />
        </View>
        <Text className="about-name">校园宜知行</Text>
        <Text className="about-version">版本 {APP_VERSION}</Text>
      </View>

      <View className="about-card">
        {items.map((item, index) => (
          <View
            key={item.label}
            className="about-cell"
            onClick={item.action}
            style={{ borderBottom: index === items.length - 1 ? 'none' : undefined }}
          >
            <Text className="about-cell-label">{item.label}</Text>
            <IconArrow className="about-arrow" size="md" />
          </View>
        ))}
      </View>

      <View className="about-card">
        {infoItems.map((item, index) => (
          <View
            key={item.label}
            className="about-cell"
            style={{ borderBottom: index === infoItems.length - 1 ? 'none' : undefined }}
          >
            <Text className="about-cell-label">{item.label}</Text>
            <Text className="about-cell-value">{item.value}</Text>
          </View>
        ))}
      </View>

      <View className="about-footer">
        <Text className="about-footer-text">
          校园信息聚合与智能推送系统 · 微信小程序客户端
          {'\n'}仅供校内师生使用
        </Text>
      </View>
    </View>
  );
}
