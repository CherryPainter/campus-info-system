/// <reference types="vite/client" />

/**
 * Vite 环境变量类型声明
 * 扩展 ImportMeta 接口以支持自定义环境变量
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  /** ICP 备案号（如 蜀ICP备2026034112号-1），部署时在 .env.local 配置 */
  readonly VITE_BEIAN_ICP?: string;
  /** 公安联网备案号（如 川公网安备51052402000130号），部署时在 .env.local 配置 */
  readonly VITE_BEIAN_MPS?: string;
  /** 联系邮箱，部署时在 .env.local 配置 */
  readonly VITE_CONTACT_EMAIL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
