/**
 * 联系我们页面
 * 校园信息聚合与智能推送系统
 */
import { Typography, Divider, Card, Row, Col } from 'antd';
import {
  TeamOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

export default function Contact() {
  return (
    <div style={{ maxWidth: 800, margin: '40px auto', padding: '0 24px' }}>
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
        <Title level={2} style={{ textAlign: 'center', marginBottom: 8 }}>联系我们</Title>
        <Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 32 }}>
          我们随时为您提供帮助与支持
        </Paragraph>
        <Divider />

        <Row gutter={[24, 24]}>
          <Col xs={24} sm={12}>
            <Card
              style={{ borderRadius: 12, background: 'linear-gradient(135deg, #f0f5ff 0%, #e6f7ff 100%)', border: 'none' }}
              styles={{ body: { padding: 24 } }}
            >
              <div style={{ textAlign: 'center' }}>
                <TeamOutlined style={{ fontSize: 40, color: '#1890ff', marginBottom: 12 }} />
                <Title level={5}>由 Campus Notify Team 维护</Title>
                <Paragraph type="secondary" style={{ fontSize: 13 }}>
                  本系统由 Campus Notify Team 开发和维护。如您在使用过程中遇到技术问题或系统故障，欢迎通过以下方式反馈。
                </Paragraph>
              </div>
            </Card>
          </Col>
          <Col xs={24} sm={12}>
            <Card
              style={{ borderRadius: 12, background: 'linear-gradient(135deg, #fff7e6 0%, #fffbe6 100%)', border: 'none' }}
              styles={{ body: { padding: 24 } }}
            >
              <div style={{ textAlign: 'center' }}>
                <ExclamationCircleOutlined style={{ fontSize: 40, color: '#faad14', marginBottom: 12 }} />
                <Title level={5}>问题反馈</Title>
                <Paragraph type="secondary" style={{ fontSize: 13 }}>
                  如您发现系统 Bug、数据异常，或有功能改进建议，请通过系统管理员或团队内部渠道反馈，我们会尽快处理。
                </Paragraph>
              </div>
            </Card>
          </Col>
        </Row>

        <Divider />

        <Title level={4}>联系邮箱</Title>
        <Paragraph>
          如需通过邮件联系我们，请发送至：
        </Paragraph>
        <Paragraph>
          <Text
            copyable
            strong
            style={{ fontSize: 16, background: '#f5f5f5', padding: '8px 16px', borderRadius: 8 }}
          >
            {import.meta.env.VITE_CONTACT_EMAIL || 'your-email@example.com'}
          </Text>
        </Paragraph>

        <Divider />

        <Title level={4}>反馈建议</Title>
        <Paragraph>
          我们非常重视每一位用户的意见与建议。您的反馈将帮助我们不断改进和完善系统功能。
          在提交反馈时，请尽量提供以下信息，以便我们更快地定位和处理问题：
        </Paragraph>
        <Paragraph>
          <ul>
            <li>问题发生的具体时间和操作步骤</li>
            <li>相关的页面链接或截图</li>
            <li>浏览器类型和版本（如适用）</li>
            <li>期望的行为或改进方向</li>
          </ul>
        </Paragraph>

        <Divider />

        <Paragraph type="secondary" style={{ textAlign: 'center', fontSize: 12 }}>
          感谢您对校园信息聚合与智能推送系统的支持与关注！
        </Paragraph>
      </Card>
    </div>
  );
}
