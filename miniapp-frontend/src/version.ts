/**
 * 小程序端版本号（前端单一真源）
 *
 * 与系统主版本号对齐（后端 .env APP_VERSION / Push_System_Flask/app/core/config.py
 * 默认值 / admin-frontend/src/version.ts / admin-frontend/package.json / README badge）。
 * 发版时同步修改本文件 + miniapp-frontend/package.json 的 "version"。
 */
export const APP_VERSION = "6.20.0";

export default APP_VERSION;