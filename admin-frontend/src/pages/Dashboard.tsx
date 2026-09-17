/**
 * 仪表盘页面
 *
 * 功能：
 * - 系统状态与运行环境概览
 * - 模块健康监控（天气 / 电量 / 课表）
 * - 任务执行核心指标 + 趋势分析（支持时间范围筛选）
 * - 最近任务 / 定时任务 / 快捷操作
 */
import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Row,
  Col,
  Statistic,
  Button,
  Tag,
  Space,
  Typography,
  Alert,
  Skeleton,
  Table,
  Badge,
  Divider,
  Timeline,
  Empty,
  App,
  DatePicker,
  Segmented,
} from "antd";
import {
  CloudOutlined,
  ThunderboltOutlined,
  ScheduleOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  ClockCircleOutlined,
  ToolOutlined,
  SendOutlined,
  SyncOutlined,
  StopOutlined,
  RiseOutlined,
  FallOutlined,
  ContainerOutlined,
} from "@ant-design/icons";
import { adminApi, type DashboardData } from "@/api/admin";
import { holidayApi, type HolidayStatus } from "@/api/holiday";
import dayjs from "dayjs";
import { formatTimeShort } from "@/utils/datetime";
import ReactECharts from "echarts-for-react";
import { useServerStatus } from "@/components/ServerStatusProvider";
import { useIntervalPolling } from "@/hooks/useIntervalPolling";
import { POLL_SLOW } from "@/hooks/pollIntervals";
import { TASK_STATUS_MAP } from "@/constants/statusMaps";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// 状态颜色映射（模块卡片用）
const STATUS_COLORS: Record<string, string> = {
  ok: "#52c41a",
  running: "#1890ff",
  disabled: "#d9d9d9",
  error: "#ff4d4f",
};

// 图表主色调
const CHART_COLORS = ["#1890ff", "#52c41a", "#faad14", "#f5222d", "#722ed1", "#13c2c2", "#eb2f96"];

// Ant Design 状态色名 → 十六进制（用于状态分布环形图配色）
const STATUS_HEX: Record<string, string> = {
  success: "#52c41a",
  error: "#ff4d4f",
  processing: "#1890ff",
  warning: "#faad14",
  default: "#d9d9d9",
  running: "#1890ff",
  pending: "#faad14",
};
const colorForStatus = (s: string): string =>
  STATUS_HEX[(TASK_STATUS_MAP[s]?.color as string) || "default"] || "#999";

/** 时间范围选项 */
const TIME_RANGE_OPTIONS = [
  { label: "本月", value: "this_month" },
  { label: "上月", value: "last_month" },
  { label: "本周", value: "this_week" },
  { label: "上周", value: "last_week" },
  { label: "自定义", value: "custom" },
];

export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<DashboardData | null>(null);
  const [timeLabel, setTimeLabel] = useState<string>("");
  const { isOffline } = useServerStatus();
  const [holidayStatus, setHolidayStatus] = useState<HolidayStatus | null>(null);
  const { message } = App.useApp();

  // 时间筛选
  const [timeRange, setTimeRange] = useState("this_month");
  const [customRange, setCustomRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  // 趋势图类型
  const [trendType, setTrendType] = useState<"area" | "line">("area");

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { time_range: timeRange };
      if (timeRange === "custom" && customRange) {
        params.start_date = customRange[0].format("YYYY-MM-DD");
        params.end_date = customRange[1].format("YYYY-MM-DD");
      }
      const res = await adminApi.getDashboard(params);
      if (res.status === "success" && res.data) {
        setData(res.data);
        // 后端返回的 time_label
        setTimeLabel((res as any).time_label || "");
      }
    } catch (error: any) {
      console.error("加载仪表盘数据失败:", error);
    } finally {
      setLoading(false);
    }
  }, [timeRange, customRange]);

  // 筛选条件变化时立即刷新数据
  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);
  // 假期模式生效状态（用于顶部静音横幅）
  useEffect(() => {
    holidayApi
      .getStatus()
      .then((res) => {
        if (res.status === "success" && res.data) setHolidayStatus(res.data);
      })
      .catch(() => {});
  }, []);
  // 每 30s 周期自动刷新（统一轮询 Hook）；immediate=false 避免与上面挂载时双拉
  useIntervalPolling(fetchDashboard, POLL_SLOW, true, false);

  const handleTriggerWeather = async () => {
    try {
      const res = await adminApi.triggerWeather("update_weather_now");
      // 假期静默拦截：后端返回 skipped，提示已跳过且不刷新
      if ((res as any).skipped) {
        message.warning(res.message || "假期静默中，已跳过");
        return;
      }
      fetchDashboard();
    } catch (error) {
      console.error("触发天气更新失败:", error);
    }
  };

  const handleTriggerSpider = async () => {
    try {
      const res = await adminApi.triggerSpider();
      // 假期静默 / 非教学周拦截：后端返回 skipped，提示已跳过且不刷新
      if ((res as any).skipped) {
        message.warning(res.message || "假期静默中，已跳过");
        return;
      }
      fetchDashboard();
    } catch (error) {
      console.error("触发爬虫失败:", error);
    }
  };

  if (loading && !data) {
    return (
      <div className="dashboard-container" style={{ padding: "0 4px" }}>
        <Skeleton.Input active size="large" style={{ width: 220, marginBottom: 24 }} />
        <Row gutter={[16, 16]}>
          {[0, 1, 2, 3].map((i) => (
            <Col xs={12} sm={6} lg={6} key={`k${i}`}>
              <Card>
                <Skeleton active paragraph={{ rows: 1 }} />
              </Card>
            </Col>
          ))}
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          {[0, 1, 2].map((i) => (
            <Col xs={24} sm={8} lg={8} key={`m${i}`}>
              <Card>
                <Skeleton active paragraph={{ rows: 2 }} />
              </Card>
            </Col>
          ))}
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={16}>
            <Card>
              <Skeleton active paragraph={{ rows: 8 }} />
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card>
              <Skeleton active paragraph={{ rows: 8 }} />
            </Card>
          </Col>
        </Row>
      </div>
    );
  }

  const processStats = data?.tasks?.process_stats ?? {
    total: 0,
    status_counts: {} as Record<string, number>,
    type_counts: {} as Record<string, number>,
    type_trend: { dates: [] as string[], series: [] as { name: string; data: number[] }[] },
    today: { total: 0, completed: 0, failed: 0 },
    week: { total: 0 },
    month: { total: 0 },
    period: { total: 0, completed: 0, failed: 0 },
    recent_tasks: [] as {
      id: number;
      name: string;
      status: string;
      started_at: string | null;
      duration: number | null;
    }[],
  };
  const scheduledJobs = data?.tasks?.scheduled_jobs ?? {
    total: 0,
    jobs: [] as {
      id: string;
      name: string;
      trigger_type: string;
      trigger_desc: string;
      next_run: string | null;
      pending: boolean;
    }[],
  };
  const taskStats = data?.tasks?.task_stats;
  const scheduleModule = data?.modules?.schedule;
  const typeCounts: Record<string, number> = processStats.type_counts || {};
  const typeTrend = processStats.type_trend ?? {
    dates: [] as string[],
    series: [] as { name: string; data: number[] }[],
  };
  const period = processStats.period ?? { total: 0, completed: 0, failed: 0 };
  const statusCounts: Record<string, number> = processStats.status_counts || {};
  const statusEntries = Object.entries(statusCounts).filter(([, v]) => (v as number) > 0);
  const statusTotal = Object.values(statusCounts).reduce((s, v) => s + ((v as number) || 0), 0) || 1;
  const periodTotal = period.total || 0;
  const periodCompleted = period.completed || 0;
  const periodFailed = period.failed || 0;
  const successRate =
    periodTotal > 0 ? Math.round((periodCompleted / periodTotal) * 100) : 0;
  const recentTasks = processStats.recent_tasks || [];
  const todayTotal = processStats.today?.total || 0;
  const monthTotal = processStats.month?.total || 0;
  const pending = taskStats?.pending ?? 0;
  const processing = taskStats?.processing ?? 0;
  const queueBacklog = pending + processing;
  const courseCrawlerRunning = data?.tasks?.spider_status?.course?.running;
  const elecCrawlerRunning = data?.tasks?.spider_status?.electricity?.running;

  const successColor =
    successRate >= 90 ? "#52c41a" : successRate >= 70 ? "#faad14" : "#ff4d4f";
  const failRate = periodTotal > 0 ? Math.round((periodFailed / periodTotal) * 100) : 0;

  // ── 图表配置 ──
  const typeEntries = Object.entries(typeCounts);
  const hasData = typeEntries.length > 0;
  const hasTrend = typeTrend.dates.length > 0;

  // 任务趋势（按类型多序列面积图）—— 仪表盘核心分析图
  const trendOption = {
    tooltip: { trigger: "axis" },
    legend: {
      data: typeTrend.series.map((s: { name: string; data: number[] }) => s.name),
      bottom: 0,
      type: "scroll" as const,
    },
    grid: { left: "3%", right: "4%", bottom: "14%", top: "6%", containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: typeTrend.dates.map((d: string) => d.slice(5)), // MM-DD
      axisLine: { lineStyle: { color: "#d9d9d9" } },
      axisLabel: { color: "#8c8c8c" },
    },
    yAxis: {
      type: "value",
      name: "次",
      minInterval: 1,
      splitLine: { lineStyle: { color: "#f0f0f0" } },
      axisLabel: { color: "#8c8c8c" },
    },
    series: typeTrend.series.map((s: { name: string; data: number[] }) => ({
      name: s.name,
      type: "line",
      data: s.data,
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2 },
      areaStyle: trendType === "area" ? { opacity: 0.12 } : undefined,
    })),
    color: CHART_COLORS,
  };

  // 任务类型分布（环形图）
  const typeDistOption = {
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { orient: "horizontal" as const, left: "center", bottom: 0, type: "scroll" as const },
    title: {
      text: String(typeEntries.reduce((s, [, v]) => s + (v as number), 0)),
      subtext: "任务总数",
      left: "center",
      top: "42%",
      textStyle: { fontSize: 22, fontWeight: 600 as const, color: "#262626" },
      subtextStyle: { fontSize: 12, color: "#8c8c8c" },
    },
    series: [
      {
        name: "任务类型",
        type: "pie",
        radius: ["52%", "74%"],
        center: ["50%", "46%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: "#fff", borderWidth: 2 },
        label: { show: false },
        data: typeEntries.map(([type, count]) => ({ name: type, value: count as number })),
      },
    ],
    color: CHART_COLORS,
  };

  // 任务状态分布（环形图，按业务状态配色）
  const statusDistOption = {
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { orient: "horizontal" as const, left: "center", bottom: 0, type: "scroll" as const },
    title: {
      text: String(statusTotal),
      subtext: "执行总数",
      left: "center",
      top: "42%",
      textStyle: { fontSize: 22, fontWeight: 600 as const, color: "#262626" },
      subtextStyle: { fontSize: 12, color: "#8c8c8c" },
    },
    series: [
      {
        name: "任务状态",
        type: "pie",
        radius: ["52%", "74%"],
        center: ["50%", "46%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: "#fff", borderWidth: 2 },
        label: { show: false },
        data: statusEntries.map(([k, v]) => ({
          name: TASK_STATUS_MAP[k]?.text || k,
          value: v as number,
          itemStyle: { color: colorForStatus(k) },
        })),
      },
    ],
  };

  return (
    <div className="dashboard-container">
      {holidayStatus?.active && (
        <Alert
          type="warning"
          showIcon
          icon={<StopOutlined />}
          style={{ marginBottom: 16 }}
          message={`推送静默生效中${holidayStatus.period ? `（${holidayStatus.period.name}）` : ""}·推送已静音`}
          description="当前处于假期区间内，全体面向用户的推送已自动静音；进程历史中的「已静音」记录即由此产生。系统/安全告警不受影响。"
        />
      )}

      {/* 页面标题 + 系统环境条 */}
      <div
        style={{
          marginBottom: 20,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0 }}>
            系统概览
          </Title>
          <Space size={6} wrap style={{ marginTop: 6 }} split={<Divider type="vertical" />}>
            <Space size={4}>
              <Badge status={isOffline ? "error" : "success"} />
              <Text type="secondary" style={{ fontSize: 13 }}>
                {isOffline ? "服务已停止" : "服务运行中"}
              </Text>
            </Space>
            <Text type="secondary" style={{ fontSize: 13 }}>
              v{data?.system?.version || "-"}
            </Text>
            <Tag
              color={data?.system?.debug ? "orange" : "green"}
              style={{ margin: 0, fontSize: 12 }}
            >
              {data?.system?.debug ? "DEBUG" : "生产环境"}
            </Tag>
            <Text type="secondary" style={{ fontSize: 13 }}>
              鉴权{data?.system?.auth_enabled ? "已开启" : "已关闭"}
            </Text>
            <Text type="secondary" style={{ fontSize: 13 }}>
              运行 {data?.system?.uptime || "-"}
            </Text>
            <Text type="secondary" style={{ fontSize: 13 }}>
              数据时间{" "}
              {data?.system?.timestamp
                ? dayjs(data.system.timestamp).format("MM-DD HH:mm")
                : "-"}
            </Text>
          </Space>
        </div>
        <Space wrap>
          <Segmented
            options={TIME_RANGE_OPTIONS}
            value={timeRange}
            onChange={(v) => setTimeRange(v as string)}
          />
          {timeRange === "custom" && (
            <RangePicker value={customRange as any} onChange={(v) => setCustomRange(v as any)} />
          )}
          <Button icon={<ReloadOutlined />} onClick={fetchDashboard} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {/* 核心指标 KPI */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6} lg={6}>
          <Card className="kpi-card" hoverable>
            <Statistic
              title="期间任务执行"
              value={periodTotal}
              suffix="次"
              valueStyle={{ fontSize: 28, fontWeight: 600 }}
            />
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                今日 {todayTotal} · 本月 {monthTotal}
              </Text>
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={6} lg={6}>
          <Card className="kpi-card" hoverable>
            <Statistic
              title="任务成功率"
              value={successRate}
              suffix="%"
              valueStyle={{ fontSize: 28, fontWeight: 600, color: successColor }}
            />
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                完成 {periodCompleted} / {periodTotal}
              </Text>
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={6} lg={6}>
          <Card className="kpi-card" hoverable>
            <Statistic
              title="失败任务"
              value={periodFailed}
              suffix="次"
              valueStyle={{ fontSize: 28, fontWeight: 600, color: "#ff4d4f" }}
            />
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                占比 {failRate}%
              </Text>
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={6} lg={6}>
          <Card className="kpi-card" hoverable>
            <Statistic
              title="队列积压"
              value={queueBacklog}
              suffix="条"
              valueStyle={{ fontSize: 28, fontWeight: 600, color: queueBacklog > 0 ? "#faad14" : "#52c41a" }}
            />
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                待处理 {pending} · 处理中 {processing}
              </Text>
            </div>
          </Card>
        </Col>
      </Row>

      {/* 模块健康 */}
      <div style={{ marginBottom: 6 }}>
        <Text type="secondary" style={{ fontSize: 13, fontWeight: 500 }}>
          模块健康
        </Text>
      </div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {/* 天气 */}
        <Col xs={24} sm={8} lg={8}>
          <Card className="status-card" hoverable>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Text type="secondary">天气模块</Text>
                <div style={{ marginTop: 8 }}>
                  <Text
                    strong
                    style={{
                      fontSize: 20,
                      color:
                        STATUS_COLORS[data?.modules?.weather?.status || "disabled"] || "#d9d9d9",
                    }}
                  >
                    {data?.modules?.weather?.enabled ? "正常" : "未启用"}
                  </Text>
                </div>
              </div>
              <CloudOutlined
                style={{
                  fontSize: 38,
                  color: STATUS_COLORS[data?.modules?.weather?.status || "disabled"] || "#d9d9d9",
                }}
              />
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space size={4} wrap>
              <Tag color={data?.modules?.weather?.cache?.now ? "green" : "default"}>实况</Tag>
              <Tag color={data?.modules?.weather?.cache?.hourly ? "green" : "default"}>预报</Tag>
              <Tag color={data?.modules?.weather?.cache?.alert ? "green" : "default"}>预警</Tag>
            </Space>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {data?.modules?.weather?.config?.city_name || "-"} · 晨报{" "}
                {data?.modules?.weather?.config?.daily_push_time || "-"}
              </Text>
            </div>
          </Card>
        </Col>

        {/* 电量 */}
        <Col xs={24} sm={8} lg={8}>
          <Card className="status-card" hoverable>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Text type="secondary">电量模块</Text>
                <div style={{ marginTop: 8 }}>
                  <Text
                    strong
                    style={{
                      fontSize: 20,
                      color:
                        STATUS_COLORS[data?.modules?.electricity?.status || "disabled"] ||
                        "#d9d9d9",
                    }}
                  >
                    {data?.modules?.electricity?.enabled ? "正常" : "未启用"}
                  </Text>
                </div>
              </div>
              <ThunderboltOutlined
                style={{
                  fontSize: 38,
                  color:
                    STATUS_COLORS[data?.modules?.electricity?.status || "disabled"] || "#d9d9d9",
                }}
              />
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space size={4} wrap>
              <Tag color={data?.modules?.electricity?.cookie_configured ? "green" : "default"}>
                Cookie{data?.modules?.electricity?.cookie_configured ? "已配" : "未配"}
              </Tag>
              {elecCrawlerRunning ? (
                <Tag color="processing">采集中</Tag>
              ) : (
                <Tag>空闲</Tag>
              )}
            </Space>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                已配 {data?.modules?.electricity?.configured_students ?? 0} 人 · 低电量阈值{" "}
                {data?.modules?.electricity?.config?.low_power_threshold ?? "-"}%
              </Text>
            </div>
          </Card>
        </Col>

        {/* 课表 */}
        <Col xs={24} sm={8} lg={8}>
          <Card className="status-card" hoverable>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Text type="secondary">课表模块</Text>
                <div style={{ marginTop: 8 }}>
                  <Badge
                    status={scheduleModule?.data_ready ? "success" : "default"}
                    text={
                      <Text
                        strong
                        style={{
                          fontSize: 18,
                          color: scheduleModule?.data_ready ? "#52c41a" : "#999",
                        }}
                      >
                        {scheduleModule?.data_ready ? "数据就绪" : "未就绪"}
                      </Text>
                    }
                  />
                </div>
              </div>
              <ScheduleOutlined
                style={{ fontSize: 38, color: scheduleModule?.data_ready ? "#1890ff" : "#999" }}
              />
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space size={4} wrap>
              <Tag>条目 {scheduleModule?.stats?.total ?? "-"}</Tag>
              <Tag>今日 {scheduleModule?.stats?.today ?? "-"}</Tag>
              {courseCrawlerRunning ? (
                <Tag color="processing">采集中</Tag>
              ) : (
                <Tag>空闲</Tag>
              )}
            </Space>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                课程 {scheduleModule?.stats?.unique_courses ?? "-"} · 教师{" "}
                {scheduleModule?.stats?.unique_teachers ?? "-"} · 更新{" "}
                {scheduleModule?.stats?.last_updated
                  ? formatTimeShort(scheduleModule.stats.last_updated)
                  : "-"}
              </Text>
            </div>
          </Card>
        </Col>
      </Row>

      {/* 任务趋势 + 分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={16}>
          <Card
            title={
              <span>
                <RiseOutlined style={{ marginRight: 8 }} />
                任务执行趋势
                {timeLabel && (
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                    {timeLabel}
                  </Text>
                )}
              </span>
            }
            extra={
              <Segmented
                size="small"
                options={[
                  { label: "面积", value: "area" },
                  { label: "折线", value: "line" },
                ]}
                value={trendType}
                onChange={(v) => setTrendType(v as "area" | "line")}
              />
            }
          >
            {hasTrend ? (
              <ReactECharts option={trendOption} style={{ height: 320 }} notMerge />
            ) : (
              <Empty
                description="当前范围暂无任务记录"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                style={{ padding: "80px 0" }}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={<span><ContainerOutlined style={{ marginRight: 8 }} />任务类型分布</span>} style={{ height: "100%" }}>
            {hasData ? (
              <ReactECharts option={typeDistOption} style={{ height: 320 }} notMerge />
            ) : (
              <Empty
                description="暂无数据"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                style={{ padding: "80px 0" }}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={8}>
          <Card title={<span><FallOutlined style={{ marginRight: 8 }} />任务状态分布</span>} style={{ height: "100%" }}>
            {statusEntries.length > 0 ? (
              <ReactECharts option={statusDistOption} style={{ height: 300 }} notMerge />
            ) : (
              <Empty
                description="暂无数据"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                style={{ padding: "80px 0" }}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card
            title={
              <span>
                <ClockCircleOutlined style={{ marginRight: 8 }} />
                最近任务
              </span>
            }
            styles={{ body: { padding: 12 } }}
            style={{ height: "100%" }}
          >
            {recentTasks.length > 0 ? (
              <Timeline
                items={recentTasks.slice(0, 6).map((task: any) => ({
                  color:
                    task.status === "completed"
                      ? "green"
                      : task.status === "failed"
                        ? "red"
                        : "blue",
                  children: (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <Text strong style={{ fontSize: 13 }}>
                          {task.name}
                        </Text>
                        <Tag color={TASK_STATUS_MAP[task.status]?.color} style={{ marginLeft: 8 }}>
                          {TASK_STATUS_MAP[task.status]?.text}
                        </Tag>
                      </div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {task.started_at ? formatTimeShort(task.started_at) : "-"}
                        {task.duration ? ` · ${task.duration.toFixed(1)}s` : ""}
                      </Text>
                    </div>
                  ),
                }))}
              />
            ) : (
              <Empty description="暂无任务记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      {/* 定时任务列表 */}
      <Card
        title={
          <span>
            <ScheduleOutlined style={{ marginRight: 8 }} />
            定时任务
            <Tag style={{ marginLeft: 8 }}>{scheduledJobs.total || 0}</Tag>
          </span>
        }
        style={{ marginTop: 0, marginBottom: 16 }}
      >
        {scheduledJobs.jobs?.length ? (
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={scheduledJobs.jobs}
            columns={[
              { title: "任务", dataIndex: "name" },
              { title: "执行频率", dataIndex: "trigger_desc" },
              {
                title: "下次执行",
                dataIndex: "next_run",
                render: (v: string | null) => (v ? dayjs(v).format("MM-DD HH:mm") : "—"),
              },
              {
                title: "状态",
                dataIndex: "pending",
                render: (p: boolean) =>
                  p ? <Tag color="warning">待运行</Tag> : <Tag color="success">已排程</Tag>,
              },
            ]}
          />
        ) : (
          <Empty description="暂无定时任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>

      {/* 快捷操作 */}
      <Card
        title={
          <span>
            <ToolOutlined style={{ marginRight: 8 }} />
            快捷操作
          </span>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} sm={8} md={6}>
            <Button
              type="primary"
              icon={<SyncOutlined />}
              onClick={handleTriggerWeather}
              block
              disabled={holidayStatus?.active}
            >
              更新天气数据
            </Button>
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Button
              icon={<SendOutlined />}
              onClick={async () => {
                try {
                  const res = await adminApi.triggerWeather("daily");
                  if ((res as any).skipped) {
                    message.warning(res.message || "假期静默中，已跳过");
                    return;
                  }
                  fetchDashboard();
                } catch (e) {
                  console.error("触发天气晨报失败:", e);
                }
              }}
              block
              disabled={holidayStatus?.active}
            >
              发送天气晨报
            </Button>
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Button
              icon={<SendOutlined />}
              onClick={async () => {
                try {
                  const res = await adminApi.triggerElectricity("daily");
                  if ((res as any).skipped) {
                    message.warning(res.message || "假期静默中，已跳过");
                    return;
                  }
                  fetchDashboard();
                } catch (e) {
                  console.error("触发电量日报失败:", e);
                }
              }}
              block
              disabled={holidayStatus?.active}
            >
              发送电量日报
            </Button>
          </Col>
          <Col xs={12} sm={8} md={6}>
            <Button
              icon={<PlayCircleOutlined />}
              onClick={handleTriggerSpider}
              block
              disabled={holidayStatus?.active}
            >
              触发课表爬虫
            </Button>
          </Col>
        </Row>
      </Card>

      <style>{`
        .dashboard-container .status-card,
        .dashboard-container .kpi-card {
          height: 100%;
        }
        .dashboard-container .ant-card-head-title {
          padding: 12px 0;
        }
      `}</style>
    </div>
  );
}
