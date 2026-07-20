/**
 * 会话管理（子组件）
 * 权限逻辑与「用户管理」一致：
 *  - 自己不能踢自己（当前登录会话禁踢）
 *  - 普管（admin 且非主管理员）只能踢普通用户的会话，不能踢任何管理员
 *  - 超管（主管理员）可踢全部
 * 普通用户视图：只展示自己的会话，提供「全设备登出（保留当前）」
 * 管理员视图：展示全部会话（含所属用户），提供单设备踢除
 * 被 AccessControl 的「会话」Tab 复用
 */
import { useState, useCallback } from "react";
import {
  Card,
  Button,
  Space,
  Tag,
  Popconfirm,
  Empty,
  Tooltip,
  App,
  Grid,
  Divider,
  Spin,
} from "antd";
import { formatDateTime } from "@/utils/datetime";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  LogoutOutlined,
  DeleteOutlined,
  DesktopOutlined,
  MobileOutlined,
  CheckCircleTwoTone,
} from "@ant-design/icons";
import { authApi, type UserSession } from "@/api/auth";
import { useUser } from "@/contexts/UserContext";
import { useIntervalPolling } from "@/hooks/useIntervalPolling";
import { POLL_NORMAL } from "@/hooks/pollIntervals";

/** 从 cookie 中读取当前会话 id */
function getCurrentSessionId(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)session_id=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/** 简单解析 User-Agent，提取设备/浏览器/系统 */
function parseUA(ua: string): { device: string; browser: string; os: string } {
  if (!ua) return { device: "未知设备", browser: "未知", os: "未知" };
  const isMobile = /Mobile|Android|iPhone|iPad|iPod/i.test(ua);
  const device = isMobile ? "移动设备" : "桌面设备";
  let browser = "未知浏览器";
  if (/Edg\//.test(ua)) browser = "Edge";
  else if (/OPR\/|Opera/.test(ua)) browser = "Opera";
  else if (/Chrome\//.test(ua)) browser = "Chrome";
  else if (/Firefox\//.test(ua)) browser = "Firefox";
  else if (/Safari\//.test(ua)) browser = "Safari";
  let os = "未知系统";
  if (/Windows NT/.test(ua)) os = "Windows";
  else if (/Mac OS X/.test(ua)) os = "macOS";
  else if (/Android/.test(ua)) os = "Android";
  else if (/iPhone|iPad|iPod/.test(ua)) os = "iOS";
  else if (/Linux/.test(ua)) os = "Linux";
  return { device, browser, os };
}

/** 格式化时间 */
function fmt(ts?: string): string {
  if (!ts) return "-";
  return formatDateTime(ts);
}

/** 角色标签 */
function RoleTag({ role, isPrimary }: { role?: string; isPrimary?: boolean }) {
  if (isPrimary) return <Tag color="gold">超管</Tag>;
  if (role === "admin") return <Tag color="blue">管理员</Tag>;
  return <Tag>普通用户</Tag>;
}

export default function SessionManager() {
  const { message } = App.useApp();
  const { user: currentUser, isPrimary } = useUser();
  const isAdmin = currentUser?.role === "admin";
  const currentSid = getCurrentSessionId();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeAllLoading, setRevokeAllLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authApi.getSessions();
      if (res.status === "success") {
        setSessions(res.data?.sessions || []);
      } else {
        message.error(res.message || "加载会话列表失败");
      }
    } catch (e: any) {
      message.error(e?.response?.data?.message || "加载会话列表失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useIntervalPolling(loadSessions, POLL_NORMAL);

  /** 单设备踢出 */
  const handleRevoke = async (session: UserSession) => {
    setRevoking(session.session_id);
    try {
      const res = await authApi.revokeSession(session.session_id);
      if (res.status === "success") {
        message.success("已踢出该设备");
        await loadSessions();
      } else {
        message.error(res.message || "操作失败");
      }
    } catch (e: any) {
      message.error(e?.response?.data?.message || "操作失败");
    } finally {
      setRevoking(null);
    }
  };

  /** 全设备登出（保留当前）——仅普通用户视图使用 */
  const handleRevokeAll = async () => {
    setRevokeAllLoading(true);
    try {
      const res = await authApi.revokeAllSessions();
      if (res.status === "success") {
        message.success(res.message || `已撤销 ${res.data?.count ?? 0} 个其他设备`);
        await loadSessions();
      } else {
        message.error(res.message || "操作失败");
      }
    } catch (e: any) {
      message.error(e?.response?.data?.message || "操作失败");
    } finally {
      setRevokeAllLoading(false);
    }
  };

  /** 计算某条会话「踢出」按钮是否禁用及禁用原因 */
  const getRevokeDisable = (row: UserSession): { disabled: boolean; tip: string } => {
    if (row.session_id === currentSid) {
      return { disabled: true, tip: "当前正在使用的设备" };
    }
    // 普管不能踢其他管理员的会话（自己作为管理员的会话除外）
    if (isAdmin && !isPrimary) {
      if (row.owner_role === "admin" && row.owner_username !== currentUser?.username) {
        return { disabled: true, tip: "无权踢出管理员会话" };
      }
    }
    return { disabled: false, tip: "" };
  };

  const baseColumns = [
    {
      title: "设备",
      key: "device",
      render: (_: any, row: UserSession) => {
        const { device, browser, os } = parseUA(row.user_agent);
        return (
          <Space>
            {device === "移动设备" ? <MobileOutlined /> : <DesktopOutlined />}
            <span>
              {browser} · {os}
            </span>
          </Space>
        );
      },
    },
    {
      title: "IP 地址",
      dataIndex: "ip_address",
      key: "ip_address",
      render: (ip: string) => <Tag color="blue">{ip || "-"}</Tag>,
    },
    {
      title: "登录时间",
      dataIndex: "created_at",
      key: "created_at",
      render: (ts: string) => fmt(ts),
    },
    {
      title: "最后活跃",
      dataIndex: "updated_at",
      key: "updated_at",
      render: (ts: string) => fmt(ts),
    },
    {
      title: "状态",
      key: "status",
      render: (_: any, row: UserSession) => {
        if (row.session_id === currentSid) {
          return (
            <Tooltip title="当前正在使用的设备">
              <Tag color="green" icon={<CheckCircleTwoTone twoToneColor="#52c41a" />}>
                当前设备
              </Tag>
            </Tooltip>
          );
        }
        return row.is_active ? <Tag color="green">活跃</Tag> : <Tag>已失效</Tag>;
      },
    },
    {
      title: "操作",
      key: "action",
      render: (_: any, row: UserSession) => {
        const { disabled, tip } = getRevokeDisable(row);
        return (
          <Tooltip title={disabled ? tip : ""}>
            <Popconfirm
              title="确认踢出该设备？"
              description="该设备将立即退出登录"
              okText="踢出"
              cancelText="取消"
              disabled={disabled}
              onConfirm={() => handleRevoke(row)}
            >
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                loading={revoking === row.session_id}
                disabled={disabled}
              >
                {row.session_id === currentSid ? "当前设备" : "踢出"}
              </Button>
            </Popconfirm>
          </Tooltip>
        );
      },
    },
  ];

  // 管理员视图追加「用户」列
  const userColumn = {
    title: "用户",
    key: "owner",
    render: (_: any, row: UserSession) => (
      <Space>
        <span>{row.owner_username || "-"}</span>
        <RoleTag role={row.owner_role} isPrimary={row.owner_is_primary} />
      </Space>
    ),
  };

  const columns = isAdmin ? [userColumn, ...baseColumns] : baseColumns;

  return (
    <Card
      title="登录会话"
      extra={
        !isAdmin ? (
          <Button
            danger
            icon={<LogoutOutlined />}
            loading={revokeAllLoading}
            onClick={handleRevokeAll}
          >
            全设备登出（保留当前）
          </Button>
        ) : undefined
      }
    >
      {isMobile ? (
        // 手机端：每个会话一张专用卡片，竖向排列
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {loading && sessions.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 0" }}>
              <Spin />
            </div>
          ) : sessions.length === 0 ? (
            <Empty description={isAdmin ? "暂无活跃会话" : "暂无其他活跃会话"} />
          ) : (
            sessions.map((row) => {
              const { device, browser, os } = parseUA(row.user_agent);
              const { disabled, tip } = getRevokeDisable(row);
              const isCurrent = row.session_id === currentSid;
              return (
                <Card key={row.session_id} size="small">
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <Space size={6}>
                      {device === "移动设备" ? <MobileOutlined /> : <DesktopOutlined />}
                      <span>
                        {browser} · {os}
                      </span>
                    </Space>
                    {isCurrent ? (
                      <Tooltip title="当前正在使用的设备">
                        <Tag color="green" icon={<CheckCircleTwoTone twoToneColor="#52c41a" />}>
                          当前设备
                        </Tag>
                      </Tooltip>
                    ) : row.is_active ? (
                      <Tag color="green">活跃</Tag>
                    ) : (
                      <Tag>已失效</Tag>
                    )}
                  </div>
                  {isAdmin && (
                    <div style={{ marginTop: 6 }}>
                      <Space size={4}>
                        <span>{row.owner_username || "-"}</span>
                        <RoleTag role={row.owner_role} isPrimary={row.owner_is_primary} />
                      </Space>
                    </div>
                  )}
                  <Divider style={{ margin: "10px 0" }} />
                  <div style={{ fontSize: 12, color: "#666", lineHeight: "20px" }}>
                    <div>IP：{row.ip_address || "-"}</div>
                    <div>登录时间：{fmt(row.created_at)}</div>
                    <div>最后活跃：{fmt(row.updated_at)}</div>
                  </div>
                  <div style={{ marginTop: 10, textAlign: "right" }}>
                    <Tooltip title={disabled ? tip : ""}>
                      <Popconfirm
                        title="确认踢出该设备？"
                        description="该设备将立即退出登录"
                        okText="踢出"
                        cancelText="取消"
                        disabled={disabled}
                        onConfirm={() => handleRevoke(row)}
                      >
                        <Button
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                          loading={revoking === row.session_id}
                          disabled={disabled}
                        >
                          {isCurrent ? "当前设备" : "踢出"}
                        </Button>
                      </Popconfirm>
                    </Tooltip>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      ) : (
        <ResponsiveTable<UserSession>
          rowKey="session_id"
          columns={columns}
          dataSource={sessions}
          loading={loading}
          pagination={false}
          locale={{
            emptyText: <Empty description={isAdmin ? "暂无活跃会话" : "暂无其他活跃会话"} />,
          }}
        />
      )}
    </Card>
  );
}
