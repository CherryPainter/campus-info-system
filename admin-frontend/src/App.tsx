/**
 * 应用入口组件
 * 配置 React Router 路由
 */
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider, App as AntdApp } from "antd";
import zhCN from "antd/locale/zh_CN";

import AuthGuard from "@/components/AuthGuard";
import AdminGuard from "@/components/AdminGuard";
import HomeRedirect from "@/components/HomeRedirect";
import { ServerStatusProvider } from "@/components/ServerStatusProvider";
import AdminLayout from "@/layouts/AdminLayout";
import { UserProvider } from "@/contexts/UserContext";
import Login from "@/pages/Login";
import Terms from "@/pages/Terms";
import About from "@/pages/About";
import Contact from "@/pages/Contact";
import Privacy from "@/pages/Privacy";
import Legal from "@/pages/Legal";
import Cookies from "@/pages/Cookies";
import Dashboard from "@/pages/Dashboard";
import Welcome from "@/pages/Welcome";
import Weather from "@/pages/Weather";
import Electricity from "@/pages/Electricity";
import Course from "@/pages/Course";
import Tasks from "@/pages/Tasks";
import Push from "@/pages/Push";
import Processes from "@/pages/Processes";
import Webhooks from "@/pages/Webhooks";
import HolidayMode from "@/pages/HolidayMode";
import Settings from "@/pages/Settings";
import Profile from "@/pages/Profile";
import AccessControl from "@/pages/AccessControl";

/**
 * App 组件
 * 应用根组件，配置路由和全局 Provider
 */
export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <AntdApp>
        <BrowserRouter>
          <UserProvider>
            <Routes>
              {/* 登录页 - 完全独立，无需认证 */}
              <Route path="/login" element={<Login />} />

              {/* 法律与信息页面 - 无需登录即可访问 */}
              <Route path="/terms" element={<Terms />} />
              <Route path="/about" element={<About />} />
              <Route path="/contact" element={<Contact />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/legal" element={<Legal />} />
              <Route path="/cookies" element={<Cookies />} />

              {/* 所有需要认证的路由，都由 AuthGuard 包裹 */}
              <Route element={<AuthGuard />}>
                {/* 带布局的路由 */}
                <Route
                  element={
                    <ServerStatusProvider>
                      <AdminLayout />
                    </ServerStatusProvider>
                  }
                >
                  {/* 默认重定向：管理员→仪表盘，普通用户→天气 */}
                  <Route path="/" element={<HomeRedirect />} />

                  {/* 功能页面 - 管理员专用 */}
                  <Route
                    path="/dashboard"
                    element={
                      <AdminGuard>
                        <Dashboard />
                      </AdminGuard>
                    }
                  />
                  <Route
                    path="/access"
                    element={
                      <AdminGuard>
                        <AccessControl />
                      </AdminGuard>
                    }
                  />
                  {/* 旧路径兼容重定向 */}
                  <Route path="/users" element={<Navigate to="/access" replace />} />
                  <Route path="/course" element={<Course />} />
                  <Route
                    path="/tasks"
                    element={
                      <AdminGuard>
                        <Tasks />
                      </AdminGuard>
                    }
                  />
                  <Route
                    path="/push"
                    element={
                      <AdminGuard>
                        <Push />
                      </AdminGuard>
                    }
                  />
                  <Route
                    path="/processes"
                    element={
                      <AdminGuard>
                        <Processes />
                      </AdminGuard>
                    }
                  />
                  <Route path="/blacklist" element={<Navigate to="/access" replace />} />
                  <Route
                    path="/webhooks"
                    element={
                      <AdminGuard>
                        <Webhooks />
                      </AdminGuard>
                    }
                  />
                  <Route
                    path="/holiday"
                    element={
                      <AdminGuard>
                        <HolidayMode />
                      </AdminGuard>
                    }
                  />
                  <Route
                    path="/settings"
                    element={
                      <AdminGuard>
                        <Settings />
                      </AdminGuard>
                    }
                  />

                  {/* 欢迎页面 - 普通用户默认首页 */}
                  <Route path="/welcome" element={<Welcome />} />

                  {/* 功能页面 - 所有用户可访问 */}
                  <Route path="/weather" element={<Weather />} />
                  <Route path="/electricity" element={<Electricity />} />
                  <Route path="/profile" element={<Profile />} />
                </Route>

                {/* 404 重定向 - 也在认证路由内 */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </UserProvider>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}
