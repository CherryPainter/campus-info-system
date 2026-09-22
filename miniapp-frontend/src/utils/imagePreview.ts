import Taro from '@tarojs/taro';

import { API_BASE_URL } from './request';

/**
 * 反馈图片预览：把后端返回的相对 URL 拼成完整地址，调起微信原生图片预览。
 *
 * 统一收口，避免 submit/list/detail 三页各写一遍拼接逻辑（单点处理）。
 *
 * @param current 当前点击的图片相对 URL
 * @param urls 该反馈全部图片的相对 URL 数组
 */
export function previewImages(current: string, urls: string[]): void {
  const all = (urls || []).map((u) => `${API_BASE_URL}${u}`);
  const cur = `${API_BASE_URL}${current}`;
  Taro.previewImage({
    current: cur,
    urls: all,
  });
}
