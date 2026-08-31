/**
 * 消息中心（统一管理页面）
 *
 * 合并原「校园通知」(announcements) 和「自定义推送」(push) 为单一入口，
 * 通过 Tab 切换两种消息模式。两套后端 API 不变，仅前端统一。
 *
 * - 校园通知：结构化公告（分类/状态/发布撤回/阅读量/附件）
 * - 即时推送：灵活消息（文本/图片/模板/定时/周期）
 *
 * 编辑操作跳转独立编辑页（MessageEditor），不再使用 Modal 弹窗。
 */
import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Card,
  Button,
  Space,
  Tag,
  Table,
  Select,
  Input,
  Popconfirm,
  Tabs,
  Grid,
  Alert,
  Statistic,
  Row,
  Col,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SendOutlined,
  RollbackOutlined,
  FileOutlined,
  PushpinOutlined,
  InfoCircleOutlined,
  NotificationOutlined,
  ThunderboltOutlined,
  EyeOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import {
  announcementApi,
  CATEGORY_OPTIONS,
  STATUS_OPTIONS,
  type AnnouncementListItem,
  type AnnouncementCategory,
  type AnnouncementStatus,
} from "@/api/announcement";
import { pushApi, type CustomPush } from "@/api/admin";
import { PUSH_STATUS_MAP } from "@/constants/statusMaps";
import dayjs from "dayjs";
import { useMessage } from "@/utils/message";

const { Option } = Select;

// ==================== 类型映射 ====================

const catMap: Record<string, { label: string; color: string }> = Object.fromEntries(
  CATEGORY_OPTIONS.map((c) => [c.value, c])
);
const statusMap: Record<string, { label: string; color: string }> = Object.fromEntries(
  STATUS_OPTIONS.map((s) => [s.value, s])
);

const pushTypeMap: Record<string, { color: string; text: string }> = {
  immediate: { color: "blue", text: "立即推送" },
  scheduled: { color: "purple", text: "定时推送" },
  recurring: { color: "cyan", text: "周期推送" },
};

const msgTypeIconMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  text: { color: "geekblue", text: "文本", icon: <FileOutlined /> },
  image: { color: "magenta", text: "图片", icon: <FileOutlined style={{ transform: "rotate(-5deg)" }} /> },
  template: { color: "volcano", text: "模板", icon: <ThunderboltOutlined /> },
};

type ActiveTab = "announcement" | "push";

export default function Messages() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const message = useMessage();

  // Tab 状态（从 URL ?tab=push|announcement 读取初始值，兼容旧路径重定向）
  const initialTab = (searchParams.get("tab") as ActiveTab) || "announcement";
  const [activeTab, setActiveTab] = useState<ActiveTab>(initialTab);

  // ========== 公告列表状态 ==========
  const [annoList, setAnnoList] = useState<AnnouncementListItem[]>([]);
  const [annoTotal, setAnnoTotal] = useState(0);
  const [annoPage, setAnnoPage] = useState(1);
  const [annoPageSize, setAnnoPageSize] = useState(10);
  const [annoKeyword, setAnnoKeyword] = useState("");
  const [annoKeywordInput, setAnnoKeywordInput] = useState("");
  const [filterCategory, setFilterCategory] = useState<AnnouncementCategory | "">("");
  const [filterStatus, setFilterStatus] = useState<AnnouncementStatus | "">("");

  // ========== 推送列表状态 ==========
  const [pushList, setPushList] = useState<CustomPush[]>([]);
  const [pushTotal, setPushTotal] = useState(0);
  const [pushPage, setPushPage] = useState(1);
  const [pushPageSize, setPushPageSize] = useState(10);

  // ========== 统计数据 ==========
  const [stats, setStats] = useState({
    annoTotal: 0,
    annoPublished: 0,
    annoToday: 0,
    pushTotal: 0,
    pushPending: 0,
  });

  // ==================== 数据加载 ====================

  const fetchAnnouncements = async () => {
    setLoading(true);
    try {
      const res = await announcementApi.list({
        page: annoPage,
        page_size: annoPageSize,
        keyword: annoKeyword || undefined,
        category: filterCategory || undefined,
        status: filterStatus || undefined,
      });
      if (res.status === "success") {
        setAnnoList((res.data as AnnouncementListItem[]) || []);
        setAnnoTotal(res.pagination?.total ?? 0);
      }
    } catch {
      // 静默失败，表格显示空态
    } finally {
      setLoading(false);
    }
  };

  const fetchPushes = async () => {
    setLoading(true);
    try {
      const res = await pushApi.getList({ page: pushPage, per_page: pushPageSize });
      setPushList(res.data || []);
      setPaginationFromRes(res.pagination);
    } catch {
      // 静默失败
    } finally {
      setLoading(false);
    }
  };

  /** 从 pushApi.getList 的 pagination 响应设置分页（字段名可能不同） */
  const setPaginationFromRes = (pag: any) => {
    if (pag) {
      setPushTotal(pag.total ?? pag.total_count ?? 0);
    }
  };

  const fetchStats = async () => {
    try {
      // 公告统计：分别查总数和今日新增
      const [allRes, todayRes] = await Promise.all([
        announcementApi.list({ page: 1, page_size: 1 }),
        announcementApi.list({
          page: 1,
          page_size: 1,
          status: "published",
          keyword: undefined,
        }),
      ]);
      const annoTotalCount = allRes.pagination?.total ?? 0;
      const publishedCount = todayRes.pagination?.total ?? 0;

      // 推送统计
      let pushTotalCount = 0;
      let pushPendingCount = 0;
      try {
        const pushRes = await pushApi.getList({ page: 1, per_page: 1 });
        setPaginationFromRes(pushRes.pagination);
        pushTotalCount = pushTotal;
        // pending 数从当前列表估算或单独接口
        pushPendingCount = pushList.filter((p) => p.status === "pending").length;
      } catch {
        /* 推送统计失败不阻塞 */
      }

      setStats({
        annoTotal: annoTotalCount,
        annoPublished: publishedCount,
        annoToday: publishedCount, // 简化：用已发布数代替
        pushTotal: pushTotalCount,
        pushPending: pushPendingCount,
      });
    } catch {
      /* 统计失败不阻塞主流程 */
    }
  };

  useEffect(() => {
    if (activeTab === "announcement") {
      fetchAnnouncements();
    } else {
      fetchPushes();
    }
    fetchStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, annoPage, annoPageSize, annoKeyword, filterCategory, filterStatus, pushPage, pushPageSize]);

  // ==================== 公告筛选 ====================

  const handleAnnoSearch = () => {
    setAnnoPage(1);
    setAnnoKeyword(annoKeywordInput.trim());
  };

  // ==================== 公告操作 ====================

  const handleAnnoPublish = async (id: number, publish: boolean) => {
    try {
      const res = publish ? await announcementApi.publish(id) : await announcementApi.withdraw(id);
      message.success(res.message || (publish ? "已发布" : "已撤回"));
      fetchAnnouncements();
      fetchStats();
    } catch {
      message.error("操作失败");
    }
  };

  const handleAnnoDelete = async (id: number) => {
    try {
      const res = await announcementApi.remove(id);
      message.success(res.message || "已删除");
      fetchAnnouncements();
      fetchStats();
    } catch {
      message.error("删除失败");
    }
  };

  // ==================== 推送操作 ====================

  const handlePushSend = async (id: number) => {
    try {
      await pushApi.send(id);
      message.success("推送发送成功");
      fetchPushes();
    } catch {
      message.error("发送失败");
    }
  };

  const handlePushCancel = async (id: number) => {
    try {
      await pushApi.cancel(id);
      message.success("推送已取消");
      fetchPushes();
    } catch {
      message.error("取消失败");
    }
  };

  const handlePushDelete = async (id: number) => {
    try {
      await pushApi.delete(id);
      message.success("推送已删除");
      fetchPushes();
    } catch {
      message.error("删除失败");
    }
  };

  // ==================== 导航到编辑器 ====================

  const goCreate = (type: "announcement" | "push") => {
    navigate(`/messages/create?type=${type}`);
  };

  const goEditAnno = (id: number) => {
    navigate(`/messages/edit/${id}?type=announcement`);
  };

  const goEditPush = (id: number) => {
    navigate(`/messages/edit/${id}?type=push`);
  };

  // ==================== 公告表格列定义 ====================

  const annoColumns: ColumnsType<AnnouncementListItem> = [
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      width: 240,
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
      width: 110,
      ellipsis: true,
      render: (d: string | null) => d || <span style={{ color: "#999" }}>-</span>,
    },
    {
      title: (
        <Tooltip title="学生端实际阅读次数">
          <span>阅读数 <EyeOutlined /></span>
        </Tooltip>
      ),
      dataIndex: "read_count",
      key: "read_count",
      width: 80,
      align: "center",
      render: (n: number) => n ?? 0,
    },
    {
      title: "附件",
      dataIndex: "attachment_count",
      key: "attachment_count",
      width: 65,
      align: "center",
      render: (n: number) =>
        n > 0 ? (
          <Tooltip title={`${n} 个附件`}>
            <span>
              <FileOutlined style={{ color: "#1677ff" }} /> {n}
            </span>
          </Tooltip>
        ) : (
          <span style={{ color: "#ccc" }}>-</span>
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
      width: 220,
      fixed: isMobile ? undefined : "right",
      render: (_: any, record: AnnouncementListItem) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => goEditAnno(record.id)}>
            编辑
          </Button>
          {record.status === "published" ? (
            <Popconfirm
              title="撤回后学生端将立即不可见"
              onConfirm={() => handleAnnoPublish(record.id, false)}
              okText="撤回"
              cancelText="取消"
            >
              <Button size="small" icon={<RollbackOutlined />}>撤回</Button>
            </Popconfirm>
          ) : (
            <Popconfirm
              title="发布后学生端立即可见"
              onConfirm={() => handleAnnoPublish(record.id, true)}
              okText="发布"
              cancelText="取消"
            >
              <Button size="small" type="primary" icon={<SendOutlined />}>发布</Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="确定删除？"
            onConfirm={() => handleAnnoDelete(record.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ==================== 推送表格列定义 ====================

  const pushColumns: ColumnsType<CustomPush> = [
    { title: "ID", dataIndex: "id", key: "id", width: 55 },
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      width: 180,
      render: (t: string) => <span style={{ fontWeight: 500 }}>{t || "-"}</span>,
    },
    {
      title: "类型",
      dataIndex: "msg_type",
      key: "msg_type",
      width: 80,
      render: (type: string) => {
        const m = msgTypeIconMap[type] || { color: "default", text: type, icon: null };
        return <Tag color={m.color} icon={m.icon}>{m.text}</Tag>;
      },
    },
    {
      title: "内容预览",
      key: "preview",
      ellipsis: true,
      render: (_: any, r: CustomPush) => {
        if (r.msg_type === "text") return (r.content || "").slice(0, 35) + ((r.content || "").length > 35 ? "..." : "");
        if (r.msg_type === "image") return <Tag color="magenta">图片</Tag>;
        return <Tag color="volcano">模板</Tag>;
      },
    },
    {
      title: "推送方式",
      dataIndex: "push_type",
      key: "push_type",
      width: 95,
      render: (t: string) => {
        const m = pushTypeMap[t] || { color: "default", text: t };
        return <Tag color={m.color}>{m.text}</Tag>;
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 80,
      render: (s: string) => {
        const m = PUSH_STATUS_MAP[s];
        return m ? <Tag color={m.color}>{m.text}</Tag> : <Tag>{s}</Tag>;
      },
    },
    {
      title: "定时时间",
      dataIndex: "scheduled_time",
      key: "scheduled_time",
      width: 140,
      render: (t: string) => (t ? dayjs(t).format("YYYY-MM-DD HH:mm") : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 200,
      fixed: isMobile ? undefined : "right",
      render: (_: any, r: CustomPush) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => goEditPush(r.id)}>编辑</Button>
          {r.status === "pending" && (
            <>
              <Button size="small" type="primary" icon={<SendOutlined />} onClick={() => handlePushSend(r.id)}>
                发送
              </Button>
              <Button size="small" onClick={() => handlePushCancel(r.id)}>取消</Button>
            </>
          )}
          {r.status === "failed" && (
            <Button size="small" type="primary" ghost icon={<SendOutlined />} onClick={() => handlePushSend(r.id)}>
              重试
            </Button>
          )}
          <Popconfirm title="确定删除？" onConfirm={() => handlePushDelete(r.id)} okText="删除" okButtonProps={{ danger: true }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ==================== 渲染 ====================

  const tabItems = [
    {
      key: "announcement",
      label: (
        <span>
          <NotificationOutlined /> 校园通知
        </span>
      ),
      children: null, // 内容在下方统一渲染
    },
    {
      key: "push",
      label: (
        <span>
          <SendOutlined /> 即时推送
        </span>
      ),
      children: null,
    },
  ];

  const isAnno = activeTab === "announcement";

  return (
    <div>
      {/* ===== 统计卡片行 ===== */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={4}>
          <Card size="small" hoverable>
            <Statistic
              title="通知总数"
              value={stats.annoTotal}
              prefix={<NotificationOutlined style={{ color: "#1677ff" }} />}
              valueStyle={{ fontSize: isMobile ? 18 : 22 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small" hoverable>
            <Statistic
              title="已发布"
              value={stats.annoPublished}
              prefix={<SendOutlined style={{ color: "#52c41a" }} />}
              valueStyle={{ fontSize: isMobile ? 18 : 22, color: "#52c41a" }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small" hoverable>
            <Statistic
              title="推送记录"
              value={stats.pushTotal}
              prefix={<ThunderboltOutlined style={{ color: "#722ed1" }} />}
              valueStyle={{ fontSize: isMobile ? 18 : 22 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4} style={{ display: isMobile ? "none" : "block" }}>
          <Card size="small" hoverable>
            <Statistic
              title="待发送"
              value={stats.pushPending}
              prefix={<ClockCircleOutlined style={{ color: "#fa8c16" }} />}
              valueStyle={{ fontSize: 22, color: "#fa8c16" }}
            />
          </Card>
        </Col>
      </Row>

      {/* ===== 主内容区 ===== */}
      <Card
        styles={{ body: { padding: isMobile ? 12 : 24 } }}
        extra={
          <Space>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => goCreate(isAnno ? "announcement" : "push")}
            >
              新建{isAnno ? "通知" : "推送"}
            </Button>
          </Space>
        }
      >
        {/* Tab 切换 */}
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as ActiveTab)}
          items={tabItems}
          size="middle"
          style={{ marginBottom: 16 }}
        />

        {/* 公告筛选栏 */}
        {isAnno && (
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
              onChange={(v) => { setAnnoPage(1); setFilterCategory(v as AnnouncementCategory | ""); }}
            >
              {CATEGORY_OPTIONS.map((c) => (
                <Option key={c.value} value={c.value}>{c.label}</Option>
              ))}
            </Select>
            <Select
              placeholder="全部状态"
              allowClear
              style={{ width: 130 }}
              value={filterStatus || undefined}
              onChange={(v) => { setAnnoPage(1); setFilterStatus(v as AnnouncementStatus | ""); }}
            >
              {STATUS_OPTIONS.map((s) => (
                <Option key={s.value} value={s.value}>{s.label}</Option>
              ))}
            </Select>
            <Input.Search
              placeholder="搜索标题"
              allowClear
              style={{ width: 220 }}
              value={annoKeywordInput}
              onChange={(e) => setAnnoKeywordInput(e.target.value)}
              onSearch={handleAnnoSearch}
              enterButton
            />
          </div>
        )}

        {/* 说明提示 */}
        {isAnno && (
          <Alert
            message="校园通知说明"
            description="纯拉取模式：学生端进入通知页或下拉刷新时主动获取已发布通知。发布后立即可见，撤回后立即不可见。"
            type="info"
            showIcon
            icon={<InfoCircleOutlined />}
            style={{ marginBottom: 16 }}
          />
        )}

        {/* 表格 */}
        <Table
          dataSource={(isAnno ? annoList : pushList) as any}
          columns={(isAnno ? annoColumns : pushColumns) as any}
          rowKey="id"
          loading={loading}
          scroll={{ x: isAnno ? 900 : 1000 }}
          size="middle"
          pagination={{
            current: isAnno ? annoPage : pushPage,
            pageSize: isAnno ? annoPageSize : pushPageSize,
            total: isAnno ? annoTotal : pushTotal,
            showSizeChanger: true,
            showQuickJumper: !isMobile,
            showTotal: (t) => `共 ${t} 条`,
            pageSizeOptions: ["10", "20", "50"],
            onChange: (p, ps) => {
              if (isAnno) {
                setAnnoPage(p);
                setAnnoPageSize(ps);
              } else {
                setPushPage(p);
                setPushPageSize(ps);
              }
            },
          }}
        />
      </Card>
    </div>
  );
}
