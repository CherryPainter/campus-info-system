/**
 * 个人中心页面
 *
 * 设计取向：与仪表盘同一套「卡片网格」视觉语言（16px 间距、等高 hover、标题图标），
 * 但内容是真实个人中心、做到企业级克制——顶部一行概览卡一眼看完关键状态，
 * 下面分内容卡（账户资料 / 安全设置）+ 登录记录表，自然纵向滚动，不堆花活。
 * 功能：
 * - 头像上传、修改用户名（需验证密码）、修改密码
 * - 双因素认证（MFA）管理
 * - 登录记录（按状态筛选 + 加载更多）
 */
import { useState, useEffect, useCallback, type ReactNode } from "react";
import {
  Card,
  Form,
  Input,
  Button,
  Avatar,
  Space,
  Row,
  Col,
  Tag,
  Typography,
  Modal,
  Select,
  Upload,
  Switch,
  App,
  Divider,
  Table,
  Badge,
  Progress,
  Grid,
} from "antd";
import dayjs from "dayjs";
import { formatTimeShort, formatDateTime, formatDate } from "@/utils/datetime";
import {
  UserOutlined,
  EditOutlined,
  LockOutlined,
  HistoryOutlined,
  GlobalOutlined,
  SafetyOutlined,
  MobileOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
} from "@ant-design/icons";
import { userApi, type LoginLog } from "@/api/admin";
import { authApi } from "@/api/auth";
import type { User } from "@/types/user";
import request from "@/api/request";
import { useServerStatus } from "@/components/ServerStatusProvider";
import OtpInput from "@/components/common/OtpInput";

const { Text, Title, Paragraph } = Typography;
const { Option } = Select;

/** 角色 → 中文名 */
const ROLE_LABEL: Record<string, string> = {
  admin: "管理员",
  user: "普通用户",
};

/** 资料卡信息行：左标签固定宽、右侧内容自适应，行间细分隔线 */
function InfoRow({
  label,
  children,
  last = false,
}: {
  label: string;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 0",
        borderBottom: last ? "none" : "1px solid #f5f5f5",
      }}
    >
      <span style={{ width: 72, flexShrink: 0, color: "rgba(0,0,0,0.45)", fontSize: 13 }}>
        {label}
      </span>
      <span style={{ flex: 1, minWidth: 0, fontSize: 13 }}>{children}</span>
    </div>
  );
}

/** 概览卡：与仪表盘 kpi-card 同一观感（标签/大值/副行 + 右上图标），保证整站语言一致 */
function OverviewCard({
  icon,
  label,
  value,
  valueColor,
  sub,
  iconColor,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  valueColor?: string;
  sub?: ReactNode;
  iconColor?: string;
}) {
  return (
    <Card hoverable style={{ height: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, color: "rgba(0,0,0,0.45)" }}>{label}</div>
          <div style={{ fontSize: 28, fontWeight: 600, lineHeight: 1.3, marginTop: 6, color: valueColor }}>
            {value}
          </div>
          {sub && <div style={{ fontSize: 12, color: "rgba(0,0,0,0.45)", marginTop: 4 }}>{sub}</div>}
        </div>
        <div style={{ fontSize: 22, color: iconColor || "#1677ff", opacity: 0.85, flexShrink: 0 }}>
          {icon}
        </div>
      </div>
    </Card>
  );
}

export default function Profile() {
  const { message } = App.useApp();
  const { isOffline } = useServerStatus();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [loading, setLoading] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [passwordForm] = Form.useForm();
  const [changingPassword, setChangingPassword] = useState(false);
  const [usernameModalVisible, setUsernameModalVisible] = useState(false);
  const [usernameForm] = Form.useForm();
  const [changingUsername, setChangingUsername] = useState(false);
  const [logs, setLogs] = useState<LoginLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logPage, setLogPage] = useState(1);
  const [logPageSize] = useState(20);
  const [logTotal, setLogTotal] = useState(0);
  const [logStatus, setLogStatus] = useState<string | undefined>();
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [mfaStatusLoading, setMfaStatusLoading] = useState(false);
  const [mfaSetupVisible, setMfaSetupVisible] = useState(false);
  const [mfaSetupLoading, setMfaSetupLoading] = useState(false);
  const [mfaQrCode, setMfaQrCode] = useState<string>("");
  const [mfaSecret, setMfaSecret] = useState<string>("");
  const [mfaCode, setMfaCode] = useState<string>("");
  const [mfaVerifyLoading, setMfaVerifyLoading] = useState(false);
  const [mfaDisableVisible, setMfaDisableVisible] = useState(false);
  const [mfaDisableCode, setMfaDisableCode] = useState("");
  const [mfaDisableLoading, setMfaDisableLoading] = useState(false);

  // 头像是否有未保存的改动（预置值与已存头像一致时禁用「保存头像」）
  const avatarDirty = (avatarPreview || "") !== (user?.avatar || "");

  useEffect(() => {
    fetchProfile();
    fetchMfaStatus();
    // 仅需挂载时拉取一次，fetchProfile/fetchMfaStatus 每次渲染都会重建身份，故不放依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchProfile = async () => {
    setLoading(true);
    try {
      const res = await userApi.getProfile();
      if (res.status === "success" && res.data) {
        setUser(res.data);
        setAvatarPreview(res.data.avatar || null);
      }
    } catch (error) {
      console.error("获取用户信息失败:", error);
      message.error("获取用户信息失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchMfaStatus = async () => {
    setMfaStatusLoading(true);
    try {
      const res = await authApi.getMfaStatus();
      if (res.status === "success" && res.data) {
        setMfaEnabled(res.data.enabled);
      }
    } catch (error) {
      console.error("获取 MFA 状态失败:", error);
    } finally {
      setMfaStatusLoading(false);
    }
  };

  const handleUpdateProfile = async () => {
    setLoading(true);
    try {
      const res = await userApi.updateProfile({
        avatar: avatarPreview || undefined,
      });
      if ((res as any).status === "success") {
        message.success("头像已更新");
        await fetchProfile();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "更新失败");
    } finally {
      setLoading(false);
    }
  };

  const handleAvatarPreview = (file: File) => {
    const isLt2M = file.size / 1024 / 1024 < 2;
    if (!isLt2M) {
      message.error("头像图片不能超过 2MB");
      return false;
    }
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => {
      setAvatarPreview(reader.result as string);
    };
    return false; // 阻止默认上传行为，使用本地预览
  };

  const handleChangePassword = async (values: any) => {
    if (values.new_password !== values.confirm_password) {
      message.error("两次输入的密码不一致");
      return;
    }
    setChangingPassword(true);
    try {
      const res = await request.post("/auth/change-password", {
        old_password: values.old_password,
        new_password: values.new_password,
      });
      if ((res as any).status === "success") {
        message.success("密码已修改，请重新登录");
        setPasswordModalVisible(false);
        passwordForm.resetFields();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "修改失败");
    } finally {
      setChangingPassword(false);
    }
  };

  const handleChangeUsername = async (values: any) => {
    setChangingUsername(true);
    try {
      const res = await userApi.updateUsername({
        username: values.new_username,
        password: values.password,
      });
      if ((res as any).status === "success") {
        message.success("用户名已修改");
        setUsernameModalVisible(false);
        usernameForm.resetFields();
        await fetchProfile();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "修改失败");
    } finally {
      setChangingUsername(false);
    }
  };

  // MFA 相关方法
  const handleMfaToggle = async (checked: boolean) => {
    if (checked) {
      await handleMfaSetup();
    } else {
      setMfaDisableVisible(true);
    }
  };

  const handleMfaSetup = async () => {
    setMfaSetupLoading(true);
    try {
      const res = await authApi.setupMfa();
      if (res.status === "success" && res.data) {
        setMfaQrCode(res.data.qr_code_base64);
        setMfaSecret(res.data.secret);
        setMfaCode("");
        setMfaSetupVisible(true);
      } else {
        message.error(res.message || "设置失败");
      }
    } catch (error: any) {
      console.error("MFA设置错误:", error);
      message.error(error.response?.data?.message || "设置失败");
    } finally {
      setMfaSetupLoading(false);
    }
  };

  const handleMfaCodeChange = (value: string) => {
    const cleanValue = value.replace(/\D/g, "").slice(0, 6);
    setMfaCode(cleanValue);
  };

  const handleMfaVerify = async () => {
    if (!mfaCode || mfaCode.length !== 6) {
      message.warning("请输入完整的6位验证码");
      return;
    }
    setMfaVerifyLoading(true);
    try {
      const res = await authApi.verifyMfa(mfaCode);
      if ((res as any).status === "success") {
        message.success("双因素认证已启用");
        setMfaSetupVisible(false);
        setMfaEnabled(true);
        setMfaCode("");
      } else {
        message.error(res.message || "验证失败");
        setMfaCode("");
      }
    } catch (error: any) {
      console.error("MFA验证错误:", error);
      message.error(error.response?.data?.message || "验证失败");
      setMfaCode("");
    } finally {
      setMfaVerifyLoading(false);
    }
  };

  const handleMfaDisable = async () => {
    if (!mfaDisableCode || mfaDisableCode.length !== 6) {
      message.warning("请输入完整的6位验证码");
      return;
    }
    setMfaDisableLoading(true);
    try {
      const res = await authApi.disableMfa(mfaDisableCode);
      if ((res as any).status === "success") {
        message.success("双因素认证已禁用");
        setMfaDisableVisible(false);
        setMfaEnabled(false);
        setMfaDisableCode("");
      } else {
        message.error(res.message || "操作失败");
        setMfaDisableCode("");
      }
    } catch (error: any) {
      console.error("MFA禁用错误:", error);
      message.error(error.response?.data?.message || "操作失败");
      setMfaDisableCode("");
    } finally {
      setMfaDisableLoading(false);
    }
  };

  const fetchLogs = useCallback(
    async (page = 1) => {
      setLogsLoading(true);
      try {
        const res = await userApi.getLoginLogs({
          page,
          page_size: logPageSize,
          status: logStatus,
        });
        setLogs(page === 1 ? res.data : (prev) => [...prev, ...res.data]);
        setLogTotal(res.pagination.total);
        setLogPage(page);
      } catch (error) {
        console.error("获取登录日志失败:", error);
        message.error("获取登录日志失败");
      } finally {
        setLogsLoading(false);
      }
    },
    [logPageSize, logStatus, message],
  );

  useEffect(() => {
    fetchLogs(1);
  }, [fetchLogs]);

  const openUsernameModal = () => {
    usernameForm.setFieldValue("new_username", user?.username);
    setUsernameModalVisible(true);
  };

  const handleRefresh = () => {
    fetchProfile();
    fetchMfaStatus();
    fetchLogs(1);
  };

  // ── 派生信息 ──
  const roleLabel = ROLE_LABEL[user?.role || ""] || user?.role || "-";
  const activeDays = user?.created_at
    ? Math.max(0, dayjs().diff(dayjs(user.created_at), "day"))
    : null;

  // 最近登录展示：移动端概览卡较窄，用紧凑日期（MM-DD）避免长值折行
  const lastLogin = user?.last_login ? dayjs(user.last_login) : null;
  const lastLoginOk = !!lastLogin && lastLogin.isValid();
  const lastLoginValue = !user?.last_login
    ? "尚未登录"
    : lastLoginOk
      ? lastLogin!.format(isMobile ? "MM-DD" : "YYYY-MM-DD")
      : "-";
  const lastLoginSub =
    !user?.last_login || !lastLoginOk ? "—" : `${lastLogin!.format("HH:mm")} · ${user.last_login_ip || "-"}`;

  // 安全评分（仅基于后端真实可取的因子，不作任何编造）
  const securityFactors: { ok: boolean; score: number; label: string; tip: string }[] = [
    { ok: mfaEnabled, score: 40, label: "双因素认证", tip: "登录需额外验证码" },
    { ok: !!user?.is_primary, score: 15, label: "主账号", tip: "拥有完整管理权限" },
    { ok: !!user?.email, score: 15, label: "绑定邮箱", tip: "可用于找回与通知" },
    { ok: true, score: 30, label: "基础账户", tip: "已激活且可正常登录" },
  ];
  const securityScore = securityFactors.reduce((s, f) => s + (f.ok ? f.score : 0), 0);
  const securityLevel = securityScore >= 80 ? "高" : securityScore >= 60 ? "中" : "待提升";
  const securityColor =
    securityScore >= 80 ? "#52c41a" : securityScore >= 60 ? "#faad14" : "#ff4d4f";

  const shortenAgent = (agent?: string) => {
    if (!agent) return "";
    const m = agent.match(/(Chrome|Firefox|Safari|Edg|MicroMessenger)\/[\d.]+/);
    return m ? m[0] : agent.slice(0, 24);
  };

  // ── 登录记录表 ──
  const logColumns = [
    {
      title: "状态",
      dataIndex: "status",
      width: 96,
      render: (s: string) => (
        <Space size={6}>
          <Badge status={s === "success" ? "success" : "error"} />
          <Text>{s === "success" ? "成功" : "失败"}</Text>
        </Space>
      ),
    },
    {
      title: "登录时间",
      dataIndex: "login_time",
      render: (t?: string) => (t ? formatDateTime(t) : "-"),
    },
    {
      title: "退出 / 在线时长",
      render: (_: unknown, r: LoginLog) =>
        r.logout_time ? (
          <span>
            {formatTimeShort(r.logout_time)}
            {r.duration ? ` · ${r.duration}` : ""}
          </span>
        ) : (
          <Text type="secondary">在线中</Text>
        ),
    },
    {
      title: "IP 地址",
      dataIndex: "ip_address",
      width: 140,
      render: (ip?: string) => (
        <Space size={4}>
          <GlobalOutlined style={{ color: "rgba(0,0,0,0.45)" }} />
          <span>{ip || "-"}</span>
        </Space>
      ),
    },
    {
      title: "设备",
      render: (_: unknown, r: LoginLog) => shortenAgent(r.user_agent) || "-",
    },
    {
      title: "失败原因",
      render: (_: unknown, r: LoginLog) =>
        r.status !== "success" && r.failure_reason ? (
          <Text style={{ color: "#ff4d4f" }}>{r.failure_reason}</Text>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
  ];

  return (
    <div>
      {/* 页头 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        {/* 与仪表盘一致：PageContainer 已渲染菜单名「个人中心」，此处用不同的内容标题，避免重复 */}
        <Title level={4} style={{ margin: 0 }}>
          账户总览
        </Title>
        <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={logsLoading}>
          刷新
        </Button>
      </div>

      {/* 账户摘要 */}
      <Card style={{ marginBottom: 16 }}>
        <Row align="middle" gutter={[24, 16]} wrap>
          <Col xs={24} sm={4} lg={3} style={{ textAlign: "center" }}>
            <div style={{ position: "relative", display: "inline-block" }}>
              <Avatar
                size={isMobile ? 80 : 92}
                src={avatarPreview}
                icon={!avatarPreview && <UserOutlined />}
                style={{ backgroundColor: "#f0f5ff", color: "#1677ff" }}
              />
              <span
                style={{
                  position: "absolute",
                  right: 6,
                  bottom: 6,
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: "#52c41a",
                  border: "3px solid #fff",
                }}
              />
            </div>
          </Col>
          <Col xs={24} sm={20} lg={21}>
            <Space size={8} wrap align="center">
              <Title level={3} style={{ margin: 0 }}>
                {user?.username || "-"}
              </Title>
              <Tag color={user?.role === "admin" ? "blue" : "default"}>{roleLabel}</Tag>
              {user?.is_primary && (
                <Tag color="gold" style={{ margin: 0 }}>
                  主账号
                </Tag>
              )}
            </Space>
            <div style={{ marginTop: 8 }}>
              <Space size={6} wrap split={<Divider type="vertical" />}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  成员 {activeDays ?? "-"} 天
                </Text>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  上次登录 {user?.last_login ? formatDateTime(user.last_login) : "-"}
                </Text>
                <Space size={4}>
                  <Badge status={isOffline ? "error" : "success"} />
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    服务{isOffline ? "已停止" : "运行中"}
                  </Text>
                </Space>
              </Space>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 概览卡（一眼看完关键状态） */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6} lg={6}>
          <OverviewCard
            icon={<SafetyOutlined />}
            label="双因素认证"
            value={mfaEnabled ? "已启用" : "未启用"}
            valueColor={mfaEnabled ? "#52c41a" : "#ff4d4f"}
            sub={mfaEnabled ? "登录需额外验证" : "建议尽快开启"}
          />
        </Col>
        <Col xs={12} sm={6} lg={6}>
          <OverviewCard
            icon={<ClockCircleOutlined />}
            label="最近登录"
            value={lastLoginValue}
            sub={lastLoginSub}
          />
        </Col>
        <Col xs={12} sm={6} lg={6}>
          <OverviewCard
            icon={<HistoryOutlined />}
            label="登录记录"
            value={logTotal}
            sub="累计登录记录"
          />
        </Col>
        <Col xs={12} sm={6} lg={6}>
          <OverviewCard
            icon={<UserOutlined />}
            label="成员时长"
            value={activeDays != null ? `${activeDays} 天` : "-"}
            sub={user?.created_at ? `自 ${formatDate(user.created_at)}` : "—"}
          />
        </Col>
      </Row>

      {/* 账户与安全 */}
      <div style={{ marginBottom: 6 }}>
        <Text type="secondary" style={{ fontSize: 13, fontWeight: 500 }}>
          账户与安全
        </Text>
      </div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {/* 账户资料 */}
        <Col xs={24} lg={16}>
          <Card title="账户资料">
            <Row gutter={[24, 20]} align="middle">
              <Col xs={24} sm={8} style={{ textAlign: "center" }}>
                <div style={{ position: "relative", display: "inline-block" }}>
                  <Avatar
                    size={isMobile ? 88 : 104}
                    src={avatarPreview}
                    icon={!avatarPreview && <UserOutlined />}
                    style={{ backgroundColor: "#f0f5ff", color: "#1677ff" }}
                  />
                  <span
                    style={{
                      position: "absolute",
                      right: 6,
                      bottom: 6,
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      background: "#52c41a",
                      border: "3px solid #fff",
                    }}
                  />
                </div>
                <div style={{ marginTop: 12 }}>
                  <Upload
                    accept=".jpg,.jpeg,.png,.gif,.webp"
                    showUploadList={false}
                    beforeUpload={handleAvatarPreview}
                  >
                    <Button icon={<EditOutlined />}>更换头像</Button>
                  </Upload>
                </div>
                <div style={{ marginTop: 8 }}>
                  <Button
                    type="primary"
                    loading={loading}
                    disabled={!avatarDirty}
                    onClick={handleUpdateProfile}
                  >
                    保存头像
                  </Button>
                </div>
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    JPG / PNG / GIF / WEBP，不超过 2MB
                  </Text>
                </div>
              </Col>
              <Col xs={24} sm={16}>
                <InfoRow label="用户名">
                  <Space size={8} wrap>
                    <Text strong style={{ fontSize: 14 }}>
                      {user?.username || "-"}
                    </Text>
                    {user?.is_primary && (
                      <Tag color="gold" style={{ margin: 0 }}>
                        主账号
                      </Tag>
                    )}
                    <Button
                      type="link"
                      size="small"
                      icon={<EditOutlined />}
                      style={{ padding: 0, height: "auto" }}
                      onClick={openUsernameModal}
                    >
                      修改
                    </Button>
                  </Space>
                </InfoRow>
                <InfoRow label="角色">
                  <Tag color={user?.role === "admin" ? "blue" : "default"} style={{ margin: 0 }}>
                    {roleLabel}
                  </Tag>
                </InfoRow>
                <InfoRow label="上次登录">
                  <Text type="secondary">{formatDateTime(user?.last_login)}</Text>
                </InfoRow>
                <InfoRow label="登录 IP">
                  <Text type="secondary">{user?.last_login_ip || "-"}</Text>
                </InfoRow>
                <InfoRow label="注册时间" last>
                  <Text type="secondary">{formatDate(user?.created_at)}</Text>
                </InfoRow>
              </Col>
            </Row>
          </Card>
        </Col>

        {/* 安全设置 */}
        <Col xs={24} lg={8}>
          <Card title="安全设置" style={{ height: "100%" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 12,
                padding: 12,
                background: "#fafafa",
                borderRadius: 8,
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div>
                  <MobileOutlined style={{ marginRight: 6, color: "#8c8c8c" }} />
                  <Text strong>双因素认证</Text>
                </div>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {mfaEnabled ? "已启用 - 登录时需要额外验证" : "未启用 - 建议开启以提高账户安全性"}
                  </Text>
                </div>
              </div>
              <Switch
                checked={mfaEnabled}
                onChange={handleMfaToggle}
                loading={mfaStatusLoading || mfaSetupLoading}
              />
            </div>
            <Divider style={{ margin: "16px 0" }} />
            <Space direction="vertical" size={10} style={{ width: "100%" }}>
              <Button type="primary" block icon={<LockOutlined />} onClick={() => setPasswordModalVisible(true)}>
                修改密码
              </Button>
              <Button block icon={<UserOutlined />} onClick={openUsernameModal}>
                修改用户名
              </Button>
            </Space>

            <Divider style={{ margin: "16px 0" }} />
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Progress percent={securityScore} showInfo={false} strokeColor={securityColor} style={{ flex: 1 }} />
              <Text strong style={{ color: securityColor, fontSize: 13, whiteSpace: "nowrap" }}>
                {securityLevel}
              </Text>
            </div>
            <div style={{ marginTop: 8 }}>
              {securityFactors.map((f) => (
                <div key={f.label} style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                  {f.ok ? (
                    <CheckCircleFilled style={{ color: "#52c41a", fontSize: 13 }} />
                  ) : (
                    <CloseCircleFilled style={{ color: "#bfbfbf", fontSize: 13 }} />
                  )}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {f.label}
                    {!f.ok && <span style={{ marginLeft: 4 }}>（可 +{f.score} 分）</span>}
                  </Text>
                </div>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      {/* 登录记录 */}
      <Card
        title={`登录记录（共 ${logTotal} 条${logStatus ? "，已筛选" : ""}）`}
        extra={
          <Space>
            <Select
              value={logStatus}
              onChange={(v) => setLogStatus(v)}
              placeholder="筛选状态"
              style={{ width: 120 }}
              allowClear
            >
              <Option value="success">成功</Option>
              <Option value="failed">失败</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={() => fetchLogs(1)} loading={logsLoading}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table<LoginLog>
          rowKey="id"
          size="middle"
          columns={logColumns}
          dataSource={logs}
          loading={logsLoading}
          pagination={false}
          scroll={{ x: 680 }}
          locale={{
            emptyText: logStatus ? "当前筛选条件下暂无登录记录" : "暂无登录记录，请重新登录以记录",
          }}
        />
        {logTotal > logs.length && (
          <div style={{ textAlign: "center", marginTop: 12 }}>
            <Button onClick={() => fetchLogs(logPage + 1)} loading={logsLoading}>
              加载更多（已显示 {logs.length} / {logTotal}）
            </Button>
          </div>
        )}
      </Card>

      {/* 修改密码弹窗 */}
      <Modal
        title="修改密码"
        open={passwordModalVisible}
        onCancel={() => {
          setPasswordModalVisible(false);
          passwordForm.resetFields();
        }}
        footer={null}
      >
        <Form form={passwordForm} layout="vertical" onFinish={handleChangePassword}>
          <Form.Item label="当前密码" name="old_password" rules={[{ required: true, message: "请输入当前密码" }]}>
            <Input.Password placeholder="请输入当前密码" />
          </Form.Item>
          <Form.Item label="新密码" name="new_password" rules={[{ required: true, message: "请输入新密码" }, { min: 6, message: "密码长度至少6位" }]}>
            <Input.Password placeholder="请输入新密码" />
          </Form.Item>
          <Form.Item label="确认新密码" name="confirm_password" rules={[{ required: true, message: "请再次输入新密码" }]}>
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
          <Form.Item>
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button onClick={() => setPasswordModalVisible(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={changingPassword}>
                确认修改
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 修改用户名弹窗 */}
      <Modal
        title="修改用户名"
        open={usernameModalVisible}
        onCancel={() => {
          setUsernameModalVisible(false);
          usernameForm.resetFields();
        }}
        footer={null}
      >
        <Form form={usernameForm} layout="vertical" onFinish={handleChangeUsername}>
          <Form.Item label="新用户名" name="new_username" rules={[{ required: true, message: "请输入新用户名" }, { min: 3, message: "用户名至少3个字符" }]}>
            <Input placeholder="请输入新用户名" />
          </Form.Item>
          <Form.Item label="确认密码" name="password" rules={[{ required: true, message: "请输入密码确认身份" }]}>
            <Input.Password placeholder="请输入当前密码" />
          </Form.Item>
          <Form.Item>
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button onClick={() => setUsernameModalVisible(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={changingUsername}>
                {usernameForm.getFieldValue("new_username") === user?.username ? "确认" : "确认修改"}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 设置 MFA 弹窗 */}
      <Modal
        title="设置双因素认证"
        open={mfaSetupVisible}
        onCancel={() => {
          setMfaSetupVisible(false);
          setMfaCode("");
        }}
        footer={null}
        centered
        width={450}
      >
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 64, height: 64, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" }}>
            <MobileOutlined style={{ fontSize: 32, color: "#1890ff" }} />
          </div>
          <Title level={4} style={{ marginBottom: 8, fontSize: 16, fontWeight: 500 }}>
            扫描二维码
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 24, fontSize: 14 }}>
            请打开 Google Authenticator 或类似应用，扫描下方二维码
          </Paragraph>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 24, padding: 16, backgroundColor: "#fff", borderRadius: 8, border: "1px solid #e8e8e8" }}>
            <img src={mfaQrCode} alt="MFA QR Code" style={{ maxWidth: 200, maxHeight: 200 }} />
          </div>
          <div style={{ marginBottom: 24 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              备用密钥（手动输入）
            </Text>
            <div style={{ marginTop: 8, padding: 12, backgroundColor: "#f5f5f5", borderRadius: 4, fontFamily: "monospace", fontSize: 14, wordBreak: "break-all" }}>
              {mfaSecret}
            </div>
          </div>
          <OtpInput value={mfaCode} onChange={handleMfaCodeChange} autoFocus />
          <div style={{ display: "flex", justifyContent: "center", gap: 8, color: "#8c8c8c", fontSize: 12, marginTop: 8 }}>
            <ClockCircleOutlined />
            <span>验证码每30秒更新一次</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <Button size="large" onClick={() => { setMfaSetupVisible(false); setMfaCode(""); }}>
              取消
            </Button>
            <Button type="primary" size="large" loading={mfaVerifyLoading} onClick={handleMfaVerify} disabled={mfaCode.length !== 6}>
              启用双因素认证
            </Button>
          </div>
        </div>
      </Modal>

      {/* 禁用 MFA 弹窗 */}
      <Modal
        title="禁用双因素认证"
        open={mfaDisableVisible}
        onCancel={() => {
          setMfaDisableVisible(false);
          setMfaDisableCode("");
        }}
        footer={null}
        centered
        width={400}
      >
        <div style={{ textAlign: "center" }}>
          <Title level={4} style={{ marginBottom: 8, fontSize: 16, fontWeight: 500 }}>
            确认禁用
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 24, fontSize: 14 }}>
            请输入当前的双因素认证验证码以确认禁用
          </Paragraph>
          <OtpInput value={mfaDisableCode} onChange={setMfaDisableCode} autoFocus />
          <div style={{ display: "flex", justifyContent: "center", gap: 8, color: "#8c8c8c", fontSize: 12, marginTop: 8 }}>
            <ClockCircleOutlined />
            <span>验证码每30秒更新一次</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <Button size="large" onClick={() => { setMfaDisableVisible(false); setMfaDisableCode(""); }}>
              取消
            </Button>
            <Button type="primary" danger size="large" loading={mfaDisableLoading} onClick={handleMfaDisable} disabled={mfaDisableCode.length !== 6}>
              确认禁用
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
