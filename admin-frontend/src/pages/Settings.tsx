/**
 * 系统设置页面
 * 
 * 功能：
 * - 分组展示各模块配置
 * - 支持修改非敏感配置
 * - 配置说明提示
 */
import { useState, useEffect, useRef } from 'react';
import { Card, Collapse, Button, Spin, Typography, Divider, Alert, Input, InputNumber, Switch, Select, Space, Tooltip, Tag, Popconfirm, Modal, QRCode, App } from 'antd';
import ResponsiveTable from '@/components/ResponsiveTable';
import OtpInput from '@/components/common/OtpInput';
import { SettingOutlined, ReloadOutlined, InfoCircleOutlined, EditOutlined, SaveOutlined, CloseOutlined, ToolOutlined, CloudOutlined, ThunderboltOutlined, SendOutlined, SafetyOutlined, CheckCircleOutlined, StopOutlined, BookOutlined, ClockCircleOutlined, MobileOutlined } from '@ant-design/icons';
import { configApi, type ModuleConfigItem, type ModuleConfigGroup } from '@/api/admin';

// 电量星期映射（用于设置页定时计划说明）
const WEEKDAY_CN: Record<string, string> = { mon: '周一', tue: '周二', wed: '周三', thu: '周四', fri: '周五', sat: '周六', sun: '周日' };
const DAYNUM_CN: Record<string, string> = { '0': '周日', '1': '周一', '2': '周二', '3': '周三', '4': '周四', '5': '周五', '6': '周六' };
import request from '@/api/request';

const { Text, Paragraph, Title } = Typography;

// 模块图标和颜色
const MODULE_META: Record<string, { icon: React.ReactNode; color: string }> = {
  system: { icon: <ToolOutlined />, color: '#1890ff' },
  weather: { icon: <CloudOutlined />, color: '#52c41a' },
  electricity: { icon: <ThunderboltOutlined />, color: '#faad14' },
  push: { icon: <SendOutlined />, color: '#722ed1' },
  course: { icon: <BookOutlined />, color: '#eb2f96' },
};

// 默认图标
const DEFAULT_MODULE_ICON = <SettingOutlined />;

export default function Settings() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [configs, setConfigs] = useState<Record<string, ModuleConfigGroup>>({});
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState<string | number | boolean>('');
  const [saving, setSaving] = useState(false);

  // MFA 状态
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaModalVisible, setMfaModalVisible] = useState(false);
  const [mfaSecret, setMfaSecret] = useState('');
  const [mfaQrUrl, setMfaQrUrl] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaSetupStep, setMfaSetupStep] = useState<'idle' | 'scan' | 'verify' | 'disable'>('idle');
  const mfaVisibleRef = useRef(false);

  // 同步 mfaVisibleRef
  useEffect(() => {
    mfaVisibleRef.current = mfaModalVisible;
  }, [mfaModalVisible]);

  // 切换到输入验证码步骤（聚焦交给 OtpInput 的 autoFocus）
  const switchToVerifyStep = () => {
    setMfaSetupStep('verify');
    setMfaCode('');
  };

  const fetchConfigs = async () => {
    setLoading(true);
    try {
      const res = await configApi.getAll();
      if (res.status === 'success' && res.data) {
        setConfigs(res.data);
      }
    } catch (error) {
      console.error('加载配置失败:', error);
      message.error('加载配置失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfigs();
    fetchMfaStatus();
  }, []);

  // 获取 MFA 状态
  const fetchMfaStatus = async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await request.get('/auth/mfa/status');
      if (res.status === 'success') {
        setMfaEnabled(res.data?.enabled || false);
      }
    } catch { /* 忽略 */ }
  };

  // 设置 MFA - 生成二维码
  const handleMfaSetup = async () => {
    setMfaLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await request.post('/auth/mfa/setup');
      if (res.status === 'success') {
        setMfaSecret(res.data?.secret || '');
        setMfaQrUrl(res.data?.qr_code_base64 || '');  // 使用 Base64 图片
        setMfaSetupStep('scan');
        setMfaModalVisible(true);
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '设置 MFA 失败');
    } finally {
      setMfaLoading(false);
    }
  };

  // 验证 MFA 代码并启用
  const handleMfaVerify = async () => {
    if (!mfaCode || mfaCode.length !== 6) {
      message.warning('请输入6位验证码');
      return;
    }
    setMfaLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await request.post('/auth/mfa/verify', { code: mfaCode });
      if (res.status === 'success') {
        message.success('MFA 已启用');
        setMfaEnabled(true);
        setMfaModalVisible(false);
        setMfaSetupStep('idle');
        setMfaCode('');
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '验证失败');
    } finally {
      setMfaLoading(false);
    }
  };

  // 禁用 MFA（聚焦交给 OtpInput 的 autoFocus）
  const handleMfaDisable = () => {
    setMfaModalVisible(true);
    setMfaSetupStep('disable');
    setMfaCode('');
  };

  const handleMfaDisableConfirm = async () => {
    if (!mfaCode || mfaCode.length !== 6) {
      message.warning('请输入6位验证码');
      return;
    }
    setMfaLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await request.post('/auth/mfa/disable', { code: mfaCode });
      if (res.status === 'success') {
        message.success('MFA 已禁用');
        setMfaEnabled(false);
        setMfaModalVisible(false);
        setMfaSetupStep('idle');
        setMfaCode('');
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '禁用失败');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleEdit = (config: ModuleConfigItem) => {
    if (!config.is_editable) {
      message.warning('此配置项不可修改');
      return;
    }
    if (config.is_sensitive) {
      message.warning('敏感配置不能通过界面修改');
      return;
    }
    setEditingKey(`${config.module}.${config.key}`);
    setEditingValue(config.value as string | number | boolean);
  };

  const handleCancel = () => {
    setEditingKey(null);
    setEditingValue('');
  };

  const handleSave = async (config: ModuleConfigItem) => {
    setSaving(true);
    try {
      const res = await configApi.update(config.module, config.key, editingValue);
      if (res.status === 'success') {
        message.success('配置已保存');
        setEditingKey(null);
        fetchConfigs();
      }
    } catch (error) {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const renderValueInput = (config: ModuleConfigItem) => {
    const isEditing = editingKey === `${config.module}.${config.key}`;

    // 课程爬虫调度模式：cron / interval 用下拉选择，避免直接手填字符串
    if (config.module === 'course' && config.key === 'spider_schedule_mode') {
      if (!isEditing) {
        return config.value === 'interval'
          ? <Tag color="blue">间隔模式</Tag>
          : <Tag color="green">定时模式(07:00/13:00)</Tag>;
      }
      return (
        <Select
          value={editingValue as string}
          onChange={(v) => setEditingValue(v)}
          style={{ width: '100%' }}
        >
          <Select.Option value="cron">定时(cron 每天07:00/13:00)</Select.Option>
          <Select.Option value="interval">间隔(每隔N小时)</Select.Option>
        </Select>
      );
    }

    if (!isEditing) {
      // 显示模式
      let displayValue = config.value;
      if (config.is_sensitive) {
        displayValue = '******';
      } else if (config.value_type === 'boolean') {
        return config.value ? <Tag color="green">是</Tag> : <Tag color="red">否</Tag>;
      }
      return <Text>{String(displayValue)}</Text>;
    }

    // 编辑模式
    switch (config.value_type) {
      case 'integer':
        return (
          <InputNumber
            value={editingValue as number}
            onChange={(v) => setEditingValue(v || 0)}
            style={{ width: '100%' }}
          />
        );
      case 'float':
        return (
          <InputNumber
            value={editingValue as number}
            onChange={(v) => setEditingValue(v || 0)}
            step={0.1}
            style={{ width: '100%' }}
          />
        );
      case 'boolean':
        return (
          <Switch
            checked={editingValue as boolean}
            onChange={(v) => setEditingValue(v)}
            checkedChildren="是"
            unCheckedChildren="否"
          />
        );
      default:
        return (
          <Input
            value={editingValue as string}
            onChange={(e) => setEditingValue(e.target.value)}
            style={{ width: '100%' }}
          />
        );
    }
  };

  const renderActions = (config: ModuleConfigItem) => {
    const isEditing = editingKey === `${config.module}.${config.key}`;

    if (!config.is_editable || config.is_sensitive) {
      return (
        <Tooltip title={config.is_sensitive ? '敏感配置，请通过环境变量修改' : '只读配置'}>
          <Tag color="default">只读</Tag>
        </Tooltip>
      );
    }

    if (isEditing) {
      return (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={() => handleSave(config)}
          >
            保存
          </Button>
          <Button size="small" icon={<CloseOutlined />} onClick={handleCancel}>
            取消
          </Button>
        </Space>
      );
    }

    return (
      <Button
        type="link"
        size="small"
        icon={<EditOutlined />}
        onClick={() => handleEdit(config)}
      >
        编辑
      </Button>
    );
  };

  // 课程模块当前调度模式（用于描述列条件提示）
  const courseSpiderMode =
    configs['course']?.configs.find((c) => c.key === 'spider_schedule_mode')?.value ?? 'cron';

  const columns = [
    {
      title: '配置项',
      dataIndex: 'key',
      key: 'key',
      width: 280,
      render: (key: string, record: ModuleConfigItem) => (
        <Space>
          <Text strong>{key}</Text>
          {record.is_sensitive && <Tag color="orange">敏感</Tag>}
        </Space>
      ),
    },
    {
      title: '当前值',
      dataIndex: 'value',
      key: 'value',
      width: 200,
      render: (_: any, record: ModuleConfigItem) => renderValueInput(record),
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (desc: string, record: ModuleConfigItem) => {
        // 当课程模块为定时模式时，间隔参数不生效，直接在描述上标注，消除“每6小时”歧义
        const note =
          record.key === 'spider_interval_hours' && courseSpiderMode === 'cron'
            ? '（当前定时模式，此参数不生效）'
            : '';
        const fullDesc = note ? `${desc} ${note}` : desc;
        return (
          <Tooltip title={fullDesc}>
            <Text type="secondary">{fullDesc}</Text>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: any, record: ModuleConfigItem) => renderActions(record),
    },
  ];

  return (
    <div>
      <Card
        title={
          <Space>
            <SettingOutlined />
            <span>系统设置</span>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchConfigs} loading={loading}>
              刷新
            </Button>
          </Space>
        }
      >
        <Alert
          message="配置说明"
          description={
            <div>
              <p>• <b>可编辑配置</b>：点击"编辑"按钮直接修改，保存后立即生效</p>
              <p>• <b>只读配置</b>：需要修改配置文件（.env）后重启服务</p>
              <p>• <b>敏感配置</b>：包含密钥、密码等，只能通过环境变量配置</p>
            </div>
          }
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          style={{ marginBottom: 24 }}
        />

        {loading ? (
          <Spin />
        ) : (
          <Collapse
            defaultActiveKey={Object.keys(configs)}
            bordered={false}
            style={{ background: '#fff' }}
            items={Object.entries(configs).map(([module, group]) => {
              const isCourse = module === 'course';
              const isElectricity = module === 'electricity';
              const ecDaily = isElectricity ? String(group.configs.find((c) => c.key === 'schedule_daily')?.value ?? '00:30') : null;
              const ecWeeklyDay = isElectricity ? String(group.configs.find((c) => c.key === 'schedule_weekly_day')?.value ?? 'mon') : null;
              const ecWeeklyTime = isElectricity ? String(group.configs.find((c) => c.key === 'schedule_weekly')?.value ?? '00:30') : null;
              const ecMonthlyDay = isElectricity ? String(group.configs.find((c) => c.key === 'schedule_monthly_day')?.value ?? '1') : null;
              const ecMonthlyTime = isElectricity ? String(group.configs.find((c) => c.key === 'schedule_monthly')?.value ?? '00:30') : null;
              const ecCookie = isElectricity ? String(group.configs.find((c) => c.key === 'cookie_check_time')?.value ?? '20:00') : null;
              const ecFullDay = isElectricity ? String(group.configs.find((c) => c.key === 'full_crawl_day')?.value ?? '0') : null;
              const ecFullTime = isElectricity ? String(group.configs.find((c) => c.key === 'full_crawl_time')?.value ?? '03:00') : null;
              const ecLowThreshold = isElectricity ? String(group.configs.find((c) => c.key === 'low_power_threshold')?.value ?? '10.0') : null;
              const ecLowInterval = isElectricity ? String(group.configs.find((c) => c.key === 'low_power_interval_hours')?.value ?? '4.0') : null;
              const spiderMode = isCourse
                ? (group.configs.find((c) => c.key === 'spider_schedule_mode')?.value ?? 'cron')
                : null;
              const spiderInterval = isCourse
                ? (group.configs.find((c) => c.key === 'spider_interval_hours')?.value ?? '6')
                : null;
              const spiderCron = isCourse
                ? (group.configs.find((c) => c.key === 'spider_cron_expression')?.value ?? '0 7,13 * * *')
                : null;
              const scheduleText =
                spiderMode === 'interval'
                  ? `间隔模式：每隔 ${spiderInterval} 小时爬取一次`
                  : `定时模式：cron 表达式「${spiderCron}」`;
              return {
                key: module,
                label: (
                  <Space>
                    <span style={{ color: MODULE_META[module]?.color }}>
                      {MODULE_META[module]?.icon || DEFAULT_MODULE_ICON}
                    </span>
                    <span style={{ fontWeight: 500 }}>{group.name}</span>
                    <Tag color={MODULE_META[module]?.color || 'default'}>
                      {group.configs.length} 项
                    </Tag>
                  </Space>
                ),
                children: (
                  <>
                    {isCourse && (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                        message="课程爬虫爬取计划"
                        description={
                          <span>
                            {scheduleText}
                            <br />
                            <Text type="secondary">
                              爬虫时间可在下方直接修改并<b>即时生效（无需重启）</b>：定时模式改「spider_cron_expression」，间隔模式改「spider_interval_hours」。
                            </Text>
                          </span>
                        }
                      />
                    )}
                    {isElectricity && (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                        message="电量模块定时计划"
                        description={
                          <span>
                            当前生效：<br />
                            • 每日报告：每天 {ecDaily}<br />
                            • 每周报告：每{WEEKDAY_CN[String(ecWeeklyDay ?? 'mon')] ?? String(ecWeeklyDay ?? 'mon')} {ecWeeklyTime}<br />
                            • 每月报告：每月{ecMonthlyDay}日 {ecMonthlyTime}<br />
                            • Cookie 检测：每天 {ecCookie}<br />
                            • 全量爬取：每周{DAYNUM_CN[String(ecFullDay ?? '0')] ?? String(ecFullDay ?? '0')} {ecFullTime}<br />
                            • 低电量检测：剩余 ≤ {ecLowThreshold} 度时告警，每 {ecLowInterval} 小时检测一次<br />
                            <Text type="secondary">
                              上述时间均可在下方表格直接修改，保存后<b>即时生效（无需重启）</b>：调度器会自动重载。
                            </Text>
                          </span>
                        }
                      />
                    )}
                    <ResponsiveTable
                      dataSource={group.configs}
                      columns={columns}
                      rowKey="id"
                      size="small"
                      pagination={false}
                      scroll={{ x: 600 }}
                      rowClassName={(record) =>
                        record.is_sensitive ? 'row-sensitive' : ''
                      }
                    />
                  </>
                ),
              };
            })}
          />
        )}
      </Card>

      {/* MFA 多因素认证 */}
      <Card
        title={<><SafetyOutlined style={{ marginRight: 8 }} />多因素认证 (MFA)</>}
        style={{ marginTop: 24 }}
      >
        <Alert
          message="什么是 MFA？"
          description="多因素认证在密码之外增加一层保护。登录时除了输入密码，还需要输入手机 APP 生成的 6 位验证码，即使密码泄露也无法登录。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space>
            <Text strong>MFA 状态：</Text>
            {mfaEnabled ? (
              <Tag icon={<CheckCircleOutlined />} color="success">已启用</Tag>
            ) : (
              <Tag icon={<StopOutlined />} color="default">未启用</Tag>
            )}
          </Space>
          <Space>
            {!mfaEnabled ? (
              <Button type="primary" icon={<SafetyOutlined />} loading={mfaLoading} onClick={handleMfaSetup}>
                启用 MFA
              </Button>
            ) : (
              <Popconfirm title="确定要禁用 MFA 吗？需要输入验证码确认。" onConfirm={handleMfaDisable}>
                <Button danger>禁用 MFA</Button>
              </Popconfirm>
            )}
          </Space>
        </div>
      </Card>

      {/* MFA 设置弹窗 */}
      <Modal
        title="两步验证"
        open={mfaModalVisible}
        onCancel={() => { setMfaModalVisible(false); setMfaSetupStep('idle'); }}
        footer={null}
        centered
        width={400}
      >
        <div style={{ textAlign: 'center' }}>
          {/* 扫描二维码步骤 */}
          {mfaSetupStep === 'scan' && (
            <>
              <div style={{ marginBottom: 16 }}>
                <Text>请使用 <Text strong>Google Authenticator</Text> 或类似 APP 扫描下方二维码</Text>
              </div>
              {mfaQrUrl && <img src={mfaQrUrl} alt="MFA 二维码" style={{ marginBottom: 16, maxWidth: '100%' }} />}
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary">手动输入密钥：</Text>
                <Text code copyable>{mfaSecret}</Text>
              </div>
              <Button type="primary" onClick={switchToVerifyStep}>下一步</Button>
            </>
          )}

          {/* 输入验证码步骤（启用或禁用） */}
          {(mfaSetupStep === 'verify' || mfaSetupStep === 'disable') && (
            <>
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
              <Title level={4} style={{ marginBottom: 8, fontSize: 16, fontWeight: 500 }}>
                {mfaSetupStep === 'verify' ? '输入验证码' : '禁用 MFA'}
              </Title>
              <Paragraph type="secondary" style={{ marginBottom: 24, fontSize: 14 }}>
                {mfaSetupStep === 'verify' 
                  ? '请输入 APP 显示的 6 位验证码以启用 MFA'
                  : '请输入 APP 显示的 6 位验证码以禁用 MFA'}
              </Paragraph>

              {/* 验证码输入框 */}
              <Space direction="vertical" size="middle" style={{ width: '100%', marginBottom: 8 }}>
                                <OtpInput value={mfaCode} onChange={setMfaCode} length={6} autoFocus />
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
                  onClick={() => { setMfaModalVisible(false); setMfaSetupStep('idle'); }}
                >
                  返回
                </Button>
                <Button
                  type="primary"
                  size="large"
                  loading={mfaLoading}
                  onClick={mfaSetupStep === 'verify' ? handleMfaVerify : handleMfaDisableConfirm}
                  disabled={mfaCode.length !== 6}
                >
                  {mfaSetupStep === 'verify' ? '启用 MFA' : '禁用 MFA'}
                </Button>
              </div>
            </>
          )}
        </div>
      </Modal>

      <style>{`
        .row-sensitive {
          background-color: #fffbe6;
        }
      `}</style>
    </div>
  );
}
