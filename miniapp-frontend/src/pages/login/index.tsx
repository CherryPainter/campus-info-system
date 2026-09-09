import { useEffect, useState } from 'react';
import { View, Text, Image } from '@tarojs/components';
import { getWindowInfo } from '@tarojs/taro';
import Taro from '@tarojs/taro';

import { login as loginApi } from '@/api/auth';
import { wxLogin } from '@/utils/auth';
import { resetPrivateClickCount } from '@/hooks/useLoginGuard';
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
 *
 * 合规要点（微信审核「登录环节」要求）：
 * 1. 登录页必须提供「显著有效」的可取消/拒绝或返回入口 —— 本页提供两处：
 *    a) 左上角「返回」按钮（栈内有上一页则 navigateBack，栈底则回首页 Tab）；
 *    b) 底部「暂不登录，随便看看」按钮（直接以游客身份回首页浏览公开内容）。
 * 2. 本页 navigationStyle=custom，没有原生导航栏，因此返回入口必须由页面自绘，
 *    否则用户进入后无法退出（这正是此前被驳回的原因）。
 * 3. 绝不自动触发 wx.login / 自动弹登录弹窗，登录只由用户主动点击发起。
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

  /**
   * 左上「返回」：退出登录流程，回到进入登录页前的页面。
   * - 页面栈 > 1（由首页/我的/时间轴等跳转进来）→ navigateBack 回上一页；
   * - 页面栈 = 1（登录页为栈底，如被 reLaunch 直达）→ 回首页 Tab，以游客身份继续浏览。
   */
  const handleBack = () => {
    try {
      const pages = Taro.getCurrentPages();
      if (pages.length > 1) {
        Taro.navigateBack();
      } else {
        Taro.switchTab({ url: '/pages/home/index' });
      }
    } catch {
      Taro.switchTab({ url: '/pages/home/index' });
    }
  };

  /** 「暂不登录，随便看看」：明确拒绝登录，以游客身份浏览公开的天气/通知公告等内容 */
  const handleSkip = () => {
    Taro.showToast({ title: '已进入游客模式，可浏览公开内容', icon: 'none' });
    Taro.switchTab({ url: '/pages/home/index' });
  };

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
      // 登录成功：清零"私有模块点击累计"（游客期攒的次数不应再触发登录弹窗）
      resetPrivateClickCount();
      Taro.showToast({ title: '登录成功', icon: 'success' });
      setTimeout(() => {
        // 从登录引导弹窗进入：返回上一页（此时已登录可正常使用）；
        // 兜底（如会话过期被回收）：回首页
        const pages = Taro.getCurrentPages();
        if (pages.length > 1) {
          Taro.navigateBack();
        } else {
          Taro.switchTab({ url: '/pages/home/index' });
        }
      }, 500);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '登录失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="login-page">
      {/* 自绘导航栏左上返回键：custom 导航下唯一的原生级返回入口 */}
      <View className="login-nav" style={{ paddingTop: `${statusBarHeight}px` }}>
        <View className="login-nav-back" hoverClass="login-nav-back-hover" onClick={handleBack}>
          <Text className="login-nav-back-icon">‹</Text>
          <Text className="login-nav-back-text">返回</Text>
        </View>
      </View>

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

        {/* 拒绝登录的次入口：与左上返回并列，保证"可拒绝"显著可见 */}
        <View className="login-skip" hoverClass="login-skip-hover" onClick={handleSkip}>
          <Text className="login-skip-text">暂不登录，随便看看</Text>
        </View>

        <Text className="login-guest-tip">
          不登录也可浏览天气、通知公告等公开内容；登录后可查看课表、宿舍电量等个人数据
        </Text>

        <View className="login-agree" onClick={() => setAgreed(!agreed)}>
          <View
            className={`login-agree-check ${agreed ? 'checked' : ''}`}
            hoverClass="login-agree-hover"
            onClick={(e) => {
              e.stopPropagation();
              setAgreed(!agreed);
            }}
          >
            {agreed ? <Text className="login-agree-check-tick">✓</Text> : null}
          </View>
          <Text className="login-agree-text">
            我已阅读并同意
            <Text
              className="login-agree-link"
              onClick={(e) => {
                e.stopPropagation();
                openAgreement();
              }}
            >《用户协议》</Text>
            与
            <Text
              className="login-agree-link"
              onClick={(e) => {
                e.stopPropagation();
                openPrivacy();
              }}
            >《隐私政策》</Text>
          </Text>
        </View>
      </View>
    </View>
  );
}
