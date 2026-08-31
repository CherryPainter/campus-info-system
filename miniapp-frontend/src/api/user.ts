import { get, post, put } from '@/utils/request';
import type { StudentProfile, StudentProfileResult, UserMeResult } from '@/types/api';

/**
 * 用户 / 学生资料 API（/api/miniapp/user、/api/miniapp/student）
 * - user_id 一律取自后端 JWT，前端不传、不可越权
 */

/** 当前学生用户信息 */
export function getMe(): Promise<UserMeResult> {
  return get<UserMeResult>('/api/miniapp/user/me');
}

/** 本人学生资料 */
export function getProfile(): Promise<StudentProfileResult> {
  return get<StudentProfileResult>('/api/miniapp/student/profile');
}

/** 更新本人学生资料（只传需要修改的字段） */
export function updateProfile(
  data: Partial<Pick<StudentProfile, 'student_number' | 'real_name' | 'college' | 'major' | 'class_name' | 'grade' | 'phone'>>,
): Promise<StudentProfileResult> {
  return put<StudentProfileResult>('/api/miniapp/student/profile', data);
}
