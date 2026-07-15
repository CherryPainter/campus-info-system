// 统一轮询间隔常量，替换散落在各页面的 1s/2s/3s/5s/30s 魔法值
export const POLL_TICK = 1000; // 时钟 / 倒计时刷新
export const POLL_FAST = 2000; // 任务状态 / 运行中列表轮询
export const POLL_NORMAL = 5000; // 一般周期刷新
export const POLL_SLOW = 30000; // 仪表盘 / 存活探测
