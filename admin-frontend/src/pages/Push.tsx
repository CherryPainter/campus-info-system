/**
 * 自定义推送管理页面
 */
import { useState, useEffect } from 'react';
import { Card, Button, Space, Tag, Modal, Form, Input, Select, DatePicker, Popconfirm, Upload, InputNumber, Alert, App } from 'antd';
import ResponsiveTable from '@/components/ResponsiveTable';
import { PlusOutlined, SendOutlined, DeleteOutlined, EditOutlined, CloseOutlined, PictureOutlined, FileTextOutlined, AppstoreOutlined, UploadOutlined } from '@ant-design/icons';
import { pushApi, type CustomPush, type PushTemplate } from '@/api/admin';
import { PUSH_STATUS_MAP } from '@/constants/statusMaps';
import dayjs from 'dayjs';
import { formatTimeShort } from '@/utils/datetime';

const { TextArea } = Input;
const { Option } = Select;

// 推送类型定义
type PushType = 'immediate' | 'scheduled' | 'recurring';
// 消息类型定义
type MsgType = 'text' | 'image' | 'template';

export default function Push() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [pushes, setPushes] = useState<CustomPush[]>([]);
  const [pagination, setPagination] = useState({ total: 0, page: 1, per_page: 20, pages: 0 });
  const [modalVisible, setModalVisible] = useState(false);
  const [editingPush, setEditingPush] = useState<CustomPush | null>(null);
  const [form] = Form.useForm();
  const [pushType, setPushType] = useState<PushType>('immediate');
  const [msgType, setMsgType] = useState<MsgType>('text');
  const [templates, setTemplates] = useState<PushTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<PushTemplate | null>(null);

  const fetchPushes = async (page = 1) => {
    setLoading(true);
    try {
      const res = await pushApi.getList({ page, per_page: 20 });
      setPushes(res.data);
      setPagination(res.pagination);
    } catch (error) {
      message.error('获取推送列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchTemplates = async () => {
    try {
      const res = await pushApi.getTemplates();
      if (res.status === 'success' && res.data) {
        setTemplates(res.data);
      }
    } catch (error) {
      console.error('获取模板列表失败:', error);
    }
  };

  useEffect(() => {
    fetchPushes();
    fetchTemplates();
  }, []);

  const handleAdd = () => {
    setEditingPush(null);
    form.resetFields();
    form.setFieldsValue({ push_type: 'immediate', msg_type: 'text' });
    setPushType('immediate');
    setMsgType('text');
    setSelectedTemplate(null);
    setModalVisible(true);
  };

  const handleEdit = (push: CustomPush) => {
    setEditingPush(push);
    const type = (push.push_type as PushType) || 'immediate';
    const msg = (push.msg_type as MsgType) || 'text';
    form.setFieldsValue({
      title: push.title,
      content: push.content,
      msg_type: msg,
      image_path: push.image_path,
      template_id: push.template_id,
      push_type: type,
      scheduled_time: push.scheduled_time ? dayjs(push.scheduled_time) : undefined,
      cron_expression: push.cron_expression,
    });
    setPushType(type);
    setMsgType(msg);

    // 设置模板参数
    if (msg === 'template' && push.template_id) {
      const tpl = templates.find(t => t.id === push.template_id);
      setSelectedTemplate(tpl || null);
      if (push.template_params) {
        try {
          const params = JSON.parse(push.template_params);
          form.setFieldsValue({ template_params: params });
        } catch (e) {}
      }
    }

    setModalVisible(true);
  };

  const handleSave = async (values: any) => {
    try {
      // 根据推送类型清理不需要的字段
      const data: any = {
        title: values.title,
        msg_type: values.msg_type,
        push_type: values.push_type,
      };

      // 消息内容
      if (values.msg_type === 'text') {
        data.content = values.content;
      } else if (values.msg_type === 'image') {
        data.image_path = values.image_path;
      } else if (values.msg_type === 'template') {
        data.template_id = values.template_id;
        data.template_params = values.template_params;
      }

      // 推送时间
      if (values.push_type === 'scheduled') {
        data.scheduled_time = values.scheduled_time?.toISOString();
      } else if (values.push_type === 'recurring') {
        data.cron_expression = values.cron_expression;
      }

      if (editingPush) {
        await pushApi.update(editingPush.id, data);
        message.success('推送更新成功');
      } else {
        await pushApi.create(data);
        message.success('推送创建成功');
      }
      setModalVisible(false);
      fetchPushes(pagination.page);
    } catch (error) {
      message.error('保存失败');
    }
  };

  // 处理推送类型变化
  const handlePushTypeChange = (value: PushType) => {
    setPushType(value);
    if (value === 'immediate') {
      form.setFieldsValue({ scheduled_time: undefined, cron_expression: undefined });
    } else if (value === 'scheduled') {
      form.setFieldsValue({ cron_expression: undefined });
    } else if (value === 'recurring') {
      form.setFieldsValue({ scheduled_time: undefined });
    }
  };

  // 处理消息类型变化
  const handleMsgTypeChange = (value: MsgType) => {
    setMsgType(value);
    form.setFieldsValue({
      content: undefined,
      image_path: undefined,
      template_id: undefined,
      template_params: undefined,
    });
    setSelectedTemplate(null);
  };

  // 处理模板选择
  const handleTemplateChange = (templateId: string) => {
    const tpl = templates.find(t => t.id === templateId);
    setSelectedTemplate(tpl || null);
    if (tpl) {
      // 初始化模板参数
      const initialParams: Record<string, string> = {};
      tpl.params.forEach(p => {
        initialParams[p] = tpl.example[p] || '';
      });
      form.setFieldsValue({ template_params: initialParams });
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await pushApi.delete(id);
      message.success('推送已删除');
      fetchPushes(pagination.page);
    } catch (error) {
      message.error('删除失败');
    }
  };

  const handleSend = async (id: number) => {
    try {
      await pushApi.send(id);
      message.success('推送发送成功');
      fetchPushes(pagination.page);
    } catch (error) {
      message.error('发送失败');
    }
  };

  const handleCancel = async (id: number) => {
    try {
      await pushApi.cancel(id);
      message.success('推送已取消');
      fetchPushes(pagination.page);
    } catch (error) {
      message.error('取消失败');
    }
  };

  const statusMap = PUSH_STATUS_MAP;

  const typeMap: Record<string, { color: string; text: string }> = {
    immediate: { color: 'blue', text: '立即推送' },
    scheduled: { color: 'purple', text: '定时推送' },
    recurring: { color: 'cyan', text: '周期推送' },
  };

  const msgTypeMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
    text: { color: 'geekblue', text: '文本', icon: <FileTextOutlined /> },
    image: { color: 'magenta', text: '图片', icon: <PictureOutlined /> },
    template: { color: 'volcano', text: '模板', icon: <AppstoreOutlined /> },
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '标题', dataIndex: 'title', key: 'title', width: 180 },
    {
      title: '消息类型',
      dataIndex: 'msg_type',
      key: 'msg_type',
      width: 90,
      render: (type: MsgType) => (
        <Tag color={msgTypeMap[type]?.color} icon={msgTypeMap[type]?.icon}>
          {msgTypeMap[type]?.text}
        </Tag>
      ),
    },
    {
      title: '内容预览',
      key: 'preview',
      ellipsis: true,
      render: (_: any, record: CustomPush) => {
        if (record.msg_type === 'text') {
          return record.content?.slice(0, 40) + (record.content && record.content.length > 40 ? '...' : '');
        } else if (record.msg_type === 'image') {
          return <Tag icon={<PictureOutlined />}>图片</Tag>;
        } else {
          const tpl = templates.find(t => t.id === record.template_id);
          return <Tag icon={<AppstoreOutlined />}>{tpl?.name || record.template_id}</Tag>;
        }
      },
    },
    {
      title: '推送类型',
      dataIndex: 'push_type',
      key: 'push_type',
      width: 100,
      render: (type: string) => <Tag color={typeMap[type]?.color}>{typeMap[type]?.text || type}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => <Tag color={statusMap[status]?.color}>{statusMap[status]?.text || status}</Tag>,
    },
    {
      title: '定时时间',
      dataIndex: 'scheduled_time',
      key: 'scheduled_time',
      width: 140,
      render: (time: string) => time ? formatTimeShort(time) : '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (time: string) => formatTimeShort(time),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: any, record: CustomPush) => (
        <Space size="small">
          {record.status === 'pending' && (
            <>
              <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handleSend(record.id)}>发送</Button>
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
              <Button type="link" size="small" icon={<CloseOutlined />} onClick={() => handleCancel(record.id)}>取消</Button>
            </>
          )}
          {record.status === 'failed' && (
            <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handleSend(record.id)}>重试</Button>
          )}
          <Popconfirm title="确定删除吗？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="自定义推送"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新建推送</Button>
        }
      >
        <ResponsiveTable
          dataSource={pushes}
          columns={columns}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1000 }}
          pagination={{
            current: pagination.page,
            pageSize: pagination.per_page,
            total: pagination.total,
            onChange: (page) => fetchPushes(page),
          }}
        />
      </Card>

      <Modal
        title={editingPush ? '编辑推送' : '新建推送'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={() => form.submit()}
        width={650}
      >
        <Form form={form} layout="vertical" onFinish={handleSave}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="推送标题" maxLength={100} />
          </Form.Item>

          {/* 消息类型选择 */}
          <Form.Item name="msg_type" label="消息类型" rules={[{ required: true }]}>
            <Select onChange={handleMsgTypeChange}>
              <Option value="text">
                <Space><FileTextOutlined />文本消息</Space>
              </Option>
              <Option value="image">
                <Space><PictureOutlined />图片消息</Space>
              </Option>
              <Option value="template">
                <Space><AppstoreOutlined />模板消息</Space>
              </Option>
            </Select>
          </Form.Item>

          {/* 文本消息：内容输入 */}
          {msgType === 'text' && (
            <Form.Item name="content" label="推送内容" rules={[{ required: true, message: '请输入内容' }]}>
              <TextArea rows={5} placeholder="支持Markdown格式&#10;例如：**加粗**、*斜体*、[链接](url)" />
            </Form.Item>
          )}

          {/* 图片消息：图片路径输入 */}
          {msgType === 'image' && (
            <>
              <Form.Item
                name="image_path"
                label="图片路径"
                rules={[{ required: true, message: '请输入图片路径' }]}
                extra="输入服务器上的图片路径，如：data/electricity/charts/chart.png"
              >
                <Input placeholder="data/electricity/charts/chart.png" />
              </Form.Item>
              <Alert
                message="提示：图片需要先上传到服务器"
                description="请将图片放置在项目 data 目录下，然后填写相对路径。"
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
              />
            </>
          )}

          {/* 模板消息：模板选择和参数填写 */}
          {msgType === 'template' && (
            <>
              <Form.Item name="template_id" label="选择模板" rules={[{ required: true, message: '请选择模板' }]}>
                <Select placeholder="选择内置模板" onChange={handleTemplateChange}>
                  {templates.map(tpl => (
                    <Option key={tpl.id} value={tpl.id}>
                      {tpl.name} - {tpl.description}
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              {selectedTemplate && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontWeight: 500, marginBottom: 8 }}>模板参数</div>
                  {selectedTemplate.params.map(param => (
                    <Form.Item
                      key={param}
                      name={['template_params', param]}
                      label={param}
                      rules={[{ required: true, message: `请输入${param}` }]}
                    >
                      <Input placeholder={selectedTemplate.example[param] || `输入${param}`} />
                    </Form.Item>
                  ))}
                </div>
              )}
            </>
          )}

          {/* 推送类型选择 */}
          <Form.Item name="push_type" label="推送类型" rules={[{ required: true }]}>
            <Select onChange={handlePushTypeChange}>
              <Option value="immediate">立即推送</Option>
              <Option value="scheduled">定时推送（单次）</Option>
              <Option value="recurring">周期推送（重复）</Option>
            </Select>
          </Form.Item>

          {/* 定时推送：显示定时时间选择器 */}
          {pushType === 'scheduled' && (
            <Form.Item
              name="scheduled_time"
              label="定时时间"
              rules={[{ required: true, message: '请选择推送时间' }]}
            >
              <DatePicker
                showTime
                style={{ width: '100%' }}
                format="YYYY-MM-DD HH:mm"
                placeholder="选择推送时间"
                disabledDate={(current) => current && current < dayjs().startOf('day')}
              />
            </Form.Item>
          )}

          {/* 周期推送：显示Cron表达式输入 */}
          {pushType === 'recurring' && (
            <>
              <Form.Item
                name="cron_expression"
                label="Cron表达式"
                rules={[
                  { required: true, message: '请输入Cron表达式' },
                  { pattern: /^[\d*,/-\s]+$/, message: 'Cron表达式格式不正确' }
                ]}
              >
                <Input placeholder="0 8 * * *" />
              </Form.Item>
              <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', borderRadius: 4, border: '1px solid #b7eb8f' }}>
                <div style={{ fontWeight: 500, marginBottom: 8, color: '#52c41a' }}>常用Cron表达式示例：</div>
                <div style={{ fontSize: 13, lineHeight: '1.8' }}>
                  <div><code>0 8 * * *</code> - 每天8:00</div>
                  <div><code>0 9 * * 1</code> - 每周一9:00</div>
                  <div><code>0 0 1 * *</code> - 每月1日0:00</div>
                  <div><code>0 */6 * * *</code> - 每6小时一次</div>
                </div>
              </div>
            </>
          )}
        </Form>
      </Modal>
    </div>
  );
}
