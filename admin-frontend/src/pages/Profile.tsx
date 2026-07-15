/**
 * 用户管理页面
 *
 * 功能：
 * - 修改用户名（需验证密码）
 * - 修改密码
 * - 查看登录日志
 * - 双因素认证设置
 */
import { useState, useEffect, useRef } from 'react';
import {
  Card,
  Form,
  Input,
  Button,
  Avatar,
  Space,
  Row,
  Col,
  Tag,
  Typography,
  Modal,
  Select,
  Descriptions,
  Upload,
  Switch,
  Timeline,
  App,
} from 'antd';
import { formatTimeShort, formatDateTime } from '@/utils/datetime';
import {
  UserOutlined,
  EditOutlined,
  LockOutlined,
  HistoryOutlined,
  GlobalOutlined,
  SafetyOutlined,
  MobileOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { userApi, type LoginLog } from '@/api/admin';
import { authApi } from '@/api/auth';
import type { User } from '@/types/user';
import request from '@/api/request';

const { Text, Title, Paragraph } = Typography;
const { Option } = Select;

export default function Profile() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [form] = Form.useForm();

  // 修改密码相关
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [passwordForm] = Form.useForm();
  const [changingPassword, setChangingPassword] = useState(false);

  // 修改用户名相关
  const [usernameModalVisible, setUsernameModalVisible] = useState(false);
  const [usernameForm] = Form.useForm();
  const [changingUsername, setChangingUsername] = useState(false);

  // 登录日志相关
  const [logs, setLogs] = useState<LoginLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logPage, setLogPage] = useState(1);
  const [logPageSize, setLogPageSize] = useState(20);
  const [logTotal, setLogTotal] = useState(0);
  const [logStatus, setLogStatus] = useState<string | undefined>();

  // 头像上传相关
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // MFA 双因素认证相关
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [mfaStatusLoading, setMfaStatusLoading] = useState(false);
  const [mfaSetupVisible, setMfaSetupVisible] = useState(false);
  const [mfaSetupLoading, setMfaSetupLoading] = useState(false);
  const [mfaQrCode, setMfaQrCode] = useState<string>('');
  const [mfaSecret, setMfaSecret] = useState<string>('');
  const [mfaCode, setMfaCode] = useState<string>('');
  const [mfaVerifyLoading, setMfaVerifyLoading] = useState(false);
  const [mfaDisableVisible, setMfaDisableVisible] = useState(false);
  const [mfaDisableCode, setMfaDisableCode] = useState('');
  const [mfaDisableLoading, setMfaDisableLoading] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mfaInputRefs = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mfaDisableInputRefs = useRef<any[]>([]);

  useEffect(() => {
    fetchProfile();
    fetchMfaStatus();
  }, []);

  const fetchProfile = async () => {
    setLoading(true);
    try {
      const res = await userApi.getProfile();
      if (res.status === 'success' && res.data) {
        setUser(res.data);
        setAvatarPreview(res.data.avatar || null);
      }
    } catch (error) {
      console.error('获取用户信息失败:', error);
      message.error('获取用户信息失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchMfaStatus = async () => {
    setMfaStatusLoading(true);
    try {
      const res = await authApi.getMfaStatus();
      if (res.status === 'success' && res.data) {
        setMfaEnabled(res.data.enabled);
      }
    } catch (error) {
      console.error('获取 MFA 状态失败:', error);
    } finally {
      setMfaStatusLoading(false);
    }
  };

  const handleUpdateProfile = async () => {
    setLoading(true);
    try {
      const res = await userApi.updateProfile({
        avatar: avatarPreview || undefined,
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((res as any).status === 'success') {
        message.success('头像已更新');
        await fetchProfile();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '更新失败');
    } finally {
      setLoading(false);
    }
  };

  // 处理 Base64 头像预览（前端先做类型/大小校验，后端再做权威校验）
  const handleAvatarPreview = (file: File) => {
    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
      message.error('仅支持 JPG / PNG / GIF / WEBP 格式头像');
      return false;
    }
    if (file.size > 2 * 1024 * 1024) {
      message.error('头像大小不能超过 2MB');
      return false;
    }
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => {
      setAvatarPreview(reader.result as string);
    };
    return false; // 阻止默认上传行为，使用本地预览
  };

  const handleChangePassword = async (values: any) => {
    if (values.new_password !== values.confirm_password) {
      message.error('两次输入的密码不一致');
      return;
    }
    setChangingPassword(true);
    try {
      const res = await request.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((res as any).status === 'success') {
        message.success('密码已修改，请重新登录');
        setPasswordModalVisible(false);
        passwordForm.resetFields();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '修改失败');
    } finally {
      setChangingPassword(false);
    }
  };

  const handleChangeUsername = async (values: any) => {
    setChangingUsername(true);
    try {
      const res = await userApi.updateUsername({
        username: values.new_username,
        password: values.password,
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((res as any).status === 'success') {
        message.success('用户名已修改');
        setUsernameModalVisible(false);
        usernameForm.resetFields();
        await fetchProfile();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '修改失败');
    } finally {
      setChangingUsername(false);
    }
  };

  // MFA 相关方法
  const handleMfaToggle = async (checked: boolean) => {
    if (checked) {
      // 启用 MFA
      await handleMfaSetup();
    } else {
      // 禁用 MFA
      setMfaDisableVisible(true);
    }
  };

  const handleMfaSetup = async () => {
    setMfaSetupLoading(true);
    try {
      const res = await authApi.setupMfa();
      if (res.status === 'success' && res.data) {
        setMfaQrCode(res.data.qr_code_base64);
        setMfaSecret(res.data.secret);
        setMfaCode('');
        setMfaSetupVisible(true);
      } else {
        // 处理非成功状态
        message.error(res.message || '设置失败');
      }
    } catch (error: any) {
      console.error('MFA设置错误:', error);
      message.error(error.response?.data?.message || '设置失败');
    } finally {
      setMfaSetupLoading(false);
    }
  };

  const handleMfaCodeChange = (value: string) => {
    const cleanValue = value.replace(/\D/g, '').slice(0, 6);
    setMfaCode(cleanValue);
  };

  const handleMfaVerify = async () => {
    if (!mfaCode || mfaCode.length !== 6) {
      message.warning('请输入完整的6位验证码');
      return;
    }
    setMfaVerifyLoading(true);
    try {
      const res = await authApi.verifyMfa(mfaCode);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((res as any).status === 'success') {
        message.success('双因素认证已启用');
        setMfaSetupVisible(false);
        setMfaEnabled(true);
        setMfaCode('');
      } else {
        message.error(res.message || '验证失败');
        setMfaCode('');
      }
    } catch (error: any) {
      console.error('MFA验证错误:', error);
      message.error(error.response?.data?.message || '验证失败');
      setMfaCode('');
    } finally {
      setMfaVerifyLoading(false);
    }
  };

  const handleMfaDisable = async () => {
    if (!mfaDisableCode || mfaDisableCode.length !== 6) {
      message.warning('请输入完整的6位验证码');
      return;
    }
    setMfaDisableLoading(true);
    try {
      const res = await authApi.disableMfa(mfaDisableCode);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((res as any).status === 'success') {
        message.success('双因素认证已禁用');
        setMfaDisableVisible(false);
        setMfaEnabled(false);
        setMfaDisableCode('');
      } else {
        message.error(res.message || '操作失败');
        setMfaDisableCode('');
      }
    } catch (error: any) {
      console.error('MFA禁用错误:', error);
      message.error(error.response?.data?.message || '操作失败');
      setMfaDisableCode('');
    } finally {
      setMfaDisableLoading(false);
    }
  };

  const fetchLogs = async (page = 1) => {
    setLogsLoading(true);
    try {
      const res = await userApi.getLoginLogs({
        page,
        page_size: logPageSize,
        status: logStatus,
      });
      // 第一页覆盖；加载更多时追加，避免时间线重复
      setLogs(page === 1 ? res.data : (prev) => [...prev, ...res.data]);
      setLogTotal(res.pagination.total);
      setLogPage(page);
    } catch (error) {
      console.error('获取登录日志失败:', error);
      message.error('获取登录日志失败');
    } finally {
      setLogsLoading(false);
    }
  };

  // 提示用户重新登录才能看到新的登录记录
  const handleRelogin = () => {
    message.warning('请重新登录以记录新的登录记录');
  };

  useEffect(() => {
    fetchLogs();
  }, [logStatus]);

  // 将登录日志转换为时间线条目（简洁展示，像日程记录一样一条条排列）
  const formatLogTime = (time: string) => formatTimeShort(time);
  const shortenAgent = (agent?: string) => {
    if (!agent) return '';
    const m = agent.match(/(Chrome|Firefox|Safari|Edg|MicroMessenger)\/[\d.]+/);
    return m ? m[0] : agent.slice(0, 24);
  };
  const logTimelineItems = (logs || []).map((log: LoginLog) => {
    const isSuccess = log.status === 'success';
    return {
      color: isSuccess ? 'green' : 'red',
      children: (
        <div style={{ paddingBottom: 4 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontWeight: 600, color: isSuccess ? '#389e0d' : '#cf1322' }}>
              {isSuccess ? '登录成功' : '登录失败'}
            </span>
            <span style={{ color: '#999', fontSize: 12, whiteSpace: 'nowrap' }}>
              {formatLogTime(log.login_time)}
            </span>
          </div>
          <div style={{ color: '#888', fontSize: 12, marginTop: 4, lineHeight: 1.6 }}>
            <GlobalOutlined style={{ marginRight: 4 }} />
            {log.ip_address || '-'}
            {shortenAgent(log.user_agent) && <span> · {shortenAgent(log.user_agent)}</span>}
            {log.logout_time && <span> · 退出 {formatLogTime(log.logout_time)}</span>}
            {log.duration && <span> · {log.duration}</span>}
          </div>
          {!isSuccess && log.failure_reason && (
            <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 2 }}>
              原因：{log.failure_reason}
            </div>
          )}
        </div>
      ),
    };
  });

  return (
    <div>
      <Row gutter={24} style={{ display: 'flex' }}>
        {/* 左侧：账户信息 */}
        <Col span={24} lg={16} style={{ display: 'flex' }}>
          <Card
            title={
              <Space>
                <UserOutlined />
                <span>账户信息</span>
              </Space>
            }
            loading={loading}
            style={{ height: '100%', width: '100%' }}
          >
            <Row gutter={[24, 16]} align="top">
              {/* 头像 */}
              <Col xs={24} sm={8} style={{ textAlign: 'center' }}>
                <Avatar
                  size={120}
                  src={avatarPreview}
                  icon={!avatarPreview && <UserOutlined />}
                  style={{ marginBottom: 16 }}
                />
                <div>
                  <Upload
                    accept=".jpg,.jpeg,.png,.gif,.webp"
                    showUploadList={false}
                    beforeUpload={handleAvatarPreview}
                    disabled={uploading}
                  >
                    <Button type="link" icon={<EditOutlined />} disabled={uploading}>
                      更换头像
                    </Button>
                  </Upload>
                  <Button type="primary" onClick={handleUpdateProfile} loading={loading}>
                    保存头像
                  </Button>
                </div>
              </Col>

              {/* 账户信息 */}
              <Col xs={24} sm={16}>
                <Descriptions column={1}>
                  <Descriptions.Item label="用户名">
                    <Space>
                      <Text strong>{user?.username}</Text>
                      <Button
                        type="link"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => {
                          usernameForm.setFieldValue('new_username', user?.username);
                          setUsernameModalVisible(true);
                        }}
                      >
                        修改
                      </Button>
                    </Space>
                  </Descriptions.Item>
                  <Descriptions.Item label="角色">
                    <Tag color="blue">{user?.role}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="当前登录">
                    <Text type="secondary">
                      {user?.last_login ? formatDateTime(user.last_login) : '-'}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="当前登录 IP">
                    <Text type="secondary">{user?.last_login_ip || '-'}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="注册时间">
                    <Text type="secondary">
                      {user?.created_at ? new Date(user.created_at).toLocaleDateString('zh-CN') : '-'}
                    </Text>
                  </Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
          </Card>
        </Col>

        {/* 右侧：快速操作 */}
        <Col span={24} lg={8} style={{ display: 'flex' }}>
          <Card 
            title={<><SafetyOutlined style={{ marginRight: 8 }} />账户安全</>}
            style={{ height: '100%', width: '100%' }}
          >
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              {/* 双因素认证 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <SafetyOutlined />
                  <span>双因素认证</span>
                </span>
                <Switch
                  checked={mfaEnabled}
                  onChange={handleMfaToggle}
                  loading={mfaStatusLoading || mfaSetupLoading}
                />
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {mfaEnabled ? '已启用 - 登录时需要额外验证' : '未启用 - 建议开启以提高账户安全性'}
              </Text>
              
              {/* 修改密码 */}
              <Button type="primary" block icon={<LockOutlined />} onClick={() => setPasswordModalVisible(true)}>
                修改密码
              </Button>
              
              {/* 修改用户名 */}
              <Button block icon={<UserOutlined />} onClick={() => {
                usernameForm.setFieldValue('new_username', user?.username);
                setUsernameModalVisible(true);
              }}>
                修改用户名
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 登录日志（时间线简洁展示） */}
      <Card
        title={
          <Space>
            <HistoryOutlined />
            <span>登录日志</span>
          </Space>
        }
        style={{ marginTop: 24 }}
        extra={
          <Space>
            <Select
              value={logStatus}
              onChange={(v) => setLogStatus(v)}
              placeholder="筛选状态"
              style={{ width: 120 }}
              allowClear
            >
              <Option value="success">成功</Option>
              <Option value="failed">失败</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={() => fetchLogs()}>刷新</Button>
          </Space>
        }
      >
        {(!logs || logs.length === 0) && !logsLoading && (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <HistoryOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />
            <p style={{ color: '#999', marginTop: 16 }}>暂无登录记录，请重新登录以记录</p>
          </div>
        )}
        {logs && logs.length > 0 && (
          <>
            <Timeline
              items={logTimelineItems}
              style={{ paddingTop: 8, paddingLeft: 4 }}
            />
            {logTotal > logs.length && (
              <div style={{ textAlign: 'center', marginTop: 8 }}>
                <Button onClick={() => fetchLogs(logPage + 1)} loading={logsLoading}>
                  加载更多（已显示 {logs.length} / {logTotal}）
                </Button>
              </div>
            )}
          </>
        )}
      </Card>

      {/* 修改密码弹窗 */}
      <Modal
        title="修改密码"
        open={passwordModalVisible}
        onCancel={() => {
          setPasswordModalVisible(false);
          passwordForm.resetFields();
        }}
        footer={null}
      >
        <Form
          form={passwordForm}
          layout="vertical"
          onFinish={handleChangePassword}
        >
          <Form.Item
            label="当前密码"
            name="old_password"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password placeholder="请输入当前密码" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码长度至少6位' },
            ]}
          >
            <Input.Password placeholder="请输入新密码" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm_password"
            rules={[
              { required: true, message: '请再次输入新密码' },
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => setPasswordModalVisible(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={changingPassword}>
                确认修改
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 修改用户名弹窗 */}
      <Modal
        title="修改用户名"
        open={usernameModalVisible}
        onCancel={() => {
          setUsernameModalVisible(false);
          usernameForm.resetFields();
        }}
        footer={null}
      >
        <Form
          form={usernameForm}
          layout="vertical"
          onFinish={handleChangeUsername}
        >
          <Form.Item
            label="新用户名"
            name="new_username"
            rules={[
              { required: true, message: '请输入新用户名' },
              { min: 3, message: '用户名至少3个字符' },
            ]}
          >
            <Input placeholder="请输入新用户名" />
          </Form.Item>
          <Form.Item
            label="确认密码"
            name="password"
            rules={[{ required: true, message: '请输入密码确认身份' }]}
          >
            <Input.Password placeholder="请输入当前密码" />
          </Form.Item>
          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => setUsernameModalVisible(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={changingUsername}>
                确认修改
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 设置 MFA 弹窗 */}
      <Modal
        title="设置双因素认证"
        open={mfaSetupVisible}
        onCancel={() => {
          setMfaSetupVisible(false);
          setMfaCode('');
        }}
        footer={null}
        centered
        width={450}
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
          <Title level={4} style={{ marginBottom: 8, fontSize: 16, fontWeight: 500 }}>扫描二维码</Title>
          <Paragraph type="secondary" style={{ marginBottom: 24, fontSize: 14 }}>
            请打开 Google Authenticator 或类似应用，扫描下方二维码
          </Paragraph>

          {/* 二维码 */}
          <div style={{ 
            display: 'flex', 
            justifyContent: 'center', 
            marginBottom: 24,
            padding: 16,
            backgroundColor: '#fff',
            borderRadius: 8,
            border: '1px solid #e8e8e8',
          }}>
            <img 
              src={mfaQrCode} 
              alt="MFA QR Code" 
              style={{ maxWidth: 200, maxHeight: 200 }}
            />
          </div>

          {/* 备用密钥 */}
          <div style={{ marginBottom: 24 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>备用密钥（手动输入）</Text>
            <div style={{ 
              marginTop: 8,
              padding: 12,
              backgroundColor: '#f5f5f5',
              borderRadius: 4,
              fontFamily: 'monospace',
              fontSize: 14,
              wordBreak: 'break-all',
            }}>
              {mfaSecret}
            </div>
          </div>

          {/* 验证码输入框 */}
          <Space direction="vertical" size="middle" style={{ width: '100%', marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
              {[0, 1, 2, 3, 4, 5].map((index) => (
                <Input
                  key={index}
                  ref={(el) => (mfaInputRefs.current[index] = el)}
                  value={mfaCode[index] || ''}
                  onChange={(e) => {
                    const newCode = mfaCode.split('');
                    const input = e.target.value.replace(/\D/g, '').slice(-1);
                    
                    if (input) {
                      newCode[index] = input;
                      handleMfaCodeChange(newCode.join(''));
                      if (index < 5) {
                        setTimeout(() => mfaInputRefs.current[index + 1]?.focus(), 0);
                      }
                    } else {
                      newCode[index] = '';
                      handleMfaCodeChange(newCode.join(''));
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Backspace' && !mfaCode[index] && index > 0) {
                      mfaInputRefs.current[index - 1]?.focus();
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

          {/* 按钮区域 */}
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Button 
              size="large" 
              onClick={() => {
                setMfaSetupVisible(false);
                setMfaCode('');
              }}
            >
              取消
            </Button>
            <Button
              type="primary"
              size="large"
              loading={mfaVerifyLoading}
              onClick={handleMfaVerify}
              disabled={mfaCode.length !== 6}
            >
              启用双因素认证
            </Button>
          </div>
        </div>
      </Modal>

      {/* 禁用 MFA 弹窗 */}
      <Modal
        title="禁用双因素认证"
        open={mfaDisableVisible}
        onCancel={() => {
          setMfaDisableVisible(false);
          setMfaDisableCode('');
        }}
        afterOpenChange={(open) => {
          if (open) {
            setMfaDisableCode('');
            setTimeout(() => {
              const firstInput = mfaDisableInputRefs.current[0];
              if (firstInput) {
                firstInput.focus();
              }
            }, 300);
          }
        }}
        footer={null}
        centered
        width={400}
      >
        <div style={{ textAlign: 'center' }}>
          <Title level={4} style={{ marginBottom: 8, fontSize: 16, fontWeight: 500 }}>确认禁用</Title>
          <Paragraph type="secondary" style={{ marginBottom: 24, fontSize: 14 }}>
            请输入当前的双因素认证验证码以确认禁用
          </Paragraph>

          {/* 验证码输入框 */}
          <Space direction="vertical" size="middle" style={{ width: '100%', marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
              {[0, 1, 2, 3, 4, 5].map((index) => (
                <Input
                  key={index}
                  ref={(el) => { mfaDisableInputRefs.current[index] = el; }}
                  value={mfaDisableCode[index] || ''}
                  onChange={(e) => {
                    const val = e.target.value.replace(/\D/g, '');
                    if (!val) return;
                    
                    const newCode = mfaDisableCode.split('');
                    newCode[index] = val[val.length - 1];
                    setMfaDisableCode(newCode.join(''));
                    
                    // 跳到下一个输入框
                    if (index < 5) {
                      setTimeout(() => {
                        mfaDisableInputRefs.current[index + 1]?.focus();
                      }, 10);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Backspace') {
                      if (mfaDisableCode[index]) {
                        const newCode = mfaDisableCode.split('');
                        newCode[index] = '';
                        setMfaDisableCode(newCode.join(''));
                      } else if (index > 0) {
                        setTimeout(() => {
                          mfaDisableInputRefs.current[index - 1]?.focus();
                        }, 10);
                      }
                    }
                  }}
                  onPaste={(e) => {
                    e.preventDefault();
                    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
                    if (pasted) {
                      setMfaDisableCode(pasted);
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

          {/* 按钮区域 */}
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Button 
              size="large" 
              onClick={() => {
                setMfaDisableVisible(false);
                setMfaDisableCode('');
              }}
            >
              取消
            </Button>
            <Button
              type="primary" danger
              size="large"
              loading={mfaDisableLoading}
              onClick={handleMfaDisable}
              disabled={mfaDisableCode.length !== 6}
            >
              确认禁用
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
