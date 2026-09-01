import { useState } from 'react';
import { View, Text, Image, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';

import * as userApi from '@/api/user';
import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import { setSharedBadgeCount } from '@/utils/feedbackBadge';
import './index.scss';

/**
 * 设置页
 * 结构（自上而下）：
 * - 账号设置（头像 / 昵称 / 学号 / 班级）
 * - 我的页面背景（预设渐变主题）
 * - 通用（清除缓存 / 关于 / 退出登录）
 */

/** 我的页背景预设（key 与后端白名单一致，渐变用于设置页色块预览） */
const BG_PRESETS: { key: string; name: string; gradient: string }[] = [
  { key: 'default', name: '默认', gradient: 'radial-gradient(circle at 30% 0%, rgba(122,167,255,0.4) 0%, rgba(122,167,255,0.12) 60%, rgba(122,167,255,0) 78%)' },
  { key: 'sunset', name: '落日', gradient: 'linear-gradient(135deg, #ffe0c2 0%, #ffd0e8 100%)' },
  { key: 'ocean', name: '海洋', gradient: 'linear-gradient(135deg, #bfe0ff 0%, #d6f0ff 100%)' },
  { key: 'forest', name: '森林', gradient: 'linear-gradient(135deg, #d3ecd0 0%, #e8f5e0 100%)' },
  { key: 'night', name: '夜空', gradient: 'linear-gradient(135deg, #cdd6f0 0%, #e6e9f8 100%)' },
];

const FIELD_MAXLEN: Record<string, number> = {
  nickname: 20,
  student_number: 30,
  class_name: 30,
};

export default function SettingsPage() {
  const { user, refreshToken, logout: clearAuth, setUser } = useAuthStore();
  const { profile, setProfile } = useUserStore();

  // 头像本地展示值（上传成功后同步到 authStore，此处仅做切换反馈）
  const [avatarSrc, setAvatarSrc] = useState<string | null>(user?.avatar || null);

  const displayName = profile?.nickname || profile?.real_name || user?.username || '同学';

  /** 行内字段保存：值未变化 / 为空跳过，否则调接口并同步 store */
  const saveField = async (key: 'nickname' | 'student_number' | 'class_name', value: string) => {
    const trimmed = (value || '').trim();
    if (!trimmed) {
      Taro.showToast({ title: '内容不能为空', icon: 'none' });
      return;
    }
    if (profile && profile[key] === trimmed) return;
    try {
      const res = await userApi.updateProfile({ [key]: trimmed });
      setProfile(res.profile);
      Taro.showToast({ title: '已保存', icon: 'success' });
    } catch (e) {
      const msg = (e as { message?: string })?.message || '保存失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    }
  };

  /** 头像更换：压缩图 → base64 → data URI → 后端校验存储 */
  const chooseAvatar = async () => {
    try {
      const res = await Taro.chooseImage({
        count: 1,
        sizeType: ['compressed'],
        sourceType: ['album', 'camera'],
      });
      const filePath = res.tempFilePaths[0];
      Taro.showLoading({ title: '上传中' });
      const fs = Taro.getFileSystemManager();
      const base64 = fs.readFileSync(filePath, 'base64');
      const ext = (filePath.match(/\.([a-zA-Z0-9]+)$/) || [])[1]?.toLowerCase() || 'jpeg';
      const mimeMap: Record<string, string> = {
        jpg: 'jpeg',
        jpeg: 'jpeg',
        png: 'png',
        gif: 'gif',
        webp: 'webp',
      };
      const dataUri = `data:image/${mimeMap[ext] || 'jpeg'};base64,${base64}`;
      const upd = await userApi.updateAvatar(dataUri);
      const next = upd.user;
      setAvatarSrc(next.avatar);
      setUser(next);
      Taro.showToast({ title: '头像已更新', icon: 'success' });
    } catch (e) {
      // 用户取消选择属正常操作，静默忽略
      if ((e as { errMsg?: string })?.errMsg?.includes('cancel')) return;
      const msg = (e as { message?: string })?.message || '头像上传失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      Taro.hideLoading();
    }
  };

  /** 切换我的页背景主题 */
  const chooseBg = async (key: string) => {
    if (profile?.profile_bg === key) return;
    try {
      const res = await userApi.updateProfile({ profile_bg: key });
      setProfile(res.profile);
      Taro.showToast({ title: '背景已更换', icon: 'success' });
    } catch (e) {
      const msg = (e as { message?: string })?.message || '切换失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    }
  };

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

  return (
    <View className="set-page">
      {/* 账号设置 */}
      <Text className="set-card-title">账号设置</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-avatar-wrap" onClick={chooseAvatar}>
          <Text className="set-avatar-hint">头像</Text>
          {avatarSrc ? (
            <Image className="set-avatar" src={avatarSrc} mode="aspectFill" />
          ) : (
            <View className="set-avatar set-avatar-placeholder">
              <Text className="set-avatar-text">{displayName.slice(0, 1)}</Text>
            </View>
          )}
        </View>
        <View className="set-row">
          <Text className="set-row-label">昵称</Text>
          <Input
            className="set-row-input"
            value={profile?.nickname || ''}
            placeholder="设置昵称"
            placeholderClass="set-row-placeholder"
            maxlength={FIELD_MAXLEN.nickname}
            onBlur={(e) => saveField('nickname', e.detail.value)}
          />
        </View>
        <View className="set-row">
          <Text className="set-row-label">学号</Text>
          <Input
            className="set-row-input"
            value={profile?.student_number || ''}
            placeholder="填写学号"
            placeholderClass="set-row-placeholder"
            maxlength={FIELD_MAXLEN.student_number}
            onBlur={(e) => saveField('student_number', e.detail.value)}
          />
        </View>
        <View className="set-row">
          <Text className="set-row-label">班级</Text>
          <Input
            className="set-row-input"
            value={profile?.class_name || ''}
            placeholder="填写班级"
            placeholderClass="set-row-placeholder"
            maxlength={FIELD_MAXLEN.class_name}
            onBlur={(e) => saveField('class_name', e.detail.value)}
          />
        </View>
      </View>

      {/* 我的页面背景 */}
      <Text className="set-card-title">我的页面背景</Text>
      <View className="set-card" style={{ marginTop: '8rpx' }}>
        <View className="set-bg-list">
          {BG_PRESETS.map((preset) => (
            <View
              key={preset.key}
              className={`set-bg-item${profile?.profile_bg === preset.key ? ' set-bg-item-active' : ''}`}
              onClick={() => chooseBg(preset.key)}
            >
              <View className="set-bg-swatch" style={{ background: preset.gradient }} />
              <Text className="set-bg-name">{preset.name}</Text>
            </View>
          ))}
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
