/**
 * 用户与权限（整合页）
 * 将「用户管理」「会话管理」「访问控制（IP 黑名单）」三个模块整合到一个页面，使用 Tabs 切换
 * 路由：/access（仅管理员可访问）
 */
import { Tabs } from 'antd';
import {
  UserOutlined,
  DesktopOutlined,
  StopOutlined,
} from '@ant-design/icons';
import UserManagement from './UserManagement';
import SessionManager from './SessionManager';
import Blacklist from './Blacklist';

export default function AccessControl() {
  return (
    <Tabs
      defaultActiveKey="users"
      destroyInactiveTabPane={false}
      items={[
        {
          key: 'users',
          label: (
            <span>
              <UserOutlined />
              用户
            </span>
          ),
          children: <UserManagement />,
        },
        {
          key: 'sessions',
          label: (
            <span>
              <DesktopOutlined />
              会话
            </span>
          ),
          children: <SessionManager />,
        },
        {
          key: 'blacklist',
          label: (
            <span>
              <StopOutlined />
              访问控制
            </span>
          ),
          children: <Blacklist />,
        },
      ]}
    />
  );
}
