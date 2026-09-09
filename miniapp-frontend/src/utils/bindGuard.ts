/**
 * 绑定引导期护栏
 *
 * 背景：登录成功但未绑定时，`handleLogin` 会 `redirectTo` 身份绑定页引导用户绑定。
 * 但此刻后台已 mount 的 Tab 页（用户来源页）的 `useEffect([isLoggedIn])` 会**立即**
 * 重新 `loadAll()`，其中 `getProfile`/`getToday` 等是 `@student_bound_required` 接口，
 * 未绑定用户必然撞 403 `STUDENT_NOT_BOUND` → `request.ts` 的 `handleStudentNotBound`
 * 会把「刚登录、正要引导绑定」的状态误判为无效登录态而降级回游客并弹
 * 「身份未绑定，已退出登录」——与登录页正要跳绑定页打架，用户看到
 * 「登录成功 → 又被退出 → 才进绑定页」的错乱时序。
 *
 * 本模块提供一个模块级「绑定引导进行中」标记：
 * - 登录页判定未绑定、即将 redirectTo 绑定页前调用 `beginBindGuide()`；
 * - `request.ts` 的 `handleStudentNotBound` 在标记生效期间**只清 profile、不 logout、
 *   不弹「已退出登录」**（未绑定期后台 403 属预期，不应反噬登录态）；
 * - 绑定成功（`finishBindGuide`）或离开绑定页（`cancelBindGuide`）后清除标记，
 *   此后若仍命中 403（如会话中被解绑）恢复原有「降级游客 + 提示」行为。
 *
 * 纯模块级布尔，非响应式；跨页面（login / bind / request）共享靠 import 同一实例。
 */
let bindGuideActive = false;

/** 是否处于「绑定引导进行中」（登录成功未绑定、正要去绑定页） */
export function isBindGuideActive(): boolean {
  return bindGuideActive;
}

/** 进入绑定引导期：登录页判定未绑定、即将 redirectTo 绑定页前调用 */
export function beginBindGuide(): void {
  bindGuideActive = true;
}

/** 结束绑定引导期：绑定成功回调里调用 */
export function finishBindGuide(): void {
  bindGuideActive = false;
}

/** 取消绑定引导期：离开绑定页 / 用户放弃绑定时调用，避免标记残留误吞后续 403 降级 */
export function cancelBindGuide(): void {
  bindGuideActive = false;
}
