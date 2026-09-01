import Taro from '@tarojs/taro';

/**
 * 底部 TabBar 选中态的模块级共享状态。
 *
 * 为什么需要它：
 * - Taro 自定义 TabBar（custom-tab-bar，编译为原生 component:true）在切换 tab 时，
 *   框架可能重建/重置 React 组件的 state（useState 回到初值 0=首页），导致「点一下短暂选中又跳回首页」。
 * - 部分 tab 页是通过其它页面的 Taro.switchTab 直接进入的（如「我的」页的「我的课表」→时间轴），
 *   不经过 TabBar 自身的点击处理函数，若只靠点击时 setCurrent，选中态会错位。
 *
 * 解法：把「当前选中的 tab 下标」放到模块级变量，切换时只改这里 + 通过 eventCenter 广播；
 * 各 tab 页在 useDidShow 时各自广播自己的下标，TabBar 订阅事件即可与任何进入路径保持一致，
 * 与组件是否被重建无关。
 */

let _tabIndex = 0;

/** 当前选中的 tab 下标（0=首页 / 1=时间轴 / 2=我的） */
export function getTabIndex(): number {
  return _tabIndex;
}

/** TabBar 选中态变化事件名（供 CustomTabBar 订阅实时同步） */
export const TAB_INDEX_EVENT = 'tab:index';

/** 更新选中下标并广播（幂等：值未变不触发事件，避免无谓重渲染） */
export function setTabIndex(idx: number): void {
  if (_tabIndex === idx) return;
  _tabIndex = idx;
  try {
    Taro.eventCenter.trigger(TAB_INDEX_EVENT, idx);
  } catch {
    /* eventCenter 未就绪时忽略（首帧） */
  }
}
