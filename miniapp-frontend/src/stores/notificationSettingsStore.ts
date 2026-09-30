import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import Taro from '@tarojs/taro';

/**
 * 消息提醒设置（本地持久化，关闭后不再显示红色数字气泡）
 *
 * 设计原则：
 * - 总开关 masterEnabled 控制是否接收任何消息提醒；关闭时所有子开关失效。
 * - 子开关按消息类型细分，用户可只静默某类提醒（如只关每日电量日报，保留低电量告警）。
 * - 关闭后前端不再拉取未读计数、不再渲染红点，但历史消息仍可在「我的消息」页查看。
 */

export interface NotificationSettings {
  /** 总开关 */
  masterEnabled: boolean;
  /** 电量日报 */
  electricityDaily: boolean;
  /** 低电量提醒 */
  lowPower: boolean;
  /** 公告通知 */
  announcement: boolean;
  /** 反馈回复 */
  feedback: boolean;
}

interface NotificationSettingsState extends NotificationSettings {
  /** 设置总开关 */
  setMasterEnabled: (enabled: boolean) => void;
  /** 设置子开关 */
  setChannelEnabled: (key: Exclude<keyof NotificationSettings, 'masterEnabled'>, enabled: boolean) => void;
  /** 一键开启全部（恢复默认） */
  enableAll: () => void;
  /** 一键关闭全部 */
  disableAll: () => void;
}

const taroStorage = createJSONStorage(() => ({
  getItem: (name: string) => Taro.getStorageSync(name) || null,
  setItem: (name: string, value: string) => Taro.setStorageSync(name, value),
  removeItem: (name: string) => Taro.removeStorageSync(name),
}));

export const useNotificationSettingsStore = create<NotificationSettingsState>()(
  persist(
    (set) => ({
      masterEnabled: true,
      electricityDaily: true,
      lowPower: true,
      announcement: true,
      feedback: true,

      setMasterEnabled: (enabled) => set({ masterEnabled: enabled }),

      setChannelEnabled: (key, enabled) => set({ [key]: enabled }),

      enableAll: () =>
        set({
          masterEnabled: true,
          electricityDaily: true,
          lowPower: true,
          announcement: true,
          feedback: true,
        }),

      disableAll: () =>
        set({
          masterEnabled: false,
          electricityDaily: false,
          lowPower: false,
          announcement: false,
          feedback: false,
        }),
    }),
    {
      name: 'miniapp.notificationSettings',
      storage: taroStorage,
      partialize: (state) => ({
        masterEnabled: state.masterEnabled,
        electricityDaily: state.electricityDaily,
        lowPower: state.lowPower,
        announcement: state.announcement,
        feedback: state.feedback,
      }),
    },
  ),
);

/**
 * 判断当前是否允许展示消息提醒红点
 * - 总开关关闭：全部不展示
 * - 按类型传入的 channel 关闭：该类型不展示
 */
export function isNotificationEnabled(
  settings: NotificationSettings,
  channel?: Exclude<keyof NotificationSettings, 'masterEnabled'>,
): boolean {
  if (!settings.masterEnabled) return false;
  if (channel && !settings[channel]) return false;
  return true;
}
