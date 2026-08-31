import type { UserConfigExport } from '@tarojs/cli';

/**
 * 生产环境配置
 * - 编译时由 config/index.ts 合并
 */
export default {
  mini: {},
  h5: {},
} satisfies UserConfigExport;
