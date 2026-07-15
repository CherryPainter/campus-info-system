/**
 * 用户协议页面
 * 校园信息聚合与智能推送系统
 */
import { Typography, Divider, Card } from 'antd';

const { Title, Paragraph, Text } = Typography;

export default function Terms() {
  return (
    <div style={{ maxWidth: 900, margin: '40px auto', padding: '0 24px' }}>
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
        <Title level={2} style={{ textAlign: 'center', marginBottom: 8 }}>用户协议</Title>
        <Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 32 }}>
          最后更新日期：2026年7月7日
        </Paragraph>

        <Divider />

        <Title level={4}>一、协议说明</Title>
        <Paragraph>
          欢迎使用<Text strong>校园信息聚合与智能推送系统</Text>（以下简称"本系统"）。
          本协议是您（以下简称"用户"）与本系统开发团队（CherryPainter）之间关于使用本系统服务所订立的协议。
        </Paragraph>
        <Paragraph>
          请您在注册和使用本系统前仔细阅读本协议。如果您不同意本协议的任何条款，请勿注册或使用本系统。
          您一旦完成注册流程或开始使用本系统，即视为您已充分阅读、理解并同意接受本协议的全部内容。
        </Paragraph>

        <Title level={4}>二、服务内容</Title>
        <Paragraph>本系统为校园用户提供以下信息服务：</Paragraph>
        <Paragraph>
          <ul>
            <li><Text strong>天气信息推送</Text>：自动获取天气数据，包括实时天气、逐小时预报及气象预警信息，并通过企业微信等渠道推送给用户。</li>
            <li><Text strong>宿舍电量监控</Text>：自动获取宿舍电表数据，提供用电量统计与查询，并在电量不足时发出预警提醒。</li>
            <li><Text strong>课程管理提醒</Text>：支持课程表导入与管理，在课程开始前自动推送上课提醒通知。</li>
            <li><Text strong>信息聚合展示</Text>：通过统一的管理后台，集中展示天气、电量、课程等校园信息。</li>
            <li><Text strong>安全与访问控制</Text>：提供 IP 黑名单、会话管理与 MFA 二次验证（TOTP），全方位保障账户与系统安全。</li>
          </ul>
        </Paragraph>

        <Title level={4}>三、用户账户</Title>
        <Paragraph>
          3.1 用户在使用本系统前需要注册账户。注册时需提供用户名、密码等基本信息。
          用户应确保所提供信息的真实性和准确性，并对其账户下发生的所有活动负责。
        </Paragraph>
        <Paragraph>
          3.2 用户应妥善保管账户及密码信息，不得将账户出借、转让或共享给他人使用。
          如因用户原因导致账户被盗用或产生损失，由用户自行承担责任。
        </Paragraph>
        <Paragraph>
          3.3 管理员有权在以下情况下暂停或终止用户账户：
          用户违反本协议约定；用户行为影响系统正常运行；用户行为侵犯他人合法权益；法律法规要求的其他情形。
        </Paragraph>

        <Title level={4}>四、用户行为规范</Title>
        <Paragraph>用户在使用本系统过程中，不得从事以下行为：</Paragraph>
        <Paragraph>
          <ul>
            <li>利用系统漏洞进行非法操作或破坏系统安全；</li>
            <li>未经授权访问、修改、删除系统数据；</li>
            <li>利用本系统传播违法、违规或有害信息；</li>
            <li>干扰、破坏本系统的正常运行；</li>
            <li>利用本系统从事任何违反法律法规或侵犯他人合法权益的活动。</li>
          </ul>
        </Paragraph>

        <Title level={4}>五、服务变更与中断</Title>
        <Paragraph>
          5.1 本系统可能因系统维护、升级、不可抗力等原因暂停服务。我们将尽力减少服务中断时间，
          并在可能的情况下提前通知用户。
        </Paragraph>
        <Paragraph>
          5.2 我们保留在不事先通知用户的情况下，修改、暂停或终止部分或全部服务的权利，
          但对因此给用户造成的损失不承担任何责任。
        </Paragraph>

        <Title level={4}>六、免责声明</Title>
        <Paragraph>
          6.1 本系统提供的天气数据来自第三方天气服务商（和风天气），电量数据来自校园电表系统，
          课程数据来自教务系统。我们对数据的准确性、完整性和及时性不作保证，用户使用上述数据产生的风险由用户自行承担。
        </Paragraph>
        <Paragraph>
          6.2 本系统仅作为信息聚合和推送工具，不对用户依据系统信息所作决策的后果承担责任。
        </Paragraph>
        <Paragraph>
          6.3 因网络故障、系统维护、第三方服务异常等原因导致的信息推送延迟或遗漏，
          我们不承担由此产生的任何责任。
        </Paragraph>

        <Title level={4}>七、知识产权</Title>
        <Paragraph>
          本系统的所有权利、所有权及知识产权（包括但不限于源代码、界面设计、系统架构等）
          均归本系统开发团队所有。未经书面许可，任何人不得复制、修改、传播或以其他方式使用本系统的知识产权内容。
        </Paragraph>

        <Title level={4}>八、协议修改</Title>
        <Paragraph>
          我们有权根据业务发展需要和法律法规要求修改本协议。修改后的协议将在系统中予以公布，
          自公布之日起生效。用户继续使用本系统即视为同意修改后的协议。
        </Paragraph>

        <Title level={4}>九、法律适用与管辖</Title>
        <Paragraph>
          本协议的订立、执行、解释及争议解决均适用中华人民共和国法律。
          因本协议引起的或与本协议有关的任何争议，双方应友好协商解决；
          协商不成的，任何一方均有权向有管辖权的人民法院提起诉讼。
        </Paragraph>

        <Title level={4}>十、联系方式</Title>
        <Paragraph>
          如您对本协议有任何疑问、意见或建议，请通过本系统的"联系我们"页面与我们取得联系。
        </Paragraph>
      </Card>
    </div>
  );
}
