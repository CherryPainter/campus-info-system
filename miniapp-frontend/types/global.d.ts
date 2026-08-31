/// <reference types="@tarojs/taro" />

declare module '*.scss';
declare module '*.css';
declare module '*.png';
declare module '*.jpg';

// Taro 注入的全局常量（config/index.ts defineConstants 可扩展）
declare const API_BASE_URL: string | undefined;
