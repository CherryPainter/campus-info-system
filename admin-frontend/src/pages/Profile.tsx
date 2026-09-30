/**
 * 个人中心页面
 *
 * 设计：区别于仪表盘的「全局监控大屏」范式，采用个人空间的标准结构——
 *   顶部个人横幅（头像 + 身份标识 + 安全评分环）
 *   下方左栏导航 / 右侧面板切换（账户资料 · 登录安全 · 登录记录）
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
  Empty,
  Tabs,
  Progress,
  Grid,
  Badge,
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
  IdcardOutlined,
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

  // 当前激活的面板（账户资料 / 登录安全 / 登录记录）
  const [tab, setTab] = useState("profile");

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

  // 处理 Base64 头像预览（前端先做类型/大小校验，后端再做权威校验）
  const handleAvatarPreview = (file: File) => {
    const allowedTypes = ["image/jpeg", "image/png", "image/gif", "image/webp"];
    if (!allowedTypes.includes(file.type)) {
      message.error("仅支持 JPG / PNG / GIF / WEBP 格式头像");
      return false;
    }
    if (file.size > 2 * 1024 * 1024) {
      message.error("头像大小不能超过 2MB");
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

  // ── 派生信息 ──
  const roleLabel = ROLE_LABEL[user?.role || ""] || user?.role || "-";
  const activeDays = user?.created_at
    ? Math.max(0, dayjs().diff(dayjs(user.created_at), "day"))
    : null;

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

  // 登录会话卡片
  const shortenAgent = (agent?: string) => {
    if (!agent) return "";
    const m = agent.match(/(Chrome|Firefox|Safari|Edg|MicroMessenger)\/[\d.]+/);
    return m ? m[0] : agent.slice(0, 24);
  };
  const SessionCard = ({ log }: { log: LoginLog }) => {
    const isSuccess = log.status === "success";
    const agent = shortenAgent(log.user_agent);
    return (
      <div
        style={{
          border: "1px solid #f0f0f0",
          borderRadius: 8,
          padding: "12px 14px",
          marginBottom: 12,
          transition: "all 0.2s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#d6e4ff")}
        onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#f0f0f0")}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Space size={8}>
            <Badge status={isSuccess ? "success" : "error"} />
            <Text strong>{isSuccess ? "登录成功" : "登录失败"}</Text>
          </Space>
          <Text type="secondary" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
            {formatTimeShort(log.login_time)}
          </Text>
        </div>
        <div style={{ marginTop: 8 }}>
          <Space size={6} wrap split={<Divider type="vertical" style={{ margin: "0 2px", borderColor: "#f0f0f0" }} />}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              <GlobalOutlined style={{ marginRight: 4 }} />
              {log.ip_address || "-"}
            </Text>
            {agent && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {agent}
              </Text>
            )}
            {log.logout_time && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                退出 {formatTimeShort(log.logout_time)}
              </Text>
            )}
            {log.duration && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                在线 {log.duration}
              </Text>
            )}
          </Space>
        </div>
        {!isSuccess && log.failure_reason && (
          <div style={{ color: "#ff4d4f", fontSize: 12, marginTop: 6 }}>
            原因：{log.failure_reason}
          </div>
        )}
      </div>
    );
  };

  // ── 三个面板 ──
  const renderProfilePanel = () => (
    <Card>
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
            <Button type="primary" loading={loading} disabled={!avatarDirty} onClick={handleUpdateProfile}>
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
  );

  const renderSecurityPanel = () => (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={14}>
        <Card>
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
        </Card>
      </Col>
      <Col xs={24} md={10}>
        <Card title="安全评分">
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Progress type="circle" percent={securityScore} size={84} strokeColor={securityColor} format={() => securityScore} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text strong style={{ color: securityColor }}>
                安全等级：{securityLevel}
              </Text>
              <div style={{ marginTop: 6 }}>
                {securityFactors.map((f) => (
                  <div key={f.label} style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                    {f.ok ? (
                      <CheckCircleFilled style={{ color: "#52c41a", fontSize: 13 }} />
                    ) : (
                      <CloseCircleFilled style={{ color: "#bfbfbf", fontSize: 13 }} />
                    )}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {f.label}
                      {!f.ok && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          （可 +{f.score} 分）
                        </Text>
                      )}
                    </Text>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      </Col>
    </Row>
  );

  const renderLogsPanel = () => (
    <Card
      title={
        <span>
          共 {logTotal} 条{logStatus ? "（已筛选）" : ""}
        </span>
      }
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
      {(!logs || logs.length === 0) && !logsLoading && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={logStatus ? "当前筛选条件下暂无登录记录" : "暂无登录记录，请重新登录以记录"}
          style={{ padding: "40px 0" }}
        />
      )}
      {logs && logs.length > 0 && (
        <>
          <div>
            {logs.map((log) => (
              <SessionCard key={log.id} log={log} />
            ))}
          </div>
          {logTotal > logs.length && (
            <div style={{ textAlign: "center", marginTop: 4 }}>
              <Button onClick={() => fetchLogs(logPage + 1)} loading={logsLoading}>
                加载更多（已显示 {logs.length} / {logTotal}）
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );

  return (
    <div>
      {/* 顶部个人横幅 */}
      <Card style={{ marginBottom: 16, position: "relative", overflow: "hidden" }}>
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 4,
            background: "#1677ff",
          }}
        />
        <Row align="middle" gutter={[24, 16]} wrap>
          {/* 断点：<md 竖排（各占满宽），>=md 横排三栏（头像 5 / 身份 13 / 安全环 6） */}
          <Col xs={24} md={5} lg={4} style={{ textAlign: "center" }}>
            <div style={{ position: "relative", display: "inline-block" }}>
              <Avatar
                size={isMobile ? 80 : 96}
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
          <Col xs={24} md={13} lg={14}>
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
                  上次登录 {formatDateTime(user?.last_login)}
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
          <Col xs={24} md={6} style={{ textAlign: "center" }}>
            <Progress
              type="circle"
              percent={securityScore}
              size={isMobile ? 72 : 84}
              strokeColor={securityColor}
              format={() => securityScore}
            />
            <div style={{ marginTop: 4 }}>
              <Text style={{ color: securityColor, fontSize: 12 }}>安全等级：{securityLevel}</Text>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 左栏导航 / 右侧面板（桌面左栏、移动顶部） */}
      <Tabs
        activeKey={tab}
        onChange={setTab}
        tabPosition={isMobile ? "top" : "left"}
        tabBarGutter={isMobile ? 12 : 32}
        items={[
          {
            key: "profile",
            label: (
              <span>
                <IdcardOutlined style={{ marginRight: 6 }} />
                账户资料
              </span>
            ),
            children: renderProfilePanel(),
          },
          {
            key: "security",
            label: (
              <span>
                <SafetyOutlined style={{ marginRight: 6 }} />
                登录安全
              </span>
            ),
            children: renderSecurityPanel(),
          },
          {
            key: "logs",
            label: (
              <span>
                <HistoryOutlined style={{ marginRight: 6 }} />
                登录记录
              </span>
            ),
            children: renderLogsPanel(),
          },
        ]}
      />

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
                确认修改
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
