/**
 * 个人资料详情页
 *
 * 入口：首页「我的」页顶部头像+昵称区域（点击跳此页）
 *
 * 设计（2026-09-08 重构，按用户示意图）：
 * - 非编辑态布局（自上而下）：
 *     [hero：大头像 + 已保存昵称 + 班级]
 *     [身份信息卡：学号/班级/学校]
 *     [学籍信息卡：学院/专业/校园卡号]
 *     [「编辑资料 ›」按钮]
 *     [注销账号]
 * - 编辑态布局（自上而下）：
 *     [编辑信息卡：头像行 + 昵称行]   ← 替代 hero 位置（hero 在编辑态隐藏）
 *     [身份信息卡：学号/班级/学校]     ← 值文字变灰，提示"不可编辑"
 *     [学籍信息卡：学院/专业/校园卡号] ← 值文字变灰，提示"不可编辑"
 *     [保存] [取消]                    ← 替代「编辑资料」按钮
 *     [注销账号]
 * - 编辑信息卡的"头像行"：点击整行触发 Taro.chooseImage，选图暂存本地（pendingAvatarUri），
 *   **未点保存不上传**；"昵称行"：右侧是 Input（受控，本地 nickname state）。
 * - 保存语义：先 updateAvatar（如有新图）→ 再 updateProfile(nickname) → 一次性写回。
 * - 取消语义：丢弃 pendingAvatarUri 和 nickname，一个都不写回。
 * - 注销账号：与编辑状态独立，无论是否编辑态都显示。
 */

import { useState } from 'react';
import { View, Text, Image, Input } from '@tarojs/components';
import Taro, { useDidShow } from '@tarojs/taro';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import { getProfile, updateProfile, updateAvatar, deleteAccount } from '@/api/user';
import type { StudentProfile } from '@/types/api';
import './index.scss';

export default function ProfileDetail() {
  const { user, setUser, refreshToken, logout: clearAuth } = useAuthStore();
  const { setProfile: syncProfile } = useUserStore();
  // 页面本地资料源：进入时拉取，展示 + 编辑后合并更新
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [editing, setEditing] = useState(false);
  // 暂存昵称（本地编辑态，未点保存不写回）
  const [nickname, setNickname] = useState('');
  // 暂存头像 data URI（本地编辑态，未点保存不上传）；null = 未选新头像
  const [pendingAvatarUri, setPendingAvatarUri] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
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

  // hero 展示的昵称：始终取**已保存**的值。
  // 编辑中的 nickname 只存在于「编辑信息」卡片表单里，未点保存不回写，hero 不跟着变。
  const name = profile?.nickname || user?.username || '同学';

  const enterEdit = () => {
    // 进入编辑态：预填当前昵称（空则回退 username）
    setNickname(profile?.nickname || user?.username || '');
    setEditing(true);
  };

  const cancelEdit = () => {
    // 取消编辑：丢弃全部暂存（昵称 + 头像），一个都不写回
    setEditing(false);
    setNickname('');
    setPendingAvatarUri(null);
  };

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

  // 编辑态选头像：压缩 → base64 → data URI → 仅写入本地 pendingAvatarUri（暂存），
  // **不**立即调 updateAvatar；只有点保存才由 handleSave 统一提交。
  const chooseAvatar = async () => {
    if (!editing) return;
    try {
      const res = await Taro.chooseImage({
        count: 1,
        sizeType: ['compressed'],
        sourceType: ['album', 'camera'],
      });
      const filePath = res.tempFilePaths[0];
      Taro.showLoading({ title: '处理中' });
      const fs = Taro.getFileSystemManager();
      const base64 = fs.readFileSync(filePath, 'base64');
      const ext = (filePath.match(/\.([a-zA-Z0-9]+)$/) || [])[1]?.toLowerCase() || 'jpeg';
      const mimeMap: Record<string, string> = {
        jpg: 'jpeg', jpeg: 'jpeg', png: 'png', gif: 'gif', webp: 'webp',
      };
      const dataUri = `data:image/${mimeMap[ext] || 'jpeg'};base64,${base64}`;
      setPendingAvatarUri(dataUri);
    } catch (e) {
      if ((e as { errMsg?: string })?.errMsg?.includes('cancel')) return;
      const msg = (e as { message?: string })?.message || '头像处理失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      Taro.hideLoading();
    }
  };

  // 保存昵称（头像已在 chooseAvatar 时即时落库）
  const handleSave = async () => {
    if (saving) return;
    const trimmed = nickname.trim();
    if (!trimmed) {
      Taro.showToast({ title: '昵称不能为空', icon: 'none' });
      return;
    }
    setSaving(true);
    try {
      // 1) 头像（仅当用户真的选过新头像才上传；没选则跳过，沿用后端现值）
      if (pendingAvatarUri) {
        const upd = await updateAvatar(pendingAvatarUri);
        setUser(upd.user);
      }
      // 2) 昵称
      const res = await updateProfile({ nickname: trimmed });
      const merged = { ...(profile || {}), ...res.profile } as StudentProfile;
      setProfile(merged);
      syncProfile(merged);
      // 清暂存 + 退出编辑
      setPendingAvatarUri(null);
      Taro.showToast({ title: '已保存', icon: 'success' });
      setEditing(false);
    } catch (e) {
      const msg = (e as { message?: string })?.message || '保存失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <View className="profile-detail-page">
      {/* 非编辑态：顶部 hero（大头像 + 已保存昵称 + 班级），编辑态让位给编辑信息卡 */}
      {!editing && (
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
      )}

      {/* 编辑态：编辑信息卡（替代 hero 位置）。非编辑态不渲染。 */}
      {editing && (
        <View className="detail-card">
          <Text className="detail-card-title">编辑信息</Text>

          {/* 头像行：整行可点 → 触发选图；右侧 [小圆头像 + 箭头 ›] */}
          <View className="detail-row detail-row-link" onClick={chooseAvatar} hoverClass="detail-row-hover" hoverStayTime={50}>
            <Text className="detail-row-label">头像</Text>
            <View className="detail-row-right">
              {pendingAvatarUri ? (
                <Image src={pendingAvatarUri} className="detail-avatar-sm" mode="aspectFill" />
              ) : user?.avatar ? (
                <Image src={user.avatar} className="detail-avatar-sm" mode="aspectFill" />
              ) : (
                <View className="detail-avatar-sm detail-avatar-placeholder">
                  <Text className="detail-avatar-text-sm">{name.slice(0, 1)}</Text>
                </View>
              )}
              <Text className="detail-card-title-arrow">›</Text>
            </View>
          </View>

          {/* 昵称行：右侧 Input 受控（本地 nickname state，未点保存不提交） */}
          <View className="detail-row detail-row-nickname">
            <Text className="detail-row-label">昵称</Text>
            <View className="detail-row-right">
              <Input
                className="detail-row-value-input"
                value={nickname}
                placeholder="请输入昵称"
                placeholderClass="detail-row-value-placeholder"
                maxlength={50}
                onInput={(e) => setNickname(e.detail.value)}
              />
              <Text className="detail-card-title-arrow">›</Text>
            </View>
          </View>
        </View>
      )}

      {/* 身份信息：编辑态值变灰（不可编辑） */}
      <View className="detail-card">
        <Text className="detail-card-title">身份信息</Text>
        <View className="detail-row">
          <Text className="detail-row-label">学号</Text>
          <Text className={editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'}>{profile?.student_number || '--'}</Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">班级</Text>
          <Text className={editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'}>{profile?.class_name || '--'}</Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">学校</Text>
          <Text className={editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'}>{profile?.school || '--'}</Text>
        </View>
      </View>

      {/* 学籍信息：编辑态值变灰（不可编辑） */}
      <View className="detail-card">
        <Text className="detail-card-title">学籍信息</Text>
        <View className="detail-row">
          <Text className="detail-row-label">学院</Text>
          <Text className={editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'}>{profile?.college || '--'}</Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">专业</Text>
          <Text className={editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'}>{profile?.major || '--'}</Text>
        </View>
        <View className="detail-row">
          <Text className="detail-row-label">校园卡号</Text>
          <Text className={editing ? 'detail-row-value detail-row-value-readonly' : 'detail-row-value'}>
            {profile?.campus_card_number || '未绑定'}
          </Text>
        </View>
      </View>

      {/* 底部操作：非编辑态=「编辑资料 ›」入口；编辑态=保存 + 取消 */}
      {!editing ? (
        <View className="detail-edit-actions">
          <View className="detail-edit-entry" onClick={enterEdit} hoverClass="detail-edit-entry-hover" hoverStayTime={50}>
            <Text>编辑资料</Text>
            <Text className="detail-card-title-arrow">›</Text>
          </View>
        </View>
      ) : (
        <View className="detail-edit-actions">
          <View className="detail-save-btn" onClick={handleSave}>
            <Text>{saving ? '保存中…' : '保存'}</Text>
          </View>
          <View className="detail-cancel-btn" onClick={cancelEdit}>
            <Text>取消</Text>
          </View>
        </View>
      )}

      {/* 注销账号：始终显示，与编辑状态独立 */}
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
