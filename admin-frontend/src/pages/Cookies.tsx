/**
 * Cookie 政策页面
 * 校园信息聚合与智能推送系统
 */
import { Typography, Divider, Card, Tag, Alert } from 'antd';
import ResponsiveTable from '@/components/ResponsiveTable';
import { SafetyOutlined } from '@ant-design/icons';

const { Title, Paragraph, Text, Link } = Typography;

export default function Cookies() {
  const cookieTable = [
    {
      key: '1',
      name: 'access_token',
      type: '必要',
      provider: '本系统',
      purpose: '身份令牌，用于身份认证和接口鉴权（httpOnly，JS 不可读取）',
      duration: '约 1 小时',
    },
    {
      key: '2',
      name: 'refresh_token',
      type: '必要',
      provider: '本系统',
      purpose: '刷新令牌，用于在访问令牌过期后自动续期（httpOnly，JS 不可读取）',
      duration: '与"记住我"联动（不勾≤1天 / 勾选≤30天）',
    },
    {
      key: '3',
      name: 'session_id',
      type: '必要',
      provider: '本系统',
      purpose: '服务端会话标识，用于维持登录状态与会话安全（httpOnly，JS 不可读取）',
      duration: '与登录时是否勾选"记住我"联动',
    },
  ];

  const columns = [
    { title: 'Cookie 名称', dataIndex: 'name', key: 'name', width: 160 },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (v: string) => (
        <Tag color={v === '必要' ? 'blue' : 'green'}>{v}</Tag>
      ),
    },
    { title: '提供方', dataIndex: 'provider', key: 'provider', width: 100 },
    { title: '用途', dataIndex: 'purpose', key: 'purpose' },
    { title: '有效期', dataIndex: 'duration', key: 'duration', width: 200 },
  ];

  return (
    <div style={{ maxWidth: 900, margin: '40px auto', padding: '0 24px' }}>
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
        <Title level={2} style={{ textAlign: 'center', marginBottom: 8 }}>Cookie 政策</Title>
        <Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 32 }}>
          最后更新日期：2026年7月15日
        </Paragraph>

        <Divider />

        <Title level={4}>一、什么是 Cookie</Title>
        <Paragraph>
          Cookie 是网站在您访问时存储在您的计算机或移动设备上的小型文本文件。
          Cookie 被广泛用于使网站正常运行、提高运行效率以及向网站所有者提供信息。
          除了 Cookie 外，我们还可能使用 localStorage（本地存储）来实现类似的功能。
        </Paragraph>

        <Title level={4}>二、我们使用的 Cookie</Title>
        <Paragraph>本系统仅使用必要的 httpOnly Cookie 来提供核心功能。这些 Cookie 由后端服务设置，前端 JavaScript 代码无法读取或修改，有效防止跨站脚本攻击窃取令牌。本系统不包含广告追踪或第三方分析 Cookie：</Paragraph>

        <ResponsiveTable
          dataSource={cookieTable}
          columns={columns}
          pagination={false}
          size="small"
          bordered
          style={{ marginTop: 12, marginBottom: 16 }}
          scroll={{ x: 700 }}
        />

        <Title level={4}>三、Cookie 的用途</Title>
        <Paragraph>本系统中的 Cookie 仅用于以下目的：</Paragraph>
        <Paragraph style={{ fontSize: 15, lineHeight: 2, textIndent: '2em' }}>
          关于<Text strong>"记住我"</Text>：登录页的「记住我」复选框决定会话时长。
          <Text strong>未勾选</Text>时为较短的临时会话；
          <Text strong>勾选</Text>时为较长的长期会话。
          无论哪种情况，关闭浏览器本身不会清空 httpOnly Cookie，但会话仍会按上述时长到期，到期后将自动退出登录。
        </Paragraph>
        <Paragraph>
          <ul>
            <li>
              <Text strong>身份认证</Text>：httpOnly Cookie 存储身份令牌，
              使您在浏览不同页面时无需重复登录，确保您的身份被正确识别。
            </li>
            <li>
              <Text strong>会话管理</Text>：维护您的登录状态，区分不同用户的请求，
              保护您的账户不被未授权访问。
            </li>
          </ul>
        </Paragraph>
        <Paragraph>
          <Text strong>我们不会使用 Cookie 来：</Text>
        </Paragraph>
        <Paragraph>
          <ul>
            <li>追踪您在其他网站上的浏览行为；</li>
            <li>收集个人身份信息用于广告投放或用户画像；</li>
            <li>与非关联第三方共享 Cookie 数据；</li>
            <li>在您登出后继续追踪您的活动。</li>
          </ul>
        </Paragraph>

        <Title level={4}>四、第三方 Cookie</Title>
        <Paragraph>
          本系统<Text strong>不使用任何第三方 Cookie</Text>（如广告追踪器、社交媒体插件、分析服务等）。
          所有 Cookie 均由本系统自身设置，数据完全由我们控制，不会被任何第三方访问。
        </Paragraph>

        <Title level={4}>五、管理 Cookie</Title>
        <Paragraph>
          大多数浏览器默认接受 Cookie，但您可以通过浏览器设置来管理或删除 Cookie。
          不同浏览器的设置方式有所不同，以下为常见浏览器的设置指南链接：
        </Paragraph>
        <Paragraph>
          <ul>
            <li>Chrome：设置 → 隐私和安全 → Cookie 和其他网站数据</li>
            <li>Edge：设置 → Cookie 和网站权限 → 管理和删除 Cookie</li>
            <li>Firefox：选项 → 隐私与安全 → Cookie 和网站数据</li>
            <li>Safari：偏好设置 → 隐私 → Cookie 和网站数据</li>
          </ul>
        </Paragraph>

        <Alert
          message="重要提示"
          description="由于本系统的 Cookie 用于维持登录状态和身份认证，如果您禁用 Cookie，将无法登录和使用本系统。建议您保持 Cookie 开启以获得完整的功能体验。"
          type="warning"
          showIcon
          style={{ marginTop: 16, marginBottom: 16, borderRadius: 8 }}
        />

        <Title level={4}>六、LocalStorage（本地存储）</Title>
        <Paragraph>
          除 httpOnly Cookie 外，本系统的前端界面状态（如侧边栏折叠、页面切换等）完全由 React 组件状态管理，
          不会持久化到浏览器本地存储。登出时，系统会清理任何历史遗留的本地存储数据。
        </Paragraph>

        <Title level={4}>七、数据安全</Title>
        <Paragraph>
          存储在 Cookie 中的身份令牌经过签名保护，可防止被篡改。
          我们建议您：
        </Paragraph>
        <Paragraph>
          <ul>
            <li>使用完毕后及时退出登录，清除会话 Cookie；</li>
            <li>不要在公共或共享设备上选择"记住我"功能；</li>
            <li>头像上传仅支持 JPG / PNG / GIF / WEBP 且不超过 2MB，请勿上传来源不明或异常格式的文件；</li>
            <li>保持浏览器和操作系统更新以获得最新的安全补丁。</li>
          </ul>
        </Paragraph>

        <Title level={4}>八、政策更新</Title>
        <Paragraph>
          我们可能会根据技术变更或法律法规要求适时更新本 Cookie 政策。
          更新后的政策将在系统中公布。建议您定期查阅本页面以了解最新信息。
        </Paragraph>

        <Title level={4}>九、相关文件</Title>
        <Paragraph>
          本 Cookie 政策应与以下文件一并阅读，以全面了解我们对您个人信息的处理方式：
        </Paragraph>
        <Paragraph>
          <ul>
            <li><Link href="/privacy">隐私政策</Link></li>
            <li><Link href="/terms">用户协议</Link></li>
            <li><Link href="/legal">法律声明</Link></li>
          </ul>
        </Paragraph>

        <Divider />
        <Paragraph type="secondary" style={{ textAlign: 'center', fontSize: 12 }}>
          校园信息聚合与智能推送系统 · CherryPainter · © 2026
        </Paragraph>
      </Card>
    </div>
  );
}
