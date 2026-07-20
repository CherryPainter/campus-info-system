/**
 * 仪表盘页面
 *
 * 功能：
 * - 系统状态概览
 * - 模块状态监控
 * - 任务执行统计（支持时间范围筛选 + 图表类型切换）
 * - 快捷操作
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
  Spin,
  Typography,
  Alert,
  Progress,
  Table,
  Badge,
  Divider,
  Tooltip,
  Timeline,
  Empty,
  App,
  DatePicker,
  Segmented,
} from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudOutlined,
  ThunderboltOutlined,
  ScheduleOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  ClockCircleOutlined,
  ToolOutlined,
  SendOutlined,
  DatabaseOutlined,
  SyncOutlined,
  WarningOutlined,
  DisconnectOutlined,
  StopOutlined,
  PieChartOutlined,
  LineChartOutlined,
} from "@ant-design/icons";
import { adminApi, type DashboardData } from "@/api/admin";
import { holidayApi, type HolidayStatus } from "@/api/holiday";
import dayjs from "dayjs";
import { formatDate, formatTimeShort } from "@/utils/datetime";
import ReactECharts from "echarts-for-react";
import { useServerStatus } from "@/components/ServerStatusProvider";
import { useIntervalPolling } from "@/hooks/useIntervalPolling";
import { POLL_SLOW } from "@/hooks/pollIntervals";
import { TASK_STATUS_MAP } from "@/constants/statusMaps";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// 状态颜色映射
const STATUS_COLORS: Record<string, string> = {
  ok: "#52c41a",
  running: "#1890ff",
  disabled: "#d9d9d9",
  error: "#ff4d4f",
};

// 图表主色调
const CHART_COLORS = ["#1890ff", "#52c41a", "#faad14", "#f5222d", "#722ed1", "#13c2c2", "#eb2f96"];

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
  // 图表类型
  const [chartType, setChartType] = useState<"pie" | "line">("pie");

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { time_range: timeRange };
      if (timeRange === "custom" && customRange) {
        params.start_date = formatDate(customRange[0]);
        params.end_date = formatDate(customRange[1]);
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
      <div style={{ textAlign: "center", padding: 50 }}>
        <Spin size="large" />
      </div>
    );
  }

  const processStats = (data as any)?.tasks?.process_stats || {};
  const scheduledJobs = (data as any)?.tasks?.scheduled_jobs || {};
  const typeCounts: Record<string, number> = processStats.type_counts || {};
  const typeTrend = processStats.type_trend || {
    dates: [] as string[],
    series: [] as { name: string; data: number[] }[],
  };
  const period = processStats.period || {};

  // ── 图表配置 ──
  const typeEntries = Object.entries(typeCounts);
  const hasData = typeEntries.length > 0;
  const hasTrend = typeTrend.dates.length > 0;

  const pieOption = {
    tooltip: {
      trigger: "item",
      formatter: "{b}: {c} ({d}%)",
    },
    legend: {
      orient: "horizontal",
      left: "center",
      bottom: 0,
    },
    series: [
      {
        name: "任务类型",
        type: "pie",
        radius: ["40%", "70%"],
        center: ["50%", "45%"],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: "#fff",
          borderWidth: 2,
        },
        label: {
          show: true,
          formatter: "{b}\n{c}",
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: "bold",
          },
        },
        data: typeEntries.map(([type, count]) => ({
          name: type,
          value: count,
        })),
      },
    ],
    color: CHART_COLORS,
  };

  const lineOption = {
    tooltip: {
      trigger: "axis",
    },
    legend: {
      data: typeTrend.series.map((s: { name: string; data: number[] }) => s.name),
      bottom: 0,
    },
    grid: {
      left: "3%",
      right: "4%",
      bottom: "12%",
      top: "6%",
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: typeTrend.dates.map((d: string) => d.slice(5)), // MM-DD
      boundaryGap: false,
    },
    yAxis: {
      type: "value",
      name: "次",
      minInterval: 1,
    },
    series: typeTrend.series.map((s: { name: string; data: number[] }) => ({
      name: s.name,
      type: "line",
      data: s.data,
      smooth: true,
      symbol: "circle",
      symbolSize: 6,
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.08 },
    })),
    color: CHART_COLORS,
  };

  const chartOption = chartType === "pie" ? pieOption : lineOption;

  return (
    <div className="dashboard-container">
      {holidayStatus?.active && (
        <Alert
          type="warning"
          showIcon
          icon={<StopOutlined />}
          style={{ marginBottom: 16 }}
          message={`假期模式生效中${holidayStatus.period ? `（${holidayStatus.period.name}）` : ""}·推送已静音`}
          description="当前处于假期区间内，全体面向用户的推送已自动静音；进程历史中的「已静音」记录即由此产生。系统/安全告警不受影响。"
        />
      )}
      {/* 页面标题 */}
      <div
        style={{
          marginBottom: 24,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <Title level={4} style={{ margin: 0 }}>
          系统概览
        </Title>
        <Space wrap>
          <Text type="secondary">
            <ClockCircleOutlined style={{ marginRight: 4 }} />
            上次更新: {dayjs().format("HH:mm:ss")}
          </Text>
          <Button icon={<ReloadOutlined />} onClick={fetchDashboard} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {/* 系统状态卡片 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card className="status-card" hoverable style={{ opacity: isOffline ? 0.5 : 1 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Text type="secondary">服务状态</Text>
                <div style={{ marginTop: 8 }}>
                  <Text strong style={{ fontSize: 20, color: isOffline ? "#ff4d4f" : "#52c41a" }}>
                    {isOffline ? "已停止" : "运行中"}
                  </Text>
                </div>
              </div>
              {isOffline ? (
                <CloseCircleOutlined style={{ fontSize: 40, color: "#ff4d4f" }} />
              ) : (
                <CheckCircleOutlined style={{ fontSize: 40, color: "#52c41a" }} />
              )}
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space split={<Divider type="vertical" />}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                v{data?.system?.version || "-"}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                运行 {data?.system?.uptime || "-"}
              </Text>
            </Space>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
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
                  fontSize: 40,
                  color: STATUS_COLORS[data?.modules?.weather?.status || "disabled"] || "#d9d9d9",
                }}
              />
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space size={4}>
              <Tag color={data?.modules?.weather?.cache?.now ? "green" : "default"}>实时</Tag>
              <Tag color={data?.modules?.weather?.cache?.hourly ? "green" : "default"}>预报</Tag>
              <Tag color={data?.modules?.weather?.cache?.alert ? "green" : "default"}>预警</Tag>
            </Space>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
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
                  fontSize: 40,
                  color:
                    STATUS_COLORS[data?.modules?.electricity?.status || "disabled"] || "#d9d9d9",
                }}
              />
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space split={<Divider type="vertical" />}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Cookie: {data?.modules?.electricity?.cookie_configured ? "已配置" : "未配置"}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                数据: {data?.modules?.electricity?.data?.remaining_exists ? "有" : "无"}
              </Text>
            </Space>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card className="status-card" hoverable style={{ opacity: isOffline ? 0.5 : 1 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <Text type="secondary">定时任务</Text>
                <div style={{ marginTop: 8 }}>
                  <Text strong style={{ fontSize: 20, color: isOffline ? "#999" : "inherit" }}>
                    {isOffline ? "离线" : `${scheduledJobs.total || 0} 个`}
                  </Text>
                </div>
              </div>
              <ScheduleOutlined style={{ fontSize: 40, color: isOffline ? "#999" : "#1890ff" }} />
            </div>
            <Divider style={{ margin: "12px 0" }} />
            <Space size="small" style={{ fontSize: 12 }}>
              <Text type="secondary">课表:</Text>
              {data?.tasks?.spider_status?.course?.running ? (
                <Tag color="processing">运行中</Tag>
              ) : (
                <Tag>空闲</Tag>
              )}
              <Text type="secondary">电量:</Text>
              {data?.tasks?.spider_status?.electricity?.running ? (
                <Tag color="processing">运行中</Tag>
              ) : (
                <Tag>空闲</Tag>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 任务统计 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card style={{ height: "100%" }}>
            {/* ── 卡片头部：标题 + 时间筛选 ── */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 12,
                marginBottom: 20,
              }}
            >
              <Space align="center">
                <DatabaseOutlined style={{ fontSize: 18, color: "#1677ff" }} />
                <Text strong style={{ fontSize: 16 }}>
                  任务执行统计
                </Text>
                {timeLabel && (
                  <Tag color="processing" style={{ marginLeft: 4 }}>
                    {timeLabel}
                  </Tag>
                )}
              </Space>

              <Space size="small" wrap>
                <Segmented
                  size="small"
                  value={timeRange}
                  onChange={(v) => setTimeRange(v as string)}
                  options={TIME_RANGE_OPTIONS}
                />
                {timeRange === "custom" && (
                  <RangePicker
                    size="small"
                    value={customRange}
                    onChange={(dates) => setCustomRange(dates as any)}
                    style={{ width: 230 }}
                    placeholder={["开始", "结束"]}
                  />
                )}
              </Space>
            </div>

            {/* ── 统计卡片 ── */}
            <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
              <Col xs={12} sm={6}>
                <Card size="small" styles={{ body: { padding: "14px 16px" } }}>
                  <Statistic
                    title={
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        {timeRange === "this_month" ? "今日执行" : "期间执行"}
                      </Text>
                    }
                    value={
                      timeRange === "this_month"
                        ? processStats.today?.total || 0
                        : period.total || 0
                    }
                    suffix="次"
                    valueStyle={{ fontSize: 28, fontWeight: 600 }}
                  />
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" styles={{ body: { padding: "14px 16px" } }}>
                  <Statistic
                    title={
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        {timeRange === "this_month" ? "今日完成" : "期间完成"}
                      </Text>
                    }
                    value={
                      timeRange === "this_month"
                        ? processStats.today?.completed || 0
                        : period.completed || 0
                    }
                    suffix="次"
                    valueStyle={{ fontSize: 28, fontWeight: 600, color: "#52c41a" }}
                  />
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" styles={{ body: { padding: "14px 16px" } }}>
                  <Statistic
                    title={
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        {timeRange === "this_month" ? "今日失败" : "期间失败"}
                      </Text>
                    }
                    value={
                      timeRange === "this_month"
                        ? processStats.today?.failed || 0
                        : period.failed || 0
                    }
                    suffix="次"
                    valueStyle={{ fontSize: 28, fontWeight: 600, color: "#ff4d4f" }}
                  />
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" styles={{ body: { padding: "14px 16px" } }}>
                  <Statistic
                    title={
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        期间总数
                      </Text>
                    }
                    value={period.total || processStats.total || 0}
                    suffix="次"
                    valueStyle={{ fontSize: 28, fontWeight: 600 }}
                  />
                </Card>
              </Col>
            </Row>

            <Divider style={{ margin: "0 0 16px 0" }} />

            {/* ── 图表标题行 ── */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <Text strong style={{ fontSize: 14 }}>
                任务类型分布
              </Text>
              <Segmented
                size="small"
                value={chartType}
                onChange={(v) => setChartType(v as "pie" | "line")}
                options={[
                  { value: "pie", icon: <PieChartOutlined />, label: "饼图" },
                  { value: "line", icon: <LineChartOutlined />, label: "折线图" },
                ]}
              />
            </div>

            {(chartType === "pie" ? hasData : hasTrend) ? (
              <div style={{ marginTop: 4 }}>
                <ReactECharts option={chartOption} style={{ height: 280 }} notMerge />
              </div>
            ) : (
              <div style={{ padding: 40, textAlign: "center" }}>
                <Text type="secondary">暂无数据</Text>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
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
            {processStats.recent_tasks?.length > 0 ? (
              <Timeline
                items={processStats.recent_tasks.slice(0, 5).map((task: any) => ({
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

      {/* 快捷操作 */}
      <Card
        title={
          <span>
            <ToolOutlined style={{ marginRight: 8 }} />
            快捷操作
          </span>
        }
        style={{ marginTop: 16 }}
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
        .dashboard-container .status-card {
          height: 100%;
        }
        .dashboard-container .ant-card-head-title {
          padding: 12px 0;
        }
      `}</style>
    </div>
  );
}
