/**
 * 电量管理页面
 */
import { useState, useEffect } from "react";
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
  Progress,
  Popconfirm,
  Space,
  Badge,
  App,
  Tag,
} from "antd";
import { useRunningTasksPolling } from "@/hooks/useRunningTasksPolling";
import { useTaskPolling } from "@/hooks/useTaskPolling";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  ThunderboltOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  LineChartOutlined,
  DeleteOutlined,
  CloudDownloadOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { adminApi, processApi, type TaskProcess } from "@/api/admin";
import {
  electricityApi,
  type ElectricityRemaining,
  type ElectricityRecord,
} from "@/api/electricity";
import ElectricityChart from "@/components/ElectricityChart";
import { useUser } from "@/contexts/UserContext";

export default function Electricity() {
  const { isAdmin } = useUser();
  const { message } = App.useApp();
  const [activeTab, setActiveTab] = useState("remaining");
  const [loading, setLoading] = useState(false);
  const [remaining, setRemaining] = useState<ElectricityRemaining | null>(null);
  const [records, setRecords] = useState<ElectricityRecord[]>([]);
  const [config, setConfig] = useState<Record<string, any>>({});
  const [form] = Form.useForm();
  // 列表轮询开关（触发电量采集任务时开启）与全量爬取按 id 轮询
  const [listPolling, setListPolling] = useState(false);
  const [fullTaskId, setFullTaskId] = useState<number | null>(null);

  const fetchRemaining = async () => {
    setLoading(true);
    try {
      const res = await electricityApi.getRemaining();
      if (res.status === "success" && res.data) setRemaining(res.data);
    } catch (error) {
      console.error("加载剩余电量失败:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchRecords = async () => {
    setLoading(true);
    try {
      const res = await electricityApi.getRecords();
      if (res.status === "success" && res.data) setRecords(res.data);
    } catch (error) {
      console.error("加载用电记录失败:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await adminApi.getElectricityConfig();
      if (res.status === "success" && res.config) {
        setConfig(res.config);
        form.setFieldsValue(res.config);
      }
    } catch (error) {
      console.error("加载配置失败:", error);
    } finally {
      setLoading(false);
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

  // 任务完成后刷新数据
  const refreshAllData = () => {
    if (activeTab === "remaining") {
      fetchRemaining();
    } else if (activeTab === "records") {
      fetchRecords();
    } else if (activeTab === "chart") {
      // 图表组件内部会自己刷新
    }
  };

  // 列表轮询：触发电量采集任务后，轮询“运行中任务列表”，空则视为完成
  const listPoll = useRunningTasksPolling({
    fetcher: () => processApi.getRunning(),
    filter: (t) => t.task_type === "electricity",
    enabled: listPolling,
    onIdle: () => {
      message.success("任务已完成，数据已刷新");
      refreshAllData();
    },
  });

  // 全量爬取按 id 轮询（统一任务模型 Hook）
  const taskPoll = useTaskPolling<TaskProcess>(fullTaskId, {
    fetcher: (id) => processApi.getTaskStatus(id),
    resolve: (d) => ({ status: d.status, message: d.error_message ?? undefined }),
    onDone: () => {
      message.success("全量爬取任务已完成！正在刷新数据...");
      refreshAllData();
    },
    onFailed: (d) => message.error(`全量爬取失败: ${d.error_message || "未知错误"}`),
  });

  // 组合轮询状态供徽标 / 告警展示
  const isPolling = listPoll.isPolling || taskPoll.isPolling;
  const runningTasks = listPoll.running;

  // 仅触发电量采集：开启列表轮询
  const handleTrigger = async (taskType: string) => {
    try {
      const res = await adminApi.triggerElectricity(taskType);
      // 假期静默拦截：后端返回 skipped，提示已跳过且不开启「已完成」轮询
      if ((res as any).skipped) {
        message.warning(res.message || "假期静默中，已跳过");
        return;
      }
      message.success(res.message || "任务已触发");
      setListPolling(true);
    } catch (error) {
      message.error("触发任务失败");
    }
  };

  // 挂载时检查是否已有运行中的电量任务，有则接管轮询
  useEffect(() => {
    (async () => {
      try {
        const res = await processApi.getRunning();
        if (res.status === "success" && res.data?.data) {
          const hasRunning = res.data.data.some((t) => t.task_type === "electricity");
          if (hasRunning) setListPolling(true);
        }
      } catch (error) {
        console.error("检查运行中电量任务失败:", error);
      }
    })();
  }, []);

  /** 全量爬取 */
  const handleFetchAll = async () => {
    try {
      const res = await electricityApi.triggerFetchAll();
      if (res.status === "success") {
        const taskId = res.data?.task_id;
        message.success("全量爬取任务已启动，正在后台执行...");
        // 统一任务模型：有 task_id 走按 id 轮询，否则走列表轮询
        if (taskId != null) {
          setFullTaskId(taskId);
        } else {
          setListPolling(true);
        }
      } else {
        message.error(res.message || "全量爬取触发失败");
      }
    } catch (error) {
      message.error("全量爬取触发失败");
    }
  };

  /** 删除全部用电记录 */
  const handleDeleteAll = async () => {
    try {
      const res = await electricityApi.deleteAllRecords();
      if (res.status === "success") {
        const d = res.data;
        message.success(`已清空全部数据（用电记录 ${d?.deleted_records} 条）`);
        setRecords([]);
        setRemaining(null);
      }
    } catch (error) {
      message.error("删除失败");
    }
  };

  useEffect(() => {
    if (activeTab === "remaining") fetchRemaining();
    else if (activeTab === "records") fetchRecords();
    else if (activeTab === "config") fetchConfig();
  }, [activeTab]);

  const [pageSize, setPageSize] = useState(10);

  // 用电记录列：列少且窄屏也能一行放下，移动端保留原生表格。
  // 用百分比宽度铺满容器 + ellipsis，超长内容以省略号截断（桌面端悬浮显示完整值）。
  const recordColumns = [
    { title: "日期", dataIndex: "time", key: "time", width: "40%", ellipsis: true },
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

  /**
   * 获取电量百分比
   * 优先使用后端计算的百分比，如果没有则返回0
   */
  const getPercent = () => {
    if (!remaining) return 0;
    // 使用后端计算的百分比
    return Math.min(Math.max(remaining.percentage || 0, 0), 100);
  };

  // 为 records 数据生成唯一 key（避免重复 time 导致 key 冲突）
  const recordsWithKeys = records.map((item, idx) => ({ ...item, _uid: `${item.time}-${idx}` }));

  // 构建标签页数组，仅管理员显示配置标签
  const tabs = [
    {
      key: "remaining",
      label: <Space>剩余电量{isPolling && <Badge dot offset={[4, -4]} />}</Space>,
      icon: <ThunderboltOutlined />,
      children: (
        <div>
          {isPolling && (
            <Alert
              message={
                <Space>
                  <LoadingOutlined spin />
                  <span>任务运行中，自动刷新...</span>
                </Space>
              }
              type="info"
              showIcon={false}
              style={{ marginBottom: 16 }}
            />
          )}
          {loading ? (
            <Spin />
          ) : remaining ? (
            <div>
              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Card>
                    <Statistic
                      title="剩余电量"
                      value={remaining.default}
                      suffix="度"
                      prefix={<ThunderboltOutlined />}
                      valueStyle={{ color: remaining.is_low_power ? "#cf1322" : "#3f8600" }}
                    />
                    <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
                      总量: {remaining.total_capacity} 度
                    </div>
                    <Progress
                      percent={getPercent()}
                      status={remaining.is_low_power ? "exception" : "active"}
                      style={{ marginTop: 16 }}
                      format={(percent) => `${percent?.toFixed(1)}%`}
                    />
                    {remaining.is_low_power && (
                      <Alert
                        message="电量不足，请及时充值"
                        type="warning"
                        showIcon
                        style={{ marginTop: 16 }}
                      />
                    )}
                  </Card>
                </Col>
              </Row>
              <Space style={{ marginTop: 16 }}>
                <Button icon={<ReloadOutlined />} onClick={fetchRemaining} disabled={isPolling}>
                  刷新数据
                </Button>
                {isAdmin && (
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={() => handleTrigger("fetch_electricity_data")}
                    disabled={isPolling}
                    loading={isPolling}
                  >
                    触发数据采集
                  </Button>
                )}
              </Space>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: 40 }}>
              <Alert message="暂无数据，请先触发数据采集" type="info" />
              {isAdmin && (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleTrigger("fetch_electricity_data")}
                  style={{ marginTop: 16 }}
                  disabled={isPolling}
                  loading={isPolling}
                >
                  触发数据采集
                </Button>
              )}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "records",
      label: <Space>用电记录{isPolling && <Badge dot offset={[4, -4]} />}</Space>,
      children: (
        <div>
          {isPolling && (
            <Alert
              message={
                <div>
                  <Space>
                    <LoadingOutlined spin />
                    <span>任务运行中，自动刷新...</span>
                  </Space>
                  {runningTasks.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      {runningTasks.map((task) => (
                        <div key={task.id} style={{ marginBottom: 4 }}>
                          <Tag color="processing">{task.task_type}</Tag>
                          <span style={{ fontSize: 12, color: "#666" }}>
                            {task.message || "正在执行..."}
                          </span>
                          {task.progress !== undefined && (
                            <Progress
                              percent={task.progress}
                              size="small"
                              style={{ marginTop: 4 }}
                              status={task.status === "failed" ? "exception" : "active"}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              }
              type="info"
              showIcon={false}
              style={{ marginBottom: 16 }}
            />
          )}
          {loading ? (
            <Spin />
          ) : (
            <div>
              <Space style={{ marginBottom: 16 }}>
                <Button icon={<ReloadOutlined />} onClick={fetchRecords} disabled={isPolling}>
                  刷新
                </Button>
                {isAdmin && (
                  <>
                    <Button
                      icon={<CloudDownloadOutlined />}
                      onClick={handleFetchAll}
                      disabled={isPolling}
                    >
                      全量爬取
                    </Button>
                    <Popconfirm
                      title="确定要删除全部用电记录吗？"
                      description="此操作不可恢复，删除后需要重新爬取数据。"
                      onConfirm={handleDeleteAll}
                      okText="确定删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button danger icon={<DeleteOutlined />} disabled={isPolling}>
                        清空全部记录
                      </Button>
                    </Popconfirm>
                  </>
                )}
              </Space>
              <ResponsiveTable
                dataSource={recordsWithKeys}
                columns={recordColumns}
                rowKey="_uid"
                mobileNativeTable
                tableLayout="fixed"
                pagination={{
                  pageSize,
                  pageSizeOptions: ["10", "20", "50"],
                  showSizeChanger: true,
                  onShowSizeChange: (_current, size) => setPageSize(size),
                }}
                size="small"
              />
            </div>
          )}
        </div>
      ),
    },
    {
      key: "chart",
      label: "数据可视化",
      icon: <LineChartOutlined />,
      children: <ElectricityChart />,
    },
  ];

  // 仅管理员添加配置标签
  if (isAdmin) {
    tabs.push({
      key: "config",
      label: "模块配置",
      icon: <SettingOutlined />,
      children: loading ? (
        <Spin />
      ) : (
        <Form form={form} layout="vertical" onFinish={handleSaveConfig} style={{ maxWidth: 600 }}>
          <Form.Item name="cookie" label="爬虫 Cookie">
            <Input.TextArea rows={3} placeholder="JSESSIONID=xxx; leech_k=xxx" />
          </Form.Item>
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
      ),
    });
  }

  return (
    <div>
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} />
      </Card>
    </div>
  );
}
