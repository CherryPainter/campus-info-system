/**
 * 路由守卫组件
 * 检查用户是否已登录，未登录则重定向到登录页
 *
 * 复用 UserContext 的认证结果，避免并发 /auth/me 请求
 */
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { Spin } from "antd";
import { useUser } from "@/contexts/UserContext";
import { useSessionHeartbeat } from "@/hooks/useSessionHeartbeat";

/**
 * AuthGuard 组件
 * 包装需要认证的路由，验证用户是否已登录
 */
export default function AuthGuard() {
  const { user, loading, authenticated } = useUser();
  const location = useLocation();

  // 会话心跳：登录态才探测，空闲时也能及时发现“已在其他设备登录 / 过期”
  useSessionHeartbeat(!!authenticated && !loading);

  // 加载中（等待 UserContext 完成认证检查）
  if (loading) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  // 未登录（authenticated 为 false 或 null）或无用户信息，重定向到登录页
  if (!authenticated || !user) {
    // 防止重定向到登录页时再次触发认证循环
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  // 已登录，渲染子路由
  return <Outlet />;
}
