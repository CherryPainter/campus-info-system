import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import Taro from '@tarojs/taro';

import type { StudentProfile } from '@/types/api';

/**
 * 学生资料状态
 * - 「我的」页展示 / 编辑后缓存，跨页面共享
 * - 仅在登录后加载，登出时清空
 */

interface UserState {
  profile: StudentProfile | null;
  setProfile: (profile: StudentProfile | null) => void;
}

const taroStorage = createJSONStorage(() => ({
  getItem: (name: string) => Taro.getStorageSync(name) || null,
  setItem: (name: string, value: string) => Taro.setStorageSync(name, value),
  removeItem: (name: string) => Taro.removeStorageSync(name),
}));

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      profile: null,
      setProfile: (profile) => set({ profile }),
    }),
    {
      name: 'miniapp.user',
      storage: taroStorage,
      partialize: (state) => ({ profile: state.profile }),
    },
  ),
);
