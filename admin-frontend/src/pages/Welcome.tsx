/**
 * 首页
 * 
 * 功能：
 * - 简洁的用户欢迎信息
 * - 快捷功能入口
 * - 系统状态概览
 */
import { useUser } from '@/contexts/UserContext';
import { Card, Row, Col, Typography, Tag, Space } from 'antd';
import { CloudOutlined, ThunderboltOutlined, FileTextOutlined, SettingOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

const menuItems = [
  { 
    path: '/weather', 
    name: '天气预警', 
    icon: <CloudOutlined />,
    description: '查看天气预警信息',
    color: '#1890ff'
  },
  { 
    path: '/electricity', 
    name: '电量查询', 
    icon: <ThunderboltOutlined />,
    description: '查询校园卡电量',
    color: '#faad14'
  },
  { 
    path: '/course', 
    name: '课程表', 
    icon: <FileTextOutlined />,
    description: '查看课程安排',
    color: '#52c41a'
  },
  { 
    path: '/profile', 
    name: '个人设置', 
    icon: <SettingOutlined />,
    description: '管理个人信息',
    color: '#722ed1'
  },
];

export default function Welcome() {
  const { user } = useUser();

  return (
    <div style={{ padding: 24 }}>
      {/* 欢迎横幅 */}
      <Card style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              欢迎回来，{user?.username || '用户'}
            </Title>
            <Text type="secondary">
              校园信息聚合与智能推送系统
            </Text>
          </div>
          <Tag color="blue">
            已登录
          </Tag>
        </div>
      </Card>

      {/* 快捷入口 */}
      <Title level={4} style={{ marginBottom: 16 }}>快捷入口</Title>
      <Row gutter={[16, 16]}>
        {menuItems.map((item) => (
          <Col xs={24} sm={12} lg={6} key={item.path}>
            <Card 
              hoverable 
              style={{ cursor: 'pointer', transition: 'all 0.2s' }}
              onClick={() => window.location.href = item.path}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div 
                  style={{ 
                    width: 40, 
                    height: 40, 
                    borderRadius: 8, 
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: `${item.color}15`
                  }}
                >
                  <span style={{ color: item.color, fontSize: 18 }}>{item.icon}</span>
                </div>
                <div>
                  <Title level={5} style={{ marginBottom: 2 }}>{item.name}</Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.description}
                  </Text>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 使用提示 */}
      <Card style={{ marginTop: 24 }}>
        <Title level={4} style={{ marginBottom: 16 }}>使用提示</Title>
        <Space direction="vertical" style={{ width: '100%' }}>
          <div style={{ display: 'flex', gap: 12 }}>
            <Tag color="blue">天气预警</Tag>
            <Text>系统会自动获取并推送天气预警信息到您的企业微信</Text>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Tag color="gold">电量查询</Tag>
            <Text>一键查询校园卡余额，低电量时自动提醒充值</Text>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Tag color="green">课程表</Tag>
            <Text>导入课表后，上课前会自动推送课程提醒</Text>
          </div>
        </Space>
      </Card>
    </div>
  );
}