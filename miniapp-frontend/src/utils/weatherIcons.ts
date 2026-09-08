import sunIcon from '@/assets/weather/sun.png';
import sunCloudIcon from '@/assets/weather/sun-cloud.png';
import cloudIcon from '@/assets/weather/cloud.png';
import rainIcon from '@/assets/weather/rain.png';
import heavyRainIcon from '@/assets/weather/heavy-rain.png';
import snowIcon from '@/assets/weather/snow.png';
import thunderIcon from '@/assets/weather/thunder.png';
import fogIcon from '@/assets/weather/fog.png';

export type WeatherIconKey =
  | 'sun'
  | 'sun-cloud'
  | 'cloud'
  | 'rain'
  | 'heavy-rain'
  | 'snow'
  | 'thunder'
  | 'fog';

const ICONS: Record<WeatherIconKey, string> = {
  sun: sunIcon,
  'sun-cloud': sunCloudIcon,
  cloud: cloudIcon,
  rain: rainIcon,
  'heavy-rain': heavyRainIcon,
  snow: snowIcon,
  thunder: thunderIcon,
  fog: fogIcon,
};

/**
 * 把和风天气中文状况（如"晴"、"多云"）映射到统一图标 key。
 * 逻辑与此前 emoji 映射保持一致，保证晴天/多云/雨/雪/雷/雾霾都有图标。
 */
export function textToIconKey(text?: string | null): WeatherIconKey {
  if (!text) return 'sun-cloud';
  if (text.includes('晴')) return text.includes('多云') ? 'sun-cloud' : 'sun';
  if (text.includes('雷')) return 'thunder';
  if (text.includes('雨')) return text.includes('大雨') || text.includes('暴雨') ? 'heavy-rain' : 'rain';
  if (text.includes('雪')) return 'snow';
  if (text.includes('云') || text.includes('阴')) return 'cloud';
  if (text.includes('雾') || text.includes('霾')) return 'fog';
  return 'sun-cloud';
}

/**
 * 直接返回可传给 Taro <Image src> 或 canvas drawImage 的本地资源字符串。
 * Taro 编译后会是 base64（小图）或文件路径，微信端均正常渲染。
 */
export function getWeatherIconSrc(text?: string | null): string {
  return ICONS[textToIconKey(text)];
}
