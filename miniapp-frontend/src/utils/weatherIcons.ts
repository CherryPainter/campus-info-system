import sunIcon from '@/assets/weather/sun.png';
import sunCloudIcon from '@/assets/weather/sun-cloud.png';
import cloudIcon from '@/assets/weather/cloud.png';
import rainIcon from '@/assets/weather/rain.png';
import heavyRainIcon from '@/assets/weather/heavy-rain.png';
import snowIcon from '@/assets/weather/snow.png';
import thunderIcon from '@/assets/weather/thunder.png';
import fogIcon from '@/assets/weather/fog.png';

// 深色背景版（天气页渐变底用）：灰色部件转白、彩色部件（太阳橙/雨滴蓝/闪电黄）保留，
// 由 tools/gen_weather_icons.py 与彩色版一并生成
import sunOnDark from '@/assets/weather/on-dark/sun.png';
import sunCloudOnDark from '@/assets/weather/on-dark/sun-cloud.png';
import cloudOnDark from '@/assets/weather/on-dark/cloud.png';
import rainOnDark from '@/assets/weather/on-dark/rain.png';
import heavyRainOnDark from '@/assets/weather/on-dark/heavy-rain.png';
import snowOnDark from '@/assets/weather/on-dark/snow.png';
import thunderOnDark from '@/assets/weather/on-dark/thunder.png';
import fogOnDark from '@/assets/weather/on-dark/fog.png';

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

/** 深色背景版图标：天气页（深色渐变背景）专用，直接引用预生成 PNG（规则见 gen_weather_icons.py） */
const ON_DARK_ICONS: Record<WeatherIconKey, string> = {
  sun: sunOnDark,
  'sun-cloud': sunCloudOnDark,
  cloud: cloudOnDark,
  rain: rainOnDark,
  'heavy-rain': heavyRainOnDark,
  snow: snowOnDark,
  thunder: thunderOnDark,
  fog: fogOnDark,
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
 * 深色背景版图标资源（天气页渐变底专用）。
 *
 * 与彩色版的差别：**只把灰色部件（云/雾/雪）转成纯白**，彩色部件原样保留
 * —— 太阳仍是橙色 #FFB300、雨滴仍是蓝色 #29B6F6、闪电仍是黄色 #FFCA28。
 * 灰色云在深色底上会"融为一体"（用户反馈的原话），而太阳/闪电若一并填白则失去
 * 辨识度，所以只白化前者（贴近 iOS 天气的分层做法）。判定用 HSV 饱和度，见生成脚本。
 *
 * 为什么不做「运行时白化」：小程序 Canvas 2D 对 `ctx.filter` 支持不完整，部分机型/
 * 基础库会静默忽略；离屏 canvas 合成也依赖 `createOffscreenCanvas` 可用性，属不确定
 * 路径。改为直接使用构建期预生成的 PNG，结果与设备、基础库彻底无关。
 * 彩色版仍供浅色背景（首页天气小卡）使用，见 getWeatherIconSrc。
 */
export function getWeatherIconSrcOnDark(text?: string | null): string {
  return ON_DARK_ICONS[textToIconKey(text)];
}
