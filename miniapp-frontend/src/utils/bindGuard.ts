import Taro from '@tarojs/taro';

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

/**
 * 本 app 运行周期内是否确认过「已绑定」
 *
 * 用途：区分「从未真正用上过账号」与「正常使用中被解绑」两种降级场景。
 * 前者（典型：上次放弃绑定后再次打开小程序，持久化登录态撞上业务接口 403 /
 * 绑定状态检查返回未绑定）应**静默**降级为游客——用户刚进 app 没有"正在使用"
 * 的体感，弹「已退出登录」既困惑又打扰；后者才需要明确提示。
 * 置位时机：finishBindGuide()（登录流程确认已绑定）与绑定状态检查返回已绑定。
 */
let bindConfirmedThisRun = false;

/** 本运行周期内是否确认过「已绑定」 */
export function hasBindConfirmedThisRun(): boolean {
  return bindConfirmedThisRun;
}

/** 标记本运行周期内确认过「已绑定」：绑定成功回调 / 绑定状态接口返回 bound 时调用 */
export function markBindConfirmed(): void {
  bindConfirmedThisRun = true;
}

/**
 * 绑定引导期「正常结束」事件名（登录 + 绑定双确认成立时广播）
 *
 * 为什么需要这个事件：引导期内 Tab 页 `useEffect([isLoggedIn])` 触发的拉取
 * 会被 `isBindGuideActive()` 拦下（防止未绑定接口必 403 的浪费与噪音），
 * 而引导期结束后 `isLoggedIn` 不再变化、该 effect 不会重发——若无人通知，
 * 首页「今日课程」等需登录数据会一直为空，用户只能手动下拉刷新。
 * 故在 `finishBindGuide()`（登录页确认已绑定 / 绑定页绑定成功，两条路径都代表
 * 「已登录且已绑定」双确认）时通过 eventCenter 广播，订阅方自行判断去重后补拉。
 * 命名与 TAB_INDEX_EVENT 等「模块级状态 + 事件广播」范式保持一致。
 */
export const BIND_GUIDE_FINISHED_EVENT = 'bindGuide:finished';

/** 是否处于「绑定引导进行中」（登录成功未绑定、正要去绑定页） */
export function isBindGuideActive(): boolean {
  return bindGuideActive;
}

/** 进入绑定引导期：登录页判定未绑定、即将 redirectTo 绑定页前调用 */
export function beginBindGuide(): void {
  bindGuideActive = true;
}

/**
 * 结束绑定引导期：绑定成功回调里调用
 *
 * 此刻「已登录且已绑定」双确认成立，除清标记外还广播 BIND_GUIDE_FINISHED_EVENT，
 * 让后台已挂载的 Tab 页（如首页）补拉引导期内被拦下的需登录数据。
 */
export function finishBindGuide(): void {
  bindGuideActive = false;
  // 引导期正常结束 = 绑定确认成立（此后本周期内若再检出未绑定，属正常使用中被解绑，
  // 降级时需提示用户，而非静默回收）
  bindConfirmedThisRun = true;
  try {
    Taro.eventCenter.trigger(BIND_GUIDE_FINISHED_EVENT);
  } catch {
    /* eventCenter 未就绪时忽略（首帧） */
  }
}

/** 取消绑定引导期：离开绑定页 / 用户放弃绑定时调用，避免标记残留误吞后续 403 降级 */
export function cancelBindGuide(): void {
  bindGuideActive = false;
}
