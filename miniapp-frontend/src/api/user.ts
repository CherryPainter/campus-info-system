import { get, post, put } from '@/utils/request';
import type {
  BindResult,
  BindStatusResult,
  SchoolsResult,
  StudentProfile,
  StudentProfileResult,
  UserInfo,
  UserMeResult,
} from '@/types/api';

/**
 * 用户 / 学生资料 API（/api/miniapp/user、/api/miniapp/student）
 * - user_id 一律取自后端 JWT，前端不传、不可越权
 * - 学号/班级/学校由「身份绑定」接口管理（须命中管理员预录名单），
 *   资料编辑接口不再接受这三项
 */

/** 当前学生用户信息 */
export function getMe(): Promise<UserMeResult> {
  return get<UserMeResult>('/api/miniapp/user/me');
}

/** 本人学生资料 */
export function getProfile(): Promise<StudentProfileResult> {
  return get<StudentProfileResult>('/api/miniapp/student/profile');
}

/** 更新本人学生资料（只传需要修改的字段；学号/班级/学校不可经此修改） */
export function updateProfile(
  data: Partial<Pick<StudentProfile, 'campus_card_number' | 'real_name' | 'nickname' | 'college' | 'major' | 'grade' | 'phone'>>,
): Promise<StudentProfileResult> {
  return put<StudentProfileResult>('/api/miniapp/student/profile', data);
}

/** 更新本人头像（data URI），返回最新用户信息 */
export function updateAvatar(avatar: string): Promise<UserMeResult> {
  return put<UserMeResult>('/api/miniapp/user/avatar', { avatar });
}

/** 身份绑定状态（是否已通过预录名单绑定） */
export function getBindStatus(): Promise<BindStatusResult> {
  return get<BindStatusResult>('/api/miniapp/student/bind-status');
}

/** 可选学校列表（含模糊干扰项；重庆科创职业学院必须保留） */
export function getSchools(): Promise<SchoolsResult> {
  return get<SchoolsResult>('/api/miniapp/student/schools');
}

/** 提交身份绑定（学校+学号+班级 三项命中名单才成功） */
export function bindStudent(data: {
  school: string;
  student_number: string;
  class_name: string;
}): Promise<BindResult> {
  return post<BindResult>('/api/miniapp/student/bind', data);
}
