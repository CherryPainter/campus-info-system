/**
 * 频道管理页面
 *
 * 管理公告「频道/栏目」受管表（announcement_channels）：
 * - 列表：名称 / 排序 / 启用状态
 * - 新增 / 编辑 / 删除 / 启停
 * 频道仅作小程序端列表顶部栏目标签用，停用后标签不再展示（公告仍可在「全部」看到）。
 */
import { useState, useEffect } from "react";
import {
  Card,
  Button,
  Space,
  Modal,
  Form,
  Input,
  InputNumber,
  Switch,
  Popconfirm,
  Typography,
} from "antd";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  AppstoreOutlined,
} from "@ant-design/icons";
import {
  announcementApi,
  type AnnouncementChannelAdmin,
} from "@/api/announcement";
import { useMessage } from "@/utils/message";

const { Text } = Typography;

export default function ChannelManage({
  embedded = false,
  registerActions,
}: {
  embedded?: boolean;
  /** 嵌入模式下把「新增频道 / 刷新」动作注册给宿主（消息中心 Tab），
      按钮挂在宿主卡片 extra 上、与页面其它 Tab 位置一致；弹窗状态仍在本组件内。
      宿主卸载时传 null 注销。 */
  registerActions?: (actions: { create: () => void; refresh: () => void } | null) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [list, setList] = useState<AnnouncementChannelAdmin[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<AnnouncementChannelAdmin | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const message = useMessage();

  const fetchAll = async () => {
    setLoading(true);
    try {
      const res = await announcementApi.channelAdmin.list();
      if (res.status === "success" && res.data) {
        setList(res.data as AnnouncementChannelAdmin[]);
      } else {
        message.error(res.message || "加载频道失败");
      }
    } catch {
      message.error("加载频道失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAdd = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, sort_order: 0 });
    setIsModalOpen(true);
  };

  const handleEdit = (record: AnnouncementChannelAdmin) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      sort_order: record.sort_order,
      is_active: record.is_active,
    });
    setIsModalOpen(true);
  };

  const handleSave = async (values: any) => {
    setSaving(true);
    try {
      const data = {
        name: (values.name || "").trim(),
        sort_order: Number(values.sort_order) || 0,
        is_active: !!values.is_active,
      };
      const res = editing
        ? await announcementApi.channelAdmin.update(editing.id, data)
        : await announcementApi.channelAdmin.create(data);
      if (res.status === "success") {
        message.success(editing ? "频道已更新" : "频道已创建");
        setIsModalOpen(false);
        fetchAll();
      } else {
        message.error(res.message || "保存失败");
      }
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await announcementApi.channelAdmin.remove(id);
      if (res.status === "success") {
        message.success("频道已删除");
        fetchAll();
      } else {
        message.error(res.message || "删除失败");
      }
    } catch {
      message.error("删除失败");
    }
  };

  const handleToggleActive = async (record: AnnouncementChannelAdmin) => {
    try {
      const res = await announcementApi.channelAdmin.update(record.id, {
        is_active: !record.is_active,
      });
      if (res.status === "success") {
        message.success(record.is_active ? "已停用" : "已启用");
        fetchAll();
      } else {
        message.error(res.message || "操作失败");
      }
    } catch {
      message.error("操作失败");
    }
  };

  // 嵌入模式：把「新增频道 / 刷新」动作注册给宿主卡片 extra
  useEffect(() => {
    if (!embedded || !registerActions) return;
    registerActions({ create: handleAdd, refresh: fetchAll });
    return () => registerActions(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embedded, registerActions]);

  const columns = [
    {
      title: "频道名称",
      dataIndex: "name",
      key: "name",
      width: 200,
      render: (text: string) => <span style={{ fontWeight: 500 }}>{text}</span>,
    },
    {
      title: "排序",
      dataIndex: "sort_order",
      key: "sort_order",
      width: 90,
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 110,
      render: (active: boolean, record: AnnouncementChannelAdmin) => (
        <Space>
          <Switch
            size="small"
            checked={active}
            onChange={() => handleToggleActive(record)}
          />
          <span style={{ color: active ? "#52c41a" : "#999" }}>
            {active ? "启用" : "停用"}
          </span>
        </Space>
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 150,
      render: (_: any, record: AnnouncementChannelAdmin) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定删除该频道？"
            description="已发布的公告仍可在「全部」中看到，仅标签页不再展示该频道。"
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

  const listContent = (
    <>
      <div style={{ marginBottom: 16, color: "#595959", fontSize: 13 }}>
        频道用于小程序端公告列表顶部的栏目标签。停用某个频道后，其标签不再展示，
        但该频道下的公告仍可在「全部」中查看。修改即时生效，无需重启服务。
      </div>

      <ResponsiveTable
        dataSource={list}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        scroll={{ x: 600 }}
        locale={{ emptyText: <Text type="secondary">暂无频道，点击右上角「新增频道」添加</Text> }}
      />
    </>
  );

  return (
    <>
      {embedded ? (
        <div>{listContent}</div>
      ) : (
        <div>
          <Card
            title={
              <Space>
                <AppstoreOutlined />
                <span>频道管理</span>
              </Space>
            }
            extra={
              <Space>
                <Button icon={<ReloadOutlined />} onClick={fetchAll}>
                  刷新
                </Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
                  新增频道
                </Button>
              </Space>
            }
          >
            {listContent}
          </Card>
        </div>
      )}

      <Modal
        title={editing ? "编辑频道" : "新增频道"}
        open={isModalOpen}
        onOk={form.submit}
        onCancel={() => setIsModalOpen(false)}
        confirmLoading={saving}
        width={520}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          initialValues={{ is_active: true, sort_order: 0 }}
        >
          <Form.Item
            name="name"
            label="频道名称"
            rules={[{ required: true, message: "请输入频道名称" }]}
          >
            <Input placeholder="如：学校要闻" maxLength={50} />
          </Form.Item>

          <Form.Item name="sort_order" label="排序（数字越小越靠前）">
            <InputNumber min={0} max={9999} style={{ width: "100%" }} />
          </Form.Item>

          <Form.Item name="is_active" label="是否启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
