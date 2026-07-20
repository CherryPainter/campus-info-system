/**
 * 管理后台布局组件
 */
import { useState, useEffect } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { ProLayout, PageContainer } from "@ant-design/pro-components";
import { Dropdown, Avatar, Spin, App, Grid } from "antd";
import {
  DashboardOutlined,
  HomeOutlined,
  CloudOutlined,
  ThunderboltOutlined,
  BookOutlined,
  ScheduleOutlined,
  SendOutlined,
  PlayCircleOutlined,
  LinkOutlined,
  SettingOutlined,
  LogoutOutlined,
  UserOutlined,
  ProfileOutlined,
  CalendarOutlined,
} from "@ant-design/icons";
import { authApi } from "@/api/auth";
import { tokenStorage } from "@/utils/token";
import { useUser } from "@/contexts/UserContext";
import Footer from "@/components/Footer";

export default function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const { user, loading: userLoading, isAdmin, logout: userLogout } = useUser();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md; // 小于 md(768px) 视为移动端

  // 移动端侧边栏状态变化时，锁定/解锁背景滚动
  useEffect(() => {
    if (!isMobile) return;

    if (collapsed) {
      // 侧边栏关闭 → 恢复背景滚动（同时清 html / body）
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
    } else {
      // 侧边栏打开（ProLayout 移动端 Drawer open=!collapsed）→ 锁定背景滚动
      // 仅用 overflow 锁，不用 position:fixed，避免抽屉滑入时定位跳动（移动端常见坑）
      document.body.style.overflow = "hidden";
      document.documentElement.style.overflow = "hidden";
    }
  }, [collapsed, isMobile]);

  // 切换到非移动端时确保恢复滚动
  useEffect(() => {
    if (!isMobile) {
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
      document.body.style.position = "";
      document.body.style.width = "";
      document.body.style.top = "";
    }
  }, [isMobile]);

  // 根据角色动态生成菜单
  const menuItems = isAdmin
    ? [
        { path: "/dashboard", name: "仪表盘", icon: <DashboardOutlined /> },
        { path: "/access", name: "用户与权限", icon: <UserOutlined /> },
        { path: "/weather", name: "天气管理", icon: <CloudOutlined /> },
        { path: "/electricity", name: "电量管理", icon: <ThunderboltOutlined /> },
        { path: "/course", name: "课程管理", icon: <BookOutlined /> },
        { path: "/tasks", name: "任务管理", icon: <ScheduleOutlined /> },
        { path: "/push", name: "自定义推送", icon: <SendOutlined /> },
        { path: "/processes", name: "进程管理", icon: <PlayCircleOutlined /> },
        { path: "/webhooks", name: "Webhook 管理", icon: <LinkOutlined /> },
        { path: "/holiday", name: "假期模式", icon: <CalendarOutlined /> },
        { path: "/settings", name: "系统设置", icon: <SettingOutlined /> },
        { path: "/profile", name: "个人设置", icon: <ProfileOutlined /> },
      ]
    : [
        { path: "/welcome", name: "首页", icon: <HomeOutlined /> },
        { path: "/weather", name: "天气管理", icon: <CloudOutlined /> },
        { path: "/electricity", name: "电量管理", icon: <ThunderboltOutlined /> },
        { path: "/course", name: "课程管理", icon: <BookOutlined /> },
        { path: "/profile", name: "个人设置", icon: <ProfileOutlined /> },
      ];

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch (error) {
      // 忽略错误
    } finally {
      tokenStorage.clearTokens();
      // 重置 UserContext 状态
      userLogout();
      navigate("/login");
    }
  };

  const userMenuItems = [
    {
      key: "profile",
      icon: <UserOutlined />,
      label: "个人设置",
      onClick: () => navigate("/profile"),
    },
    { type: "divider" },
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: "退出登录",
      onClick: handleLogout,
    },
  ];

  if (userLoading) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          height: "100vh",
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  return (
    <ProLayout
      title={isMobile ? (isAdmin ? "后台" : "首页") : isAdmin ? "管理中心" : "个人设置"}
      logo={
        <div style={{ fontSize: "24px" }}>
          <DashboardOutlined />
        </div>
      }
      layout="mix"
      collapsed={collapsed}
      onCollapse={setCollapsed}
      breakpoint="md"
      location={{ pathname: location.pathname }}
      menuItemRender={(item, dom) => <div onClick={() => navigate(item.path || "/")}>{dom}</div>}
      menuDataRender={() => menuItems}
      actionsRender={() => [
        <Dropdown key="user" menu={{ items: userMenuItems as any }} placement="bottomRight">
          <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <Avatar size="small" icon={<UserOutlined />} src={user?.avatar} />
            {!isMobile && <span>{user?.username}</span>}
          </div>
        </Dropdown>,
      ]}
      footerRender={() => <Footer />}
    >
      <PageContainer
        header={{
          ghost: true,
          breadcrumb: isMobile ? {} : undefined,
        }}
      >
        <Outlet />
      </PageContainer>
    </ProLayout>
  );
}
