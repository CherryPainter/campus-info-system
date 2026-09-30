import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';

import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { setSharedBadgeCount } from '@/utils/feedbackBadge';
import { useUserStore } from '@/stores/userStore';
import {
  useNotificationSettingsStore,
  type NotificationSettings,
} from '@/stores/notificationSettingsStore';
import { APP_VERSION } from '@/version';
import IconArrow from '@/components/IconArrow';
import Switch from '@/components/Switch';
import './index.scss';

/**
 * 设置页
 * - 顶部「个人资料」入口指向 `pages/profile-detail/index`。
 * - 「消息提醒」分组：总开关 + 电量日报/低电量/公告/反馈回复子开关，
 *   关闭后不再显示红色数字气泡，但仍可进入「我的消息」查看历史。
 * - 「关于」跳转独立页面，聚合用户协议/隐私政策/第三方 SDK/开源声明等条款。
 */

export default function SettingsPage() {
  const { refreshToken, logout: clearAuth } = useAuthStore();
  const { setProfile } = useUserStore();
  const {
    masterEnabled,
    electricityDaily,
    lowPower,
    announcement,
    feedback,
    setMasterEnabled,
    setChannelEnabled,
  } = useNotificationSettingsStore();

  /** 清除本地缓存（不含登录态 Token / 用户信息） */
  const handleClearCache = () => {
    Taro.showModal({
      title: '清除缓存',
      content: '将清除反馈红点状态、消息提醒设置与学生资料缓存，登录状态不受影响，确定继续吗？',
      confirmText: '清除',
      confirmColor: '#e8380f',
      success: (res) => {
        if (!res.confirm) return;
        try {
          // 反馈红点已读状态 + 学生资料缓存 + 消息提醒设置（保留 miniapp.auth 登录态）
          Taro.removeStorageSync('feedback.viewedStatus');
          Taro.removeStorageSync('miniapp.user');
          Taro.removeStorageSync('miniapp.notificationSettings');
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

  const goAbout = () => {
    Taro.navigateTo({ url: '/pages/about/index' });
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

  const toggleMaster = (value: boolean) => {
    setMasterEnabled(value);
    // 关闭总开关时同步清空 TabBar 反馈红点，避免残留
    if (!value) {
      setSharedBadgeCount(0);
    }
  };

  const toggleChannel = (key: Exclude<keyof NotificationSettings, 'masterEnabled'>) => {
    return (value: boolean) => setChannelEnabled(key, value);
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

      {/* 服务：电表配置 / 我的消息 */}
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

      {/* 消息提醒：总开关 + 分类开关 */}
      <Text className="set-card-title">消息提醒</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell set-cell-switch">
          <View className="set-cell-label-group">
            <Text className="set-cell-label">接收消息提醒</Text>
            <Text className="set-cell-hint">关闭后不再显示红色数字气泡</Text>
          </View>
          <Switch checked={masterEnabled} onChange={toggleMaster} />
        </View>
        {masterEnabled && (
          <>
            <View className="set-cell set-cell-switch">
              <Text className="set-cell-label">每日电量日报</Text>
              <Switch checked={electricityDaily} onChange={toggleChannel('electricityDaily')} />
            </View>
            <View className="set-cell set-cell-switch">
              <Text className="set-cell-label">低电量提醒</Text>
              <Switch checked={lowPower} onChange={toggleChannel('lowPower')} />
            </View>
            <View className="set-cell set-cell-switch">
              <Text className="set-cell-label">公告通知</Text>
              <Switch checked={announcement} onChange={toggleChannel('announcement')} />
            </View>
            <View className="set-cell set-cell-switch">
              <Text className="set-cell-label">反馈回复</Text>
              <Switch checked={feedback} onChange={toggleChannel('feedback')} />
            </View>
          </>
        )}
      </View>

      {/* 通用 */}
      <Text className="set-card-title">通用</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-cell" onClick={handleClearCache}>
          <Text className="set-cell-label">清除缓存</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
        <View className="set-cell" onClick={goAbout}>
          <Text className="set-cell-label">关于</Text>
          <IconArrow className="set-arrow" size="md" />
        </View>
      </View>

      <View className="set-logout" onClick={handleLogout}>
        <View className="set-logout-btn">
          <Text className="set-logout-text">退出登录</Text>
        </View>
      </View>

      <Text className="set-version">校园宜知行 v{APP_VERSION}</Text>
    </View>
  );
}
