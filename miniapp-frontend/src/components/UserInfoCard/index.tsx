import { View, Text, Image } from '@tarojs/components';

import type { StudentProfile, UserInfo } from '@/types/api';
import './index.scss';

interface UserInfoCardProps {
  user: UserInfo | null;
  profile: StudentProfile | null;
  onEdit?: () => void;
}

/**
 * 用户资料卡片（§14）
 * - 展示字段以后端实际返回为准：头像（有则显示）/ 姓名（profile.real_name 优先）/ 学号 / 专业·学院 / 班级·年级
 */
export default function UserInfoCard({ user, profile, onEdit }: UserInfoCardProps) {
  const name = profile?.real_name || user?.username || '同学';
  const majorCollege = [profile?.major, profile?.college].filter(Boolean).join(' · ');
  const classGrade = [profile?.class_name, profile?.grade ? `${profile.grade}级` : '']
    .filter(Boolean)
    .join(' · ');

  return (
    <View className="user-card" onClick={onEdit}>
      {user?.avatar ? (
        <Image className="user-avatar" src={user.avatar} mode="aspectFill" />
      ) : (
        <View className="user-avatar user-avatar-placeholder">
          <Text className="avatar-text">{name.slice(0, 1)}</Text>
        </View>
      )}
      <View className="user-info">
        <Text className="user-name">{name}</Text>
        {profile?.student_number ? (
          <Text className="user-sub">学号 {profile.student_number}</Text>
        ) : null}
        {majorCollege ? <Text className="user-sub">{majorCollege}</Text> : null}
        {classGrade ? <Text className="user-sub">{classGrade}</Text> : null}
      </View>
    </View>
  );
}
