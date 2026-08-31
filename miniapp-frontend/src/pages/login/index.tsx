import { useEffect, useState } from 'react';
import { View, Text } from '@tarojs/components';
import { getWindowInfo } from '@tarojs/taro';
import Taro from '@tarojs/taro';

import { login as loginApi } from '@/api/auth';
import { wxLogin } from '@/utils/auth';
import { useAuthStore } from '@/stores/authStore';
import './index.scss';

/**
 * 登录页
 * - 微信一键登录：wx.login → code → POST /api/miniapp/auth/login → 保存 Token → 进首页
 * - openid 交换全部在后端完成，前端只负责传递 code
 * - 按钮用 View 自定义（不用 Button 内置组件，避免 primary 类型默认 100% 宽 + 内置样式干扰图标布局）
 */
export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const setAuth = useAuthStore((s) => s.setAuth);

  // custom 导航栏：读取状态栏高度，避免内容被遮挡
  useEffect(() => {
    try {
      const info = getWindowInfo();
      if (info.statusBarHeight) setStatusBarHeight(info.statusBarHeight);
    } catch {
      // 兜底 20
    }
  }, []);

  const handleLogin = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const code = await wxLogin();
      const result = await loginApi(code);
      setAuth({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        expiresIn: result.expires_in,
        user: result.user,
      });
      Taro.showToast({ title: '登录成功', icon: 'success' });
      setTimeout(() => {
        Taro.switchTab({ url: '/pages/home/index' });
      }, 500);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '登录失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="login-page" style={{ paddingTop: `${statusBarHeight}px` }}>
      <View className="login-hero">
        <View className="login-logo">知行</View>
        <Text className="login-title">校园宜知行</Text>
        <Text className="login-sub">校园信息聚合与智能推送</Text>
      </View>

      <View className="login-body">
        <View
          className={`login-btn ${loading ? 'login-btn-loading' : ''}`}
          hoverClass="login-btn-hover"
          onClick={handleLogin}
        >
          <Text className="iconfont icon-denglu-weixindenglu login-btn-icon" />
          <Text className="login-btn-text">{loading ? '正在登录…' : '微信一键登录'}</Text>
        </View>
        <Text className="login-tip">登录即代表同意《用户协议》与《隐私政策》</Text>
      </View>
    </View>
  );
}
