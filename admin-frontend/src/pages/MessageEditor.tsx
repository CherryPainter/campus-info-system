/**
 * 消息编辑器（独立页面）—— 左编辑 + 右手机预览
 *
 * 统一处理「校园通知」和「即时推送」的创建与编辑。
 * 路由：
 *   /messages/create?type=announcement|push  → 新建
 *   /messages/edit/:id?type=announcement|push → 编辑
 *
 * 布局：
 *   左侧：表单编辑区（标题/分类/部门/置顶/摘要/正文/附件）
 *   右侧：iPhone 手机模型，实时预览小程序通知详情页效果（仅公告模式）
 *
 * 集成 WangEditor v5 富文本编辑器。
 */
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
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
  Tooltip,
} from "antd";
import {
  SaveOutlined,
  SendOutlined,
  RollbackOutlined,
  ArrowLeftOutlined,
  UploadOutlined,
  DeleteOutlined,
  FileOutlined,
  PlusOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
  MobileOutlined,
  StarOutlined,
  StarFilled,
} from "@ant-design/icons";
import { announcementApi, CATEGORY_OPTIONS, type AnnouncementPayload } from "@/api/announcement";
import { pushApi, type CustomPush, type PushTemplate } from "@/api/admin";
import { tokenStorage } from "@/utils/token";
import { useMessage } from "@/utils/message";
import dayjs from "dayjs";
import "../styles/iconfont.css";
import "@wangeditor/editor/dist/css/style.css";

// WangEditor v5（动态导入，避免未安装时构建失败）
let Editor: any;
let EditorToolbar: any;
let editorModulesLoaded = false;

async function loadEditorModules() {
  if (editorModulesLoaded) return true;
  try {
    const reactMod = await import("@wangeditor/editor-for-react");
    const core = await import("@wangeditor/editor");
    // editor-for-react 只有命名导出 Editor / Toolbar（无 default export）
    Editor = reactMod.Editor;
    // Toolbar 也在 editor-for-react 里（需要 editor 实例作为 prop）；@wangeditor/editor
    // 没有 React 版的 Toolbar 导出，所以从这里取
    EditorToolbar = reactMod.Toolbar;
    // 保留 core 引用以备后续需要（如注册插件）
    void core;
    editorModulesLoaded = true;
    return true;
  } catch (err) {
    console.error("[WangEditor] 加载失败:", err);
    return false;
  }
}

const { Option } = Select;
const { TextArea } = Input;

type EditorMode = "announcement" | "push";
type PushMsgType = "text" | "image" | "template";
type PushPushType = "immediate" | "scheduled" | "recurring";

/** 分类中文标签映射 */
const CATEGORY_LABEL_MAP: Record<string, string> = {};
CATEGORY_OPTIONS.forEach((c) => { CATEGORY_LABEL_MAP[c.value] = c.label; });

export default function MessageEditor() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  // 大屏才显示右侧预览
  const showPreview = screens.lg && !isMobile;
  // App 上下文 message（替代静态 antMessage，正确消费主题/语言配置）
  const antMessage = useMessage();

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
  const [editorInstance, setEditorInstance] = useState<any>(null);

  // 预览相关状态
  const [showPhonePreview, setShowPhonePreview] = useState(true);
  const [previewKey, setPreviewKey] = useState(0);
  const handleFieldChange = useCallback(() => {
    setPreviewKey((k) => k + 1);
  }, []);

  // 右侧手机预览「京东式」固定定位：scroll 时测量 Col 的位置与宽度，
  // 当 Col 顶部越过视口 top:72 时钉住（position:fixed），否则复位让出顶部面包屑。
  // （sticky 依赖父容器高度，在 antd Row/Col 下不可靠，故用 JS fixed）
  const previewColRef = useRef<HTMLDivElement | null>(null);
  const [previewState, setPreviewState] = useState<
    { left: number; width: number; pinned: boolean } | null
  >(null);

  useEffect(() => {
    if (!(isAnno && showPreview && showPhonePreview)) return;
    const update = () => {
      const el = previewColRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      // 滚到 Col 顶部到达/越过 72px 时钉住；往上回到顶部时复位让面包屑可见
      const pinned = rect.top <= 72;
      setPreviewState({ left: rect.left, width: rect.width, pinned });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    // 编辑器/内容异步加载后再校准一次，避免布局抖动导致定位偏移
    const t = window.setTimeout(update, 300);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      window.clearTimeout(t);
    };
  }, [isAnno, showPreview, showPhonePreview, previewKey]);

  // ==================== 实时预览数据 ====================

  /** 订阅整个表单的值（避免在 Form 未挂载时调用 getFieldsValue 触发
      "useForm is not connected to any Form element" 告警） */
  const watchedFormValues: any = Form.useWatch([], form) || {};

  /** 从表单提取当前预览数据（previewKey 变化时重算，实现实时联动）*/
  const previewData = useMemo(() => {
    const values = watchedFormValues;
    return {
      title: values.title || "通知标题",
      category: values.category || "notice",
      categoryLabel: CATEGORY_LABEL_MAP[values.category] || CATEGORY_LABEL_MAP["notice"] || "通知",
      department: values.department || "教务处",
      is_top: !!values.is_top,
      summary: values.summary || "",
      content: editorHtml || "<p style='color:#999;font-size:13px;'>正文内容预览区域</p>",
      published_at: dayjs().format("YYYY-MM-DD HH:mm"),
      view_count: Math.floor(Math.random() * 2000) + 100,
      attachments: attachments.map((a) => ({
        file_name: a.file_name,
        file_size_label: a.file_size_label,
      })),
    };
  }, [watchedFormValues, editorHtml, attachments, previewKey]);

  // ==================== 加载编辑器组件 ====================

  useEffect(() => {
    loadEditorModules().then((ok) => setEditorReady(ok));
  }, []);

  // ==================== 加载初始数据（编辑模式）====================

  useEffect(() => {
    if (!isEdit) {
      setInitialDataLoaded(true);
      form.setFieldsValue({
        category: "notice",
        is_top: false,
        push_type: "immediate",
        msg_type: "text",
      });
      return;
    }

    const loadDetail = async () => {
      setLoading(true);
      try {
        if (isAnno) {
          const res = await announcementApi.detail(Number(id));
          if (res.status === "success" && res.data) {
            const d = res.data;
            // 前端兜底：剥除历史脏数据（含完整标签 + 截断的 <img ... 无闭合 >）。
            // 数据可能因手动误填缺闭合符，正则需宽容处理。
            const stripHtml = (s: string) => {
              if (!s) return "";
              let r = String(s).replace(/<[^>]+>/g, ""); // 1) 完整标签
              r = r.replace(/<img\b[\s\S]*$/gi, "");     // 2) 截断的 <img ...（到末尾）
              return r.trim();
            };
            form.setFieldsValue({
              title: d.title,
              category: d.category || "notice",
              department: d.department || "",
              is_top: d.is_top || false,
              summary: stripHtml(d.summary || ""),
              expired_at: d.expired_at ? dayjs(d.expired_at) : null,
            });
            setEditorHtml(d.content || "");
            setCurrentStatus(d.status);
            setAttachments(d.attachments || []);
          }
        } else {
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
    : (isEdit ? "编辑自定义推送" : "新建自定义推送");

  // WangEditor 配置（注意：初始内容走 <Editor defaultContent={...}> 顶层 prop，
  // editor-for-react 的 createEditor({content}) 只认顶层 defaultContent，
  // 放 config.defaultContent 里不会生效）
  const editorConfig = {
    placeholder: isAnno ? "输入通知正文..." : "输入推送内容...",
    onChange: (editor: any) => {
      setEditorHtml(editor.getHtml());
      handleFieldChange();
    },
    MENU_CONF: {
      uploadImage: {
        server: "/api/admin/announcements/upload-image",
        fieldName: "file",
        maxFileSize: 20 * 1024 * 1024,
        allowedFileTypes: ["image/*"],
        headers: {
          Authorization: `Bearer ${tokenStorage.getAccessToken() || ""}`,
        },
      },
    },
  };

  const toolbarConfig = {
    excludeKeys: isMobile
      ? ["fullScreen", "group-video"]
      : [],
  };

  // ==================== 手机模型预览组件 ====================

  const PhonePreview = useMemo(() => {
    if (!isAnno) return null;

    const d = previewData;

    return (
      <div className="phone-mockup-wrapper">
        {/* 手机外框 */}
        <div className="phone-frame">
          {/* 刘海 */}
          <div className="phone-notch">
            <div className="notch-speaker" />
          </div>

          {/* 状态栏 */}
          <div className="phone-statusbar">
            <span className="status-time">{dayjs().format("HH:mm")}</span>
            <div className="status-icons">
              <span className="pv-iconfont pv-xinhao1 status-signal" />
              <span className="pv-iconfont pv-xinhao status-wifi" />
              <span className="status-battery">
                <span className="pv-iconfont pv-dianchi battery-icon" />
                <span className="battery-pct">100%</span>
              </span>
            </div>
          </div>

          {/* 导航栏 */}
          <div className="phone-navbar">
            <span className="pv-iconfont pv-fanhui navbar-back" />
            <span className="navbar-title">通知详情</span>
            <span className="navbar-placeholder" />
          </div>

          {/* 内容滚动区 */}
          <div className="phone-scroll-content">
            {/* 标题区 */}
            <div className="preview-header">
              <div className="preview-title-row">
                {d.is_top ? (
                  <span className="preview-top-tag">置顶</span>
                ) : (
                  <span className="preview-cat-tag">{d.categoryLabel}</span>
                )}
                <span className="preview-title-text">{d.title}</span>
                <span className="pv-iconfont pv-bianji1 preview-edit-icon" />
              </div>
              <div className="preview-meta-row">
                <span className="preview-dept">{d.department}</span>
                <span className="meta-sep">&middot;</span>
                <span className="preview-time">{dayjs(d.published_at).format("MM-DD HH:mm")}</span>
              </div>
              <div className="preview-views-row">
                <span className="preview-views">阅读 {d.view_count}</span>
              </div>
            </div>

            {/* 分隔线 */}
            <div className="preview-divider" />

            {/* 正文 */}
            <div
              className="preview-content"
              dangerouslySetInnerHTML={{ __html: d.content }}
            />

            {/* 落款 */}
            <div className="preview-signature">
              <div className="sign-line">{d.department}</div>
              <div className="sign-line">{dayjs(d.published_at).format("YYYY年M月D日")}</div>
            </div>

            {/* 附件 */}
            {d.attachments.length > 0 && (
              <>
                <div className="preview-section-title">附件</div>
                {d.attachments.map((att, idx) => (
                  <div key={idx} className="preview-attach-item">
                    <span className="attach-file-icon">&#128206;</span>
                    <div className="attach-info">
                      <span className="attach-name">{att.file_name}</span>
                      <span className="attach-size">{att.file_size_label}</span>
                    </div>
                    <span className="pv-iconfont pv-xiazai attach-dl-icon" />
                  </div>
                ))}
              </>
            )}

            {/* 相关推荐 */}
            <div className="preview-section-title">相关推荐</div>
            <div className="preview-related-item">
              <span className="related-cat-tag" style={{ background: "rgba(26,115,232,0.1)", color: "#1a73e8" }}>{d.categoryLabel}</span>
              <span className="related-title">示例相关通知标题</span>
              <div className="related-meta">
                <span>{d.department}</span>
                <span className="meta-sep">&middot;</span>
                <span>08-28 10:00</span>
              </div>
            </div>

            {/* 底部占位（给操作栏留空间） */}
            <div style={{ height: 80 }} />
          </div>

          {/* 底部操作栏 */}
          <div className="phone-actions-bar">
            <div className="phone-action-btn">
              <StarOutlined className="phone-action-icon" />
              <span className="phone-action-text">收藏</span>
            </div>
            <div className="phone-action-btn">
              <span className="pv-iconfont pv-fenxiang phone-action-icon" />
              <span className="phone-action-text">分享</span>
            </div>
            <div className="phone-action-btn">
              <span className="pv-iconfont pv-yiyuedu phone-action-icon" />
              <span className="phone-action-text">已阅</span>
            </div>
          </div>

          {/* Home 指示条 */}
          <div className="home-indicator" />
        </div>
      </div>
    );
  }, [previewData, previewKey, isAnno]);

  // ==================== 主渲染 ====================

  return (
    <div className="message-editor-page">
      {/* 面包屑导航 */}
      <Card size="small" className="editor-breadcrumb" styles={{ body: { padding: "8px 16px" } }}>
        <Breadcrumb items={[
          { title: <a onClick={() => navigate("/messages")}>消息中心</a> },
          { title: pageTitle },
        ]} />
      </Card>

      <Spin spinning={loading && !initialDataLoaded}>
        <Row gutter={showPreview ? 24 : 0} align="stretch" className="editor-main-row">
          {/* ===== 左侧：编辑区 ===== */}
          <Col xs={24} lg={showPreview ? 14 : 24} xl={showPreview ? 13 : 24}>
            <Card
              title={pageTitle}
              extra={
                <Space>
                  {isAnno && showPreview && (
                    <Tooltip title={showPhonePreview ? "隐藏预览" : "显示预览"}>
                      <Button
                        icon={showPhonePreview ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                        onClick={() => setShowPhonePreview(!showPhonePreview)}
                        size="small"
                      >
                        预览
                      </Button>
                    </Tooltip>
                  )}
                  <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/messages")}>
                    返回列表
                  </Button>
                </Space>
              }
              className="editor-card"
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
                onValuesChange={handleFieldChange}
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

                    {msgType === "template" && (
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
                  {/* 编辑模式且数据加载完后才挂载 WangEditor：
                      Editor 的 defaultContent 只在挂载时生效一次。
                      loadDetail 是异步 useEffect，若 Editor 第一次渲染时
                      content 还在加载中（空），挂载后就再也不读 defaultContent。
                      用 key={id} 切换不同公告时强制重新挂载。 */}
                  {editorReady && Editor && initialDataLoaded ? (
                    <div className="editor-wrapper">
                      <div className="editor-toolbar-sticky">
                        <EditorToolbar
                          editor={editorInstance}
                          defaultConfig={toolbarConfig}
                          mode="default"
                        />
                      </div>
                      <Editor
                        key={String(id ?? "new")}
                        defaultHtml={editorHtml}
                        defaultConfig={editorConfig}
                        mode="default"
                        style={{ minHeight: 400, height: "auto" }}
                        onCreated={(editor: any) => {
                          setEditorInstance(editor);
                        }}
                      />
                    </div>
                  ) : (
                    <TextArea
                      rows={8}
                      placeholder={
                        isAnno
                          ? editorReady
                            ? "通知内容加载中..."
                            : "富文本编辑器加载中，请稍候..."
                          : "推送内容"
                      }
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
              <div className="editor-footer-actions">
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
          </Col>

          {/* ===== 右侧：手机模型预览（仅公告模式 + 大屏）===== */}
          {isAnno && showPreview && showPhonePreview && (
            <Col xs={0} lg={10} xl={11} ref={previewColRef} style={{ display: "flex" }}>
              <div
                className="preview-sticky-wrap"
                style={
                  previewState
                    ? previewState.pinned
                      ? {
                          position: "fixed",
                          top: 72,
                          left: previewState.left,
                          width: previewState.width,
                          zIndex: 10,
                        }
                      : { position: "static", zIndex: 10 }
                    : undefined
                }
              >
                <Card
                  className="preview-card"
                  title={
                    <Space>
                      <MobileOutlined />
                      <span>手机页面消息预览</span>
                    </Space>
                  }
                size="small"
              >
                {PhonePreview}
              </Card>
              </div>
            </Col>
          )}
        </Row>
      </Spin>

      {/* ===== 全局样式 ===== */}
      <style>{`
        /* ========== 页面布局 ========== */
        .message-editor-page {
          max-width: 1440px;
          margin: 0 auto;
          padding: 0 16px;
        }

        .editor-breadcrumb {
          margin-bottom: 16px;
        }

        .editor-main-row {
          /* 不覆盖 align，由 <Row align="stretch"> 控制，确保右侧 Col 拉伸到与左侧同高 */
        }

        .editor-card {
          min-height: 400px;
        }

        .editor-wrapper {
          border: 1px solid #d9d9d9;
          border-radius: 6px;
          /* overflow 改 visible，让 WangEditor 内容多时自然撑开外层，
             编辑器不再内部固定 400px 滚动 */
          overflow: visible;
        }

        /* 富文本工具栏吸顶：长文向下滚动时工具栏固定在视口顶部，
           提升编辑体验。
           关键：antd Card 根元素默认 overflow:hidden，会让内部 sticky
           相对 Card 而非视口（钉不住）。必须解除该 Card 的裁剪，
           使工具栏的滚动容器回归视口。 */
        .editor-card.ant-card { overflow: visible !important; }
        .editor-toolbar-sticky {
          position: sticky;
          top: 72px;
          z-index: 20;
          background: #fff;
          border-top-left-radius: 5px;
          border-top-right-radius: 5px;
          border-bottom: 1px solid #f0f0f0;
          box-shadow: 0 2px 6px -2px rgba(0, 0, 0, 0.08);
        }

        .editor-footer-actions {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding-top: 8px;
          flex-wrap: wrap;
          gap: 8px;
        }

        /* ========== 预览卡片（京东式固定定位：左侧滚动时右侧始终钉在视口）========== */
        /* 实现：JS 测量 Col 位置后给 wrapper 设 position:fixed（top/left/width 由 inline style 注入）。
           此处 CSS 仅作测量完成前的 fallback（sticky），避免首帧闪跳。 */
        .preview-sticky-wrap {
          position: sticky;
          top: 72px;
          align-self: flex-start;
          width: 100%;
          z-index: 10;
        }

        .preview-card {
          display: flex;
          flex-direction: column;
          max-height: calc(100vh - 88px);

          .ant-card-head {
            flex-shrink: 0;
          }

          .ant-card-body {
            flex: 1;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            min-height: 0;
          }
        }

        /* ========== 手机模型外框 ========== */
        .phone-mockup-wrapper {
          display: flex;
          justify-content: center;
          padding: 16px 0;
          flex: 1;
          overflow-y: auto;
          min-height: 0;
          /* 隐藏滚动条但保留滚动功能 */
          scrollbar-width: none; /* Firefox */
          -ms-overflow-style: none; /* IE/Edge */
          &::-webkit-scrollbar {
            display: none; /* Chrome/Safari */
          }
        }

        .phone-frame {
          width: 320px;
          height: 640px;
          background: #fff;
          border-radius: 36px;
          box-shadow:
            0 0 0 2px #333,
            0 0 0 4px #555,
            0 12px 40px rgba(0,0,0,0.2);
          position: relative;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        /* 刘海 */
        .phone-notch {
          position: absolute;
          top: 0;
          left: 50%;
          transform: translateX(-50%);
          width: 120px;
          height: 28px;
          background: #000;
          border-radius: 0 0 18px 18px;
          z-index: 10;
          display: flex;
          justify-content: center;
          align-items: center;
        }

        .notch-speaker {
          width: 50px;
          height: 6px;
          background: #333;
          border-radius: 3px;
        }

        /* 状态栏 */
        .phone-statusbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px 20px 4px;
          font-size: 13px;
          font-weight: 600;
          background: #fff;
          z-index: 5;
        }

        .status-time { letter-spacing: 0.5px; }

        .status-icons {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 10px;
        }

        .status-signal { font-size: 13px; color: #111; line-height: 1; }
        .status-wifi { font-size: 13px; color: #111; line-height: 1; }
        .status-battery {
          display: flex;
          align-items: center;
          gap: 2px;
          font-size: 11px;
          color: #111;
        }
        .battery-icon { font-size: 16px; line-height: 1; }
        .battery-pct { font-size: 11px; }

        /* 导航栏 */
        .phone-navbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 6px 12px;
          border-bottom: 0.5px solid #eee;
          font-size: 15px;
          font-weight: 600;
          background: #fff;
          z-index: 5;
        }

        .navbar-back { font-size: 18px; color: #1a73e8; cursor: pointer; line-height: 1; }
        .navbar-title { font-size: 15px; font-weight: 600; }
        .navbar-placeholder { width: 24px; }

        /* 滚动内容区 */
        .phone-scroll-content {
          flex: 1;
          overflow-y: auto;
          padding: 14px 14px 0;
          background: #fff;
          font-size: 13px;
          line-height: 1.6;
          -webkit-overflow-scrolling: touch;
        }

        .phone-scroll-content::-webkit-scrollbar {
          width: 0;
          display: none;
        }

        /* ---------- 标题区 ---------- */
        .preview-header {
          margin-bottom: 12px;
        }

        .preview-title-row {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .preview-top-tag {
          font-size: 11px;
          line-height: 1.4;
          color: #cf1322;
          background: rgba(207,19,34,0.08);
          padding: 2px 8px;
          border-radius: 4px;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .preview-cat-tag {
          font-size: 11px;
          line-height: 1.4;
          color: #1a73e8;
          background: rgba(26,115,232,0.1);
          padding: 2px 8px;
          border-radius: 4px;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .preview-title-text {
          font-size: 17px;
          font-weight: 700;
          color: #1a1a1a;
          line-height: 1.4;
          flex: 1;
          word-break: break-all;
        }

        .preview-edit-icon {
          font-size: 15px;
          color: #c8ccd4;
          flex-shrink: 0;
          line-height: 1;
        }

        .preview-meta-row {
          margin-top: 6px;
          font-size: 12px;
          color: #888;
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .meta-sep { margin: 0 2px; }

        .preview-dept { color: #555; }
        .preview-time { color: #888; }

        .preview-views-row {
          margin-top: 4px;
        }

        .preview-views {
          font-size: 12px;
          color: #999;
        }

        .preview-divider {
          height: 0.5px;
          background: #eee;
          margin: 10px 0;
        }

        /* ---------- 正文 ---------- */
        .preview-content {
          font-size: 13px;
          color: #333;
          line-height: 1.75;
          word-break: break-word;
        }

        .preview-content img {
          max-width: 100%;
          border-radius: 4px;
        }

        .preview-content p {
          margin: 0 0 8px;
        }

        .preview-content:empty::after {
          content: '暂无正文';
          color: #bbb;
        }

        /* ---------- 落款 ---------- */
        .preview-signature {
          margin-top: 16px;
          text-align: right;
          font-size: 12px;
          color: #888;
          line-height: 1.8;
        }

        .sign-line { display: block; }

        /* ---------- 附件 ---------- */
        .preview-section-title {
          font-size: 13px;
          font-weight: 600;
          color: #1a1a1a;
          margin: 18px 0 10px;
          padding-left: 8px;
          border-left: 3px solid #1a73e8;
        }

        .preview-attach-item {
          display: flex;
          align-items: center;
          padding: 10px 12px;
          background: #fafafa;
          border-radius: 8px;
          margin-bottom: 8px;
          gap: 10px;
        }

        .attach-file-icon {
          font-size: 20px;
          flex-shrink: 0;
        }

        .attach-info {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
        }

        .attach-name {
          font-size: 13px;
          color: #333;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .attach-size {
          font-size: 11px;
          color: #aaa;
        }

        .attach-dl-icon {
          font-size: 17px;
          color: #1a73e8;
          flex-shrink: 0;
          line-height: 1;
        }

        /* ---------- 相关推荐 ---------- */
        .preview-related-item {
          padding: 10px 12px;
          background: #fafafa;
          border-radius: 8px;
          margin-bottom: 8px;
        }

        .related-cat-tag {
          display: inline-block;
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 4px;
          margin-right: 6px;
          vertical-align: middle;
        }

        .related-title {
          font-size: 13px;
          font-weight: 500;
          color: #333;
        }

        .related-meta {
          margin-top: 4px;
          font-size: 11px;
          color: #aaa;
          display: flex;
          align-items: center;
          gap: 2px;
        }

        /* ---------- 底部操作栏 ---------- */
        .phone-actions-bar {
          display: flex;
          justify-content: space-around;
          align-items: center;
          padding: 10px 16px 20px;
          border-top: 0.5px solid #eee;
          background: #fff;
          z-index: 5;
        }

        .phone-action-btn {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 2px;
          cursor: pointer;
        }

        .phone-action-icon {
          font-size: 22px;
          color: #8a8f99;
          line-height: 1;
        }

        .phone-action-text {
          font-size: 11px;
          color: #8a8f99;
        }

        /* Home 指示条 */
        .home-indicator {
          width: 100px;
          height: 4px;
          background: #333;
          border-radius: 2px;
          margin: 6px auto 4px;
          flex-shrink: 0;
        }

        /* ========== 移动端适配 ========== */
        @media (max-width: 992px) {
          .preview-card {
            display: none;
          }
        }
      `}</style>
    </div>
  );
}
