/**
 * 登录页面
 * 使用5张云科技风格背景图，每次打开随机显示一张
 */
import { useState, useMemo, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Button, Card, Typography, Modal, Divider, Space, App, Checkbox } from 'antd';
import { UserOutlined, LockOutlined, CloudServerOutlined, MobileOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { authApi } from '@/api/auth';
import { useUser } from '@/contexts/UserContext';
import request from '@/api/request';
import Footer from '@/components/Footer';
import { APP_VERSION } from '@/version';

// 导入5张背景图
import loginBg1 from '@/assets/login-bg-1.jpg';
import loginBg2 from '@/assets/login-bg-2.jpg';
import loginBg3 from '@/assets/login-bg-3.jpg';
import loginBg4 from '@/assets/login-bg-4.jpg';
import loginBg5 from '@/assets/login-bg-5.jpg';

const { Title, Text, Paragraph } = Typography;

// 背景图数组
const backgroundImages = [loginBg1, loginBg2, loginBg3, loginBg4, loginBg5];

/**
 * 获取随机背景图
 * 使用 useMemo 确保只在组件挂载时随机选择一次
 */
function useRandomBackground() {
  return useMemo(() => {
    const randomIndex = Math.floor(Math.random() * backgroundImages.length);
    return backgroundImages[randomIndex];
  }, []);
}

/**
 * 显示错误消息的辅助函数
 * @param msg - 错误消息
 * @param messageApi - 来自 App.useApp() 的 message 实例
 */
const showError = (msg: string, messageApi: ReturnType<typeof App.useApp>['message']) => {
  setTimeout(() => {
    messageApi.error(msg);
  }, 0);
};

export default function Login() {
  const navigate = useNavigate();
  const { loginSuccess } = useUser();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [mfaVisible, setMfaVisible] = useState(false);
  const [mfaToken, setMfaToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaLoading, setMfaLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [rememberMe, setRememberMe] = useState(false);
  const [form] = Form.useForm();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inputRefs = useRef<any[]>([]);
  
  // 随机选择一张背景图（组件挂载时只执行一次）
  const randomBg = useRandomBackground();

  // 清除错误消息
  const clearError = useCallback(() => {
    setErrorMessage(null);
  }, []);

  const handleSubmit = async (values: { username: string; password: string }) => {
    // 清除之前的错误
    clearError();
    setLoading(true);
    
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await authApi.login(values.username, values.password, rememberMe);
      
      if (res.status === 'mfa_required') {
        // 需要 MFA 验证
        setMfaToken(res.mfa_token || '');
        setMfaVisible(true);
        setMfaCode('');
        message.info('请输入MFA验证码');
        setLoading(false);
        return;
      }
      
      // 使用 httpOnly cookie，后端不再返回 token
      if (res.status === 'success') {
        message.success('登录成功');
        // 更新 UserContext 状态
        if (res.user) {
          loginSuccess(res.user);
        }
        // 根据角色决定跳转目标：管理员到仪表盘，普通用户到首页
        const targetPath = res.user?.role === 'admin' ? '/dashboard' : '/welcome';
        navigate(targetPath);
      } else {
        // 其他错误状态
        const errMsg = res.message || '登录失败';
        setErrorMessage(errMsg);
        message.error(errMsg);
      }
    } catch (error: any) {
      // 显示后端返回的具体错误消息
      const status = error.response?.status;
      let errorMsg = '登录失败，请检查用户名和密码';
      
      if (status === 429) {
        errorMsg = '请求过于频繁，请稍后再试';
      } else if (status === 401) {
        errorMsg = '用户名或密码错误';
      } else if (status === 403) {
        errorMsg = '登录被拒绝，请联系管理员';
      } else if (error.response?.data?.message) {
        errorMsg = error.response.data.message;
      }
      
      // 同时用 state 和 message 两种方式显示错误
      setErrorMessage(errorMsg);
      showError(errorMsg, message);
    } finally {
      setLoading(false);
    }
  };

  const handleMfaSubmit = async () => {
    const code = mfaCode;
    if (!code || code.length !== 6) {
      message.warning('请输入完整的6位验证码');
      return;
    }
    
    setMfaLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await request.post('/auth/login/mfa', {
        mfa_token: mfaToken,
        code: code
      });
      
      if (res.status === 'success') {
        message.success('登录成功');
        setMfaVisible(false);
        // 更新 UserContext 状态
        if (res.user) {
          loginSuccess(res.user);
        }
        // 根据角色决定跳转目标：管理员到仪表盘，普通用户到首页
        const targetPath = res.user?.role === 'admin' ? '/dashboard' : '/welcome';
        navigate(targetPath);
      } else {
        const errMsg = res.message || '验证失败';
        message.error(errMsg);
        // 清除输入框
        setMfaCode('');
        setTimeout(() => inputRefs.current[0]?.focus(), 100);
      }
    } catch (error: any) {
      const errorMsg = error.response?.data?.message || '验证失败，请重试';
      message.error(errorMsg);
      // 清除输入框
      setMfaCode('');
      setTimeout(() => inputRefs.current[0]?.focus(), 100);
    } finally {
      setMfaLoading(false);
    }
  };

  const handleCodeChange = (value: string) => {
    const cleanValue = value.replace(/\D/g, '').slice(0, 6);
    setMfaCode(cleanValue);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && mfaCode.length === 6) {
      handleMfaSubmit();
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      backgroundImage: `url(${randomBg})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundRepeat: 'no-repeat',
      backgroundColor: '#f5f5f5',
    }}>
      {/* 登录卡片区域 - 占据flex: 1自动扩展到中间 */}
      <div style={{
        flex: 1,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '20px 16px',
      }}>
      {/* 登录卡片 */}
      <Card
        style={{
          width: '100%',
          maxWidth: 400,
          borderRadius: 6,
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
          backdropFilter: 'blur(10px)',
          backgroundColor: 'rgba(255, 255, 255, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.3)',
          paddingBottom: 32,
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{ 
              width: 64, 
              height: 64, 
              borderRadius: 8, 
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
              background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #7dd3fc 100%)',
              boxShadow: '0 4px 12px rgba(147, 197, 253, 0.4)',
            }}>
              <CloudServerOutlined style={{ fontSize: 32, color: '#0369a1' }} />
            </div>
            <Title level={3} style={{ marginBottom: 4, fontSize: 18, fontWeight: 500, wordBreak: 'break-all' }}>校园信息聚合与智能推送系统</Title>
            <Text type="secondary" style={{ fontSize: 14, display: 'block' }}>管理后台登录</Text>
          </div>
          
          {/* 错误提示 - 左对齐显示 */}
          {errorMessage && (
            <div style={{ 
              marginBottom: 16, 
              color: '#ff4d4f',
              fontSize: 14,
              textAlign: 'left',
            }}>
              {errorMessage}
            </div>
          )}
          
          <Form form={form} layout="vertical" onFinish={handleSubmit} autoComplete="off">
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input 
                prefix={<UserOutlined />} 
                placeholder="请输入用户名" 
                size="large" 
              />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password 
                prefix={<LockOutlined />} 
                placeholder="请输入密码" 
                size="large" 
              />
            </Form.Item>
            <div style={{ marginBottom: 12, textAlign: 'left' }}>
              <Checkbox checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)}>
                记住我（30 天内保持登录）
              </Checkbox>
            </div>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button 
                type="primary" 
                htmlType="submit" 
                size="large" 
                loading={loading} 
                block
              >
                登录
              </Button>
            </Form.Item>
          </Form>
          
          {/* 版本号 */}
          <div style={{ 
            position: 'absolute', 
            bottom: 8, 
            right: 16, 
            fontSize: 11, 
            color: '#bfbfbf' 
          }}>
            v{APP_VERSION}
          </div>
        </Card>
      </div>

      {/* 公共 Footer */}
      <Footer />

      {/* MFA 验证弹窗 */}
      <Modal
        title="两步验证"
        open={mfaVisible}
        onCancel={() => setMfaVisible(false)}
        afterOpenChange={(open) => {
          if (open) {
            // 弹窗打开后确保聚焦第一个输入框
            setTimeout(() => {
              const firstInput = inputRefs.current[0];
              if (firstInput) {
                firstInput.focus();
                firstInput.select();
              }
            }, 300);
          }
        }}
        footer={null}
        centered
        width={400}
      >
        <div style={{ textAlign: 'center' }}>
          {/* 图标区域 */}
          <div style={{
            width: 64,
            height: 64,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 20px',
          }}>
            <MobileOutlined style={{ fontSize: 32, color: '#1890ff' }} />
          </div>

          {/* 说明文字 */}
          <Title level={4} style={{ marginBottom: 8, fontSize: 16, fontWeight: 500 }}>输入验证码</Title>
          <Paragraph type="secondary" style={{ marginBottom: 24, fontSize: 14 }}>
            请打开您的身份验证器应用，输入6位验证码
          </Paragraph>

          {/* 验证码输入框 */}
          <Space direction="vertical" size="middle" style={{ width: '100%', marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
              {[0, 1, 2, 3, 4, 5].map((index) => (
                <Input
                  key={index}
                  ref={(el) => { inputRefs.current[index] = el; }}
                  value={mfaCode[index] || ''}
                  onChange={(e) => {
                    const val = e.target.value.replace(/\D/g, '');
                    if (!val) return;
                    
                    const newCode = mfaCode.split('');
                    newCode[index] = val[val.length - 1];
                    setMfaCode(newCode.join(''));
                    
                    // 跳到下一个输入框
                    if (index < 5) {
                      setTimeout(() => {
                        inputRefs.current[index + 1]?.focus();
                      }, 10);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Backspace') {
                      if (mfaCode[index]) {
                        const newCode = mfaCode.split('');
                        newCode[index] = '';
                        setMfaCode(newCode.join(''));
                      } else if (index > 0) {
                        setTimeout(() => {
                          inputRefs.current[index - 1]?.focus();
                        }, 10);
                      }
                    }
                    if (e.key === 'Enter') {
                      handleKeyDown(e);
                    }
                  }}
                  onPaste={(e) => {
                    e.preventDefault();
                    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
                    if (pasted) {
                      setMfaCode(pasted);
                    }
                  }}
                  maxLength={1}
                  size="large"
                  style={{
                    width: 44,
                    height: 48,
                    textAlign: 'center',
                    fontSize: 20,
                    fontWeight: 500,
                    borderRadius: 4,
                  }}
                />
              ))}
            </div>
            
            {/* 提示信息 */}
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8, color: '#8c8c8c', fontSize: 12 }}>
              <ClockCircleOutlined />
              <span>验证码每30秒更新一次</span>
            </div>
          </Space>

          <Divider style={{ margin: '20px 0' }} />

          {/* 按钮区域 */}
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Button 
              size="large" 
              onClick={() => setMfaVisible(false)}
            >
              返回
            </Button>
            <Button
              type="primary"
              size="large"
              loading={mfaLoading}
              onClick={handleMfaSubmit}
              disabled={mfaCode.length !== 6}
            >
              验证并登录
            </Button>
          </div>
        </div>
      </Modal>

      {/* 自定义样式 */}
      <style>{`
        .mfa-code-input:focus {
          border-color: #1890ff !important;
          box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.1);
        }
      `}</style>
    </div>
  );
}
