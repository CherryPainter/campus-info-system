import Taro from '@tarojs/taro';

/**
 * 微信登录辅助
 * - 只负责 wx.login 换取临时 code，openid 交换必须交给后端（绝不信任客户端 openid）
 */

export function wxLogin(): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    Taro.login({
      success: (res) => {
        if (res.code) {
          resolve(res.code);
        } else {
          reject(new Error('微信登录未返回 code'));
        }
      },
      fail: (err) => reject(new Error(err.errMsg || 'wx.login 调用失败')),
    });
  });
}
