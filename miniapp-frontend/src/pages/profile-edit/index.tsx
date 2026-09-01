import { useEffect, useState } from 'react';
import { View, Text, Image, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';

import * as userApi from '@/api/user';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import './index.scss';

const FIELD_MAXLEN: Record<string, number> = {
  nickname: 20,
  campus_card_number: 30,
};

type FieldKey = 'nickname' | 'campus_card_number';

/**
 * 账号设置（独立页）
 * 设计：受控表单 + 显式保存按钮（不沿用之前"blur 即保存"的隐式提交，
 * 避免误触；保存按钮按下前所有改动只在本地预览，不写后端）。
 *
 * 提交策略：一次 updateProfile 提交全部字段（用户一次操作完成全部修改）。
 * 注意：学号/班级/学校由「身份绑定」管理，此处只读展示，不可修改。
 */
export default function ProfileEditPage() {
  const { user, setUser } = useAuthStore();
  const { profile, setProfile } = useUserStore();

  // 本地表单（受控 + onInput）：初始从 profile/avatar 拷贝，profile 加载/变更后回填
  const [form, setForm] = useState<Record<FieldKey, string>>({
    nickname: '',
    campus_card_number: '',
  });
  const [avatarSrc, setAvatarSrc] = useState<string | null>(user?.avatar || null);
  const [saving, setSaving] = useState(false);

  // 回填 profile（仅在用户尚未编辑字段时；空值不覆盖避免清空被回填成旧值）
  useEffect(() => {
    if (!profile) return;
    setForm((f) => ({
      nickname: f.nickname || profile.nickname || '',
      campus_card_number: f.campus_card_number || profile.campus_card_number || '',
    }));
  }, [profile]);

  // 头像处理：与之前 settings 相同链路（压缩 → base64 → data URI → 后端校验）
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
        jpg: 'jpeg', jpeg: 'jpeg', png: 'png', gif: 'gif', webp: 'webp',
      };
      const dataUri = `data:image/${mimeMap[ext] || 'jpeg'};base64,${base64}`;
      const upd = await userApi.updateAvatar(dataUri);
      const next = upd.user;
      setAvatarSrc(next.avatar);
      setUser(next);
      Taro.showToast({ title: '头像已更新', icon: 'success' });
    } catch (e) {
      if ((e as { errMsg?: string })?.errMsg?.includes('cancel')) return;
      const msg = (e as { message?: string })?.message || '头像上传失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      Taro.hideLoading();
    }
  };

  /** 显式保存：trim 后全字段提交；昵称必填 */
  const handleSave = async () => {
    if (saving) return;
    const payload = {
      nickname: (form.nickname || '').trim(),
      campus_card_number: (form.campus_card_number || '').trim(),
    };
    if (!payload.nickname) {
      Taro.showToast({ title: '昵称不能为空', icon: 'none' });
      return;
    }
    setSaving(true);
    try {
      const res = await userApi.updateProfile(payload);
      setProfile(res.profile);
      Taro.showToast({ title: '已保存', icon: 'success' });
      // 延迟返回上一页，让 toast 完整显示
      setTimeout(() => Taro.navigateBack(), 600);
    } catch (e) {
      const msg = (e as { message?: string })?.message || '保存失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setSaving(false);
    }
  };

  const displayName = form.nickname || profile?.real_name || user?.username || '同学';

  return (
    <View className="pedit-page">
      <View className="pedit-card">
        {/* 头像（点击更换） */}
        <View className="pedit-avatar-row" onClick={chooseAvatar}>
          <Text className="pedit-row-label">头像</Text>
          {avatarSrc ? (
            <Image className="pedit-avatar" src={avatarSrc} mode="aspectFill" />
          ) : (
            <View className="pedit-avatar pedit-avatar-placeholder">
              <Text className="pedit-avatar-text">{displayName.slice(0, 1)}</Text>
            </View>
          )}
          <Text className="pedit-arrow">›</Text>
        </View>

        <View className="pedit-row">
          <Text className="pedit-row-label">昵称</Text>
          <Input
            className="pedit-row-input"
            value={form.nickname}
            placeholder="设置昵称"
            placeholderClass="pedit-row-placeholder"
            maxlength={FIELD_MAXLEN.nickname}
            onInput={(e) => setForm((f) => ({ ...f, nickname: e.detail.value }))}
          />
        </View>

        {/* 身份信息：由管理员预录名单绑定，只读展示，不可修改 */}
        <View className="pedit-identity">
          <View className="pedit-identity-title">身份信息（绑定后不可修改）</View>
          <View className="pedit-identity-row">
            <Text className="pedit-identity-label">学校</Text>
            <Text className="pedit-identity-value">{profile?.school || '未绑定'}</Text>
          </View>
          <View className="pedit-identity-row">
            <Text className="pedit-identity-label">学号</Text>
            <Text className="pedit-identity-value">{profile?.student_number || '未绑定'}</Text>
          </View>
          <View className="pedit-identity-row">
            <Text className="pedit-identity-label">班级</Text>
            <Text className="pedit-identity-value">{profile?.class_name || '未绑定'}</Text>
          </View>
        </View>

        <View className="pedit-row">
          <Text className="pedit-row-label">校园卡号</Text>
          <Input
            className="pedit-row-input"
            value={form.campus_card_number}
            placeholder="填写校园卡号（一卡通号，非学号）"
            placeholderClass="pedit-row-placeholder"
            maxlength={FIELD_MAXLEN.campus_card_number}
            onInput={(e) => setForm((f) => ({ ...f, campus_card_number: e.detail.value }))}
          />
        </View>
      </View>

      <Text className="pedit-hint">点击底部按钮保存所有修改</Text>

      <View className="pedit-save-wrap">
        <View
          className={`pedit-save-btn${saving ? ' pedit-save-btn-disabled' : ''}`}
          onClick={handleSave}
        >
          <Text className="pedit-save-text">{saving ? '保存中…' : '保存'}</Text>
        </View>
      </View>
    </View>
  );
}