import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';
import './index.scss';

/**
 * 登录引导弹窗（游客访问受限功能时弹出）
 *
 * 用于微信小程序「先体验后授权」合规：游客浏览天气/公告等公开内容无需登录，
 * 一旦点击需要登录的功能（课表、电量、我的等），弹出本弹窗，
 * 点「确定」跳转到登录页，点「取消」关闭弹窗继续浏览。
 *
 * 用法：
 *   const [showLogin, setShowLogin] = useState(false);
 *   <LoginModal visible={showLogin} onCancel={() => setShowLogin(false)} />
 */

interface LoginModalProps {
  visible: boolean;
  title?: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm?: () => void;
  onCancel?: () => void;
}

export default function LoginModal({
  visible,
  title = '需要登录',
  message = '该功能需要登录后使用，是否前往登录？',
  confirmText = '确定',
  cancelText = '取消',
  onConfirm,
  onCancel,
}: LoginModalProps) {
  if (!visible) return null;

  // 关键修复：点"确定"跳登录页时必须同步关闭自身。
  // 原因：跳走是异步的（Taro.navigateTo 异步），但导航成功后 source 页面组件实例常驻内存，
  // useState(showLogin=true) 不会被重置；登录完返回后弹窗仍在屏幕上（典型场景：
  // 首页/我的/时间轴任意 guard → 弹窗 → 确定 → 登录成功 → 弹窗还在）。
  // 这里 onCancel = 各页面挂的关闭回调（home/profile/schedule 都接到 setXxxShowLogin(false)），
  // 同步触发即可让返回后弹窗已消失。
  const handleConfirm = () => {
    onConfirm?.();
    onCancel?.();
    Taro.navigateTo({ url: '/pages/login/index' });
  };

  const handleCancel = () => {
    onCancel?.();
  };

  return (
    <View className="login-mask" onClick={handleCancel}>
      <View className="login-modal" onClick={(e) => e.stopPropagation()}>
        <Text className="login-modal-title">{title}</Text>
        <Text className="login-modal-msg">{message}</Text>
        <View className="login-modal-actions">
          <View className="login-modal-btn login-modal-cancel" hoverClass="login-modal-btn-hover" onClick={handleCancel}>
            <Text className="login-modal-btn-text">{cancelText}</Text>
          </View>
          <View className="login-modal-btn login-modal-confirm" hoverClass="login-modal-btn-hover" onClick={handleConfirm}>
            <Text className="login-modal-btn-text">{confirmText}</Text>
          </View>
        </View>
      </View>
    </View>
  );
}
