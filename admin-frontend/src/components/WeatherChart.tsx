/**
 * 天气可视化组件
 * 包含：天气概况卡片 + 温度趋势折线图 + 降水概率柱状图 + 湿度变化折线图
 */
import { useState, useEffect } from "react";
import { Row, Col, Card, Statistic, Spin, Empty, Tag } from "antd";
import { CloudOutlined, FireOutlined, FlagOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import { weatherApi, type WeatherStatistics } from "@/api/weather";

/** 天气图标映射（emoji） */
const WEATHER_ICON: Record<string, string> = {
  晴: "☀️",
  多云: "⛅",
  阴: "☁️",
  小雨: "🌧️",
  中雨: "🌧️",
  大雨: "🌧️",
  暴雨: "⛈️",
  雷阵雨: "⛈️",
  小雪: "🌨️",
  中雪: "🌨️",
  大雪: "❄️",
  雾: "🌫️",
  霾: "🌫️",
};

/** 天气图标精灵图位置映射（5行×4列）
 * 第1行: 雷阵雨(0,0) 多云转雨(1,0) 雨夹雪(2,0) 雾(3,0)
 * 第2行: 多云(0,1) 雾霾(1,1) 夜间多云(2,1) 冰雹(3,1)
 * 第3行: 阴天(0,2) 晴夜(1,2) 彩虹(2,2) 夜间雨(3,2)
 * 第4行: 风向(0,3) 晴天(1,3) 月亮(2,3) 小雪(3,3)
 * 第5行: 雷雨(0,4) 夜间雷雨(1,4) 大雨(2,4) 日出(3,4)
 */
const WEATHER_SPRITE_MAP: Record<string, { x: number; y: number }> = {
  晴: { x: 1, y: 3 }, // 晴天
  多云: { x: 0, y: 1 }, // 多云
  阴: { x: 0, y: 2 }, // 阴天
  小雨: { x: 1, y: 0 }, // 多云转雨
  中雨: { x: 2, y: 4 }, // 大雨
  大雨: { x: 2, y: 4 }, // 大雨
  暴雨: { x: 2, y: 4 }, // 大雨
  雷阵雨: { x: 0, y: 0 }, // 雷阵雨
  小雪: { x: 3, y: 3 }, // 小雪
  中雪: { x: 3, y: 3 }, // 小雪
  大雪: { x: 3, y: 3 }, // 小雪
  雾: { x: 3, y: 0 }, // 雾
  霾: { x: 1, y: 1 }, // 雾霾
};

/** 获取天气图标背景样式 */
const getWeatherBgStyle = (weatherText: string): React.CSSProperties => {
  const pos = WEATHER_SPRITE_MAP[weatherText] || { x: 1, y: 3 }; // 默认晴天
  const iconSize = 100; // 每个图标100×100像素
  const displaySize = 80; // 显示大小
  return {
    backgroundImage: "url(/weather-icons.png)",
    backgroundSize: "400px 500px", // 4列×5行
    backgroundPosition: `-${pos.x * iconSize}px -${pos.y * iconSize}px`,
    width: `${displaySize}px`,
    height: `${displaySize}px`,
    opacity: 0.2,
  };
};

export default function WeatherChart() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<WeatherStatistics | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await weatherApi.getStatistics();
      if (res.status === "success" && res.data) setData(res.data);
    } catch (error) {
      console.error("加载天气统计失败:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading)
    return (
      <div style={{ textAlign: "center", padding: 50 }}>
        <Spin size="large" />
      </div>
    );
  if (!data || !data.hourly.length) return <Empty description="暂无天气数据，请稍后重试" />;

  const { now, hourly } = data;

  /** 从 fxTime 中提取小时 */
  const hours = hourly.map((h) => {
    const t = h.time || "";
    return t.includes("T") ? t.split("T")[1].slice(0, 5) : t.slice(11, 16);
  });

  const temps = hourly.map((h) => parseFloat(h.temp) || 0);
  const pops = hourly.map((h) => parseFloat(h.pop) || 0);
  const humidities = hourly.map((h) => parseFloat(h.humidity) || 0);

  /** 温度 + 降水概率组合图 */
  const tempPopOption = {
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: any) => {
        let s = `${params[0].axisValue}<br/>`;
        params.forEach((p: any) => {
          s += `${p.marker} ${p.seriesName}: ${p.value}${p.seriesName === "温度" ? "°C" : "%"}`;
        });
        return s;
      },
    },
    legend: { data: ["温度", "降水概率"], top: 0 },
    grid: { left: 50, right: 50, top: 50, bottom: 60 },
    xAxis: {
      type: "category" as const,
      data: hours,
      axisLabel: {
        fontSize: 10,
        rotate: 45,
        interval: "auto",
      },
    },
    yAxis: [
      {
        type: "value" as const,
        name: "温度(°C)",
        nameTextStyle: { fontSize: 11 },
        min: Math.min(...temps) - 2,
        max: Math.max(...temps) + 2,
      },
      {
        type: "value" as const,
        name: "降水概率(%)",
        nameTextStyle: { fontSize: 11 },
        max: 100,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "温度",
        type: "line",
        data: temps,
        smooth: true,
        areaStyle: { opacity: 0.12 },
        itemStyle: { color: "#ff6b35" },
        lineStyle: { width: 2 },
      },
      {
        name: "降水概率",
        type: "bar",
        yAxisIndex: 1,
        data: pops,
        barWidth: "40%",
        itemStyle: { color: "#4096ff", borderRadius: [3, 3, 0, 0], opacity: 0.7 },
      },
    ],
  };

  /** 湿度变化折线图 */
  const humidityOption = {
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: any) => `${params[0].axisValue}<br/>湿度: ${params[0].value}%`,
    },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: {
      type: "category" as const,
      data: hours,
      axisLabel: { fontSize: 11, rotate: hours.length > 12 ? 45 : 0 },
    },
    yAxis: {
      type: "value" as const,
      name: "湿度(%)",
      nameTextStyle: { fontSize: 11 },
      min: 0,
      max: 100,
    },
    series: [
      {
        name: "湿度",
        type: "line",
        data: humidities,
        smooth: true,
        areaStyle: { opacity: 0.15 },
        itemStyle: { color: "#52c41a" },
        lineStyle: { width: 2 },
      },
    ],
  };

  /** 风力信息 */
  const windInfo = hourly.map((h) => ({
    time: hours[hourly.indexOf(h)],
    text: h.text,
    wind: `${h.wind_dir} ${(h as any).wind_scale || (h as any).windScale}级`,
  }));

  return (
    <div>
      {/* 天气概况卡片 */}
      {now && (
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}>
            <Card
              size="small"
              styles={{ body: { height: 90, position: "relative", overflow: "hidden" } }}
            >
              {/* 背景图标 */}
              <div
                style={{
                  ...getWeatherBgStyle(now.text),
                  position: "absolute",
                  right: 8,
                  bottom: 8,
                  pointerEvents: "none",
                  zIndex: 0,
                }}
              />
              <Statistic
                title="当前天气"
                value={now.text}
                prefix={<CloudOutlined />}
                valueStyle={{ color: "#1890ff", fontSize: 20 }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card
              size="small"
              styles={{
                body: {
                  height: 90,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                },
              }}
            >
              <Statistic
                title="当前温度"
                value={now.temp}
                suffix="°C"
                prefix={<FireOutlined />}
                valueStyle={{ color: "#ff6b35" }}
              />
              <div style={{ color: "#999", fontSize: 12, marginTop: 4 }}>
                体感 {now.feels_like}°C
              </div>
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card
              size="small"
              styles={{
                body: {
                  height: 90,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                },
              }}
            >
              <Statistic
                title="相对湿度"
                value={now.humidity}
                suffix="%"
                prefix={<CloudOutlined />}
                valueStyle={{ color: "#52c41a" }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card
              size="small"
              styles={{
                body: {
                  height: 90,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                },
              }}
            >
              <Statistic
                title="风向风力"
                value={`${now.wind_dir} ${now.wind_scale}级`}
                prefix={<FlagOutlined />}
                valueStyle={{ fontSize: 16 }}
              />
              <div style={{ color: "#999", fontSize: 12, marginTop: 4 }}>{now.city_name}</div>
            </Card>
          </Col>
        </Row>
      )}

      {/* 图表区域 */}
      <Row gutter={[16, 16]}>
        <Col xs={24}>
          <Card title="24 小时温度与降水趋势" size="small">
            <ReactECharts option={tempPopOption} style={{ height: 320 }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="24 小时湿度变化" size="small">
            <ReactECharts option={humidityOption} style={{ height: 280 }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="逐时天气概况" size="small">
            <div style={{ maxHeight: 280, overflowY: "auto" }}>
              {windInfo.map((w, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "6px 0",
                    borderBottom: "1px solid #f0f0f0",
                  }}
                >
                  <span style={{ color: "#666", width: 80, flexShrink: 0 }}>{w.time}</span>
                  <span
                    style={{
                      flex: 1,
                      textAlign: "center",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 6,
                    }}
                  >
                    <span>{WEATHER_ICON[w.text] || "🌤️"}</span>
                    <span>{w.text}</span>
                  </span>
                  <Tag
                    color="blue"
                    style={{ width: 110, textAlign: "center", justifyContent: "center" }}
                  >
                    {w.wind}
                  </Tag>
                </div>
              ))}
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
