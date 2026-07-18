/**
 * Webhook 管理页面
 * 
 * 功能：
 * - 查看所有 webhook
 * - 添加/编辑/删除 webhook
 * - 测试 webhook
 * - 启用/禁用 webhook
 * - 重载适配器配置
 */
import { useState, useEffect } from 'react';
import {
  Card, Button, Space, Tag, Modal, Form, Input, Select, Switch,
  Popconfirm, Tooltip, Badge, Alert, Descriptions, Divider
} from 'antd';
import ResponsiveTable from '@/components/ResponsiveTable';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SendOutlined,
  LinkOutlined, InfoCircleOutlined, CheckOutlined, StopOutlined,
  WarningOutlined
} from '@ant-design/icons';
import { webhookApi } from '@/api/admin';
import dayjs from 'dayjs';
import { WEBHOOK_TEST_STATUS_MAP } from '@/constants/statusMaps';
import { useMessage } from '@/utils/message';

const { Option } = Select;
const { TextArea } = Input;

interface Webhook {
  id: number;
  name: string;
  url: string;
  modules: string;
  module_list: string[];
  is_enabled: boolean;
  description?: string;
  last_test_status?: 'success' | 'failed' | 'pending';
  last_test_time?: string;
  created_at?: string;
  updated_at?: string;
}

const MODULE_MAP: Record<string, { label: string; color: string }> = {
  all: { label: '全局', color: 'gold' },
  course: { label: '课表', color: 'blue' },
  weather: { label: '天气', color: 'cyan' },
  electricity: { label: '电量', color: 'orange' },
  system: { label: '系统', color: 'red' },
};

// TEST_STATUS_MAP 已迁至 @/constants/statusMaps（WEBHOOK_TEST_STATUS_MAP）

export default function Webhooks() {
  const [loading, setLoading] = useState(false);
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingWebhook, setEditingWebhook] = useState<Webhook | null>(null);
  const [form] = Form.useForm();
  const [testingId, setTestingId] = useState<number | null>(null);
  const [reloading, setReloading] = useState(false);
  const message = useMessage();

  const fetchWebhooks = async () => {
    setLoading(true);
    try {
      const res = await webhookApi.getList();
      if (res.status === 'success' && res.data) {
        setWebhooks(res.data as any);
      }
    } catch (error) {
      message.error('加载 webhook 列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWebhooks();
  }, []);

  const handleAdd = () => {
    setEditingWebhook(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEdit = (record: Webhook) => {
    setEditingWebhook(record);
    form.setFieldsValue({
      name: record.name,
      url: record.url,
      modules: record.module_list || [],
      is_enabled: record.is_enabled,
      description: record.description,
    });
    setIsModalOpen(true);
  };

  const handleSave = async (values: any) => {
    try {
      // 将 modules 数组转换为逗号分隔的字符串
      const data = {
        ...values,
        modules: Array.isArray(values.modules) ? values.modules.join(',') : values.modules,
      };

      if (editingWebhook) {
        // 更新
        const res = await webhookApi.update(editingWebhook.id, data);
        if (res.status === 'success') {
          message.success('Webhook 更新成功');
          setIsModalOpen(false);
          fetchWebhooks();
        }
      } else {
        // 创建
        const res = await webhookApi.create(data);
        if (res.status === 'success') {
          message.success('Webhook 创建成功');
          setIsModalOpen(false);
          fetchWebhooks();
        }
      }
    } catch (error) {
      message.error('保存失败');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await webhookApi.delete(id);
      if (res.status === 'success') {
        message.success('Webhook 已删除');
        fetchWebhooks();
      }
    } catch (error) {
      message.error('删除失败');
    }
  };

  const handleTest = async (record: Webhook) => {
    setTestingId(record.id);
    try {
      const res = await webhookApi.test(record.id);
      if (res.status === 'success') {
        message.success('测试消息发送成功');
      } else {
        message.error(res.message || '测试失败');
      }
      fetchWebhooks();
    } catch (error) {
      message.error('测试失败');
    } finally {
      setTestingId(null);
    }
  };

  const handleToggleEnabled = async (record: Webhook) => {
    try {
      const res = await webhookApi.update(record.id, {
        is_enabled: !record.is_enabled,
      });
      if (res.status === 'success') {
        message.success(record.is_enabled ? '已禁用' : '已启用');
        fetchWebhooks();
      }
    } catch (error) {
      message.error('操作失败');
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      const res = await webhookApi.reload();
      if (res.status === 'success') {
        message.success('适配器配置已重载');
      }
    } catch (error) {
      message.error('重载失败');
    } finally {
      setReloading(false);
    }
  };

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 140,
      render: (text: string, record: Webhook) => (
        <Space>
          <span style={{ fontWeight: 500 }}>{text}</span>
          {!record.is_enabled && <Tag color="default">禁用</Tag>}
        </Space>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      width: 200,
      ellipsis: true,
      render: (url: string) => (
        <Tooltip title={url}>
          <a style={{ color: '#1677ff' }}>
            <LinkOutlined style={{ marginRight: 4 }} />
            {url.substring(0, 40)}...
          </a>
        </Tooltip>
      ),
    },
    {
      title: '模块',
      dataIndex: 'module_list',
      key: 'module_list',
      width: 120,
      render: (modules: string[]) => {
        if (!modules || modules.length === 0) return <span style={{ color: '#999' }}>-</span>;
        return (
          <Space size="small" wrap>
            {modules.map(m => {
              const meta = MODULE_MAP[m] || { label: m, color: 'default' };
              return <Tag key={m} color={meta.color}>{meta.label}</Tag>;
            })}
          </Space>
        );
      },
    },
    {
      title: '测试',
      dataIndex: 'last_test_status',
      key: 'last_test_status',
      width: 130,
      render: (status: string, record: Webhook) => {
        const isTesting = testingId === record.id;
        // 配置在「上次测试之后」被改动过（或未曾测试）→ 需重新测试
        const needsTest = !record.last_test_time
          || dayjs(record.updated_at).isAfter(dayjs(record.last_test_time));
        if (isTesting) {
          return <Badge status="processing" text="测试中" />;
        }
        if (needsTest) {
          return (
            <Tooltip title="配置已更新，建议重新发送测试以确认可用性">
              <Tag color="warning" icon={<WarningOutlined />}>须测试</Tag>
            </Tooltip>
          );
        }
        if (!status) return <span style={{ color: '#999' }}>-</span>;
        const meta = WEBHOOK_TEST_STATUS_MAP[status];
        return (
          <div style={{ whiteSpace: 'nowrap' }}>
            <Badge
              status={meta.color as any}
              text={meta.text}
            />
            {record.last_test_time && (
              <span style={{ fontSize: 11, color: '#999', marginLeft: 4 }}>
                {dayjs(record.last_test_time).format('MM-DD')}
              </span>
            )}
          </div>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: any, record: Webhook) => (
        <Space size="small">
          <Button
            size="small"
            icon={<SendOutlined />}
            loading={testingId === record.id}
            onClick={() => handleTest(record)}
          >
            测试
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Button
            size="small"
            icon={record.is_enabled ? <StopOutlined /> : <CheckOutlined />}
            onClick={() => handleToggleEnabled(record)}
          >
            {record.is_enabled ? '禁用' : '启用'}
          </Button>
          <Popconfirm
            title="确定删除此 webhook？"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const enabledCount = webhooks.filter(w => w.is_enabled).length;

  return (
    <div>
      <Card
        title={
          <Space>
            <LinkOutlined />
            <span>Webhook 管理</span>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} loading={reloading} onClick={handleReload}>
              重载配置
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
              添加 Webhook
            </Button>
          </Space>
        }
      >
        <Alert
          message="Webhook 配置说明"
          description={
            <div>
              <p>• 一个 webhook 可以属于多个模块</p>
              <p>• <b>全局</b>：接收所有推送（四合一）</p>
              <p>• <b>课表</b>：课程推送、上课提醒</p>
              <p>• <b>天气</b>：天气晨报、预警通知</p>
              <p>• <b>电量</b>：电量日报、低电量告警</p>
              <p>• <b>系统</b>：爬虫失败、系统异常告警</p>
              <p>• 修改配置后点击"重载配置"使更改生效</p>
            </div>
          }
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          style={{ marginBottom: 16 }}
        />

        <Descriptions bordered size="small" style={{ marginBottom: 16 }}>
          <Descriptions.Item label="总数量">{webhooks.length}</Descriptions.Item>
          <Descriptions.Item label="已启用">{enabledCount}</Descriptions.Item>
        </Descriptions>

        <ResponsiveTable
          dataSource={webhooks}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={false}
          scroll={{ x: 800 }}
        />
      </Card>

      <Modal
        title={editingWebhook ? '编辑 Webhook' : '添加 Webhook'}
        open={isModalOpen}
        onOk={form.submit}
        onCancel={() => setIsModalOpen(false)}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          initialValues={{ modules: ['course'], is_enabled: true }}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="如：班级群、测试群" />
          </Form.Item>

          <Form.Item
            name="url"
            label="Webhook URL"
            rules={[
              { required: true, message: '请输入 URL' },
              { pattern: /^https:/, message: 'URL 必须以 https:// 开头' },
            ]}
          >
            <Input.TextArea
              rows={2}
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
            />
          </Form.Item>

          <Form.Item
            name="modules"
            label="所属模块"
            rules={[{ required: true, message: '请选择至少一个模块' }]}
          >
            <Select mode="multiple" placeholder="选择此 webhook 接收哪些模块的消息">
              <Option value="all">全局（接收所有推送）</Option>
              <Option value="course">课表（课程推送、上课提醒）</Option>
              <Option value="weather">天气（天气晨报、预警通知）</Option>
              <Option value="electricity">电量（电量日报、低电量告警）</Option>
              <Option value="system">系统（爬虫失败、系统异常）</Option>
            </Select>
          </Form.Item>

          <Form.Item name="is_enabled" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item name="description" label="描述（可选）">
            <TextArea rows={2} placeholder="可选的描述信息" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}