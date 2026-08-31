/**
 * 消息编辑器（独立页面）
 *
 * 统一处理「校园通知」和「即时推送」的创建与编辑。
 * 路由：
 *   /messages/create?type=announcement|push  → 新建
 *   /messages/edit/:id?type=announcement|push → 编辑
 *
 * 集成 WangEditor v5 富文本编辑器（公告正文/推送内容）。
 * 公告模式：标题 + 富文本 + 分类 + 来源部门 + 置顶 + 过期时间 + 摘要 + 附件
 * 推送模式：标题 + 富文本/图片/模板 + 推送类型(即时/定时/周期) + 定时设置
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Card,
  Button,
  Space,
  Form,
  Input,
  Select,
  Switch,
  DatePicker,
  Upload,
  Alert,
  Spin,
  Row,
  Col,
  Divider,
  Popconfirm,
  Breadcrumb,
  Grid,
} from "antd";
import { message as antMessage } from "antd";
import {
  SaveOutlined,
  SendOutlined,
  RollbackOutlined,
  ArrowLeftOutlined,
  UploadOutlined,
  DeleteOutlined,
  FileOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { announcementApi, CATEGORY_OPTIONS, type AnnouncementPayload } from "@/api/announcement";
import { pushApi, type CustomPush, type PushTemplate } from "@/api/admin";
import dayjs from "dayjs";

// WangEditor v5（动态导入，避免未安装时构建失败）
let Editor: any;
let EditorToolbar: any;
let editorModulesLoaded = false;

async function loadEditorModules() {
  if (editorModulesLoaded) return true;
  try {
    const mod = await import("@wangeditor/editor-for-react");
    const core = await import("@wangeditor/editor");
    Editor = mod.default;
    EditorToolbar = core.Toolbar;
    editorModulesLoaded = true;
    return true;
  } catch {
    return false;
  }
}

const { Option } = Select;
const { TextArea } = Input;

type EditorMode = "announcement" | "push";
type PushMsgType = "text" | "image" | "template";
type PushPushType = "immediate" | "scheduled" | "recurring";

export default function MessageEditor() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // 模式判断
  const mode: EditorMode = (searchParams.get("type") as EditorMode) || "announcement";
  const isEdit = !!id;
  const isAnno = mode === "announcement";

  // 表单状态
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [initialDataLoaded, setInitialDataLoaded] = useState(false);

  // 公告特有状态
  const [currentStatus, setCurrentStatus] = useState<string>("draft");
  const [attachments, setAttachments] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);

  // 推送特有状态
  const [msgType, setMsgType] = useState<PushMsgType>("text");
  const [pushType, setPushType] = useState<PushPushType>("immediate");
  const [templates, setTemplates] = useState<PushTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<PushTemplate | null>(null);

  // 编辑器状态
  const [editorReady, setEditorReady] = useState(false);
  const [editorHtml, setEditorHtml] = useState("");

  // ==================== 加载编辑器组件 ====================

  useEffect(() => {
    loadEditorModules().then((ok) => setEditorReady(ok));
  }, []);

  // ==================== 加载初始数据（编辑模式）====================

  useEffect(() => {
    if (!isEdit) {
      setInitialDataLoaded(true);
      // 新建模式：设默认值
      form.setFieldsValue({
        category: "notice",
        is_top: false,
        push_type: "immediate",
        msg_type: "text",
      });
      return;
    }

    // 编辑模式：加载详情
    const loadDetail = async () => {
      setLoading(true);
      try {
        if (isAnno) {
          const res = await announcementApi.detail(Number(id));
          if (res.status === "success" && res.data) {
            const d = res.data;
            form.setFieldsValue({
              title: d.title,
              category: d.category || "notice",
              department: d.department || "",
              is_top: d.is_top || false,
              summary: d.summary || "",
              expired_at: d.expired_at ? dayjs(d.expired_at) : null,
            });
            setEditorHtml(d.content || "");
            setCurrentStatus(d.status);
            setAttachments(d.attachments || []);
          }
        } else {
          // 推送编辑：从列表中获取（简化：重新拉取）
          const listRes = await pushApi.getList({ page: 1, per_page: 200 });
          const target = (listRes.data || []).find((p: CustomPush) => p.id === Number(id));
          if (target) {
            form.setFieldsValue({
              title: target.title,
              msg_type: target.msg_type || "text",
              push_type: target.push_type || "immediate",
              image_path: target.image_path,
              template_id: target.template_id,
              scheduled_time: target.scheduled_time ? dayjs(target.scheduled_time) : undefined,
              cron_expression: target.cron_expression,
            });
            setMsgType(target.msg_type || "text");
            setPushType(target.push_type || "immediate");
            if (target.content) setEditorHtml(target.content);
          }
        }
      } catch {
        antMessage.error("加载详情失败");
      } finally {
        setLoading(false);
        setInitialDataLoaded(true);
      }
    };

    loadDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, mode]);

  // 加载推送模板列表
  useEffect(() => {
    if (!isAnno) {
      pushApi.getTemplates().then((res) => {
        if (res.status === "success" && res.data) setTemplates(res.data);
      }).catch(() => {});
    }
  }, [isAnno]);

  // ==================== 公告操作 ====================

  const handleSaveAnno = async (publishNow = false) => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const values = form.getFieldsValue();
      const payload: AnnouncementPayload = {
        title: (values.title || "").trim(),
        category: values.category || "notice",
        department: (values.department || "").trim(),
        is_top: !!values.is_top,
        content: editorHtml,
        summary: (values.summary || "").trim(),
        expired_at: values.expired_at ? dayjs(values.expired_at).format("YYYY-MM-DD HH:mm:ss") : null,
        publish: publishNow,
      };

      let res;
      if (isEdit) {
        res = await announcementApi.update(Number(id), payload);
      } else {
        res = await announcementApi.create(payload);
      }

      if (res.status === "success") {
        antMessage.success(publishNow ? (isEdit ? "已保存并发布" : "已创建并发布") : "已保存草稿");
        if (!isEdit && res.data?.id) {
          // 新建成功后留在编辑态，方便继续操作
          navigate(`/messages/edit/${res.data.id}?type=announcement`, { replace: true });
        } else {
          navigate("/messages");
        }
      } else {
        antMessage.error(res.message || "保存失败");
      }
    } catch {
      antMessage.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePublish = async (publish: boolean) => {
    if (!id) return;
    setPublishing(true);
    try {
      const res = publish
        ? await announcementApi.publish(Number(id))
        : await announcementApi.withdraw(Number(id));
      if (res.status === "success") {
        antMessage.success(publish ? "已发布" : "已撤回");
        setCurrentStatus(res.data?.status || (publish ? "published" : "draft"));
      } else {
        antMessage.error(res.message || "操作失败");
      }
    } catch {
      antMessage.error("操作失败");
    } finally {
      setPublishing(false);
    }
  };

  // ==================== 推送操作 ====================

  const handleSavePush = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const values = form.getFieldsValue();
      const data: any = {
        title: values.title,
        msg_type: values.msg_type,
        push_type: values.push_type,
      };
      if (values.msg_type === "text") {
        data.content = editorHtml;
      } else if (values.msg_type === "image") {
        data.image_path = values.image_path;
      } else if (values.msg_type === "template") {
        data.template_id = values.template_id;
        data.template_params = values.template_params;
      }
      if (values.push_type === "scheduled") {
        data.scheduled_time = values.scheduled_time?.toISOString();
      } else if (values.push_type === "recurring") {
        data.cron_expression = values.cron_expression;
      }

      if (isEdit) {
        await pushApi.update(Number(id), data);
        antMessage.success("推送更新成功");
      } else {
        await pushApi.create(data);
        antMessage.success("推送创建成功");
      }
      navigate("/messages");
    } catch {
      antMessage.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  // ==================== 附件上传（公告专用）====================

  const customUpload = useCallback(async (options: any) => {
    const { file, onSuccess, onError } = options;
    const editId = isEdit ? Number(id) : null;
    if (!editId) {
      antMessage.warning("请先保存通知后再上传附件");
      onError?.(new Error("请先保存"));
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await announcementApi.uploadAttachment(editId, formData);
      if (res.status === "success" && res.data) {
        setAttachments((prev) => [...prev, res.data]);
        antMessage.success("附件上传成功");
        onSuccess?.(res.data);
      } else {
        antMessage.error(res.message || "上传失败");
        onError?.(new Error(res.message));
      }
    } catch {
      antMessage.error("上传失败");
      onError?.(new Error("上传失败"));
    } finally {
      setUploading(false);
    }
  }, [id, isEdit]);

  const handleDeleteAttachment = async (attId: number) => {
    try {
      const res = await announcementApi.deleteAttachment(attId);
      if (res.status === "success") {
        setAttachments((prev) => prev.filter((a) => a.id !== attId));
        antMessage.success("附件已删除");
      }
    } catch {
      antMessage.error("删除失败");
    }
  };

  // ==================== 渲染 ====================

  const pageTitle = isAnno
    ? (isEdit ? "编辑通知" : "新建通知")
    : (isEdit ? "编辑推送" : "新建推送");

  // WangEditor 配置
  const editorConfig = {
    placeholder: isAnno ? "输入通知正文..." : "输入推送内容...",
    onChange: (editor: any) => setEditorHtml(editor.getHtml()),
    defaultContent: editorHtml,
    MENU_CONF: {
      uploadImage: {
        server: "/api/admin/announcements/upload", // 复用公告附件上传接口
        fieldName: "file",
        maxFileSize: 20 * 1024 * 1024, // 20MB
        allowedFileTypes: ["image/*"],
      },
    },
  };

  const toolbarConfig = {
    excludeKeys: isMobile
      ? ["fullScreen", "group-video"]
      : [],
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      {/* 面包屑导航 */}
      <Card size="small" style={{ marginBottom: 16 }} styles={{ body: { padding: "8px 16px" } }}>
        <Breadcrumb items={[
          { title: <a onClick={() => navigate("/messages")}>消息中心</a> },
          { title: pageTitle },
        ]} />
      </Card>

      <Spin spinning={loading && !initialDataLoaded}>
        <Card
          title={pageTitle}
          extra={
            <Space>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/messages")}>
                返回列表
              </Button>
            </Space>
          }
        >
          <Form
            form={form}
            layout="vertical"
            requiredMark={isMobile ? false : "optional"}
            initialValues={{
              category: "notice",
              is_top: false,
              msg_type: "text",
              push_type: "immediate",
            }}
          >
            {/* ===== 基础信息 ===== */}
            <Form.Item
              name="title"
              label="标题"
              rules={[{ required: true, message: "请输入标题" }]}
            >
              <Input
                placeholder={isAnno ? "如：关于 2026 年中秋节放假安排的通知" : "推送标题"}
                maxLength={200}
                showCount
              />
            </Form.Item>

            {/* ===== 公告专属字段 ===== */}
            {isAnno && (
              <>
                <Row gutter={16}>
                  <Col xs={24} sm={12}>
                    <Form.Item name="category" label="分类">
                      <Select>
                        {CATEGORY_OPTIONS.map((c) => (
                          <Option key={c.value} value={c.value}>{c.label}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col xs={24} sm={12}>
                    <Form.Item name="department" label="来源部门">
                      <Input placeholder="如：学生处" maxLength={100} />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col xs={12} sm={8}>
                    <Form.Item name="is_top" label="置顶" valuePropName="checked">
                      <Switch checkedChildren="置顶" unCheckedChildren="普通" />
                    </Form.Item>
                  </Col>
                  <Col xs={12} sm={16}>
                    <Form.Item name="expired_at" label="过期时间">
                      <DatePicker
                        showTime
                        format="YYYY-MM-DD HH:mm:ss"
                        placeholder="留空表示长期有效"
                        style={{ width: "100%" }}
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Form.Item name="summary" label="摘要（可选）">
                  <TextArea
                    placeholder="列表页展示的简短摘要，留空则自动截取正文前 100 字"
                    rows={2}
                    maxLength={300}
                    showCount
                  />
                </Form.Item>
              </>
            )}

            {/* ===== 推送专属字段 ===== */}
            {!isAnno && (
              <>
                <Row gutter={16}>
                  <Col xs={24} sm={12}>
                    <Form.Item name="msg_type" label="消息类型" rules={[{ required: true }]}>
                      <Select onChange={(v: PushMsgType) => {
                        setMsgType(v);
                        form.setFieldsValue({ content: undefined, image_path: undefined, template_id: undefined });
                      }}>
                        <Option value="text">文本消息</Option>
                        <Option value="image">图片消息</Option>
                        <Option value="template">模板消息</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col xs={24} sm={12}>
                    <Form.Item name="push_type" label="推送方式" rules={[{ required: true }]}>
                      <Select onChange={(v: PushPushType) => {
                        setPushType(v);
                        form.setFieldsValue({ scheduled_time: undefined, cron_expression: undefined });
                      }}>
                        <Option value="immediate">立即推送</Option>
                        <Option value="scheduled">定时推送（单次）</Option>
                        <Option value="recurring">周期推送（重复）</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                </Row>

                {/* 定时推送 */}
                {pushType === "scheduled" && (
                  <Form.Item
                    name="scheduled_time"
                    label="定时时间"
                    rules={[{ required: true, message: "请选择推送时间" }]}
                  >
                    <DatePicker
                      showTime
                      format="YYYY-MM-DD HH:mm"
                      style={{ width: "100%" }}
                      disabledDate={(current) => current && current < dayjs().startOf("day")}
                    />
                  </Form.Item>
                )}

                {/* 周期推送 */}
                {pushType === "recurring" && (
                  <>
                    <Form.Item
                      name="cron_expression"
                      label="Cron 表达式"
                      rules={[
                        { required: true, message: "请输入 Cron 表达式" },
                        { pattern: /^[\d*,/-\s]+$/, message: "格式不正确" },
                      ]}
                    >
                      <Input placeholder="0 8 * * *" />
                    </Form.Item>
                    <Alert
                      description={
                        <div style={{ fontSize: 12, lineHeight: 1.8 }}>
                          <code>0 8 * * *</code> 每天 8:00 &nbsp;|&nbsp;
                          <code>0 9 * * 1</code> 每周一 9:00 &nbsp;|&nbsp;
                          <code>0 */6 * * *</code> 每 6 小时
                        </div>
                      }
                      type="info"
                      showIcon
                      style={{ marginBottom: 16 }}
                    />
                  </>
                )}

                {/* 图片消息路径 */}
                {msgType === "image" && (
                  <Form.Item
                    name="image_path"
                    label="图片路径"
                    rules={[{ required: true, message: "请输入图片路径" }]}
                    extra="服务器上的图片相对路径，如 data/electricity/charts/chart.png"
                  >
                    <Input placeholder="data/images/notice.jpg" />
                  </Form.Item>
                )}

                {/* 模板消息选择 */}
                {msgType === "template" && (
                  <>
                    <Form.Item
                      name="template_id"
                      label="选择模板"
                      rules={[{ required: true, message: "请选择模板" }]}
                    >
                      <Select placeholder="选择内置模板">
                        {templates.map((tpl) => (
                          <Option key={tpl.id} value={tpl.id}>
                            {tpl.name} - {tpl.description}
                          </Option>
                        ))}
                      </Select>
                    </Form.Item>
                    {/* 模板参数动态渲染可后续扩展 */}
                  </>
                )}
              </>
            )}

            {/* ===== 分隔线 ===== */}
            <Divider />

            {/* ===== 富文本编辑器 ===== */}
            <Form.Item
              label={isAnno ? "正文" : "内容"}
              rules={[{ required: true, message: "请输入内容" }]}
              validateTrigger={[]}
            >
              {editorReady && Editor ? (
                <div
                  style={{
                    border: "1px solid #d9d9d9",
                    borderRadius: 6,
                    overflow: "hidden",
                  }}
                >
                  <EditorToolbar {...toolbarConfig} defaultConfig={editorConfig} />
                  <Editor
                    defaultConfig={editorConfig}
                    mode="default"
                    style={{ height: isMobile ? 300 : 400 }}
                  />
                </div>
              ) : (
                <TextArea
                  rows={8}
                  placeholder={isAnno ? "通知正文内容（富文本编辑器加载中，请稍候...）" : "推送内容"}
                  value={editorHtml}
                  onChange={(e) => setEditorHtml(e.target.value)}
                />
              )}
            </Form.Item>

            {/* ===== 公告附件区（仅编辑模式显示）===== */}
            {isAnno && isEdit && (
              <>
                <Divider>附件管理</Divider>
                <div style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: 600 }}>已传附件（{attachments.length}）</span>
                  <Upload
                    multiple
                    showUploadList={false}
                    customRequest={customUpload}
                    accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip,.rar,.7z,.jpg,.jpeg,.png,.gif,.webp"
                  >
                    <Button icon={<UploadOutlined />} loading={uploading}>上传附件</Button>
                  </Upload>
                </div>

                {attachments.length === 0 ? (
                  <div style={{ color: "#999", padding: "16px 0", textAlign: "center" }}>暂无附件</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {attachments.map((att) => (
                      <div
                        key={att.id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "10px 14px",
                          border: "1px solid #f0f0f0",
                          borderRadius: 6,
                          background: "#fafafa",
                        }}
                      >
                        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          <FileOutlined style={{ marginRight: 8, color: "#1677ff" }} />
                          <a href={att.download_url} target="_blank" rel="noreferrer">{att.file_name}</a>
                          <span style={{ color: "#999", marginLeft: 8 }}>{att.file_size_label}</span>
                        </span>
                        <Popconfirm
                          title="确定删除该附件？"
                          onConfirm={() => handleDeleteAttachment(att.id)}
                          okText="删除"
                          okButtonProps={{ danger: true }}
                        >
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ color: "#bbb", fontSize: 12, marginTop: 8 }}>
                  支持格式：pdf/doc/xls/ppt/txt/zip/rar/7z/jpg/png/gif/webp，单文件不超过 20MB
                </div>
              </>
            )}
          </Form>

          {/* ===== 底部操作栏 ===== */}
          <Divider />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              paddingTop: 8,
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            <div>
              {isAnno && isEdit && (
                <>
                  {currentStatus === "published" ? (
                    <Popconfirm
                      title="撤回后学生端将立即不可见"
                      onConfirm={() => handleTogglePublish(false)}
                      okText="撤回"
                    >
                      <Button danger icon={<RollbackOutlined />} loading={publishing}>撤回</Button>
                    </Popconfirm>
                  ) : (
                    <Popconfirm
                      title="发布后学生端立即可见"
                      onConfirm={() => handleTogglePublish(true)}
                      okText="发布"
                    >
                      <Button type="primary" ghost icon={<SendOutlined />} loading={publishing}>发布</Button>
                    </Popconfirm>
                  )}
                </>
              )}
            </div>
            <Space>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/messages")}>
                返回
              </Button>
              {isAnno ? (
                <>
                  {!isEdit && (
                    <Button icon={<SaveOutlined />} loading={saving} onClick={() => handleSaveAnno(false)}>
                      保存草稿
                    </Button>
                  )}
                  <Button
                    type="primary"
                    icon={<SaveOutlined />}
                    loading={saving}
                    onClick={() => handleSaveAnno(isEdit ? false : true)}
                  >
                    {isEdit ? "保存修改" : "保存并发布"}
                  </Button>
                </>
              ) : (
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={handleSavePush}
                >
                  {isEdit ? "保存修改" : "创建推送"}
                </Button>
              )}
            </Space>
          </div>
        </Card>
      </Spin>
    </div>
  );
}
