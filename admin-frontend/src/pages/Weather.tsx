/**
 * 天气管理页面
 */
import { useState, useEffect } from 'react';
import { Card, Tabs, Statistic, Row, Col, Alert, Form, Input, InputNumber, Switch, Button, Spin, Tag, Descriptions, Space, Badge, App } from 'antd';
import { useRunningTasksPolling } from '@/hooks/useRunningTasksPolling';
import { CloudOutlined, ReloadOutlined, PlayCircleOutlined, LineChartOutlined, LoadingOutlined, FireOutlined, EnvironmentOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { adminApi, processApi } from '@/api/admin';
import { weatherApi, type WeatherNow, type HourlyForecast, type WeatherAlert, type WeatherConfig } from '@/api/weather';
import { holidayApi, type HolidayStatus } from '@/api/holiday';
import WeatherChart from '@/components/WeatherChart';
import { useUser } from '@/contexts/UserContext';

/** 天气文字 → emoji 图标（按常见中文天气描述匹配） */
const WEATHER_EMOJI: [RegExp, string][] = [
  [/雷|暴/, '⛈️'],
  [/雨/, '🌧️'],
  [/雪/, '❄️'],
  [/雾|霾|沙|尘/, '🌫️'],
  [/阴/, '☁️'],
  [/多云/, '⛅'],
  [/晴/, '☀️'],
];
const weatherEmoji = (text: string): string => {
  for (const [re, emoji] of WEATHER_EMOJI) if (re.test(text || '')) return emoji;
  return '🌡️';
};

/** 天气文字 → 主题强调色 */
const weatherAccent = (text: string): string => {
  if (/雨|雪|雷/.test(text || '')) return '#1677ff';
  if (/晴/.test(text || '')) return '#fa8c16';
  if (/多云/.test(text || '')) return '#13c2c2';
  if (/阴|雾|霾/.test(text || '')) return '#8c8c8c';
  return '#1677ff';
};

/** 格式化时间字符串为 HH:mm */
const fmtHour = (t: string): string => {
  if (!t) return '--:--';
  const d = new Date(t);
  if (isNaN(d.getTime())) return t;
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

export default function Weather() {
  const { isAdmin } = useUser();
  const { message } = App.useApp();
  const [activeTab, setActiveTab] = useState('now');
  const [loading, setLoading] = useState(false);
  const [nowData, setNowData] = useState<WeatherNow | null>(null);
  const [hourlyData, setHourlyData] = useState<HourlyForecast[]>([]);
  const [alertData, setAlertData] = useState<WeatherAlert[]>([]);
  const [alertHistory, setAlertHistory] = useState<WeatherAlert[]>([]);
  const [alertHistoryPage, setAlertHistoryPage] = useState(1);
  const [alertHistoryTotal, setAlertHistoryTotal] = useState(0);
  const [alertHistoryLoading, setAlertHistoryLoading] = useState(false);
  const [config, setConfig] = useState<WeatherConfig>({});
  const [form] = Form.useForm();
  // 列表轮询开关（触发天气任务时开启）
  const [listPolling, setListPolling] = useState(false);
  // 假期模式状态：active 时手动触发天气任务会被后端静默拦截，前端同步禁用触发按钮
  const [holidayStatus, setHolidayStatus] = useState<HolidayStatus | null>(null);

  const fetchNow = async () => {
    setLoading(true);
    try {
      const res = await weatherApi.getNow();
      if (res.status === 'success' && res.data) setNowData(res.data);
    } catch (error: any) {
      console.error('加载实时天气失败:', error);
      if (error.isAxiosError && error.code === 'ECONNABORTED') {
        message.warning('请求超时，请稍后重试');
      } else if (error.isOffline) {
        message.warning('无法连接到服务器，请检查后端服务是否运行');
      } else {
        message.error('加载实时天气失败，请稍后重试');
      }
    }
    finally { setLoading(false); }
  };

  const fetchHourly = async () => {
    setLoading(true);
    try {
      const res = await weatherApi.getHourly();
      if (res.status === 'success' && res.data) setHourlyData(res.data);
    } catch (error: any) {
      console.error('加载24h预报失败:', error);
      if (error.isAxiosError && error.code === 'ECONNABORTED') {
        message.warning('请求超时，请稍后重试');
      } else if (error.isOffline) {
        message.warning('无法连接到服务器，请检查后端服务是否运行');
      } else {
        message.error('加载24h预报失败，请稍后重试');
      }
    }
    finally { setLoading(false); }
  };

  const fetchAlert = async () => {
    setLoading(true);
    try {
      const res = await weatherApi.getAlert();
      if (res.status === 'success' && res.data) setAlertData(res.data.warnings || []);
    } catch (error: any) {
      console.error('加载预警信息失败:', error);
      if (error.isAxiosError && error.code === 'ECONNABORTED') {
        message.warning('请求超时，请稍后重试');
      } else if (error.isOffline) {
        message.warning('无法连接到服务器，请检查后端服务是否运行');
      } else {
        message.error('加载预警信息失败，请稍后重试');
      }
    }
    finally { setLoading(false); }
  };

  const fetchAlertHistory = async (page = 1) => {
    setAlertHistoryLoading(true);
    try {
      const res = await weatherApi.getAlertHistory(page);
      if (res.status === 'success' && res.data) {
        const list = res.data || [];
        setAlertHistory((prev) => (page === 1 ? list : [...prev, ...list]));
        setAlertHistoryTotal(res.pagination?.total ?? list.length);
        setAlertHistoryPage(page);
      }
    } catch (error: any) {
      console.error('加载预警历史失败:', error);
      if (error.isAxiosError && error.code === 'ECONNABORTED') {
        message.warning('请求超时，请稍后重试');
      } else if (error.isOffline) {
        message.warning('无法连接到服务器，请检查后端服务是否运行');
      } else {
        message.error('加载预警历史失败，请稍后重试');
      }
    }
    finally { setAlertHistoryLoading(false); }
  };

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await adminApi.getWeatherConfig();
      if (res.status === 'success' && res.config) { setConfig(res.config); form.setFieldsValue(res.config); }
    } catch (error: any) {
      console.error('加载配置失败:', error);
      if (error.isAxiosError && error.code === 'ECONNABORTED') {
        message.warning('请求超时，请稍后重试');
      } else if (error.isOffline) {
        message.warning('无法连接到服务器，请检查后端服务是否运行');
      } else {
        message.error('加载配置失败，请稍后重试');
      }
    }
    finally { setLoading(false); }
  };

  const handleSaveConfig = async (values: WeatherConfig) => {
    try {
      const res = await adminApi.updateWeatherConfig(values);
      if (res.status === 'success') { message.success('配置已保存'); fetchConfig(); }
    } catch (error) { message.error('保存配置失败'); }
  };

  // 任务完成后刷新数据
  const refreshAllData = () => {
    if (activeTab === 'now') {
      fetchNow();
    } else if (activeTab === 'hourly') {
      fetchHourly();
    } else if (activeTab === 'alert') {
      fetchAlert();
    }
  };

  // 列表轮询：触发天气任务后，轮询“运行中任务列表”，空则视为完成
  const listPoll = useRunningTasksPolling({
    fetcher: () => processApi.getRunning(),
    filter: (t) => t.task_type === 'weather',
    enabled: listPolling,
    onIdle: () => {
      message.success('任务已完成，数据已刷新');
      refreshAllData();
    },
  });

  // 组合轮询状态供徽标 / 告警展示
  const isPolling = listPoll.isPolling;

  // 触发天气任务：开启列表轮询
  const handleTrigger = async (taskType: string) => {
    try {
      const res = await adminApi.triggerWeather(taskType);
      // 假期静默拦截：后端返回 skipped，提示已跳过且不开启「已完成」轮询
      if ((res as any).skipped) {
        message.warning(res.message || '假期静默中，已跳过');
        return;
      }
      message.success(res.message || '任务已触发');
      setListPolling(true);
    } catch (error) { message.error('触发任务失败'); }
  };

  // 挂载时检查是否已有运行中的天气任务，有则接管轮询
  useEffect(() => {
    (async () => {
      try {
        const res = await processApi.getRunning();
        if (res.status === 'success' && res.data?.data) {
          const hasRunning = res.data.data.some((t) => t.task_type === 'weather');
          if (hasRunning) setListPolling(true);
        }
      } catch (error) {
        console.error('检查运行中天气任务失败:', error);
      }
    })();
  }, []);

  // 挂载时拉取假期模式状态，用于同步禁用触发按钮
  useEffect(() => {
    holidayApi.getStatus()
      .then((res) => { if (res.status === 'success' && res.data) setHolidayStatus(res.data); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (activeTab === 'now') fetchNow();
    else if (activeTab === 'hourly') fetchHourly();
    else if (activeTab === 'alert') {
      fetchAlert();
      fetchAlertHistory();
    }
    else if (activeTab === 'config') fetchConfig();
  }, [activeTab]);

  // 构建标签页数组，仅管理员显示配置标签
  const tabs = [
    {
      key: 'now', label: <Space>实时天气{isPolling && <Badge dot offset={[4, -4]} />}</Space>, icon: <CloudOutlined />,
      children: (
        <div>
          {isPolling && (
            <Alert
              message={
                <Space>
                  <LoadingOutlined spin />
                  <span>任务运行中，自动刷新...</span>
                </Space>
              }
              type="info"
              showIcon={false}
              style={{ marginBottom: 16 }}
            />
          )}
          {loading ? <Spin /> : nowData ? (
            <div>
              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} md={6}>
                  <Card>
                    <Statistic 
                    title="当前温度" 
                    value={nowData.temp} 
                    suffix="°C" 
                    prefix={<FireOutlined style={{ fontSize: 20, marginRight: 8 }} />} 
                    />
                  </Card>
                </Col>
                <Col xs={24} sm={12} md={6}>
                  <Card>
                    <Statistic 
                    title="体感温度" 
                    value={nowData.feels_like} 
                    suffix="°C" 
                    prefix={<EnvironmentOutlined style={{ fontSize: 20, marginRight: 8 }} />} 
                    />
                  </Card>
                </Col>
                <Col xs={24} sm={12} md={6}>
                  <Card>
                    <Statistic 
                    title="湿度" 
                    value={nowData.humidity} 
                    suffix="%" 
                    prefix={<CloudOutlined style={{ fontSize: 20, marginRight: 8 }} />} 
                    />
                  </Card>
                </Col>
                <Col xs={24} sm={12} md={6}>
                  <Card>
                    <Statistic 
                    title="风向风力" 
                    value={`${nowData.wind_dir} ${nowData.wind_scale}级`} 
                    prefix={<ThunderboltOutlined style={{ fontSize: 20, marginRight: 8 }} />} 
                    />
                  </Card>
                </Col>
              </Row>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 16 }}>
                <div style={{ flex: 1, textAlign: 'left' }}>
                  <span style={{ color: '#999', marginRight: 8 }}>城市:</span>
                  <span>{nowData.city_name}</span>
                </div>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <span style={{ color: '#999', marginRight: 8 }}>天气:</span>
                  <span>{nowData.text}</span>
                </div>
                {(nowData as any).update_time && (
                  <div style={{ flex: 1, textAlign: 'right' }}>
                    <span style={{ color: '#999', marginRight: 8 }}>更新时间:</span>
                    <span>
                      {(() => {
                        const date = new Date((nowData as any).update_time);
                        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
                      })()}
                    </span>
                  </div>
                )}
              </div>
              <Space style={{ marginTop: 16 }}>
                <Button icon={<ReloadOutlined />} onClick={fetchNow} disabled={isPolling}>刷新数据</Button>
                {isAdmin && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleTrigger('update_weather_now')} disabled={isPolling || holidayStatus?.active} loading={isPolling}>更新天气数据</Button>}
              </Space>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Alert message="暂无数据，请先触发数据采集" type="info" />
              {isAdmin && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleTrigger('update_weather_now')} style={{ marginTop: 16 }} disabled={isPolling || holidayStatus?.active} loading={isPolling}>更新天气数据</Button>}
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'hourly', label: '24h预报',
      children: loading ? <Spin /> : (
        hourlyData.length > 0 ? (
          <div style={{ paddingLeft: 4 }}>
            {hourlyData.map((item, idx) => {
              const accent = weatherAccent(item.text);
              const isCurrent = idx === 0;
              const len = hourlyData.length;
              return (
                <div
                  key={`${item.time}-${idx}`}
                  title={item.text}
                  style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 0' }}
                >
                  {/* 轴线 + emoji 节点 */}
                  <div style={{ position: 'relative', width: 34, flexShrink: 0, display: 'flex', justifyContent: 'center' }}>
                    {idx < len - 1 && (
                      <span style={{ position: 'absolute', top: '50%', bottom: 'calc(-50% - 7px)', left: '50%', transform: 'translateX(-50%)', width: 2, background: '#eee' }} />
                    )}
                    <div
                      style={{
                        position: 'relative',
                        zIndex: 1,
                        width: 30,
                        height: 30,
                        borderRadius: '50%',
                        background: isCurrent ? `${accent}1a` : '#fff',
                        border: `1px solid ${isCurrent ? accent : '#f0f0f0'}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 15,
                        boxShadow: isCurrent ? `0 2px 8px ${accent}22` : 'none',
                      }}
                    >
                      {weatherEmoji(item.text)}
                    </div>
                  </div>
                  {/* 内容行 */}
                  <div style={{ flex: 1, display: 'flex', alignItems: 'baseline', gap: 10 }}>
                    <span style={{ fontSize: 12, color: isCurrent ? accent : '#999', fontWeight: isCurrent ? 600 : 400, width: 40, flexShrink: 0 }}>
                      {isCurrent ? '现在' : fmtHour(item.time)}
                    </span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: accent }}>{item.temp}°</span>
                    <span style={{ fontSize: 12, color: '#1677ff', marginLeft: 'auto' }}>💧{item.pop}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <Alert message="暂无 24h 预报数据，请先触发数据采集" type="info" showIcon />
        )
      ),
    },
    {
      key: 'alert', label: '预警信息',
      children: loading ? <Spin /> : (
        <div>
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ marginBottom: 12 }}>当前预警</h3>
            {alertData.length > 0 ? (
              alertData.map((alert) => (
                <Alert
                  key={alert.id}
                  message={alert.headline}
                  description={alert.description}
                  type={alert.color_code === 'red' ? 'error' : alert.color_code === 'orange' ? 'warning' : 'info'}
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              ))
            ) : (
              <Alert message="当前无天气预警" type="success" showIcon />
            )}
          </div>
          <div>
            <h3 style={{ marginBottom: 12 }}>预警历史</h3>
            {alertHistoryLoading && alertHistoryPage === 1 ? (
              <Spin />
            ) : alertHistory.length > 0 ? (
              <>
                {alertHistory.map((alert) => (
                  <Alert
                    key={alert.id}
                    message={
                      <Space>
                        {alert.headline}
                        <Tag color={alert.is_pushed ? 'green' : 'default'}>
                          {alert.is_pushed ? '已推送' : '未推送'}
                        </Tag>
                      </Space>
                    }
                    description={alert.description}
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                  />
                ))}
                {alertHistoryTotal > alertHistory.length && (
                  <Button
                    onClick={() => fetchAlertHistory(alertHistoryPage + 1)}
                    loading={alertHistoryLoading}
                    style={{ marginTop: 8 }}
                  >
                    加载更多（已显示 {alertHistory.length} / {alertHistoryTotal}）
                  </Button>
                )}
              </>
            ) : (
              <Alert message="暂无预警历史记录" type="info" showIcon />
            )}
          </div>
        </div>
      ),
    },
    {
      key: 'chart', label: '数据可视化', icon: <LineChartOutlined />,
      children: <WeatherChart />,
    },
  ];
  
  // 仅管理员添加配置标签
  if (isAdmin) {
    tabs.push({
      key: 'config', label: '模块配置',
      children: loading ? <Spin /> : (
        <Form form={form} layout="vertical" onFinish={handleSaveConfig} style={{ maxWidth: 600 }}>
          {/* 认证方式显示 */}
          <Form.Item label="认证方式">
            <Input
              value={config.auth_type === 'jwt_ed25519' ? 'JWT Ed25519 (推荐)' : config.auth_type === 'api_key' ? 'API Key (兼容)' : '未配置'}
              disabled
            />
          </Form.Item>

          {/* JWT Ed25519 配置 */}
          {config.auth_type === 'jwt_ed25519' && (
            <>
              <Form.Item label="凭据 ID">
                <Input value={config.credential_id} disabled />
              </Form.Item>
              <Form.Item label="项目 ID">
                <Input
                  value={config.project_id_configured ? '已配置' : '未配置'}
                  disabled
                  status={config.project_id_configured ? '' : 'error'}
                />
              </Form.Item>
              <Form.Item label="私钥文件">
                <Input
                  value={config.private_key_configured ? '已找到' : '未找到'}
                  disabled
                  status={config.private_key_configured ? '' : 'error'}
                />
              </Form.Item>
            </>
          )}

          {/* 项目 ID 输入（当使用 JWT 时） */}
          <Form.Item
            name="project_id"
            label="项目 ID (sub)"
            tooltip="在和风天气控制台-项目管理中查看"
            rules={[{ required: config.auth_type === 'jwt_ed25519', message: '请输入项目 ID' }]}
          >
            <Input.Password placeholder="输入项目 ID 以启用 JWT 认证" visibilityToggle />
          </Form.Item>

          {/* API Key 配置（兼容旧版） */}
          <Form.Item
            name="api_key"
            label="API Key (兼容旧版)"
            tooltip="仅当不使用 JWT 时需要填写"
          >
            <Input.Password placeholder="和风天气 API Key" />
          </Form.Item>

          <Form.Item name="location" label="位置坐标"><Input placeholder="经度,纬度 或 LocationID" /></Form.Item>
          <Form.Item name="city_name" label="城市名称"><Input placeholder="如：重庆" /></Form.Item>
          <Form.Item name="daily_push_time" label="每日推送时间"><Input placeholder="如：07:00" /></Form.Item>

          <Alert
            type="info"
            showIcon
            message="推送时段与频率控制"
            description="开启夜间免打扰后，安静时段内天气模块完全休息、不再推送任何消息；每日上限用于防止白天频繁打扰。"
            style={{ marginBottom: 16 }}
          />
          <Form.Item
            name="quiet_hours_enabled"
            label="夜间免打扰"
            valuePropName="checked"
            tooltip="开启后，在设定时段内不推送任何天气消息（晨报/预警/分析均暂停）"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="quiet_hours_start" label="免打扰开始时间" tooltip="格式 HH:MM（24小时制）">
            <Input placeholder="如：23:00" />
          </Form.Item>
          <Form.Item name="quiet_hours_end" label="免打扰结束时间" tooltip="格式 HH:MM（24小时制），可跨午夜，如 23:00 - 07:00">
            <Input placeholder="如：07:00" />
          </Form.Item>
          <Form.Item
            name="daily_push_limit"
            label="每日推送上限"
            tooltip="每天最多推送的天气消息条数，0 表示不限。用于限制白天推送频率"
          >
            <InputNumber min={0} max={50} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item
            name="alert_enabled"
            label="天气预警推送"
            valuePropName="checked"
            tooltip="关闭后不再推送气象预警消息（历史记录仍会正常保存）"
          >
            <Switch />
          </Form.Item>

          <Form.Item><Button type="primary" htmlType="submit">保存配置</Button></Form.Item>
        </Form>
      ),
    });
  }

  return (
    <div>
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} />
      </Card>
    </div>
  );
}
