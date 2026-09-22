import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { setSharedBadgeCount } from '@/utils/feedbackBadge';
import { useUserStore } from '@/stores/userStore';
import IconArrow from '@/components/IconArrow';
import './index.scss';

/**
 * 设置页（仅保留「通用」与「退出登录」）
 * - 顶部「个人资料」入口指向 `pages/profile-detail/index`：包含头像/身份信息/
 *   学籍信息/可编辑资料/注销账号。
 * - 2026-09-07 起个人资料页已改为「原地编辑」：详情页内切换编辑态，仅昵称+头像可改，
 *   学号/班级/学校/学院/专业/校园卡号置灰只读；原独立页 `pages/profile-edit/index`
 *   已无入口、从路由移除，源码亦已删除（可在历史 git 中找回）。
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
        // 仅清空本地登录态，留在「设置」页自动渲染游客态（功能列表折叠为引导卡），
        // 不要 reLaunch 到登录页 —— 那样等于"退出即强登录"，违反"先体验后授权"合规
        clearAuth();
      },
    });
  };

  const goProfileDetail = () => {
    Taro.navigateTo({ url: '/pages/profile-detail/index' });
  };

  const goElectricityConfig = () => {
    Taro.navigateTo({ url: '/pages/electricity-config/index' });
  };

  const goMessages = () => {
    Taro.navigateTo({ url: '/pages/messages/index' });
  };

  return (
    <View className="set-page">
      {/* 个人资料入口（指向详情页，包含头像/身份/基础资料/编辑/注销） */}
      <Text className="set-card-title">个人资料</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell" onClick={goProfileDetail}>
          <Text className="set-cell-label">个人资料</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
      </View>

      {/* 服务：电表配置（学生自行配置宿舍电表 Cookie）/ 我的消息（电量日报/低电量提醒等站内通知） */}
      <Text className="set-card-title">服务</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell" onClick={goElectricityConfig}>
          <Text className="set-cell-label">电表配置</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
        <View className="set-cell" onClick={goMessages}>
          <Text className="set-cell-label">我的消息</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
      </View>

      {/* 通用 */}
      <Text className="set-card-title">通用</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell" onClick={handleClearCache}>
          <Text className="set-cell-label">清除缓存</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
        <View className="set-cell" onClick={handleAbout}>
          <Text className="set-cell-label">关于</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
      </View>

      <View className="set-logout" onClick={handleLogout}>
        <View className="set-logout-btn">
          <Text className="set-logout-text">退出登录</Text>
        </View>
      </View>

      <Text className="set-version">校园宜知行 v1.0.0</Text>
    </View>
  );
}
