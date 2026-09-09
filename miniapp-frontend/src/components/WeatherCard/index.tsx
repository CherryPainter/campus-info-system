import { View, Text, Image } from '@tarojs/components';
import Taro from '@tarojs/taro';

import type { WeatherNow } from '@/types/api';
import { getWeatherIconSrc } from '@/utils/weatherIcons';
import './index.scss';

interface WeatherCardProps {
  weather: WeatherNow | null;
  /** 24 小时预报温度区间（最高/最低，来自 weather/hourly） */
  tempRange?: { min: number; max: number } | null;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
}

/**
 * 天气小卡（首页头部右侧，对照原型图布局）
 * - 顶部：当前温度（weather/current）+ 天气图标 PNG
 * - 底部：天气文字 + 24h 温度区间（weather/hourly 的最高/最低，原型图"多云 18°~26°"）
 * - 展示字段严格以后端实际返回为准，不虚构
 */
export default function WeatherCard({ weather, tempRange, loading, error, onRetry }: WeatherCardProps) {
  if (loading) {
    return (
      <View className="weather-mini weather-mini-skeleton">
        <Text className="weather-mini-temp">--°</Text>
        <Text className="weather-mini-text">加载中</Text>
      </View>
    );
  }

  if (error || !weather) {
    return (
      <View className="weather-mini weather-mini-error" onClick={onRetry}>
        <Text className="weather-mini-temp weather-mini-temp-dim">--°</Text>
        <Text className="weather-mini-text">点击重试</Text>
      </View>
    );
  }

  const temp = weather.temp != null ? Math.round(weather.temp) : '--';
  const text = weather.text || '未知';
  const rangeText =
    tempRange && tempRange.min != null && tempRange.max != null
      ? `${Math.round(tempRange.min)}°~${Math.round(tempRange.max)}°`
      : '';

  return (
    <View className="weather-mini" onClick={() => Taro.navigateTo({ url: '/pages/weather/index' })}>
      <View className="weather-mini-main">
        <Text className="weather-mini-temp">{temp}°</Text>
        <Image className="weather-mini-icon" src={getWeatherIconSrc(text)} mode="aspectFit" />
      </View>
      <View className="weather-mini-bottom">
        <Text className="weather-mini-text">
          {text}
          {rangeText ? ` ${rangeText}` : ''}
        </Text>
      </View>
    </View>
  );
}