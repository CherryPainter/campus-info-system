import { del, get, post, put } from '@/utils/request';
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

/** 可选学校列表（从管理端组织树动态读取） */
export function getSchools(): Promise<SchoolsResult> {
  return get<SchoolsResult>('/api/miniapp/student/schools');
}

/** 提交身份绑定（学校+学号+一次性绑定码 命中名单才成功；班级/学院/专业由名单继承） */
export function bindStudent(data: {
  school: string;
  student_number: string;
  bind_code: string;
}): Promise<BindResult> {
  return post<BindResult>('/api/miniapp/student/bind', data);
}

/**
 * 注销当前账号（DELETE /api/miniapp/auth/user/me）
 * - 后端软删 users.is_active=False + 撤销当前 access_token + 可选撤销 refresh_token
 * - 注销后该微信号无法再次登录小程序（同 openid 命中 is_active=False 用户会被拒）
 * - refresh_token 通过 query 传入（避免 DELETE body 不规范）
 */
export function deleteAccount(refreshToken?: string): Promise<{ status: string; message: string }> {
  const params: Record<string, string> = {};
  if (refreshToken) params.refresh_token = refreshToken;
  return del('/api/miniapp/auth/user/me', params);
}
