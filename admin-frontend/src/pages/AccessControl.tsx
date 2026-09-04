/**
 * 用户与权限（整合页）
 * 扁平四分区，使用 Tabs 切换：
 *   - 账号：登录账号（网页 admin/user + 微信 student，来源感知列与操作）
 *   - 学生身份：预录名单（门禁）+ 绑定状态合一（名单条目被哪个用户认领）
 *   - 会话：ServerSession 管理
 *   - 访问控制：IP 黑名单
 * 路由：/access（仅管理员可访问）
 */
import { Tabs } from "antd";
import {
  UserOutlined,
  IdcardOutlined,
  DesktopOutlined,
  StopOutlined,
} from "@ant-design/icons";
import UserManagement from "./UserManagement";
import UserManagementRoster from "./UserManagementRoster";
import SessionManager from "./SessionManager";
import Blacklist from "./Blacklist";

export default function AccessControl() {
  return (
    <Tabs
      defaultActiveKey="accounts"
      destroyInactiveTabPane={false}
      items={[
        {
          key: "accounts",
          label: (
            <span>
              <UserOutlined />
              账号
            </span>
          ),
          children: <UserManagement />,
        },
        {
          key: "student-identity",
          label: (
            <span>
              <IdcardOutlined />
              学生身份
            </span>
          ),
          children: <UserManagementRoster />,
        },
        {
          key: "sessions",
          label: (
            <span>
              <DesktopOutlined />
              会话
            </span>
          ),
          children: <SessionManager />,
        },
        {
          key: "blacklist",
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
