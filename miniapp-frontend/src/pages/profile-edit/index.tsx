import { useEffect, useState } from 'react';
import { View, Text, Image, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';

import * as userApi from '@/api/user';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import './index.scss';

/**
 * 字段最大长度（与后端 StudentProfile 模型 String(N) 对齐，超长后端会被截断/拒绝）
 *
 * 仅保留后端真正需要的字段（2026-09-06 精简）：
 * - nickname（必填）
 * - campus_card_number（校园卡/一卡通号）
 * - college / major（学院、专业；名单绑定后通常已有，但允许学生补充/纠错）
 *
 * 移除字段及原因：
 * - real_name：小程序未提供采集入口，且后端身份绑定逻辑没从名单拷贝过来，
 *   学生填了也是空，徒增表单负担 → 移除；后端模型字段保留，需要时再走采集
 * - phone：小程序完全没有采集入口（仅后端模型占位），恒为 null → 移除
 * - grade：后端模型有但没有采集入口，恒为 null → 移除
 */
const FIELD_MAXLEN = {
  nickname: 50,
  campus_card_number: 30,
  college: 100,
  major: 100,
} as const;

type FieldKey = keyof typeof FIELD_MAXLEN;

/**
 * 编辑资料页（受控表单 + 显式保存）
 *
 * 设计要点：
 * - 受控 `<Input value>` 必须配 onInput 更新 state，否则打不进字。
 * - 一次 updateProfile 提交全部字段，用户一次操作完成所有修改。
 * - 学号/班级/学校由「身份绑定」管理，此处只读展示，不允许编辑。
 * - 表单字段：nickname（必填）/ campus_card_number / college / major
 * - 头像单独走 updateAvatar 接口，不与其他字段混合提交。
 */
export default function ProfileEditPage() {
  const { user, setUser } = useAuthStore();
  const { profile, setProfile } = useUserStore();

  // 本地表单（受控 + onInput）：初始从 profile 拷贝，profile 加载/变更后回填
  const [form, setForm] = useState<Record<FieldKey, string>>({
    nickname: '',
    campus_card_number: '',
    college: '',
    major: '',
  });
  const [avatarSrc, setAvatarSrc] = useState<string | null>(user?.avatar || null);
  const [saving, setSaving] = useState(false);

  // 回填 profile（仅在用户尚未编辑字段时；空值不覆盖避免清空被回填成旧值）
  useEffect(() => {
    if (!profile) return;
    setForm((f) => ({
      nickname: f.nickname || profile.nickname || '',
      campus_card_number: f.campus_card_number || profile.campus_card_number || '',
      college: f.college || profile.college || '',
      major: f.major || profile.major || '',
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

  /**
   * 显式保存：trim 后全字段提交；昵称必填；空串视为清空（存 NULL）。
   * 后端只接受白名单字段，不在白名单的（学号/班级/学校）即使前端被绕也无效。
   */
  const handleSave = async () => {
    if (saving) return;
    const trimAll = (s: string) => s.trim();

    const payload = {
      nickname: trimAll(form.nickname),
      campus_card_number: trimAll(form.campus_card_number),
      college: trimAll(form.college),
      major: trimAll(form.major),
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

  const displayName = form.nickname || user?.username || '同学';

  // 渲染单行输入（label + input）
  const renderInputRow = (
    label: string,
    field: FieldKey,
    placeholder: string,
    options: { type?: 'text' | 'number' } = {},
  ) => (
    <View className="pedit-row" key={field}>
      <Text className="pedit-row-label">{label}</Text>
      <Input
        className="pedit-row-input"
        value={form[field]}
        placeholder={placeholder}
        placeholderClass="pedit-row-placeholder"
        maxlength={FIELD_MAXLEN[field]}
        type={options.type || 'text'}
        onInput={(e) => setForm((f) => ({ ...f, [field]: e.detail.value }))}
      />
    </View>
  );

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

        {/* 学籍信息：学院 / 专业（仅保留有意义的 2 项） */}
        <View className="pedit-section-title">学籍信息</View>
        {renderInputRow('学院', 'college', '如：计算机学院')}
        {renderInputRow('专业', 'major', '如：软件工程')}

        {/* 联系方式：校园卡号（手机号暂无采集入口，已移除） */}
        <View className="pedit-section-title">联系方式</View>
        {renderInputRow('校园卡号', 'campus_card_number', '一卡通号，非学号')}
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