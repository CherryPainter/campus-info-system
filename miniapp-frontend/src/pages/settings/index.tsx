import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { setSharedBadgeCount } from '@/utils/feedbackBadge';
import { useUserStore } from '@/stores/userStore';
import './index.scss';

/**
 * 设置页（仅保留「通用」与「退出登录」）
 * - 账号设置（头像/昵称/学号/班级）已迁到独立页 pages/profile-edit/index：
 *   受控表单 + 显式保存按钮，避免之前"行内编辑 + blur 即保存"的隐式提交误触。
 * - 从「我的」页"设置"项可进入账号设置，从本页亦可通过顶部入口跳转。
 */

export default function SettingsPage() {
  const { refreshToken, logout: clearAuth } = useAuthStore();
  const { setProfile } = useUserStore();

  /** 清除本地缓存（不含登录态 Token / 用户信息） */
  const handleClearCache = () => {
    Taro.showModal({
      title: '清除缓存',
      content: '将清除反馈红点状态与学生资料缓存，登录状态不受影响，确定继续吗？',
      confirmText: '清除',
      confirmColor: '#e8380f',
      success: (res) => {
        if (!res.confirm) return;
        try {
          // 反馈红点已读状态 + 学生资料缓存（保留 miniapp.auth 登录态）
          Taro.removeStorageSync('feedback.viewedStatus');
          Taro.removeStorageSync('miniapp.user');
          // 内存中的 TabBar 共享红点一并复位
          setSharedBadgeCount(0);
          setProfile(null);
        } catch {
          /* 个别 key 删除失败不影响整体 */
        }
        Taro.showToast({ title: '缓存已清除', icon: 'success' });
      },
    });
  };

  const handleAbout = () => {
    Taro.showModal({
      title: '关于',
      content: '校园宜知行 · 校园信息聚合与智能推送系统\n微信小程序客户端',
      showCancel: false,
    });
  };

  const handleLogout = () => {
    Taro.showModal({
      title: '退出登录',
      content: '确定要退出当前账号吗？',
      confirmText: '退出',
      confirmColor: '#e8380f',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await logoutApi(refreshToken || undefined);
        } catch {
          // 后端登出失败不阻塞本地退出
        }
        clearAuth();
        Taro.reLaunch({ url: '/pages/login/index' });
      },
    });
  };

  const goAccountEdit = () => {
    Taro.navigateTo({ url: '/pages/profile-edit/index' });
  };

  return (
    <View className="set-page">
      {/* 账号设置入口（跳转独立页） */}
      <Text className="set-card-title">账号</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell" onClick={goAccountEdit}>
          <Text className="set-cell-label">账号设置</Text>
          <Text className="set-arrow">›</Text>
        </View>
      </View>

      {/* 通用 */}
      <Text className="set-card-title">通用</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell" onClick={handleClearCache}>
          <Text className="set-cell-label">清除缓存</Text>
          <Text className="set-arrow">›</Text>
        </View>
        <View className="set-cell" onClick={handleAbout}>
          <Text className="set-cell-label">关于</Text>
          <Text className="set-arrow">›</Text>
        </View>
      </View>

      <View className="set-logout" onClick={handleLogout}>
        <View className="set-logout-btn">
          <Text className="set-logout-text">退出登录</Text>
        </View>
      </View>

      <Text className="set-version">校园宜知行 v0.1.0</Text>
    </View>
  );
}
