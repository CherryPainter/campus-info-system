import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { authApi } from '@/api/auth';
import type { User } from '@/types/user';

interface UserContextType {
  user: User | null;
  loading: boolean;
  /** true = 已认证, false = 认证失败(未登录/token无效), null = 尚未检查 */
  authenticated: boolean | null;
  refreshUser: () => Promise<void>;
  loginSuccess: (userData: User) => void;
  logout: () => void;
  isAdmin: boolean;
  isPrimary: boolean;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

// 公开页面列表（无需登录即可访问）
const PUBLIC_PATHS = ['/login', '/terms', '/about', '/contact', '/privacy', '/legal', '/cookies'];

// 检查当前是否在公开页面（无需鉴权）
function isPublicPage(pathname: string): boolean {
  return PUBLIC_PATHS.includes(pathname);
}

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const location = useLocation();

  const refreshUser = async () => {
    // 如果已经明确是未登录状态，就不要再尝试请求了
    if (authenticated === false) {
      setLoading(false);
      return;
    }

    // 如果在公开页面，不执行认证检查
    if (isPublicPage(location.pathname)) {
      setLoading(false);
      return;
    }
    
    try {
      const res = await authApi.getMe();
      if (res.status === 'success' && res.user) {
        setUser(res.user);
        setAuthenticated(true);
      } else {
        setUser(null);
        setAuthenticated(false);
      }
    } catch {
      setUser(null);
      setAuthenticated(false);
    } finally {
      setLoading(false);
    }
  };

  /**
   * 登录成功时调用此方法更新用户状态
   * 直接使用登录响应中的用户数据，避免等待 /auth/me 接口
   */
  const loginSuccess = (userData: User) => {
    setUser(userData);
    setAuthenticated(true);
    setLoading(false);
  };

  /**
   * 退出登录时调用此方法重置状态
   */
  const logout = () => {
    setUser(null);
    setAuthenticated(false);
    setLoading(false);
  };

  useEffect(() => {
    // 只在非公开页面执行认证检查
    if (!isPublicPage(location.pathname)) {
      refreshUser();
    } else {
      // 在公开页面，直接结束加载状态
      setLoading(false);
      setAuthenticated(false);
    }
  }, [location.pathname]);

  return (
    <UserContext.Provider value={{
      user,
      loading,
      authenticated,
      refreshUser,
      loginSuccess,
      logout,
      isAdmin: user?.role === 'admin',
      isPrimary: user?.is_primary === true,
    }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error('useUser must be used within UserProvider');
  }
  return context;
}
