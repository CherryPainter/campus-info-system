/**
 * 近期提醒管理页面
 *
 * 功能：
 * - 列表（分页 / 分类 / 关键词 / 仅启用筛选）
 * - 新建 / 编辑 / 删除
 * - 启停（控制是否出现在小程序时间轴「近期提醒」卡片）
 *
 * 数据归属：小程序时间轴「近期提醒」卡片的后台定义，经 /api/miniapp/notifications/upcoming 供学生端读取。
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
  Table,
  DatePicker,
  InputNumber,
  Grid,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  PoweroffOutlined,
} from "@ant-design/icons";
import {
  notificationApi,
  NOTIFICATION_CATEGORY_OPTIONS,
  type NotificationItem,
  type NotificationCategory,
} from "@/api/admin";
import dayjs from "dayjs";
import { useMessage } from "@/utils/message";

const { TextArea } = Input;

const catMap: Record<NotificationCategory, { label: string; color: string }> = {
  exam: { label: "考试", color: "red" },
  holiday: { label: "节假日", color: "blue" },
  activity: { label: "活动", color: "green" },
  other: { label: "其他", color: "default" },
};

export default function Notifications({
  embedded = false,
  registerCreate,
}: {
  embedded?: boolean;
  /** 嵌入模式下把「打开新建弹窗」注册给宿主：新建按钮挂在宿主的卡片 extra 上
      （与页面其它 Tab 位置一致），而弹窗状态在本组件内，故用注册回调交付动作。
      宿主卸载时传 null 注销。 */
  registerCreate?: (fn: (() => void) | null) => void;
}) {
  const [loading, setLoading] = useState(false);
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const message = useMessage();

  // 列表与筛选
  const [list, setList] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [keyword, setKeyword] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [filterCategory, setFilterCategory] = useState<NotificationCategory | "">("");
  const [filterActive, setFilterActive] = useState<"" | "true" | "false">("");

  // 弹窗与表单
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const isEdit = editingId !== null;

  const fetchList = async () => {
    setLoading(true);
    try {
      const res = await notificationApi.getList({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        category: filterCategory || undefined,
        active: filterActive || undefined,
      });
      if (res.status === "success") {
        setList(res.data || []);
        setTotal(res.pagination?.total ?? 0);
      } else {
        message.error(res.message || "加载列表失败");
      }
    } catch {
      message.error("加载列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, keyword, filterCategory, filterActive]);

  // ==================== 筛选 ====================
  const handleSearch = () => {
    setPage(1);
    setKeyword(keywordInput.trim());
  };

  // ==================== 弹窗 ====================
  const openCreate = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({
      category: "other",
      remind_days: 30,
      sort_order: 0,
      is_active: true,
      event_date: dayjs().add(7, "day").startOf("day"),
    });
    setModalOpen(true);
  };

  // 把「打开新建弹窗」注册给宿主（仅嵌入模式）。openCreate 内部只调用稳定的
  // setState 与 form 实例，注册一次即可，故不把 openCreate 放进依赖。
  useEffect(() => {
    if (!embedded || !registerCreate) return;
    registerCreate(openCreate);
    return () => registerCreate(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embedded, registerCreate]);

  const openEdit = async (record: NotificationItem) => {
    setEditingId(record.id);
    form.resetFields();
    form.setFieldsValue({
      title: record.title,
      category: record.category,
      event_date: dayjs(record.event_date),
      remind_days: record.remind_days,
      sort_order: record.sort_order,
      is_active: record.is_active,
      description: record.description || "",
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    let values: any;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const payload = {
      title: (values.title || "").trim(),
      category: values.category || "other",
      event_date: values.event_date
        ? dayjs(values.event_date).format("YYYY-MM-DDTHH:mm:ss")
        : undefined,
      remind_days: Number(values.remind_days ?? 30),
      sort_order: Number(values.sort_order ?? 0),
      is_active: !!values.is_active,
      description: (values.description || "").trim() || undefined,
    };
    if (!payload.event_date) {
      message.error("请选择事件日期");
      return;
    }

    setSaving(true);
    try {
      const res = isEdit
        ? await notificationApi.update(editingId as number, payload)
        : await notificationApi.create(payload);
      if (res.status === "success") {
        message.success(isEdit ? "已更新" : "已创建");
        setModalOpen(false);
        fetchList();
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
      const res = await notificationApi.remove(id);
      if (res.status === "success") {
        message.success("已删除");
        fetchList();
      } else {
        message.error(res.message || "删除失败");
      }
    } catch {
      message.error("删除失败");
    }
  };

  const handleToggle = async (record: NotificationItem) => {
    try {
      const res = await notificationApi.toggle(record.id);
      if (res.status === "success") {
        message.success(res.data?.is_active ? "已启用" : "已停用");
        fetchList();
      } else {
        message.error(res.message || "操作失败");
      }
    } catch {
      message.error("操作失败");
    }
  };

  // ==================== 表格 ====================
  const columns: ColumnsType<NotificationItem> = [
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      ellipsis: true,
      render: (text: string, record) => (
        <div>
          <div style={{ fontWeight: 500 }}>{text}</div>
          {record.description && (
            <div style={{ fontSize: 12, color: "#999", marginTop: 2 }}>{record.description}</div>
          )}
        </div>
      ),
    },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      width: 80,
      filters: undefined,
      render: (cat: NotificationCategory) => (
        <Tag color={catMap[cat]?.color}>{catMap[cat]?.label || cat}</Tag>
      ),
    },
    {
      title: "事件日期",
      dataIndex: "event_date_label",
      key: "event_date_label",
      width: 110,
      render: (label: string, record) => (
        <div>
          <div>{label}</div>
          <div style={{ fontSize: 12, color: record.is_expired ? "#cf1322" : "#999" }}>
            {record.is_expired
              ? `已过期 ${Math.abs(record.days_left)} 天`
              : `还剩 ${record.days_left} 天`}
          </div>
        </div>
      ),
    },
    {
      title: "提前提醒",
      dataIndex: "remind_days",
      key: "remind_days",
      width: 80,
      render: (d: number) => `${d} 天`,
    },
    {
      title: "排序",
      dataIndex: "sort_order",
      key: "sort_order",
      width: 65,
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 80,
      render: (active: boolean) =>
        active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: "操作",
      key: "action",
      width: 180,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={<PoweroffOutlined />}
            onClick={() => handleToggle(record)}
          >
            {record.is_active ? "停用" : "启用"}
          </Button>
          <Popconfirm
            title="确认删除该提醒？"
            description="删除后小程序时间轴将不再展示"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => handleDelete(record.id)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ==================== 内容 ====================
  // 筛选栏 + 表格，embedded 模式下不包外层 Card（由消息中心 Tab 承载）
  const listContent = (
    <>
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索标题"
          allowClear
          value={keywordInput}
          onChange={(e) => setKeywordInput(e.target.value)}
          onSearch={handleSearch}
          style={{ width: 220 }}
        />
        <Select
          placeholder="全部分类"
          allowClear
          style={{ width: 140 }}
          value={filterCategory || undefined}
          onChange={(v) => {
            setPage(1);
            setFilterCategory(v || "");
          }}
          options={NOTIFICATION_CATEGORY_OPTIONS}
        />
        <Select
          placeholder="全部状态"
          allowClear
          style={{ width: 140 }}
          value={filterActive || undefined}
          onChange={(v) => {
            setPage(1);
            setFilterActive((v as "" | "true" | "false") || "");
          }}
          options={[
            { label: "仅启用", value: "true" },
            { label: "仅停用", value: "false" },
          ]}
        />
      </Space>

      <Table<NotificationItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={list}
        scroll={{ x: "max-content" }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
    </>
  );

  return (
    <>
      {embedded ? (
        <div>{listContent}</div>
      ) : (
        <div style={{ padding: isMobile ? 12 : 24 }}>
          <Card
            title="近期提醒管理"
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                新建提醒
              </Button>
            }
          >
            {listContent}
          </Card>
        </div>
      )}

      <Modal
        title={isEdit ? "编辑提醒" : "新建提醒"}
        open={modalOpen}
        onOk={handleSubmit}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={560}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            label="标题"
            name="title"
            rules={[{ required: true, message: "请输入标题" }]}
          >
            <Input placeholder="如：英语四级考试报名截止" maxLength={200} />
          </Form.Item>
          <Form.Item label="分类" name="category" rules={[{ required: true }]}>
            <Select options={NOTIFICATION_CATEGORY_OPTIONS} />
          </Form.Item>
          <Form.Item
            label="事件日期"
            name="event_date"
            rules={[{ required: true, message: "请选择事件日期" }]}
          >
            <DatePicker
              showTime
              format="YYYY-MM-DD HH:mm"
              placeholder="选择事件发生时间"
              style={{ width: "100%" }}
            />
          </Form.Item>
          <Space size="large" style={{ display: "flex" }}>
            <Form.Item label="提前提醒天数" name="remind_days" rules={[{ required: true }]}>
              <InputNumber min={0} max={365} style={{ width: 160 }} addonAfter="天" />
            </Form.Item>
            <Form.Item label="排序" name="sort_order" rules={[{ required: true }]}>
              <InputNumber min={0} max={9999} style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item label="描述" name="description">
            <TextArea rows={3} maxLength={500} placeholder="可选，补充说明" />
          </Form.Item>
          <Form.Item label="启用" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
