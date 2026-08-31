import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import Taro from '@tarojs/taro';

import type { UserInfo } from '@/types/api';
import { clearTokens, clearUserInfo, setTokens, setUserInfo } from '@/utils/storage';

/**
 * 认证状态（全局唯一真相源）
 * - accessToken / refreshToken / userInfo / isLoggedIn 跨页面共享
 * - 持久化到本地 storage（小程序冷启动后恢复登录态）
 * - Token 的读写只允许经过本 store 与 utils/request.ts
 */

interface AuthState {
  accessToken: string;
  refreshToken: string;
  user: UserInfo | null;
  isLoggedIn: boolean;
  setAuth: (payload: {
    accessToken: string;
    refreshToken: string;
    expiresIn?: number;
    user: UserInfo;
  }) => void;
  setUser: (user: UserInfo | null) => void;
  logout: () => void;
}

/** 微信小程序 storage 适配 zustand persist */
const taroStorage = createJSONStorage(() => ({
  getItem: (name: string) => Taro.getStorageSync(name) || null,
  setItem: (name: string, value: string) => Taro.setStorageSync(name, value),
  removeItem: (name: string) => Taro.removeStorageSync(name),
}));

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: '',
      refreshToken: '',
      user: null,
      isLoggedIn: false,

      setAuth: ({ accessToken, refreshToken, expiresIn, user }) => {
        setTokens(accessToken, refreshToken, expiresIn);
        setUserInfo(user);
        set({ accessToken, refreshToken, user, isLoggedIn: true });
      },

      setUser: (user) => {
        if (user) {
          setUserInfo(user);
        } else {
          clearUserInfo();
        }
        set({ user });
      },

      logout: () => {
        clearTokens();
        clearUserInfo();
        set({ accessToken: '', refreshToken: '', user: null, isLoggedIn: false });
      },
    }),
    {
      name: 'miniapp.auth',
      storage: taroStorage,
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isLoggedIn: state.isLoggedIn,
      }),
    },
  ),
);
