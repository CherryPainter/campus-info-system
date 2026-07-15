/**
 * 法律声明页面
 * 校园信息聚合与智能推送系统
 */
import { Typography, Divider, Card, Alert } from 'antd';
import { SafetyOutlined } from '@ant-design/icons';

const { Title, Paragraph, Text, Link } = Typography;

export default function Legal() {
  return (
    <div style={{ maxWidth: 900, margin: '40px auto', padding: '0 24px' }}>
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
        <Title level={2} style={{ textAlign: 'center', marginBottom: 8 }}>法律声明</Title>
        <Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 32 }}>
          最后更新日期：2026年7月7日
        </Paragraph>

        <Alert
          message="请仔细阅读以下法律声明"
          description="使用本系统即表示您已阅读、理解并同意接受本法律声明的全部条款。如您不同意任何条款，请立即停止使用本系统。"
          type="info"
          showIcon
          icon={<SafetyOutlined />}
          style={{ marginBottom: 24, borderRadius: 8 }}
        />

        <Divider />

        <Title level={4}>一、版权声明</Title>
        <Paragraph>
          1.1 本系统（校园信息聚合与智能推送系统）的名称、标识、界面设计、源代码、
          文档以及其他所有相关内容的著作权和相关知识产权归 Campus Notify Team 所有，
          受《中华人民共和国著作权法》、《计算机软件保护条例》等法律法规的保护。
        </Paragraph>
        <Paragraph>
          1.2 未经 Campus Notify Team 书面许可，任何单位或个人不得以任何方式复制、修改、
          传播、反编译、反向工程或以其他方式使用本系统的任何组成部分。
        </Paragraph>
        <Paragraph>
          1.3 本系统中展示的图标部分来源于 Ant Design 图标库，遵循 MIT 开源协议。
        </Paragraph>

        <Title level={4}>二、名称与标识</Title>
        <Paragraph>
          本系统中使用的名称和标识由 Campus Notify Team 设计和使用。
          未经授权，任何单位或个人不得在可能导致公众混淆的情况下使用与本系统相同或近似的名称与标识。
        </Paragraph>

        <Title level={4}>三、数据来源声明</Title>
        <Paragraph>
          3.1 本系统提供的天气数据来源于<Text strong>和风天气</Text>（https://www.qweather.com），
          数据版权归和风天气所有。本系统通过和风天气开发者接口获取天气数据。
        </Paragraph>
        <Paragraph>
          3.2 本系统提供的电量数据来源于校园电表管理系统，课程数据来源于教务系统。
          上述数据的准确性、完整性和及时性由数据源系统负责，本系统不作任何明示或默示的保证。
        </Paragraph>
        <Paragraph>
          3.3 本系统仅作为信息聚合和推送平台，不以任何方式对原始数据进行修改或歪曲进行展示。
        </Paragraph>

        <Title level={4}>四、免责声明</Title>
        <Paragraph>
          4.1 <Text strong>信息准确性</Text>：本系统尽力确保所提供信息的准确性和可靠性，
          但由于数据来源的局限性，不保证信息的绝对准确、完整和及时。
          用户依据本系统信息作出的任何决策，由其自行承担风险。
        </Paragraph>
        <Paragraph>
          4.2 <Text strong>服务可用性</Text>：本系统可能因系统维护、网络故障、第三方服务中断、
          不可抗力等原因暂时无法提供服务。我们不对因服务中断造成的任何损失承担责任。
        </Paragraph>
        <Paragraph>
          4.3 <Text strong>第三方链接</Text>：本系统可能包含指向第三方网站或服务的链接（如 ICP 备案查询），
          这些链接仅供用户便利使用。我们对第三方网站的内容、隐私政策和行为不承担任何责任。
        </Paragraph>
        <Paragraph>
          4.4 <Text strong>用户行为</Text>：用户应自行对其在系统中的行为负责。
          若用户违反法律法规或本协议规定使用本系统，由其自行承担相应法律责任。
        </Paragraph>

        <Title level={4}>五、责任限制</Title>
        <Paragraph>
          在法律允许的最大范围内，本系统及其开发团队对以下情形不承担任何责任：
        </Paragraph>
        <Paragraph>
          <ul>
            <li>因使用或无法使用本系统服务而产生的任何直接、间接、附带、特殊或继发性损失；</li>
            <li>因第三方服务（天气API、企业微信、教务系统等）的故障或变更导致的服务异常；</li>
            <li>因用户终端设备、网络环境或操作不当导致的问题；</li>
            <li>因不可抗力事件（自然灾害、战争、政府行为等）导致的服务中断或数据丢失。</li>
          </ul>
        </Paragraph>

        <Title level={4}>六、链接政策</Title>
        <Paragraph>
          6.1 未经 Campus Notify Team 书面同意，任何网站或平台不得建立指向本系统的超链接。
        </Paragraph>
        <Paragraph>
          6.2 如需在您的网站或应用中引用本系统的信息，应当注明信息来源，
          并确保引用的信息准确无误，不得进行歪曲或断章取义的转载。
        </Paragraph>

        <Title level={4}>七、适用法律与管辖</Title>
        <Paragraph>
          7.1 本法律声明的订立、执行、解释及争议解决均适用中华人民共和国法律。
        </Paragraph>
        <Paragraph>
          7.2 因本声明引起的或与本声明有关的任何争议，双方应首先友好协商解决。
          协商不成的，任何一方均可向有管辖权的人民法院提起诉讼。
        </Paragraph>

        <Title level={4}>八、声明更新</Title>
        <Paragraph>
          我们保留随时修改本法律声明的权利，修改后的版本将在系统中公示。
          建议您定期查阅本页面以了解最新信息。重大变更将通过适当方式通知您。
        </Paragraph>

        <Title level={4}>九、相关文件</Title>
        <Paragraph>
          本法律声明应与以下文件一并阅读，共同构成您使用本系统的完整法律基础：
        </Paragraph>
        <Paragraph>
          <ul>
            <li><Link href="/terms">用户协议</Link></li>
            <li><Link href="/privacy">隐私政策</Link></li>
            <li><Link href="/cookies">Cookie 政策</Link></li>
          </ul>
        </Paragraph>

        <Divider />
        <Paragraph type="secondary" style={{ textAlign: 'center', fontSize: 12 }}>
          校园信息聚合与智能推送系统 · Campus Notify Team · © 2026
        </Paragraph>
      </Card>
    </div>
  );
}
