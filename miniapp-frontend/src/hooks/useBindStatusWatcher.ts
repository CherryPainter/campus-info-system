import Taro, { useDidShow } from '@tarojs/taro';

import * as userApi from '@/api/user';
import { useUserStore } from '@/stores/userStore';
import { useAuthStore } from '@/stores/authStore';
import { resetPrivateClickCount } from '@/hooks/useLoginGuard';

/**
 * 身份状态主动监察 + 无效登录态回收
 *
 * 核心判定：**「已登录但未绑定身份」是无效登录态，必须整体回退为游客。**
 *
 * 理由：此时 access token 有效、isLoggedIn=true，但所有业务接口一律
 * 403 STUDENT_NOT_BOUND——用户既用不了任何功能，又没有出口退回游客态，
 * 是个死状态。常见成因：
 *   1) 登录成功但未完成认证（新用户 / 在绑定页放弃绑定直接返回）；
 *   2) 会话中被管理员解绑（管理端「解绑/收回身份」）。
 * 两种成因统一处理：撤销登录态 + 一次性提示，回到游客态重新走流程。
 *
 * 触发点：Tab 页 useDidShow（home / profile / schedule）。
 * 非 Tab 页（如从课表详情进入绑定页再返回）由绑定页 useUnload 兜底。
 *
 * 合规：只回退状态，**不强制跳转**任何页面；游客仍可浏览公开内容。
 */

/** 同一原因只提示一次（避免切 Tab / 多页面重复 toast） */
let lastNoticeKey = '';

function notifyOnce(key: string, message: string): void {
  if (lastNoticeKey === key) return;
  lastNoticeKey = key;
  Taro.showToast({ title: message, icon: 'none', duration: 2500 });
}

/** 登录成功后调用：解除提示节流，允许下一次提示 */
export function resetBindNotice(): void {
  lastNoticeKey = '';
}

/**
 * 撤销登录态，回退为游客（同步执行，可在页面卸载回调中使用）
 *
 * 只清本地令牌，不再回调后端 logout：
 * - 解绑场景：服务端会话已被 `delete_all_user_sessions` 吊销，无需重复；
 * - 未绑定场景：该账号本就无任何业务数据访问权（一律 403），
 *   残留会话会在 1 小时内自然过期，无实际风险。
 */
export function revokeSession(message: string, noticeKey = 'revoke'): void {
  useAuthStore.getState().logout();
  useUserStore.getState().setProfile(null);
  // 回退为游客：私有模块点击累计也应清零，否则游客期攒的次数会误触发登录弹窗
  resetPrivateClickCount();
  notifyOnce(noticeKey, message);
}

export function useBindStatusWatcher(): void {
  useDidShow(() => {
    if (!useAuthStore.getState().isLoggedIn) return;
    userApi
      .getBindStatus()
      .then((res) => {
        const bound = !!res?.bound;
        const store = useUserStore.getState();

        if (bound) {
          // 已绑定：本地无缓存则补拉，保证「我的」页正常展示
          if (!store.profile) {
            userApi
              .getProfile()
              .then((p) => {
                if (p?.profile) useUserStore.getState().setProfile(p.profile);
              })
              .catch(() => {
                /* 忽略 */
              });
          }
          return;
        }

        // 未绑定：无效登录态，回退为游客。
        // 区分成因给不同提示（本地曾缓存过学号 = 会话中被解绑）
        const wasBound = !!store.profile?.student_number;
        revokeSession(
          wasBound
            ? '身份已被管理员解绑，请重新登录并认证'
            : '尚未完成身份认证，已退出登录',
          'unbound',
        );
      })
      .catch(() => {
        /* 网络/未登录失败静默，不阻塞主流程 */
      });
  });
}
