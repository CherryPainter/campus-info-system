/**
 * Taro 3 babel 配置（官方模板方案）
 * - 使用 babel-preset-taro，框架与 TS 在 preset 参数里声明，
 *   JSX → 小程序模板的转换由 preset 内置完成。
 */
module.exports = {
  presets: [
    [
      'taro',
      {
        framework: 'react',
        ts: true,
      },
    ],
  ],
};
