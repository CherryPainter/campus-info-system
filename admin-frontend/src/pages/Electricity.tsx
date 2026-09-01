/**
 * 电量管理页面（管理端改版 2026-09-01）
 *
 * 用户化改造后，电量数据按学生（user_id）隔离，本页改为学生维度管理：
 * - 学生总览：全部微信端学生 + 配置状态 + 最新剩余电量/低电量标记（未配置标灰）
 * - 用电明细：选中学生后切换到此 Tab，查看剩余电量 / 用电记录 / 统计图表
 * - 模块配置：模块级通用配置（Cookie 由学生在小程序自配，本页不再管理全局 Cookie）
 *
 * 历史全局数据（user_id 为 NULL）已完全移除展示，不再提供全量爬取/清空记录入口。
 */
import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Tabs,
  Statistic,
  Row,
  Col,
  Alert,
  Form,
  Input,
  Button,
  Spin,
  Tag,
  Avatar,
  Space,
  App,
  Grid,
  Empty,
  Typography,
} from "antd";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  ThunderboltOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  LineChartOutlined,
  TeamOutlined,
  ArrowLeftOutlined,
  CheckCircleOutlined,
  MinusCircleOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  adminApi,
  type ElectricityStudent,
  type ElectricityStudentsOverview,
  type StudentElectricityRemaining,
  type StudentElectricityRecords,
} from "@/api/admin";
import ElectricityChart from "@/components/ElectricityChart";
import { useUser } from "@/contexts/UserContext";

const { Text } = Typography;

export default function Electricity() {
  const { isAdmin } = useUser();
  const { message } = App.useApp();
  // 移动端断点：收缩外层/内层 Card 的 body padding，避免 Card→Tabs→Card 三层留白累加
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // 三个 Tab：students（学生总览）/ detail（用电明细）/ config（模块配置）
  const [activeTab, setActiveTab] = useState("students");
  const [overview, setOverview] = useState<ElectricityStudentsOverview | null>(null);
  const [students, setStudents] = useState<ElectricityStudent[]>([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  // 明细：当前选中学生 + 剩余电量 + 记录分页
  const [selected, setSelected] = useState<ElectricityStudent | null>(null);
  const [remaining, setRemaining] = useState<StudentElectricityRemaining | null>(null);
  const [records, setRecords] = useState<StudentElectricityRecords | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [recordPage, setRecordPage] = useState(1);
  const [recordPageSize, setRecordPageSize] = useState(10);
  const [fetchAllLoading, setFetchAllLoading] = useState(false);

  // ============ 学生总览 ============
  const fetchOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      const res = await adminApi.getElectricityStudents();
      if (res.status === "success" && res.data) {
        setOverview(res.data);
        setStudents(res.data.students ?? []);
      }
    } catch (error) {
      console.error("加载学生电量总览失败:", error);
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  // ============ 用电明细 ============
  const fetchRemaining = useCallback(async (userId: number) => {
    try {
      const res = await adminApi.getStudentElectricityRemaining(userId);
      if (res.status === "success") setRemaining(res.data);
    } catch (error) {
      console.error("加载剩余电量失败:", error);
      setRemaining(null);
    }
  }, []);

  const fetchRecords = useCallback(
    async (userId: number, page: number, pageSize: number) => {
      setDetailLoading(true);
      try {
        const res = await adminApi.getStudentElectricityRecords(userId, {
          limit: pageSize,
          offset: (page - 1) * pageSize,
        });
        if (res.status === "success" && res.data) setRecords(res.data);
      } catch (error) {
        console.error("加载用电记录失败:", error);
      } finally {
        setDetailLoading(false);
      }
    },
    []
  );

  // 选中学生：切入「用电明细」Tab 并加载其数据
  const handleSelectStudent = (student: ElectricityStudent) => {
    setSelected(student);
    setRemaining(null);
    setRecords(null);
    setRecordPage(1);
    setActiveTab("detail");
  };

  // 返回学生总览
  const handleBack = () => {
    setSelected(null);
    setActiveTab("students");
    fetchOverview();
  };

  // 明细 Tab 数据加载（选中学生变化 / 记录翻页时）
  useEffect(() => {
    if (activeTab === "detail" && selected) {
      fetchRemaining(selected.user_id);
      fetchRecords(selected.user_id, recordPage, recordPageSize);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selected, recordPage, recordPageSize]);

  // ============ 触发采集（全部已配置学生） ============
  const handleTriggerFetch = async () => {
    try {
      setFetchAllLoading(true);
      const res = await adminApi.triggerElectricity("fetch_electricity_data");
      if ((res as any).skipped) {
        message.warning(res.message || "假期静默中，已跳过");
        return;
      }
      message.success((res.message as string) || "采集任务已触发，可在「进程管理」查看进度");
      // 触发后稍候刷新总览，低电量/剩余电量可能有变化
      setTimeout(() => fetchOverview(), 3000);
    } catch (error) {
      message.error("触发采集失败");
    } finally {
      setFetchAllLoading(false);
    }
  };

  // 挂载时加载总览
  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

  // ============ 模块配置 ============
  const [config, setConfig] = useState<Record<string, any>>({});
  const [configLoading, setConfigLoading] = useState(false);
  const [form] = Form.useForm();

  const fetchConfig = async () => {
    setConfigLoading(true);
    try {
      const res = await adminApi.getElectricityConfig();
      // 后端统一返回 data 包裹（历史版本曾顶层返回 config，兼容读取）
      const cfg = res.data ?? res.config;
      if (res.status === "success" && cfg) {
        setConfig(cfg);
        form.setFieldsValue(cfg);
      }
    } catch (error) {
      console.error("加载配置失败:", error);
    } finally {
      setConfigLoading(false);
    }
  };

  const handleSaveConfig = async (values: Record<string, any>) => {
    try {
      const res = await adminApi.updateElectricityConfig(values);
      if (res.status === "success") {
        message.success("配置已保存");
        fetchConfig();
      }
    } catch (error) {
      message.error("保存配置失败");
    }
  };

  useEffect(() => {
    if (activeTab === "config") fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // ============ 学生总览表格列 ============
  const studentColumns = [
    {
      title: "学生",
      dataIndex: "display_name",
      key: "display_name",
      width: "26%",
      ellipsis: true,
      render: (_: string, record: ElectricityStudent) => (
        <Space>
          <Avatar
            size="small"
            style={{ backgroundColor: record.configured ? "#1890ff" : "#bfbfbf" }}
          >
            {(record.display_name || "?").slice(0, 1)}
          </Avatar>
          <span
            style={{ color: record.configured ? undefined : "#bfbfbf" }}
          >
            {record.display_name || `用户 #${record.user_id}`}
          </span>
        </Space>
      ),
    },
    {
      title: "学号 / 班级",
      dataIndex: "student_number",
      key: "class_info",
      width: "20%",
      ellipsis: true,
      render: (_: string, record: ElectricityStudent) =>
        record.student_number || record.class_name
          ? `${record.student_number || "-"} / ${record.class_name || "-"}`
          : "-",
    },
    {
      title: "配置状态",
      dataIndex: "configured",
      key: "configured",
      width: "14%",
      render: (configured: boolean) =>
        configured ? (
          <Tag color="success" icon={<CheckCircleOutlined />}>
            已配置
          </Tag>
        ) : (
          <Tag color="default" icon={<MinusCircleOutlined />}>
            未配置
          </Tag>
        ),
    },
    {
      title: "剩余电量",
      dataIndex: "remaining",
      key: "remaining",
      width: "16%",
      render: (_: number | null, record: ElectricityStudent) => {
        if (!record.configured) return <span style={{ color: "#bfbfbf" }}>未配置</span>;
        if (record.remaining == null) return <span style={{ color: "#bfbfbf" }}>暂无数据</span>;
        return (
          <span style={{ color: record.is_low_power ? "#cf1322" : "#3f8600", fontWeight: 500 }}>
            {record.remaining} 度
            {record.is_low_power && (
              <Tag color="error" icon={<WarningOutlined />} style={{ marginLeft: 6 }}>
                低电量
              </Tag>
            )}
          </span>
        );
      },
    },
    {
      title: "记录时间",
      dataIndex: "recorded_at",
      key: "recorded_at",
      width: "14%",
      ellipsis: true,
      render: (v: string | null) => v || "-",
    },
    {
      title: "操作",
      key: "action",
      width: "10%",
      render: (_: unknown, record: ElectricityStudent) => (
        <Button type="link" size="small" onClick={() => handleSelectStudent(record)}>
          查看明细
        </Button>
      ),
    },
  ];

  // 用电记录列（与旧版保持一致，数据来自分页接口）
  const recordColumns = [
    { title: "日期", dataIndex: "record_time", key: "record_time", width: "40%", ellipsis: true },
    {
      title: "用电量",
      dataIndex: "usage",
      key: "usage",
      width: "22%",
      ellipsis: true,
      render: (v: number) => (v != null ? `${v} 度` : "-"),
    },
    { title: "电表", dataIndex: "meter", key: "meter", width: "38%", ellipsis: true },
  ];

  const recordsWithKeys = (records?.records ?? []).map((item, idx) => ({
    ...item,
    _uid: `${item.record_time}-${idx}`,
  }));

  // ============ 学生总览 Tab ============
  const studentsTab = {
    key: "students",
    label: "学生总览",
    icon: <TeamOutlined />,
    children: (
      <div>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={8}>
            <Card size="small">
              <Statistic title="学生总数" value={overview?.summary.total_students ?? 0} suffix="人" />
            </Card>
          </Col>
          <Col xs={12} sm={8}>
            <Card size="small">
              <Statistic
                title="已配置电表"
                value={overview?.summary.configured_students ?? 0}
                suffix="人"
                valueStyle={{ color: "#1890ff" }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={8}>
            <Card size="small">
              <Statistic
                title="低电量"
                value={overview?.summary.low_power_count ?? 0}
                suffix="人"
                valueStyle={{ color: overview?.summary.low_power_count ? "#cf1322" : "#3f8600" }}
              />
            </Card>
          </Col>
        </Row>
        <Alert
          type="info"
          showIcon
          message="电表 Cookie 由学生在小程序「设置 - 电表配置」自行配置；未配置的学生不产生电量数据。"
          style={{ marginBottom: 16 }}
        />
        <Space style={{ marginBottom: 16 }}>
          <Button icon={<ReloadOutlined />} onClick={fetchOverview} disabled={overviewLoading}>
            刷新
          </Button>
          {isAdmin && (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleTriggerFetch}
              loading={fetchAllLoading}
            >
              触发数据采集
            </Button>
          )}
        </Space>
        {overviewLoading ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : students.length === 0 ? (
          <Empty description="暂无学生用户（学生首次登录微信小程序后才会出现在此）" />
        ) : (
          <ResponsiveTable
            dataSource={students}
            columns={studentColumns}
            rowKey="user_id"
            mobileNativeTable
            tableLayout="fixed"
            pagination={{
              pageSize: 10,
              pageSizeOptions: ["10", "20", "50"],
              showSizeChanger: true,
            }}
            size="small"
          />
        )}
      </div>
    ),
  };

  // ============ 用电明细 Tab ============
  const detailTab = {
    key: "detail",
    label: "用电明细",
    icon: <LineChartOutlined />,
    children: !selected ? (
      <Empty
        description="请先在「学生总览」中选择一名学生"
        style={{ padding: 40 }}
      />
    ) : (
      <div>
        <Space style={{ marginBottom: 16 }} wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>
            返回学生列表
          </Button>
          <Avatar style={{ backgroundColor: "#1890ff" }}>
            {(selected.display_name || "?").slice(0, 1)}
          </Avatar>
          <Text strong>{selected.display_name || `用户 #${selected.user_id}`}</Text>
          {selected.student_number && <Text type="secondary">学号 {selected.student_number}</Text>}
          {selected.class_name && <Text type="secondary">班级 {selected.class_name}</Text>}
          {selected.configured ? (
            <Tag color="success" icon={<CheckCircleOutlined />}>
              已配置
            </Tag>
          ) : (
            <Tag color="default" icon={<MinusCircleOutlined />}>
              未配置
            </Tag>
          )}
          {!selected.configured && (
            <Alert
              type="warning"
              showIcon
              message="该学生未配置电表 Cookie，暂无电量数据。请引导学生在小程序「设置 - 电表配置」完成配置。"
              style={{ width: "100%" }}
            />
          )}
        </Space>

        {selected.configured && (
          <>
            <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
              <Col xs={24} sm={12}>
                <Card size="small" styles={{ body: { padding: isMobile ? 12 : 24 } }}>
                  {remaining ? (
                    <>
                      <Statistic
                        title="最新剩余电量"
                        value={remaining.remaining}
                        suffix="度"
                        prefix={<ThunderboltOutlined />}
                        valueStyle={{ color: remaining.is_low_power ? "#cf1322" : "#3f8600" }}
                      />
                      <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
                        总量: {remaining.total_capacity} 度
                        {remaining.meter ? ` | 电表: ${remaining.meter}` : ""}
                        {remaining.recorded_at ? ` | 记录于 ${remaining.recorded_at}` : ""}
                      </div>
                      {remaining.is_low_power && (
                        <Alert
                          message="电量不足，请提醒学生及时充值"
                          type="warning"
                          showIcon
                          style={{ marginTop: 16 }}
                        />
                      )}
                    </>
                  ) : (
                    <Empty description="暂无剩余电量数据" />
                  )}
                </Card>
              </Col>
              <Col xs={24} sm={12}>
                <Card size="small" styles={{ body: { padding: isMobile ? 12 : 24 } }}>
                  <Statistic
                    title="用电记录总数"
                    value={records?.total ?? 0}
                    suffix="条"
                    prefix={<ThunderboltOutlined />}
                  />
                  <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
                    统计图表见下方「数据可视化」
                  </div>
                </Card>
              </Col>
            </Row>

            <Card title="用电记录" size="small" style={{ marginBottom: 16 }}>
              {detailLoading ? (
                <div style={{ textAlign: "center", padding: 30 }}>
                  <Spin />
                </div>
              ) : (
                <ResponsiveTable
                  dataSource={recordsWithKeys}
                  columns={recordColumns}
                  rowKey="_uid"
                  mobileNativeTable
                  tableLayout="fixed"
                  pagination={{
                    current: recordPage,
                    pageSize: recordPageSize,
                    total: records?.total ?? 0,
                    showSizeChanger: true,
                    pageSizeOptions: ["10", "20", "50"],
                    onChange: (page, size) => {
                      setRecordPage(page);
                      setRecordPageSize(size);
                    },
                  }}
                  size="small"
                />
              )}
            </Card>

            <Card title="数据可视化" size="small">
              <ElectricityChart userId={selected.user_id} />
            </Card>
          </>
        )}
      </div>
    ),
  };

  // ============ 模块配置 Tab（仅管理员） ============
  const configTab = {
    key: "config",
    label: "模块配置",
    icon: <SettingOutlined />,
    children: configLoading ? (
      <Spin />
    ) : (
      <div style={{ maxWidth: 600 }}>
        <Alert
          type="info"
          showIcon
          message="电表 Cookie 由学生在小程序「设置 - 电表配置」自行配置"
          description={`当前已有 ${config.configured_students ?? 0} 名学生配置了电表 Cookie，系统将按用户分别采集并推送。`}
          style={{ marginBottom: 16 }}
        />
        <Form form={form} layout="vertical" onFinish={handleSaveConfig}>
          <Form.Item name="low_power_threshold" label="低电量阈值">
            <Input type="number" placeholder="如：10" suffix="度" />
          </Form.Item>
          <Form.Item name="daily_push_time" label="每日推送时间">
            <Input placeholder="如：00:30" />
          </Form.Item>
          <Form.Item name="weekly_push_day" label="每周推送日">
            <Input placeholder="如：mon" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              保存配置
            </Button>
          </Form.Item>
        </Form>
      </div>
    ),
  };

  const tabs: any[] = [studentsTab, detailTab];
  if (isAdmin) tabs.push(configTab);

  return (
    <div>
      <Card styles={{ body: { padding: isMobile ? 12 : 24 } }}>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} />
      </Card>
    </div>
  );
}
