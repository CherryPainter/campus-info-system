import { View, Text } from '@tarojs/components';
import './index.scss';

/**
 * 用户协议
 * 仅描述本小程序当前真实提供的服务与使用规范，不夸大、不虚构。
 */
export default function UserAgreement() {
  return (
    <View className="agreement-page">
      <Text className="agreement-title">用户协议</Text>
      <Text className="agreement-meta">最后更新：2026 年 9 月</Text>

      <View className="agreement-section">
        <Text className="section-h">一、服务内容</Text>
        <Text className="section-p">
          「校园宜知行」（以下简称"本小程序"）是一款面向校内学生的校园信息聚合工具，目前已实现以下功能：
        </Text>
        <View className="section-list">
          <Text className="section-li">课表查询：展示本人所在班级的周课表与单日课程</Text>
          <Text className="section-li">天气查询：展示当前所在地天气与生活指数</Text>
          <Text className="section-li">电量查询：展示本人宿舍电表剩余电量（需用户自配接入信息）</Text>
          <Text className="section-li">通知公告：查看校内发布的通知与公告</Text>
          <Text className="section-li">意见反馈：提交问题与建议，接收站内回复</Text>
          <Text className="section-li">个人资料：维护昵称、学院、专业、校园卡号等信息</Text>
        </View>
      </View>

      <View className="agreement-section">
        <Text className="section-h">二、账号与身份</Text>
        <Text className="section-p">
          本小程序使用微信一键登录，您的微信身份经后端换取为小程序内部用户身份，不会保存您的微信密码。
          首次使用部分功能前需要按学校下发的绑定码完成身份绑定，绑定后将根据学校预录名单同步学校、学院、专业、班级信息。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">三、使用规范</Text>
        <Text className="section-p">使用本小程序时请您：</Text>
        <View className="section-list">
          <Text className="section-li">使用本人真实的身份信息进行绑定，不冒用他人身份</Text>
          <Text className="section-li">妥善保管您的绑定码与本人宿舍电表的接入信息，不向他人泄露</Text>
          <Text className="section-li">不通过技术手段批量获取、传播本小程序展示的内容</Text>
          <Text className="section-li">不上传违法违规、色情、暴力、虚假或骚扰性内容</Text>
        </View>
      </View>

      <View className="agreement-section">
        <Text className="section-h">四、信息展示说明</Text>
        <Text className="section-p">
          课表、通知公告等内容来源于学校教务系统与校内发布渠道；天气数据来源于第三方天气服务；
          电量数据来源于您本人宿舍电表的官方查询接口。本小程序不对上述信息的绝对准确性承担法律责任，
          如有疑问请以原始来源为准。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">五、服务变更与终止</Text>
        <Text className="section-p">
          本小程序可在不另行通知的情况下，对功能进行调整、升级或下线停停。
          如您违反本协议任一条款，我们有权限制或终止您的使用。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">六、免责声明</Text>
        <Text className="section-p">
          本小程序按"现有技术水平"提供信息查询与展示服务，不对因网络中断、第三方接口异常、
          不可抗力等原因造成的服务中断或数据偏差承担赔偿责任。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">七、协议变更</Text>
        <Text className="section-p">
          本协议可能根据功能调整进行修订，修订后将在本页面公布。继续使用本小程序视为接受修订后的协议。
        </Text>
      </View>

      <View className="agreement-footer">
        <Text className="footer-tip">如有疑问，可通过小程序内"意见反馈"入口与我们联系</Text>
      </View>
    </View>
  );
}