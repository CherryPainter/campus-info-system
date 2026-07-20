/**
 * 电量可视化组件
 * 包含：时间筛选器 + 统计卡片 + 用电趋势折线图 + 电表对比柱状图 + 用电占比饼图
 */
import { useState, useEffect } from "react";
import { Row, Col, Card, Statistic, Spin, Empty, Radio, DatePicker, Space, Typography } from "antd";
import {
  ThunderboltOutlined,
  BarChartOutlined,
  PieChartOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
} from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import { electricityApi, type ElectricityStatistics, type RangeType } from "@/api/electricity";
import dayjs from "dayjs";

const { Text } = Typography;
const { RangePicker } = DatePicker;

/** 主题色 */
const COLORS = ["#1890ff", "#52c41a", "#faad14", "#ff4d4f", "#722ed1", "#13c2c2"];

/** 时间范围选项 */
const RANGE_OPTIONS = [
  { label: "本周", value: "week" },
  { label: "上周", value: "last_week" },
  { label: "本月", value: "month" },
  { label: "上月", value: "last_month" },
];

export default function ElectricityChart() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ElectricityStatistics | null>(null);
  const [rangeType, setRangeType] = useState<RangeType>("month");
  const [customDates, setCustomDates] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  const fetchData = async () => {
    if (rangeType === "custom") return; // 自定义日期单独处理
    setLoading(true);
    try {
      const res = await electricityApi.getStatistics(rangeType);
      if (res.status === "success" && res.data) setData(res.data);
    } catch (error) {
      console.error("加载用电统计失败:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rangeType]);

  // 处理时间范围切换
  const handleRangeChange = (e: any) => {
    const value = e.target.value as RangeType;
    setRangeType(value);
    setCustomDates(null);
  };

  // 处理自定义日期选择
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleCustomDateChange: any = (dates: any) => {
    if (dates && dates[0] && dates[1]) {
      setCustomDates(dates);
      setRangeType("custom");
      // 使用 setTimeout 确保状态更新后再获取数据
      setTimeout(() => {
        fetchCustomData(dates);
      }, 0);
    }
  };

  // 获取自定义日期范围的数据
  const fetchCustomData = async (dates: [dayjs.Dayjs, dayjs.Dayjs]) => {
    setLoading(true);
    try {
      const res = await electricityApi.getStatistics(
        "custom",
        dates[0].format("YYYY-MM-DD"),
        dates[1].format("YYYY-MM-DD")
      );
      if (res.status === "success" && res.data) setData(res.data);
    } catch (error) {
      console.error("加载用电统计失败:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading)
    return (
      <div style={{ textAlign: "center", padding: 50 }}>
        <Spin size="large" />
      </div>
    );
  if (!data || !data.daily.length) return <Empty description="暂无用电数据，请先触发数据采集" />;

  const { daily, by_meter, summary, range } = data;

  // 显示当前查询的时间范围
  const rangeText = range ? `${range.start_date} 至 ${range.end_date}` : "";

  /** 折线图：每日用电趋势 */
  const lineOption = {
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: any) =>
        `${params[0].axisValue}<br/>用电量: ${Number(params[0].value).toFixed(2)} 度`,
    },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: "category" as const,
      data: daily.map((d) => d.date.slice(5)),
      axisLabel: { fontSize: 11 },
    },
    yAxis: { type: "value" as const, name: "用电量(度)", nameTextStyle: { fontSize: 11 } },
    series: [
      {
        name: "用电量",
        type: "line",
        data: daily.map((d) => Number(d.usage.toFixed(2))),
        smooth: true,
        areaStyle: { opacity: 0.15 },
        itemStyle: { color: "#1890ff" },
      },
    ],
  };

  /** 柱状图：各电表用电对比 */
  const barOption = {
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: any) => `${params[0].name}<br/>用电量: ${params[0].value} 度`,
    },
    grid: { left: 120, right: 20, top: 20, bottom: 30 },
    xAxis: { type: "value" as const, name: "用电量(度)", nameTextStyle: { fontSize: 11 } },
    yAxis: {
      type: "category" as const,
      data: by_meter.map((m) => m.meter),
      axisLabel: { fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        data: by_meter.map((m, i) => ({
          value: m.usage,
          itemStyle: { color: COLORS[i % COLORS.length], borderRadius: [0, 4, 4, 0] },
        })),
        barWidth: "50%",
      },
    ],
  };

  /** 饼图：各电表用电占比 */
  const pieOption = {
    tooltip: {
      trigger: "item" as const,
      formatter: (params: any) => `${params.name}<br/>${params.value} 度 (${params.percent}%)`,
    },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    series: [
      {
        type: "pie",
        radius: ["40%", "65%"],
        center: ["50%", "45%"],
        data: by_meter.map((m, i) => ({
          name: m.meter,
          value: m.usage,
          itemStyle: { color: COLORS[i % COLORS.length] },
        })),
        label: { formatter: "{b}\n{d}%", fontSize: 11 },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.2)" },
        },
      },
    ],
  };

  return (
    <div>
      {/* 时间筛选器 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space>
            <Text strong>时间范围：</Text>
            <Radio.Group
              options={RANGE_OPTIONS}
              value={rangeType}
              onChange={handleRangeChange}
              optionType="button"
              buttonStyle="solid"
            />
            <RangePicker
              value={customDates}
              onChange={handleCustomDateChange}
              placeholder={["开始日期", "结束日期"]}
              style={{ width: 240 }}
            />
          </Space>
          {rangeText && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前查询：{rangeText}
            </Text>
          )}
        </Space>
      </Card>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总用电量"
              value={summary.total_usage}
              suffix="度"
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: "#1890ff" }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="日均用电"
              value={summary.avg_daily}
              suffix="度"
              prefix={<BarChartOutlined />}
              valueStyle={{ color: "#52c41a" }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="单日最高"
              value={summary.max_daily}
              suffix="度"
              prefix={<ArrowUpOutlined />}
              valueStyle={{ color: "#ff4d4f" }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="单日最低"
              value={summary.min_daily}
              suffix="度"
              prefix={<ArrowDownOutlined />}
              valueStyle={{ color: "#52c41a" }}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表区域 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title={`每日用电趋势 (${daily.length}天)`} size="small">
            <ReactECharts option={lineOption} style={{ height: 300 }} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="电表用电占比" size="small">
            <ReactECharts option={pieOption} style={{ height: 300 }} />
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="各电表用电对比" size="small">
            <ReactECharts
              option={barOption}
              style={{ height: Math.max(200, by_meter.length * 50) }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
