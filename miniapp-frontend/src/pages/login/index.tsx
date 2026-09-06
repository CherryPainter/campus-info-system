import { useEffect, useState } from 'react';
import { View, Text, Image } from '@tarojs/components';
import { getWindowInfo } from '@tarojs/taro';
import Taro from '@tarojs/taro';

import { login as loginApi } from '@/api/auth';
import { wxLogin } from '@/utils/auth';
import { useAuthStore } from '@/stores/authStore';
import loginIllustration from '@/assets/images/login-illustration.png';
import './index.scss';

/**
 * 登录页
 * - 微信一键登录：wx.login → code → POST /api/miniapp/auth/login → 保存 Token → 进首页
 * - openid 交换全部在后端完成，前端只负责传递 code
 * - 必须勾选并阅读《用户协议》《隐私政策》后方可登录（合规要求）
 * - 按钮用 View 自定义（不用 Button 内置组件，避免 primary 类型默认 100% 宽 + 内置样式干扰图标布局）
 * - 顶部 logo 用真实校园插画替代文字 logo（产品迭代统一形象）
 */
export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [agreed, setAgreed] = useState(false);
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

  const openAgreement = () => {
    Taro.navigateTo({ url: '/pages/user-agreement/index' });
  };

  const openPrivacy = () => {
    Taro.navigateTo({ url: '/pages/privacy-policy/index' });
  };

  const handleLogin = async () => {
    if (loading) return;
    if (!agreed) {
      Taro.showToast({ title: '请先阅读并同意协议', icon: 'none' });
      return;
    }
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
        <Image
          className="login-logo"
          src={loginIllustration}
          mode="aspectFit"
        />
        <Text className="login-title">校园宜知行</Text>
        <Text className="login-sub">校园信息聚合与智能推送</Text>
      </View>

      <View className="login-body">
        <View
          className={`login-btn ${loading || !agreed ? 'login-btn-disabled' : ''} ${loading ? 'login-btn-loading' : ''}`}
          hoverClass={agreed && !loading ? 'login-btn-hover' : ''}
          onClick={handleLogin}
        >
          <Text className="iconfont icon-denglu-weixindenglu login-btn-icon" />
          <Text className="login-btn-text">{loading ? '正在登录…' : '微信一键登录'}</Text>
        </View>

        <View className="login-agree">
          <View
            className={`login-agree-check ${agreed ? 'checked' : ''}`}
            hoverClass="login-agree-hover"
            onClick={() => setAgreed(!agreed)}
          >
            {agreed ? <Text className="login-agree-check-tick">✓</Text> : null}
          </View>
          <Text className="login-agree-text">
            我已阅读并同意
            <Text className="login-agree-link" onClick={openAgreement}>《用户协议》</Text>
            与
            <Text className="login-agree-link" onClick={openPrivacy}>《隐私政策》</Text>
          </Text>
        </View>
      </View>
    </View>
  );
}