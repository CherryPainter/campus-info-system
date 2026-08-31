import path from 'path';
import type { UserConfigExport } from '@tarojs/cli';
import devConfig from './dev';
import prodConfig from './prod';

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
  defineConstants: {},
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
