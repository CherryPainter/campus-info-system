/**
 * 根路径智能重定向
 * 管理员 → /dashboard，普通用户 → /welcome
 */
import { Navigate } from 'react-router-dom';
import { useUser } from '@/contexts/UserContext';
import { Spin } from 'antd';

export default function HomeRedirect() {
  const { loading, isAdmin } = useUser();

  if (loading) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  return <Navigate to={isAdmin ? '/dashboard' : '/welcome'} replace />;
}
