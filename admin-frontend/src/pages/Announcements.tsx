/**
 * 校园通知（公告）管理页面
 *
 * 功能：
 * - 公告列表（分页 / 状态 / 分类 / 关键词筛选）
 * - 新建 / 编辑 / 删除
 * - 发布 / 撤回（学生端即时可见 / 不可见）
 * - 附件上传与删除（文档 / 图片 / 压缩包，单文件 ≤ 20MB）
 * - 阅读数 / 附件数统计展示
 *
 * 送达方式：纯拉取（小程序侧主动请求），本页面不涉及任何推送动作。
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
  Upload,
  Grid,
  Tooltip,
  Alert,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  UploadOutlined,
  RollbackOutlined,
  SendOutlined,
  PushpinOutlined,
  FileOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import {
  announcementApi,
  CATEGORY_OPTIONS,
  CHANNEL_OPTIONS,
  STATUS_OPTIONS,
  type AnnouncementListItem,
  type AnnouncementAttachment,
  type AnnouncementCategory,
  type AnnouncementStatus,
  type AnnouncementPayload,
} from "@/api/announcement";
import dayjs from "dayjs";
import { useMessage } from "@/utils/message";

const { Option } = Select;
const { TextArea } = Input;

const catMap: Record<string, { label: string; color: string }> = Object.fromEntries(
  CATEGORY_OPTIONS.map((c) => [c.value, c])
);
const statusMap: Record<string, { label: string; color: string }> = Object.fromEntries(
  STATUS_OPTIONS.map((s) => [s.value, s])
);

export default function Announcements() {
  const [loading, setLoading] = useState(false);
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const message = useMessage();

  // 列表与筛选
  const [list, setList] = useState<AnnouncementListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [keyword, setKeyword] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [filterCategory, setFilterCategory] = useState<AnnouncementCategory | "">("");
  const [filterStatus, setFilterStatus] = useState<AnnouncementStatus | "">("");

  // 弹窗与表单
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [currentStatus, setCurrentStatus] = useState<AnnouncementStatus>("draft");
  const [attachments, setAttachments] = useState<AnnouncementAttachment[]>([]);
  const [saving, setSaving] = useState(false);
  const [acting, setActing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [coverUrl, setCoverUrl] = useState<string>("");
  const [form] = Form.useForm();

  const isEdit = editingId !== null;

  const fetchList = async () => {
    setLoading(true);
    try {
      const res = await announcementApi.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        category: filterCategory || undefined,
        status: filterStatus || undefined,
      });
      if (res.status === "success") {
        setList((res.data as AnnouncementListItem[]) || []);
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
  }, [page, pageSize, keyword, filterCategory, filterStatus]);

  // ==================== 筛选 ====================
  const handleSearch = () => {
    setPage(1);
    setKeyword(keywordInput.trim());
  };

  const handleCategoryChange = (value: AnnouncementCategory | "") => {
    setPage(1);
    setFilterCategory(value);
  };

  const handleStatusChange = (value: AnnouncementStatus | "") => {
    setPage(1);
    setFilterStatus(value);
  };

  // ==================== 弹窗 ====================
  const buildPayload = (): AnnouncementPayload => {
    const values = form.getFieldsValue();
    return {
      title: (values.title || "").trim(),
      category: values.category || "notice",
      department: (values.department || "").trim(),
      channel: (values.channel || "").trim(),
      is_top: !!values.is_top,
      content: values.content || "",
      summary: (values.summary || "").trim(),
      expired_at: values.expired_at ? dayjs(values.expired_at).format("YYYY-MM-DD HH:mm:ss") : null,
      cover_url: coverUrl || null,
    };
  };

  const openCreate = () => {
    setEditingId(null);
    setCurrentStatus("draft");
    setAttachments([]);
    setCoverUrl("");
    form.resetFields();
    form.setFieldsValue({ category: "notice", is_top: false });
    setModalOpen(true);
  };

  const openEdit = async (record: AnnouncementListItem) => {
    setEditingId(record.id);
    setCurrentStatus(record.status);
    form.resetFields();
    form.setFieldsValue({
      category: "notice",
      is_top: false,
    });
    setModalOpen(true);
    try {
      const res = await announcementApi.detail(record.id);
      if (res.status === "success" && res.data) {
        const d = res.data;
        form.setFieldsValue({
          title: d.title,
          category: d.category,
          department: d.department || "",
          channel: d.channel || "",
          is_top: d.is_top,
          content: d.content || "",
          summary: d.summary || "",
          expired_at: d.expired_at ? dayjs(d.expired_at) : null,
        });
        setAttachments(d.attachments || []);
        setCoverUrl(d.cover_url || "");
      } else {
        message.error(res.message || "加载详情失败");
      }
    } catch {
      message.error("加载详情失败");
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingId(null);
    setAttachments([]);
    setCoverUrl("");
    form.resetFields();
  };

  // ==================== 增删改 / 发布 ====================
  const handleCreate = async (publishNow: boolean) => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const payload = buildPayload();
      payload.publish = publishNow;
      const res = await announcementApi.create(payload);
      if (res.status === "success" && res.data) {
        message.success(publishNow ? "已创建并发布" : "已保存草稿");
        // 保留在编辑态，方便继续补充附件 / 发布
        setEditingId(res.data.id);
        setCurrentStatus(res.data.status);
        setAttachments(res.data.attachments || []);
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

  const handleUpdate = async () => {
    if (editingId == null) return;
    try {
      await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const res = await announcementApi.update(editingId, buildPayload());
      if (res.status === "success") {
        message.success("已保存");
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

  const handleTogglePublish = async (publish: boolean) => {
    if (editingId == null) return;
    setActing(true);
    try {
      const res = publish
        ? await announcementApi.publish(editingId)
        : await announcementApi.withdraw(editingId);
      if (res.status === "success" && res.data) {
        message.success(publish ? "已发布" : "已撤回");
        setCurrentStatus(res.data.status);
        fetchList();
      } else {
        message.error(res.message || "操作失败");
      }
    } catch {
      message.error("操作失败");
    } finally {
      setActing(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await announcementApi.remove(id);
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

  // ==================== 附件 ====================
  const customUpload = async (options: any) => {
    const { file, onSuccess, onError } = options;
    if (editingId == null) {
      message.warning("请先保存通知后再上传附件");
      onError?.(new Error("请先保存"));
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await announcementApi.uploadAttachment(editingId, formData);
      if (res.status === "success" && res.data) {
        setAttachments((prev) => [...prev, res.data as AnnouncementAttachment]);
        message.success("附件上传成功");
        onSuccess?.(res.data);
      } else {
        message.error(res.message || "附件上传失败");
        onError?.(new Error(res.message || "附件上传失败"));
      }
    } catch {
      message.error("附件上传失败");
      onError?.(new Error("附件上传失败"));
    } finally {
      setUploading(false);
    }
  };

  // ==================== 封面 ====================
  const customUploadCover = async (options: any) => {
    const { file, onSuccess, onError } = options;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await announcementApi.uploadCover(formData);
      if (res.status === "success" && res.data?.url) {
        setCoverUrl(res.data.url);
        message.success("封面上传成功");
        onSuccess?.(res.data);
      } else {
        message.error(res.message || "封面上传失败");
        onError?.(new Error(res.message || "封面上传失败"));
      }
    } catch {
      message.error("封面上传失败");
      onError?.(new Error("封面上传失败"));
    } finally {
      setUploading(false);
    }
  };

  const removeCover = () => {
    setCoverUrl("");
  };

  const handleDeleteAttachment = async (attId: number) => {
    try {
      const res = await announcementApi.deleteAttachment(attId);
      if (res.status === "success") {
        setAttachments((prev) => prev.filter((a) => a.id !== attId));
        message.success("附件已删除");
      } else {
        message.error(res.message || "删除失败");
      }
    } catch {
      message.error("删除失败");
    }
  };

  // ==================== 表格 ====================
  const columns: ColumnsType<AnnouncementListItem> = [
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      width: 260,
      render: (text: string, record) => (
        <Space>
          {record.is_top && (
            <Tag color="gold" icon={<PushpinOutlined />}>
              置顶
            </Tag>
          )}
          <span style={{ fontWeight: 500 }}>{text}</span>
        </Space>
      ),
    },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      width: 90,
      render: (cat: string) => {
        const meta = catMap[cat] || { label: cat, color: "default" };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (st: string) => {
        const meta = statusMap[st] || { label: st, color: "default" };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "来源部门",
      dataIndex: "department",
      key: "department",
      width: 120,
      ellipsis: true,
      render: (d: string | null) => d || <span style={{ color: "#999" }}>-</span>,
    },
    {
      title: "频道",
      dataIndex: "channel",
      key: "channel",
      width: 110,
      ellipsis: true,
      render: (c: string | null) => c || <span style={{ color: "#999" }}>-</span>,
    },
    {
      title: "阅读数",
      dataIndex: "read_count",
      key: "read_count",
      width: 80,
      render: (n: number) => n ?? 0,
    },
    {
      title: "附件",
      dataIndex: "attachment_count",
      key: "attachment_count",
      width: 70,
      render: (n: number) => (
        <span>
          <FileOutlined style={{ marginRight: 4, color: "#999" }} />
          {n ?? 0}
        </span>
      ),
    },
    {
      title: "发布时间",
      dataIndex: "published_label",
      key: "published_label",
      width: 140,
      render: (t: string | null) => t || <span style={{ color: "#999" }}>未发布</span>,
    },
    {
      title: "操作",
      key: "action",
      width: 200,
      fixed: isMobile ? undefined : "right",
      render: (_: any, record) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          {record.status === "published" ? (
            <Popconfirm
              title="撤回后学生端将立即不可见，确定撤回？"
              onConfirm={() => handleTogglePublish(false)}
              okText="撤回"
              cancelText="取消"
            >
              <Button size="small" icon={<RollbackOutlined />}>
                撤回
              </Button>
            </Popconfirm>
          ) : (
            <Popconfirm
              title="发布后学生端将立即可见，确定发布？"
              onConfirm={() => handleTogglePublish(true)}
              okText="发布"
              cancelText="取消"
            >
              <Button size="small" type="primary" icon={<SendOutlined />}>
                发布
              </Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="确定删除此通知？"
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

  return (
    <div>
      <Card styles={{ body: { padding: isMobile ? 12 : 24 } }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            marginBottom: 16,
            alignItems: "center",
          }}
        >
          <Select
            placeholder="全部分类"
            allowClear
            style={{ width: 130 }}
            value={filterCategory || undefined}
            onChange={handleCategoryChange}
          >
            {CATEGORY_OPTIONS.map((c) => (
              <Option key={c.value} value={c.value}>
                {c.label}
              </Option>
            ))}
          </Select>
          <Select
            placeholder="全部状态"
            allowClear
            style={{ width: 130 }}
            value={filterStatus || undefined}
            onChange={handleStatusChange}
          >
            {STATUS_OPTIONS.map((s) => (
              <Option key={s.value} value={s.value}>
                {s.label}
              </Option>
            ))}
          </Select>
          <Input.Search
            placeholder="搜索标题"
            allowClear
            style={{ width: 220 }}
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onSearch={handleSearch}
            enterButton
          />
          <div style={{ flex: 1 }} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建通知
          </Button>
        </div>

        <Alert
          message="校园通知说明"
          description="通知采用纯拉取模式：学生端（微信小程序）在进入通知页或下拉刷新时主动获取已发布的通知，本系统不主动推送。发布后学生端立即可见，撤回后立即不可见。此外，发布时会给近 7 天新注册的学生在「我的消息」推送一条站内通知（带封面，点击跳转详情）。"
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          style={{ marginBottom: 16 }}
        />

        <Table<AnnouncementListItem>
          dataSource={list}
          columns={columns}
          rowKey="id"
          loading={loading}
          scroll={{ x: 900 }}
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
      </Card>

      <Modal
        title={isEdit ? "编辑通知" : "新建通知"}
        open={modalOpen}
        onCancel={closeModal}
        width={720}
        footer={
          isEdit ? (
            <>
              <Button onClick={closeModal}>取消</Button>
              {currentStatus === "published" ? (
                <Popconfirm
                  title="撤回后学生端将立即不可见，确定撤回？"
                  onConfirm={() => handleTogglePublish(false)}
                  okText="撤回"
                  cancelText="取消"
                >
                  <Button danger loading={acting} icon={<RollbackOutlined />}>
                    撤回
                  </Button>
                </Popconfirm>
              ) : (
                <Popconfirm
                  title="发布后学生端将立即可见，确定发布？"
                  onConfirm={() => handleTogglePublish(true)}
                  okText="发布"
                  cancelText="取消"
                >
                  <Button type="primary" loading={acting} icon={<SendOutlined />}>
                    发布
                  </Button>
                </Popconfirm>
              )}
              <Button type="primary" loading={saving} onClick={handleUpdate}>
                保存
              </Button>
            </>
          ) : (
            <>
              <Button onClick={closeModal}>取消</Button>
              <Button loading={saving} onClick={() => handleCreate(false)}>
                保存草稿
              </Button>
              <Button type="primary" loading={saving} onClick={() => handleCreate(true)}>
                保存并发布
              </Button>
            </>
          )
        }
        styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: "请输入标题" }]}
          >
            <Input placeholder="如：关于 2026 年中秋节放假安排的通知" maxLength={200} />
          </Form.Item>

          <Space size="large" wrap>
            <Form.Item name="category" label="分类" initialValue="notice">
              <Select style={{ width: 140 }}>
                {CATEGORY_OPTIONS.map((c) => (
                  <Option key={c.value} value={c.value}>
                    {c.label}
                  </Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item name="department" label="来源部门">
              <Input placeholder="如：学生处" style={{ width: 200 }} maxLength={100} />
            </Form.Item>
            <Form.Item name="channel" label="频道">
              <Select
                placeholder="如：学校要闻"
                style={{ width: 160 }}
                allowClear
                options={CHANNEL_OPTIONS.map((c) => ({ value: c.value, label: c.label }))}
              />
            </Form.Item>
            <Form.Item name="is_top" label="置顶" valuePropName="checked">
              <Switch checkedChildren="置顶" unCheckedChildren="普通" />
            </Form.Item>
          </Space>

          <Form.Item name="expired_at" label="过期时间（留空表示长期有效）">
            <DatePicker
              showTime
              format="YYYY-MM-DD HH:mm:ss"
              placeholder="选择过期时间"
              style={{ width: 240 }}
            />
          </Form.Item>

          <Form.Item name="summary" label="摘要（可选，留空则自动截取正文）">
            <Input placeholder="列表页展示的简短摘要" maxLength={300} />
          </Form.Item>

          <Form.Item
            label="封面图（可选）"
            extra="展示在公告详情页顶部与「我的消息」推送卡片。列表卡片为纯文字、不配图（留空即可）。"
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Upload
                listType="picture-card"
                showUploadList={false}
                customRequest={customUploadCover}
                accept=".jpg,.jpeg,.png,.gif,.webp"
                disabled={uploading}
              >
                {coverUrl ? (
                  <img
                    src={coverUrl}
                    alt="封面"
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                      borderRadius: 6,
                    }}
                  />
                ) : (
                  <div>
                    <PlusOutlined />
                    <div style={{ marginTop: 4 }}>上传封面</div>
                  </div>
                )}
              </Upload>
              {coverUrl && (
                <Button size="small" danger onClick={removeCover}>
                  移除
                </Button>
              )}
            </div>
          </Form.Item>

          <Form.Item name="content" label="正文">
            <TextArea rows={6} placeholder="通知正文内容" />
          </Form.Item>
        </Form>

        {isEdit && (
          <div style={{ marginTop: 8 }}>
            <DividerPlain />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 12,
              }}
            >
              <span style={{ fontWeight: 600 }}>附件（{attachments.length}）</span>
              <Upload
                multiple
                showUploadList={false}
                customRequest={customUpload}
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip,.rar,.7z,.jpg,.jpeg,.png,.gif,.webp"
              >
                <Button icon={<UploadOutlined />} loading={uploading}>
                  上传附件
                </Button>
              </Upload>
            </div>

            {attachments.length === 0 ? (
              <div style={{ color: "#999", fontSize: 13 }}>暂无附件</div>
            ) : (
              <Space direction="vertical" style={{ width: "100%" }} size={8}>
                {attachments.map((att) => (
                  <div
                    key={att.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 12px",
                      border: "1px solid #f0f0f0",
                      borderRadius: 6,
                    }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      <FileOutlined style={{ marginRight: 6, color: "#1677ff" }} />
                      <a href={att.download_url} target="_blank" rel="noreferrer">
                        {att.file_name}
                      </a>
                      <span style={{ color: "#999", marginLeft: 8 }}>{att.file_size_label}</span>
                    </span>
                    <Popconfirm
                      title="确定删除该附件？"
                      onConfirm={() => handleDeleteAttachment(att.id)}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </div>
                ))}
              </Space>
            )}
            <div style={{ color: "#999", fontSize: 12, marginTop: 8 }}>
              支持格式：pdf / doc / docx / xls / xlsx / ppt / pptx / txt / zip / rar / 7z / jpg /
              jpeg / png / gif / webp，单文件不超过 20MB。
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

/** 轻量分隔线（避免与 antd Divider 的额外 margin 冲突） */
function DividerPlain() {
  return <div style={{ height: 1, background: "#f0f0f0", margin: "4px 0 12px" }} />;
}
