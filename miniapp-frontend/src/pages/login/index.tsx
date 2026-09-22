import { useState } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro from '@tarojs/taro';

import { login as loginApi } from '@/api/auth';
import * as userApi from '@/api/user';
import { wxLogin } from '@/utils/auth';
import { resetBindNotice } from '@/hooks/useBindStatusWatcher';
import { beginBindGuide, finishBindGuide } from '@/utils/bindGuard';
import { useAuthStore } from '@/stores/authStore';
import loginIllustration from '@/assets/images/login-illustration.png';
import './index.scss';

/**
 * 登录页
 * - 微信一键登录：wx.login → code → POST /api/miniapp/auth/login → 保存 Token → 回上一页
 * - openid 交换全部在后端完成，前端只负责传递 code
 * - 必须勾选并阅读《用户协议》《隐私政策》后方可登录（合规要求）
 * - 按钮用 View 自定义（不用 Button 内置组件，避免 primary 类型默认 100% 宽 + 内置样式干扰图标布局）
 * - 顶部 logo 用真实校园插画替代文字 logo（产品迭代统一形象）
 *
 * 合规要点（微信审核「登录环节」要求）：
 * 1. 使用 WeChat 原生标准顶栏（左侧自动出现 `< 返回` 箭头、居中标题），即满足
 *    「显著有效的可取消/拒绝或返回按钮」。本页不再自定义顶栏也不再提供底部拒绝按钮，
 *    避免双重入口互相干扰造成体感割裂。
 * 2. 不自动触发 wx.login、不自动弹登录弹窗；登录只由用户主动点击发起。
 */
export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);

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
      // 登录成功：解除绑定提示节流
      resetBindNotice();

      // 进入绑定引导期（先置位，覆盖下面的 await 窗口）：
      // setAuth 使 isLoggedIn=true 后，后台已挂载的 Tab 页会因 useEffect([isLoggedIn])
      // 立刻重拉"需绑定"的私有接口；未绑定前这些必然 403，纯浪费 + 刷 403 噪音。
      // 引导期置位后这些页面不再发私有请求；request 层撞 403 也只清缓存不降级。
      beginBindGuide();

      // 立即确认身份绑定状态（@student_required，未绑定返回 bound:false 而不 403）：
      // - 已绑定 → 结束引导期，返回上一页正常使用；
      // - 未绑定 → 保持引导期，用绑定页**替换**登录页（redirectTo），避免返回时退回
      //   "已登录"的登录页。完成绑定即可正常使用；若放弃绑定直接返回，由 Tab 页
      //   watcher 与绑定页 useUnload 兜底撤销登录态，不会卡在"已登录却啥也用不了"。
      let bound = false;
      try {
        const st = await userApi.getBindStatus();
        bound = !!st?.bound;
      } catch {
        // 查询失败按未绑定处理，交由绑定页 / 后续 watcher 兜底
        bound = false;
      }

      if (bound) {
        finishBindGuide();
        Taro.showToast({ title: '登录成功', icon: 'success' });
        setTimeout(() => {
          const pages = Taro.getCurrentPages();
          if (pages.length > 1) {
            Taro.navigateBack();
          } else {
            Taro.switchTab({ url: '/pages/home/index' });
          }
        }, 500);
      } else {
        Taro.showToast({ title: '登录成功，请先完成身份认证', icon: 'none' });
        setTimeout(() => {
          Taro.redirectTo({ url: '/pages/bind/index' });
        }, 500);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '登录失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="login-page">
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

        <View className="login-agree" onClick={() => setAgreed(!agreed)}>
          <View
            className={`login-agree-check ${agreed ? 'checked' : ''}`}
            hoverClass="login-agree-hover"
            onClick={(e) => {
              e.stopPropagation();
              setAgreed(!agreed);
            }}
          >
            {agreed ? <View className="login-agree-check-tick" /> : null}
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