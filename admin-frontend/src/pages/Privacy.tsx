/**
 * 隐私政策页面
 * 校园信息聚合与智能推送系统
 */
import { Typography, Divider, Card } from "antd";

const { Title, Paragraph, Text, Link } = Typography;

export default function Privacy() {
  return (
    <div style={{ maxWidth: 900, margin: "40px auto", padding: "0 24px" }}>
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}>
        <Title level={2} style={{ textAlign: "center", marginBottom: 8 }}>
          隐私政策
        </Title>
        <Paragraph type="secondary" style={{ textAlign: "center", marginBottom: 32 }}>
          最后更新日期：2026年7月15日
        </Paragraph>

        <Divider />

        <Paragraph style={{ fontSize: 15, lineHeight: 2, textIndent: "2em" }}>
          校园信息聚合与智能推送系统（以下简称"本系统"）是面向高校内部使用的信息聚合与推送工具。
          我们深知个人信息保护的重要性，在此向您说明本系统的数据处理方式。
        </Paragraph>

        <Title level={4}>一、我们收集什么</Title>
        <Paragraph>
          本系统<Text strong>不收集、不存储用户的个人身份信息</Text>
          （如真实姓名、学号、身份证号、手机号等）。 系统仅存储保障基本功能运行所需的最少数据：
        </Paragraph>
        <Paragraph>
          <ul>
            <li>
              <Text strong>登录凭证</Text>：用户名和加密后的密码哈希值，仅用于身份认证；
            </li>
            <li>
              会话采用带时效的身份令牌机制，令牌具有有效期限制，会话整体保留时长取决于登录时是否勾选「记住我」，详见下方
              Cookie 政策；
            </li>
            <li>
              <Text strong>系统业务数据</Text>
              ：课程信息（从教务系统爬取）、电量使用数据、天气信息等，均为系统自动化功能所需的结构化数据，不涉及个人隐私。
            </li>
          </ul>
        </Paragraph>
        <Paragraph type="secondary" style={{ fontSize: 12 }}>
          注：本系统无邮箱绑定、无手机号收集等个人身份信息采集功能。用户可选择上传头像用于个性化展示，头像上传进行类型与大小校验，且为安全起见
          <Text strong>每自然年仅允许修改 3 次</Text>。
        </Paragraph>

        <Title level={4}>二、数据用途</Title>
        <Paragraph>本系统存储的所有数据仅用于以下内部用途：</Paragraph>
        <Paragraph>
          <ul>
            <li>
              <Text strong>身份认证</Text>：验证用户登录合法性，保障系统安全；
            </li>
            <li>
              <Text strong>信息推送</Text>：天气通知、电量告警、课程提醒等核心推送功能；
            </li>
            <li>
              <Text strong>数据展示</Text>
              ：在系统管理后台中展示课程表、电量趋势、天气信息等聚合数据。
            </li>
          </ul>
        </Paragraph>
        <Paragraph>
          本系统不会将任何数据用于商业目的，不会向第三方出售、分享或转让任何数据。
        </Paragraph>

        <Title level={4}>三、数据存储与安全</Title>
        <Paragraph>
          3.1 <Text strong>存储位置</Text>
          ：所有数据存储于本系统所在的服务器上，不涉及云端第三方存储。
        </Paragraph>
        <Paragraph>
          3.2 <Text strong>安全措施</Text>：
          <ul>
            <li>密码使用哈希算法加密存储，不以明文形式保存；</li>
            <li>使用带时效的身份令牌进行身份认证，令牌具有有效期限制；</li>
            <li>
              <Text strong>启用多因素认证</Text>（MFA）进行登录二次验证，进一步提升账户安全性；
            </li>
            <li>头像上传进行类型与大小校验，拒绝危险文件格式；</li>
            <li>提供「记住我」选项以延长会话有效期，降低公共设备被冒用风险；</li>
            <li>系统仅向通过身份认证的管理员开放，并采取访问控制等安全措施限制暴露面。</li>
          </ul>
        </Paragraph>

        <Title level={4}>四、Cookie 与本地存储</Title>
        <Paragraph>
          本系统使用必要的 httpOnly Cookie（access_token、refresh_token 与
          session_id）来维持用户会话状态，
          不会追踪您在其他网站的活动。其中会话整体有效期取决于登录时是否勾选「记住我」。 禁用 Cookie
          可能导致无法正常登录本系统。详细信息请查阅我们的 <Link href="/cookies">Cookie 政策</Link>
          。
        </Paragraph>

        <Title level={4}>五、第三方服务</Title>
        <Paragraph>本系统依赖以下第三方服务来实现功能：</Paragraph>
        <Paragraph>
          <ul>
            <li>
              <Text strong>和风天气 API</Text>：用于获取天气数据，查询请求发送至和风天气服务器；
            </li>
            <li>
              <Text strong>企业微信 Webhook</Text>：用于推送消息通知至指定群聊；
            </li>
            <li>
              <Text strong>教务系统</Text>
              ：爬取课程数据时需使用教务系统账户凭证，该凭证仅用于数据获取，不会被传播或用于其他目的。
            </li>
          </ul>
        </Paragraph>

        <Title level={4}>六、政策更新</Title>
        <Paragraph>
          我们可能会根据系统功能变化适时更新本隐私政策。更新后的政策将在系统中公布。
          建议您定期查阅本政策以了解最新的隐私保护措施。
        </Paragraph>

        <Title level={4}>七、联系我们</Title>
        <Paragraph>
          如您对本隐私政策有任何疑问，请通过<Link href="/contact">联系我们</Link>
          页面中提供的方式与我们取得联系。
        </Paragraph>
      </Card>
    </div>
  );
}
