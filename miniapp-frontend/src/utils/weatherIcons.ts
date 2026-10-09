import sunIcon from '@/assets/weather/sun.png';
import sunCloudIcon from '@/assets/weather/sun-cloud.png';
import cloudIcon from '@/assets/weather/cloud.png';
import rainIcon from '@/assets/weather/rain.png';
import heavyRainIcon from '@/assets/weather/heavy-rain.png';
import snowIcon from '@/assets/weather/snow.png';
import thunderIcon from '@/assets/weather/thunder.png';
import fogIcon from '@/assets/weather/fog.png';

// 白色版（深色背景专用）：与彩色版同形状、纯白填充，由 tools/gen_weather_icons.py 一并生成
import sunWhite from '@/assets/weather/white/sun.png';
import sunCloudWhite from '@/assets/weather/white/sun-cloud.png';
import cloudWhite from '@/assets/weather/white/cloud.png';
import rainWhite from '@/assets/weather/white/rain.png';
import heavyRainWhite from '@/assets/weather/white/heavy-rain.png';
import snowWhite from '@/assets/weather/white/snow.png';
import thunderWhite from '@/assets/weather/white/thunder.png';
import fogWhite from '@/assets/weather/white/fog.png';

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

/** 白色版图标：天气页（深色渐变背景）专用，直接引用预白化 PNG */
const WHITE_ICONS: Record<WeatherIconKey, string> = {
  sun: sunWhite,
  'sun-cloud': sunCloudWhite,
  cloud: cloudWhite,
  rain: rainWhite,
  'heavy-rain': heavyRainWhite,
  snow: snowWhite,
  thunder: thunderWhite,
  fog: fogWhite,
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

/**
 * 白色版图标资源（深色背景专用，如天气页渐变底）。
 *
 * 为什么不做「运行时白化」：小程序 Canvas 2D 对 `ctx.filter` 支持不完整，部分机型/
 * 基础库会静默忽略；离屏 canvas 合成（source-in 填白）也依赖 `createOffscreenCanvas`
 * 可用性，属不确定路径。改为直接使用预生成的纯白 PNG，等价于把白化前置到构建期，
 * 结果与设备、基础库彻底无关。
 * 彩色版仍供浅色背景（首页天气小卡）使用，见 getWeatherIconSrc。
 */
export function getWeatherIconSrcWhite(text?: string | null): string {
  return WHITE_ICONS[textToIconKey(text)];
}
