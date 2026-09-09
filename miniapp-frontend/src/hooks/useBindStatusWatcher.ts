import Taro, { useDidShow } from '@tarojs/taro';

import * as userApi from '@/api/user';
import { useUserStore } from '@/stores/userStore';
import { useAuthStore } from '@/stores/authStore';

/**
 * 身份状态主动监察（承接管理端「解绑/收回身份」新特性）
 *
 * 在 Tab 页 useDidShow 时调用 GET /student/bind-status（仅 @student_required，
 * 未绑定时返回 bound:false 而不会 403），用于「管理员在小程序后台解绑某学生」后，
 * 前端无需等某次业务请求撞 403 才感知：
 * - 本已绑定（本地 profile.student_number 存在）却被判定未绑定 → 清空本地身份缓存并提示一次，
 *   **不自动跳转绑定页**（合规：不得强制打断用户，认证入口由用户主动进入或点击私有功能时触发）；
 * - 已绑定但本地无 profile 缓存 → 补拉资料，保证「我的」页正常展示。
 * 失败（网络/未登录/游客）静默，不阻塞主流程。
 */

/** 同一次解绑只提示一次（避免每次切 Tab 都弹 toast） */
let lastUnbindNoticed = '';

export function useBindStatusWatcher(): void {
  useDidShow(() => {
    if (!useAuthStore.getState().isLoggedIn) return;
    userApi
      .getBindStatus()
      .then((res) => {
        const bound = !!res?.bound;
        const store = useUserStore.getState();
        if (!bound && store.profile?.student_number) {
          // 已被管理员解绑：清空身份缓存（学号/班级不再显旧值）+ 提示一次。
          // 不 reLaunch 绑定页：认证属于用户主动行为，未认证时仍可浏览公开内容。
          const num = store.profile.student_number;
          store.setProfile(null);
          if (lastUnbindNoticed !== num) {
            lastUnbindNoticed = num;
            Taro.showToast({ title: '身份已被解绑，请重新认证后使用', icon: 'none' });
          }
        } else if (bound && !store.profile) {
          // 已绑定但本地无缓存：补拉，保证展示
          userApi
            .getProfile()
            .then((p) => {
              if (p?.profile) useUserStore.getState().setProfile(p.profile);
            })
            .catch(() => {
              /* 忽略 */
            });
        }
      })
      .catch(() => {
        /* 网络/未登录失败静默 */
      });
  });
}
