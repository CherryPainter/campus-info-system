/**
 * 意见与反馈 管理页面
 *
 * 管理员查看学生提交的反向反馈，支持：
 * - 按状态筛选（待处理 / 处理中 / 已解决）
 * - 查看反馈详情（类型 / 内容 / 截图 / 提交时间 / 联系方式）
 * - 标记处理状态（pending / processing / resolved）
 * - 回复学生（回复后自动置为已解决）
 *
 * 与「消息中心」（管理员 → 学生推送）完全独立，是两条不同的通道。
 */
import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Button,
  Space,
  Tag,
  Drawer,
  Input,
  Descriptions,
  Segmented,
  Image,
  Spin,
  Alert,
  Empty,
  Typography,
  Grid,
} from "antd";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  MessageOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  SendOutlined,
} from "@ant-design/icons";
import { feedbackApi, FEEDBACK_TYPE_OPTIONS, FEEDBACK_STATUS_OPTIONS } from "@/api/feedback";
import type { FeedbackDetail, FeedbackItem, FeedbackStatus } from "@/api/feedback";
import { useMessage } from "@/utils/message";

const { TextArea } = Input;
const { Text } = Typography;

const TYPE_COLOR: Record<string, string> = Object.fromEntries(
  FEEDBACK_TYPE_OPTIONS.map((o) => [o.value, o.color])
);
const TYPE_LABEL: Record<string, string> = Object.fromEntries(
  FEEDBACK_TYPE_OPTIONS.map((o) => [o.value, o.label])
);
const STATUS_COLOR: Record<string, string> = Object.fromEntries(
  FEEDBACK_STATUS_OPTIONS.map((o) => [o.value, o.color])
);
const STATUS_LABEL: Record<string, string> = Object.fromEntries(
  FEEDBACK_STATUS_OPTIONS.map((o) => [o.value, o.label])
);

export default function FeedbackPage() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<FeedbackStatus | "">("");
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [current, setCurrent] = useState<FeedbackDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reply, setReply] = useState("");
  const [acting, setActing] = useState(false);
  const message = useMessage();

  const PAGE_SIZE = 20;

  const fetchList = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      try {
        const res = await feedbackApi.list({
          page: targetPage,
          page_size: PAGE_SIZE,
          status: statusFilter,
        });
        if (res.status === "success" && res.data) {
          setItems(res.data.items);
          setTotal(res.data.total);
          setPage(targetPage);
        } else {
          message.error(res.message || "加载反馈列表失败");
        }
      } catch {
        message.error("加载反馈列表失败");
      } finally {
        setLoading(false);
      }
    },
    [statusFilter, message]
  );

  useEffect(() => {
    fetchList(1);
  }, [fetchList]);

  const openDetail = async (id: number) => {
    setDrawerOpen(true);
    setCurrent(null);
    setReply("");
    setDetailLoading(true);
    try {
      const res = await feedbackApi.detail(id);
      if (res.status === "success" && res.data) {
        setCurrent(res.data.feedback);
        setReply(res.data.feedback.reply || "");
      } else {
        message.error(res.message || "加载详情失败");
      }
    } catch {
      message.error("加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleResolve = async (status: FeedbackStatus) => {
    if (!current) return;
    setActing(true);
    try {
      const res = await feedbackApi.resolve(current.id, status);
      if (res.status === "success" && res.data) {
        message.success(`已标记为「${STATUS_LABEL[status]}」`);
        setCurrent(res.data.feedback);
        fetchList(page);
      } else {
        message.error(res.message || "操作失败");
      }
    } catch {
      message.error("操作失败");
    } finally {
      setActing(false);
    }
  };

  const handleReply = async () => {
    if (!current) return;
    if (!reply.trim()) {
      message.warning("请输入回复内容");
      return;
    }
    setActing(true);
    try {
      const res = await feedbackApi.reply(current.id, reply.trim());
      if (res.status === "success" && res.data) {
        message.success("已回复并标记为已解决");
        setCurrent(res.data.feedback);
        fetchList(page);
      } else {
        message.error(res.message || "回复失败");
      }
    } catch {
      message.error("回复失败");
    } finally {
      setActing(false);
    }
  };

  const columns = [
    {
      title: "类型",
      dataIndex: "type",
      key: "type",
      width: 110,
      render: (t: string) => <Tag color={TYPE_COLOR[t]}>{TYPE_LABEL[t] || t}</Tag>,
    },
    {
      title: "内容",
      dataIndex: "content",
      key: "content",
      ellipsis: true,
      render: (text: string) => <span style={{ color: "#1d2129" }}>{text}</span>,
    },
    {
      title: "提交用户",
      dataIndex: "user_id",
      key: "user_id",
      width: 100,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (s: string) => <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s] || s}</Tag>,
    },
    {
      title: "提交时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (t: string) => <span style={{ color: "#8a8f99", fontSize: 13 }}>{t}</span>,
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      render: (_: any, record: FeedbackItem) => (
        <Button size="small" type="link" onClick={() => openDetail(record.id)}>
          查看
        </Button>
      ),
    },
  ];

  const pendingCount = items.filter((i) => i.status === "pending").length;

  return (
    <div>
      <Card styles={{ body: { padding: isMobile ? 12 : 24 } }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <Segmented
            value={statusFilter || "all"}
            onChange={(v) => setStatusFilter(v === "all" ? "" : (v as FeedbackStatus))}
            options={[
              { label: "全部", value: "all" },
              ...FEEDBACK_STATUS_OPTIONS.map((o) => ({ label: o.label, value: o.value })),
            ]}
          />
          <Text type="secondary" style={{ fontSize: 13 }}>
            共 {total} 条，其中待处理 {pendingCount} 条
          </Text>
        </div>

        <Alert
          type="info"
          showIcon
          icon={<MessageOutlined />}
          message="意见与反馈是学生对系统的反向反馈（独立于消息中心），处理后可回复，学生端会看到处理结果。"
          style={{ marginBottom: 16 }}
        />

        <ResponsiveTable
          dataSource={items}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            onChange: (p) => fetchList(p),
            showSizeChanger: false,
          }}
          scroll={{ x: 700 }}
          onRow={(record) => ({
            onClick: () => openDetail(record.id),
            style: { cursor: "pointer" },
          })}
        />
      </Card>

      <Drawer
        title="反馈详情"
        width={isMobile ? "100%" : 520}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        footer={
          current ? (
            <Space wrap>
              <Button
                icon={<SyncOutlined />}
                loading={acting}
                onClick={() => handleResolve("processing")}
                disabled={current.status === "processing"}
              >
                标记处理中
              </Button>
              <Button
                icon={<CheckCircleOutlined />}
                loading={acting}
                onClick={() => handleResolve("resolved")}
                disabled={current.status === "resolved"}
              >
                标记已解决
              </Button>
            </Space>
          ) : null
        }
      >
        {detailLoading ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin />
          </div>
        ) : current ? (
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="类型">
                <Tag color={TYPE_COLOR[current.type]}>{TYPE_LABEL[current.type]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[current.status]}>{STATUS_LABEL[current.status]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="提交用户">用户 #{current.user_id}</Descriptions.Item>
              {current.contact ? (
                <Descriptions.Item label="联系方式">{current.contact}</Descriptions.Item>
              ) : null}
              <Descriptions.Item label="提交时间">{current.created_at}</Descriptions.Item>
            </Descriptions>

            <div>
              <Text strong>反馈内容</Text>
              <div
                style={{
                  marginTop: 8,
                  padding: 12,
                  background: "#f6f7fb",
                  borderRadius: 8,
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.7,
                  fontSize: 14,
                  color: "#1d2129",
                }}
              >
                {current.content}
              </div>
            </div>

            {current.images && current.images.length > 0 ? (
              <div>
                <Text strong>截图</Text>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {current.images.map((url, i) => (
                    <Image
                      key={url + i}
                      src={`/api/feedback-images${url.startsWith("/") ? url : "/" + url}`}
                      width={100}
                      height={100}
                      style={{ borderRadius: 8, objectFit: "cover" }}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            <div>
              <Text strong>回复学生</Text>
              <TextArea
                rows={4}
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder="输入回复内容，学生端将看到处理结果"
                style={{ marginTop: 8 }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={acting}
                onClick={handleReply}
                style={{ marginTop: 12 }}
                block
              >
                发送回复（并标记为已解决）
              </Button>
            </div>

            {current.reply ? (
              <div>
                <Text strong>已回复</Text>
                <div
                  style={{
                    marginTop: 8,
                    padding: 12,
                    background: "#e8f0fe",
                    borderRadius: 8,
                    whiteSpace: "pre-wrap",
                    lineHeight: 1.7,
                    fontSize: 14,
                    color: "#1d2129",
                  }}
                >
                  {current.reply}
                </div>
                {current.replied_at ? (
                  <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: "block" }}>
                    回复时间：{current.replied_at}
                  </Text>
                ) : null}
              </div>
            ) : null}
          </Space>
        ) : (
          <Empty description="暂无详情" />
        )}
      </Drawer>
    </div>
  );
}
