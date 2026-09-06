/**
 * 个人资料详情页
 *
 * 入口：首页「我的」页顶部头像+昵称区域（点击跳此页）
 *
 * 内容：
 * - 顶部头像 + 昵称（与「我的」页 hero 区对齐）
 * - 资料块：学号 / 班级 / 学校（只读，绑定后锁定）+ 校园卡号 / 学院 / 专业 / 年级 / 手机
 * - 底部"注销账号"危险操作（红色按钮 + 二次确认 + 调用 DELETE /auth/user/me）
 *
 * 注销账号（与「退出登录」区别）：
 * - 退出登录：仅撤销当前 token，本地清空，可重新登录
 * - 注销账号：users.is_active=False（软删）+ 撤销 token + 写日志，该微信号无法再次登录
 *   如需恢复请联系管理员在管理端重新启用（users.is_active=True）
 */

import { useState } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import { useAuthStore } from '@/stores/authStore';
import { getProfile, deleteAccount } from '@/api/user';
import type { StudentProfile } from '@/types/api';
import './index.scss';

export default function ProfileDetail() {
  const { user, refreshToken, logout: clearAuth } = useAuthStore();
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [deleting, setDeleting] = useState(false);

  // 首次进入拉取资料
  useDidShow(async () => {
    try {
      const res = await getProfile();
      if (res.status === 'success' && res.profile) {
        setProfile(res.profile);
      }
    } catch {
      // 静默失败，使用本地缓存展示
    }
  });

  const name =
    profile?.nickname || user?.username || '同学';

  const handleDelete = () => {
    Taro.showModal({
      title: '注销账号',
      content:
        '注销后该账号将永久无法登录小程序，包括所有数据。如需重新使用请联系管理员。\n\n确定要注销当前账号吗？',
      confirmText: '确认注销',
      confirmColor: '#e8380f',
      cancelText: '再想想',
      success: async (res) => {
        if (!res.confirm) return;
        setDeleting(true);
        try {
          // 注销接口（DELETE /user/me），refresh_token 通过 query 传避免 body
          await deleteAccount(refreshToken || undefined);
          // 后端已软删 is_active=False + 撤销 token；本地清空 + 跳登录页
          clearAuth();
          Taro.showToast({ title: '账号已注销', icon: 'none' });
          setTimeout(() => {
            Taro.reLaunch({ url: '/pages/login/index' });
          }, 800);
        } catch (err) {
          const msg =
            (err as { message?: string })?.message || '注销失败，请稍后重试';
          Taro.showToast({ title: msg, icon: 'none' });
        } finally {
          setDeleting(false);
        }
      },
    });
  };

  return (
    <View className="profile-detail-page">
      {/* 顶部：头像 + 昵称 */}
      <View className="detail-hero">
        {user?.avatar ? (
          <Image src={user.avatar} className="detail-avatar" mode="aspectFill" />
        ) : (
          <View className="detail-avatar detail-avatar-placeholder">
            <Text className="detail-avatar-text">{name.slice(0, 1)}</Text>
          </View>
        )}
        <Text className="detail-name">{name}</Text>
        {profile?.class_name ? (
          <Text className="detail-sub">{profile.class_name}</Text>
        ) : null}
      </View>

      {/* 身份信息（只读，绑定后锁定） */}
      <View className="detail-card">
        <Text className="detail-card-title">身份信息</Text>
        <View className="detail-row">
          <Text className="detail-row-label">学号</Text>
          <Text className="detail-row-value">
            {profile?.student_number || '--'}
          </Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">班级</Text>
          <Text className="detail-row-value">
            {profile?.class_name || '--'}
          </Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">学校</Text>
          <Text className="detail-row-value">
            {profile?.school || '--'}
          </Text>
        </View>
      </View>

      {/* 基础资料（仅展示后端有采集入口 + 名单带出的字段；删除真实姓名/手机号/年级） */}
      <View className="detail-card">
        <Text className="detail-card-title">基础资料</Text>
        <View className="detail-row">
          <Text className="detail-row-label">昵称</Text>
          <Text className="detail-row-value">
            {profile?.nickname || '未设置'}
          </Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">校园卡号</Text>
          <Text className="detail-row-value">
            {profile?.campus_card_number || '未绑定'}
          </Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">学院</Text>
          <Text className="detail-row-value">{profile?.college || '--'}</Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">专业</Text>
          <Text className="detail-row-value">{profile?.major || '--'}</Text>
        </View>
        <View
          className="detail-row detail-row-link"
          onClick={() => Taro.navigateTo({ url: '/pages/profile-edit/index' })}
        >
          <Text className="detail-row-label">编辑资料</Text>
          <Text className="detail-row-arrow">›</Text>
        </View>
      </View>

      {/* 危险操作：注销账号 */}
      <View className="detail-danger-zone">
        <View
          className="detail-delete-btn"
          onClick={handleDelete}
          hoverClass="detail-delete-btn-hover"
          hoverStayTime={50}
        >
          <Text>{deleting ? '注销中...' : '注销账号'}</Text>
        </View>
        <Text className="detail-delete-tip">
          注销后该账号将被禁用且数据无法恢复
        </Text>
      </View>
    </View>
  );
}
