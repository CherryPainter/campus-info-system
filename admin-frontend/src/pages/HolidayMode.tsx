/**
 * 假期模式页面
 *
 * 功能：
 * - 总开关：开启后，落在「假期静默区间」内的日期全体面向用户的推送自动静默
 * - 实时状态横幅：未开启 / 已开启·非假期 / 静默中
 * - 假期区间表格：新增 / 编辑 / 删除 / 启用停用
 */
import { useState, useEffect } from "react";
import {
  Card,
  Button,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Popconfirm,
  Alert,
  Typography,
  DatePicker,
} from "antd";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  CalendarOutlined,
  StopOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { holidayApi, type HolidayPeriod, type HolidayStatus } from "@/api/holiday";
import dayjs from "dayjs";
import { useMessage } from "@/utils/message";

const { RangePicker } = DatePicker;
const { Text, Paragraph, Title } = Typography;

const TYPE_MAP: Record<string, { label: string; color: string }> = {
  winter: { label: "寒假", color: "blue" },
  summer: { label: "暑假", color: "orange" },
  custom: { label: "自定义", color: "default" },
};

export default function HolidayMode() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<HolidayStatus | null>(null);
  const [periods, setPeriods] = useState<HolidayPeriod[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editing, setEditing] = useState<HolidayPeriod | null>(null);
  const [form] = Form.useForm();
  const [masterLoading, setMasterLoading] = useState(false);
  const message = useMessage();

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [sRes, pRes] = await Promise.all([holidayApi.getStatus(), holidayApi.list()]);
      if (sRes.status === "success" && sRes.data) setStatus(sRes.data);
      if (pRes.status === "success" && pRes.data) setPeriods(pRes.data as any);
    } catch (error) {
      message.error("加载假期模式数据失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const handleToggleMaster = async (checked: boolean) => {
    setMasterLoading(true);
    try {
      const res = await holidayApi.setMaster(checked);
      if (res.status === "success") {
        message.success(checked ? "假期模式已开启" : "假期模式已关闭");
        setStatus((prev) => (prev ? { ...prev, enabled: checked } : prev));
      }
    } catch (error) {
      message.error("切换总开关失败");
    } finally {
      setMasterLoading(false);
    }
  };

  const handleAdd = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ holiday_type: "summer", enabled: true });
    setIsModalOpen(true);
  };

  const handleEdit = (record: HolidayPeriod) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      holiday_type: record.holiday_type,
      dates: [dayjs(record.start_date), dayjs(record.end_date)],
      enabled: record.enabled,
      note: record.note || "",
    });
    setIsModalOpen(true);
  };

  const handleSave = async (values: any) => {
    try {
      const [start, end] = values.dates;
      const data = {
        name: values.name?.trim(),
        holiday_type: values.holiday_type,
        start_date: start.format("YYYY-MM-DD"),
        end_date: end.format("YYYY-MM-DD"),
        enabled: values.enabled,
        note: (values.note || "").trim() || undefined,
      };
      const res = editing
        ? await holidayApi.update(editing.id, data)
        : await holidayApi.create(data);
      if (res.status === "success") {
        message.success(editing ? "假期区间已更新" : "假期区间已创建");
        setIsModalOpen(false);
        fetchAll();
      }
    } catch (error) {
      message.error("保存失败");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await holidayApi.remove(id);
      if (res.status === "success") {
        message.success("假期区间已删除");
        fetchAll();
      }
    } catch (error) {
      message.error("删除失败");
    }
  };

  const handleToggleEnabled = async (record: HolidayPeriod) => {
    try {
      const res = await holidayApi.update(record.id, { enabled: !record.enabled });
      if (res.status === "success") {
        message.success(record.enabled ? "已停用" : "已启用");
        fetchAll();
      }
    } catch (error) {
      message.error("操作失败");
    }
  };

  const columns = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      width: 160,
      render: (text: string) => <span style={{ fontWeight: 500 }}>{text}</span>,
    },
    {
      title: "类型",
      dataIndex: "holiday_type",
      key: "holiday_type",
      width: 100,
      render: (t: string) => {
        const meta = TYPE_MAP[t] || { label: t, color: "default" };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "开始",
      dataIndex: "start_date",
      key: "start_date",
      width: 120,
    },
    {
      title: "结束",
      dataIndex: "end_date",
      key: "end_date",
      width: 120,
    },
    {
      title: "状态",
      dataIndex: "enabled",
      key: "enabled",
      width: 90,
      render: (enabled: boolean, record: HolidayPeriod) => (
        <Space>
          <Switch size="small" checked={enabled} onChange={() => handleToggleEnabled(record)} />
          <span style={{ color: enabled ? "#52c41a" : "#999" }}>{enabled ? "启用" : "停用"}</span>
        </Space>
      ),
    },
    {
      title: "备注",
      dataIndex: "note",
      key: "note",
      width: 160,
      ellipsis: true,
      render: (note: string | null) => note || <span style={{ color: "#999" }}>-</span>,
    },
    {
      title: "操作",
      key: "action",
      width: 150,
      render: (_: any, record: HolidayPeriod) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定删除该假期区间？"
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

  let banner: React.ReactNode = null;
  if (status) {
    if (!status.enabled) {
      banner = (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="假期模式未开启"
          description="开启后，落在假期区间内的日期将自动静默全体面向用户的推送。"
        />
      );
    } else if (status.active && status.period) {
      banner = (
        <Alert
          type="warning"
          showIcon
          icon={<StopOutlined />}
          message={`静默中：${status.period.name}（${status.period.start_date} ~ ${status.period.end_date}）`}
          description="当前处于假期区间内，全体面向用户的推送已自动静默（系统/安全告警不受影响）。"
        />
      );
    } else {
      banner = (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message="假期模式已开启 · 当前非假期"
          description="未命中任何假期区间，推送照常进行。"
        />
      );
    }
  }

  return (
    <div>
      <Card
        title={
          <Space>
            <CalendarOutlined />
            <span>假期模式</span>
          </Space>
        }
        extra={
          <Space>
            <Text type="secondary">总开关</Text>
            <Switch
              loading={masterLoading}
              checked={status?.enabled || false}
              onChange={handleToggleMaster}
              checkedChildren="开启"
              unCheckedChildren="关闭"
            />
            <Button icon={<ReloadOutlined />} onClick={fetchAll}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
              新增区间
            </Button>
          </Space>
        }
      >
        {banner && <div style={{ marginBottom: 16 }}>{banner}</div>}

        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          style={{ marginBottom: 16 }}
          message="说明"
          description={
            <div>
              <p>• 总开关关闭时，假期区间完全不生效（避免误配导致永久失声）。</p>
              <p>• 总开关开启且今天落在某「启用」区间内时，全体面向用户的推送自动静默。</p>
              <p>• 系统/安全告警（如爬虫失败、IP 安全事件）不受假期模式影响，仍会发送。</p>
              <p>• 修改即时生效，无需重启服务。</p>
            </div>
          }
        />

        <ResponsiveTable
          dataSource={periods}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={false}
          scroll={{ x: 800 }}
        />
      </Card>

      <Modal
        title={editing ? "编辑假期区间" : "新增假期区间"}
        open={isModalOpen}
        onOk={form.submit}
        onCancel={() => setIsModalOpen(false)}
        width={560}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          initialValues={{ holiday_type: "summer", enabled: true }}
        >
          <Form.Item
            name="name"
            label="假期名称"
            rules={[{ required: true, message: "请输入假期名称" }]}
          >
            <Input placeholder="如：2026年暑假" />
          </Form.Item>

          <Form.Item
            name="holiday_type"
            label="假期类型"
            rules={[{ required: true, message: "请选择假期类型" }]}
          >
            <Select>
              <Select.Option value="winter">寒假</Select.Option>
              <Select.Option value="summer">暑假</Select.Option>
              <Select.Option value="custom">自定义</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="dates"
            label="静默日期区间"
            rules={[{ required: true, message: "请选择开始与结束日期" }]}
          >
            <RangePicker style={{ width: "100%" }} />
          </Form.Item>

          <Form.Item name="enabled" label="是否启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>

          <Form.Item name="note" label="备注（可选）">
            <Input.TextArea rows={2} placeholder="可选备注" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
