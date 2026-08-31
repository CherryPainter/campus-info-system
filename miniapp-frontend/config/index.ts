import fs from 'fs';
import path from 'path';
import type { UserConfigExport } from '@tarojs/cli';
import devConfig from './dev';
import prodConfig from './prod';

/**
 * 读取项目根目录 .env 中 TARO_APP_ 前缀变量，注入到编译产物。
 *
 * 背景：storage.ts / request.ts 通过 process.env.TARO_APP_* 读取 dev token 与后端地址，
 * 但 Taro 默认不会把 .env 注入小程序包（未装 @tarojs/plugin-dotenv，defineConstants 为空），
 * 导致 dev token 永远是 undefined → 请求不带 Authorization 头 → 接口 401。
 * 这里用 defineConstants 在构建期把变量替换成字面量，与官方 dotenv 插件行为一致，
 * 且不引入额外依赖。如需更完整的 .env 解析，可改回 @tarojs/plugin-dotenv。
 */
function loadTaroEnv(): Record<string, string> {
  const envPath = path.resolve(__dirname, '..', '.env');
  const result: Record<string, string> = {};
  if (!fs.existsSync(envPath)) return result;
  const content = fs.readFileSync(envPath, 'utf-8');
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const m = trimmed.match(/^(TARO_APP_\w+)\s*=\s*(.*)$/);
    if (m) {
      const value = m[2].replace(/^["']|["']$/g, '').trim();
      result[`process.env.${m[1]}`] = JSON.stringify(value);
    }
  }
  return result;
}

const config: UserConfigExport = {
  projectName: 'miniapp-frontend',
  date: '2026-8-27',
  designWidth: 750,
  deviceRatio: { '640': 2.34 / 2, '750': 1, '828': 1.81 / 2, '375': 2 / 1 },
  sourceRoot: 'src',
  outputRoot: 'dist',
  // @/ 别名与 tsconfig paths 保持一致（Taro 顶层 alias 字段，webpackChain 方式在此版本不生效）
  alias: {
    '@': path.resolve(__dirname, '..', 'src'),
  },
  defineConstants: loadTaroEnv(),
  copy: {
    patterns: [],
    options: {},
  },
  framework: 'react',
  compiler: 'webpack5',
  cache: {
    enable: false,
  },
  sass: {
    // 全局注入 Design Token 变量文件（页面 SCSS 可直接使用 $primary-color 等，无需手动 @import）
    resource: ['src/styles/variables.scss'],
  },
  mini: {
    postcss: {
      pxtransform: { enable: true, config: {} },
    },
  },
  h5: {
    publicPath: '/',
    staticDirectory: 'static',
    output: { filename: 'static/js/[name].[hash:8].js', chunkFilename: 'static/js/[name].[chunkhash:8].js' },
  },
};

export default process.env.NODE_ENV === 'development' ? { ...config, ...devConfig } : { ...config, ...prodConfig };
