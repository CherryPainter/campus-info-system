/**
 * 首页
 *
 * 功能：
 * - 简洁的用户欢迎信息
 * - 快捷功能入口
 * - 系统状态概览
 */
import { useNavigate } from "react-router-dom";
import { useUser } from "@/contexts/UserContext";
import { Card, Row, Col, Typography, Tag, Space, Grid } from "antd";
import {
  CloudOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  SettingOutlined,
} from "@ant-design/icons";

const { Title, Text } = Typography;

const menuItems = [
  {
    path: "/weather",
    name: "天气预警",
    icon: <CloudOutlined />,
    description: "查看天气预警信息",
    color: "#1890ff",
  },
  {
    path: "/electricity",
    name: "电量查询",
    icon: <ThunderboltOutlined />,
    description: "查询校园卡电量",
    color: "#faad14",
  },
  {
    path: "/course",
    name: "课程表",
    icon: <FileTextOutlined />,
    description: "查看课程安排",
    color: "#52c41a",
  },
  {
    path: "/profile",
    name: "个人中心",
    icon: <SettingOutlined />,
    description: "账号与安全设置",
    color: "#722ed1",
  },
];

export default function Welcome() {
  const { user } = useUser();
  const navigate = useNavigate();
  // 移动端断点：收缩根容器 padding，避免与 PageContainer 留白累加
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // 快捷入口用 SPA 内导航，避免整页跳转污染浏览器历史栈
  // （整页跳转会 push 独立历史条目，手机上左滑返回时容易落到“栈底刷新”）
  const handleNavigate = (path: string) => {
    navigate(path);
  };

  return (
    <div style={{ padding: isMobile ? 8 : 24 }}>
      {/* 欢迎横幅 */}
      <Card style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              欢迎回来，{user?.username || "用户"}
            </Title>
            <Text type="secondary">校园信息聚合与智能推送系统</Text>
          </div>
          <Tag color="blue">已登录</Tag>
        </div>
      </Card>

      {/* 快捷入口 */}
      <Title level={4} style={{ marginBottom: 16 }}>
        快捷入口
      </Title>
      <Row gutter={[16, 16]}>
        {menuItems.map((item) => (
          <Col xs={24} sm={12} lg={6} key={item.path}>
            <Card
              hoverable
              style={{ cursor: "pointer", transition: "all 0.2s" }}
              onClick={() => handleNavigate(item.path)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 8,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: `${item.color}15`,
                  }}
                >
                  <span style={{ color: item.color, fontSize: 18 }}>{item.icon}</span>
                </div>
                <div>
                  <Title level={5} style={{ marginBottom: 2 }}>
                    {item.name}
                  </Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.description}
                  </Text>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 使用提示：统一"彩色圆点 + 主题 + 说明"列表结构，避免 flex 横排长文字折行导致
          Tag 与其他行视觉不对齐；用 Antd icon 替代 emoji 作为彩色主题标记 */}
      <Card style={{ marginTop: 24 }} styles={{ body: { padding: isMobile ? 12 : 24 } }}>
        <Title level={4} style={{ marginBottom: 16 }}>
          使用提示
        </Title>
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          {[
            { color: "#1677ff", bg: "#e6f4ff", label: "天气预警", text: "系统会自动获取并推送天气预警信息到您的企业微信" },
            { color: "#fa8c16", bg: "#fff7e6", label: "电量查询", text: "一键查询校园卡余额，低电量时自动提醒充值" },
            { color: "#52c41a", bg: "#f6ffed", label: "课程表", text: "导入课表后，上课前会自动推送课程提醒" },
          ].map((item) => (
            <div
              key={item.label}
              style={{ display: "flex", alignItems: "flex-start", gap: 10 }}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minWidth: 56,
                  height: 22,
                  padding: "0 8px",
                  borderRadius: 4,
                  backgroundColor: item.bg,
                  color: item.color,
                  fontSize: 12,
                  fontWeight: 600,
                  flexShrink: 0,
                  lineHeight: 1,
                }}
              >
                {item.label}
              </span>
              <Text style={{ flex: 1, minWidth: 0 }}>{item.text}</Text>
            </div>
          ))}
        </Space>
      </Card>
    </div>
  );
}
