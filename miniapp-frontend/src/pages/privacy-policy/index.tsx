import { View, Text } from '@tarojs/components';
import './index.scss';

/**
 * 隐私政策
 * 仅描述本小程序当前真实收集与使用的信息项目，不夸大、不虚构。
 */
export default function PrivacyPolicy() {
  return (
    <View className="agreement-page">
      <Text className="agreement-title">隐私政策</Text>
      <Text className="agreement-meta">最后更新：2026 年 9 月</Text>

      <View className="agreement-section">
        <Text className="section-h">一、我们收集哪些信息</Text>
        <Text className="section-p">为提供校园信息查询服务，本小程序会在您使用相应功能时收集以下必要信息：</Text>
        <View className="section-list">
          <Text className="section-li">微信身份信息：通过 wx.login 取得 openid 用于识别您的微信身份，不获取您的微信昵称、头像</Text>
          <Text className="section-li">身份绑定信息：您在身份绑定时填写的学校、学号、绑定码</Text>
          <Text className="section-li">学校预录信息：绑定时按学校预录名单同步的学校、学院、专业、班级、姓名</Text>
          <Text className="section-li">个人资料：您主动维护的昵称、校园卡号等可选信息</Text>
          <Text className="section-li">宿舍电表接入信息：您本人宿舍电表的鉴权字符串，仅用于为您单独查询本人宿舍电量</Text>
          <Text className="section-li">反馈内容：您主动提交的意见反馈文字与图片</Text>
        </View>
      </View>

      <View className="agreement-section">
        <Text className="section-h">二、信息的使用方式</Text>
        <Text className="section-p">
          上述信息仅用于为您提供本小程序的查询与展示服务，包括但不限于：
          课表查询、天气查询、电量查询、通知公告、意见反馈与回复。
          我们不会将您的个人信息用于商业广告、营销推广或任何与服务无关的目的，
          也不会将您的个人信息出售给第三方。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">三、信息存储与保护</Text>
        <Text className="section-p">
          您的个人信息保存在本小程序部署的服务端数据库中，仅用于向您本人提供查询服务。
          敏感的接入信息（如宿舍电表鉴权字符串）仅做脱敏展示（前 4 后 2 中间掩码），
          完整字符串不会回显给您以外的任何人。
          我们采取合理的技术措施保护您的数据安全，但请理解任何系统都不能保证绝对安全。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">四、第三方共享</Text>
        <Text className="section-p">
          为实现天气查询与电量查询等基础功能，您的查询请求可能由第三方接口处理（如天气服务、电费查询接口），
          但仅传递必要的技术参数，不包含您的身份信息。您的个人信息不在任何第三方处留存。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">五、您的权利</Text>
        <Text className="section-p">您对自己的个人信息享有以下权利：</Text>
        <View className="section-list">
          <Text className="section-li">查看与修改：通过"个人资料"页面查看并修改昵称、校园卡号等信息</Text>
          <Text className="section-li">删除接入信息：通过"电表配置"页面清除宿舍电表接入信息</Text>
          <Text className="section-li">注销账号：通过"个人资料 → 注销账号"申请账号注销，注销后相关信息将被删除</Text>
          <Text className="section-li">投诉与反馈：通过"意见反馈"入口与我们沟通</Text>
        </View>
      </View>

      <View className="agreement-section">
        <Text className="section-h">六、未成年人保护</Text>
        <Text className="section-p">
          本小程序面向校内学生使用，如您为未成年人，请在监护人指导下阅读本协议并使用本小程序。
        </Text>
      </View>

      <View className="agreement-section">
        <Text className="section-h">七、政策变更</Text>
        <Text className="section-p">
          本政策可能根据功能调整进行修订，修订后将在本页面公布。
          重大变更将通过站内通知或小程序公告提示您。
        </Text>
      </View>

      <View className="agreement-footer">
        <Text className="footer-tip">如有疑问，可通过小程序内"意见反馈"入口与我们联系</Text>
      </View>
    </View>
  );
}