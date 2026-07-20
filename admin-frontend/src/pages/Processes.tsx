/**
 * 任务进程管理页面
 */
import { useState, useEffect, useRef } from 'react';
import { Card, Button, Space, Tag, Progress, Badge, Popconfirm, Select, Tooltip, Modal, Descriptions, Statistic, Row, Col, Timeline, Alert, Divider, App, Tabs, Form, Radio, Input, DatePicker } from 'antd';
import ResponsiveTable from '@/components/ResponsiveTable';
import { ThunderboltOutlined, ReloadOutlined, PauseCircleOutlined, DeleteOutlined, ClockCircleOutlined, ScheduleOutlined, HistoryOutlined, EyeOutlined, ExclamationCircleOutlined, CheckCircleFilled, CloseCircleFilled, ClockCircleFilled, NotificationOutlined, BookOutlined, PlusOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons';
import { processApi, type TaskProcess, type ScheduledJob, type DynamicRule } from '@/api/admin';
import { holidayApi, type HolidayStatus } from '@/api/holiday';
import { PROCESS_STATUS_MAP, CRAWL_TASK_STATUS_MAP } from '@/constants/statusMaps';
import { courseApi, type CrawlTask } from '@/api/course';
import CrawlScheduler from './CrawlScheduler';
import dayjs from 'dayjs';
import { formatDateTime, formatTimeShort } from '@/utils/datetime';
import { useIntervalPolling } from '@/hooks/useIntervalPolling';
import { useTaskPolling } from '@/hooks/useTaskPolling';
import { POLL_TICK, POLL_NORMAL } from '@/hooks/pollIntervals';

const { Option } = Select;

export default function Processes() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [processes, setProcesses] = useState<TaskProcess[]>([]);
  const [runningCount, setRunningCount] = useState(0);
  const [scheduledJobs, setScheduledJobs] = useState<ScheduledJob[]>([]);
  const scheduledJobsRef = useRef<ScheduledJob[]>([]);
  const [dynamicRules, setDynamicRules] = useState<DynamicRule[]>([]);
  const [now, setNow] = useState(dayjs());
  const [pagination, setPagination] = useState({ total: 0, page: 1, per_page: 20, pages: 0 });
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterTaskType, setFilterTaskType] = useState<string>('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedProcess, setSelectedProcess] = useState<TaskProcess | null>(null);
  const [stats, setStats] = useState({
    total: 0,
    completed: 0,
    failed: 0,
    running: 0,
    avgDuration: 0,
  });
  const [holidayStatus, setHolidayStatus] = useState<HolidayStatus | null>(null);

  // ===== 课程爬取预约任务（增删改查） =====
  const [crawlTasks, setCrawlTasks] = useState<CrawlTask[]>([]);
  const [crawlLoading, setCrawlLoading] = useState(false);
  const [crawlPagination, setCrawlPagination] = useState({ total: 0, page: 1, per_page: 20, pages: 0 });
  const [crawlFilterStatus, setCrawlFilterStatus] = useState<string>('');
  const [crawlSchedulerVisible, setCrawlSchedulerVisible] = useState(false);
  const [crawlDetailVisible, setCrawlDetailVisible] = useState(false);
  const [selectedCrawlTask, setSelectedCrawlTask] = useState<CrawlTask | null>(null);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editForm] = Form.useForm();
  const [editingTask, setEditingTask] = useState<CrawlTask | null>(null);
  const [editLoading, setEditLoading] = useState(false);

  const fetchCrawlTasks = async (page = 1, status = crawlFilterStatus) => {
    setCrawlLoading(true);
    try {
      const res = await courseApi.crawlTasks.list({ page, per_page: 20, status });
      setCrawlTasks(res.data);
      setCrawlPagination(res.pagination);
    } catch (error) {
      message.error('获取爬取预约任务失败');
    } finally {
      setCrawlLoading(false);
    }
  };

  const handleCrawlDelete = async (id: number) => {
    try {
      await courseApi.crawlTasks.delete(id);
      message.success('已删除');
      fetchCrawlTasks(crawlPagination.page);
    } catch (error) {
      message.error('删除失败');
    }
  };

  // 爬取任务按 id 轮询（统一任务模型 Hook），完成即刷新进程与爬取列表
  const [procCrawlId, setProcCrawlId] = useState<number | null>(null);
  useTaskPolling<CrawlTask>(procCrawlId, {
    fetcher: (id) => courseApi.crawlTasks.get(id),
    resolve: (d) => ({ status: d.status, message: d.message ?? d.error_message ?? undefined }),
    onDone: () => {
      fetchCrawlTasks(crawlPagination.page);
      fetchProcesses(pagination.page, filterStatus, filterTaskType);
      message.success('爬取任务已完成');
    },
    onFailed: (d) => message.error(d.error_message || '爬取任务失败'),
  });

  const handleCrawlCancel = async (id: number) => {
    try {
      await courseApi.crawlTasks.cancel(id);
      message.success('已取消');
      fetchCrawlTasks(crawlPagination.page);
    } catch (error) {
      message.error('取消失败');
    }
  };

  const handleCrawlRun = async (id: number) => {
    try {
      await courseApi.crawlTasks.run(id);
      message.success('已立即启动');
      fetchCrawlTasks(crawlPagination.page);
    } catch (error) {
      message.error('启动失败');
    }
  };

  const openEdit = (task: CrawlTask) => {
    setEditingTask(task);
    editForm.setFieldsValue({
      name: task.name,
      scope: task.scope,
      schedule_type: task.schedule_type,
      scheduled_at: task.scheduled_at ? dayjs(task.scheduled_at) : null,
    });
    setEditModalVisible(true);
  };

  const submitEdit = async () => {
    if (!editingTask) return;
    try {
      const values = await editForm.validateFields();
      setEditLoading(true);
      const payload: any = {
        name: values.name,
        scope: values.scope,
        schedule_type: values.schedule_type,
      };
      if (values.scope === 'semester') {
        payload.semester_id = editingTask.semester_id;
        payload.eams_id = editingTask.eams_id || undefined;
      }
      if (values.schedule_type === 'scheduled') {
        payload.scheduled_at = values.scheduled_at
          ? dayjs(values.scheduled_at).format('YYYY-MM-DDTHH:mm:ss')
          : null;
      }
      const res = await courseApi.crawlTasks.update(editingTask.id, payload);
      if (res.status === 'success') {
        message.success('已更新');
        setEditModalVisible(false);
        fetchCrawlTasks(crawlPagination.page);
      } else {
        message.error(res.message || '更新失败');
      }
    } catch (error) {
      console.error(error);
    } finally {
      setEditLoading(false);
    }
  };

  const fetchProcesses = async (page = 1, status = filterStatus, taskType = filterTaskType) => {
    setLoading(true);
    try {
      const res = await processApi.getList({ page, per_page: 20, status, task_type: taskType });
      
      // 后端返回结构：{ data: [...], pagination: {...}, stats: {...} }
      const processList = Array.isArray(res.data) ? res.data : [];
      const paginationData = res.pagination || { total: processList.length, page: 1, per_page: 20, pages: 1 };
      const statsData = res.stats || { total: 0, completed: 0, failed: 0, running: 0, avg_duration: 0 };

      setProcesses(processList);
      setPagination(paginationData);

      // 使用后端返回的统计数据（基于所有数据）
      setStats({
        total: statsData.total,
        completed: statsData.completed,
        failed: statsData.failed,
        running: statsData.running,
        avgDuration: statsData.avg_duration,
      });

      // 获取运行中进程数
      const runningRes = await processApi.getRunning();
      if (runningRes.status === 'success') {
        setRunningCount(runningRes.data?.count || 0);
      }
    } catch (error) {
      message.error('获取进程列表失败');
    } finally {
      setLoading(false);
    }
  };

  /** 独立获取动态规则配置（与进程列表分离，从后端实时读取） */
  const fetchDynamicRules = async () => {
    try {
      const rulesRes = await processApi.getRules();
      if (rulesRes.status === 'success') {
        setDynamicRules((rulesRes as any).data || []);
      }
    } catch (error) {
      // 静默失败，不打断轮询
    }
  };

  /** 独立获取定时任务计划（与进程列表分离，避免进程列表API出错时影响定时任务刷新） */
  const fetchScheduledJobs = async () => {
    try {
      const scheduledRes = await processApi.getScheduled();
      if (scheduledRes.status === 'success') {
        setScheduledJobs((scheduledRes as any).data || []);
      }
    } catch (error) {
      // 静默失败，不打断轮询
    }
  };

  // 初始化加载数据
  useEffect(() => {
    fetchProcesses();
    fetchScheduledJobs();
    fetchDynamicRules();
    fetchCrawlTasks();
    // 假期模式生效状态（用于顶部静音横幅）
    holidayApi.getStatus()
      .then((res) => { if (res.status === 'success' && res.data) setHolidayStatus(res.data); })
      .catch(() => {});
  }, []);

  // 爬取预约任务自动刷新（5秒，统一轮询 Hook；immediate=false 保持原「先等一个周期」行为）
  useIntervalPolling(() => fetchCrawlTasks(crawlPagination.page), POLL_NORMAL, autoRefresh, false);

  // 同步 scheduledJobs 到 ref（供智能轮询间隔计算使用）
  useEffect(() => {
    scheduledJobsRef.current = scheduledJobs;
  }, [scheduledJobs]);

  // 自动刷新进程列表（5秒间隔，统一轮询 Hook）
  useIntervalPolling(
    () => fetchProcesses(pagination.page, filterStatus, filterTaskType),
    POLL_NORMAL,
    autoRefresh,
    false,
  );

  // 独立轮询定时任务计划（智能间隔：即将执行/数据过期时2秒，正常5秒）
  useEffect(() => {
    if (!autoRefresh) return;

    let timeoutId: ReturnType<typeof setTimeout>;

    const poll = async () => {
      await fetchScheduledJobs();

      // 根据当前任务状态决定下次轮询间隔
      const jobs = scheduledJobsRef.current;
      const currentTime = dayjs();
      const hasImminent = jobs.some(job => {
        if (!job.next_run) return false;
        const diff = dayjs(job.next_run).diff(currentTime);
        return diff > 0 && diff <= 10000; // 10秒内即将执行
      });
      const hasStale = jobs.some(job => {
        if (!job.next_run) return false;
        return dayjs(job.next_run).diff(currentTime) <= 0; // 已过期
      });

      // 即将执行或数据过期时加快轮询频率
      const interval = (hasImminent || hasStale) ? 2000 : 5000;
      timeoutId = setTimeout(poll, interval);
    };

    timeoutId = setTimeout(poll, 3000);

    return () => clearTimeout(timeoutId);
  }, [autoRefresh]);

  // 每秒更新当前时间（用于倒计时，统一轮询 Hook）
  useIntervalPolling(() => setNow(dayjs()), POLL_TICK);

  /** 格式化倒计时
   *  @param nextRun 下次执行时间（ISO 格式）
   *  @param pending 任务是否正在执行中（来自 APScheduler 的 pending 状态）
   */
  const formatCountdown = (nextRun: string | null, pending: boolean) => {
    if (!nextRun) return null;

    // 解析下次执行时间（处理带时区的ISO格式）
    const nextRunTime = dayjs(nextRun);
    if (!nextRunTime.isValid()) return null;

    // 计算与当前时间的差值（毫秒）
    const diff = nextRunTime.diff(now);

    // 任务正在执行中（APScheduler 标记为 pending）
    if (pending && diff <= 0) return '执行中';

    // next_run 已过期但任务尚未开始执行，等待调度器更新下次时间
    if (diff <= 0) return '等待更新';

    // 如果即将执行（5秒内）
    if (diff <= 5000) return '即将执行';

    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    // 根据时间长度返回不同格式
    if (seconds < 60) {
      return `${seconds}秒后`;
    } else if (minutes < 60) {
      return `${minutes}分${seconds % 60}秒后`;
    } else if (hours < 24) {
      return `${hours}小时${minutes % 60}分后`;
    } else {
      return `${days}天${hours % 24}小时后`;
    }
  };

  const handleStop = async (id: number) => {
    try {
      await processApi.stop(id);
      message.success('进程已停止');
      fetchProcesses(pagination.page);
    } catch (error) {
      message.error('停止失败');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await processApi.delete(id);
      message.success('进程已删除');
      fetchProcesses(pagination.page);
    } catch (error) {
      message.error('删除失败');
    }
  };

  const handleRefresh = () => {
    fetchProcesses(pagination.page);
    fetchScheduledJobs();
    fetchDynamicRules();
  };

  const handleViewDetail = (record: TaskProcess) => {
    setSelectedProcess(record);
    setDetailModalVisible(true);
  };

  const handleCloseDetail = () => {
    setDetailModalVisible(false);
    setSelectedProcess(null);
  };

  const statusMap = PROCESS_STATUS_MAP;

  const typeMap: Record<string, { color: string; text: string }> = {
    spider: { color: 'blue', text: '课表爬虫' },
    course_spider: { color: 'blue', text: '课表爬虫' },
    course_full_crawl: { color: 'purple', text: '全量爬取' },
    course: { color: 'green', text: '课表' },
    weather: { color: 'cyan', text: '天气' },
    electricity: { color: 'orange', text: '电量' },
    system: { color: 'red', text: '系统' },
    custom: { color: 'purple', text: '自定义' },
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${Math.floor(seconds)}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分${Math.floor(seconds % 60)}秒`;
    return `${Math.floor(seconds / 3600)}时${Math.floor((seconds % 3600) / 60)}分`;
  };

  // 爬取预约任务状态映射（列表列、折叠头部、详情共用）
  const crawlStatusMap = CRAWL_TASK_STATUS_MAP;

  /** 渲染任务进程详情（供桌面端详情弹窗与移动端折叠面板复用） */
  const renderProcessDetail = (p: TaskProcess) => (
    <div>
      {/* 状态概览 */}
      <Alert
        message={<Space>{statusMap[p.status]?.icon}<span>{statusMap[p.status]?.text}</span></Space>}
        type={p.status === 'completed' ? 'success' : p.status === 'failed' ? 'error' : p.status === 'running' ? 'info' : p.status === 'skipped' ? 'warning' : 'warning'}
        showIcon={false}
        style={{ marginBottom: 16 }}
      />

      {/* 基本信息（移动端单列、桌面端双列） */}
      <Descriptions title="基本信息" bordered column={{ xs: 1, sm: 2 }} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="任务名称">{p.name}</Descriptions.Item>
        <Descriptions.Item label="任务类型">
          <Tag color={typeMap[p.task_type]?.color}>{typeMap[p.task_type]?.text}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="进程ID">{p.pid || '-'}</Descriptions.Item>
        <Descriptions.Item label="创建人">{p.created_by || 'system'}</Descriptions.Item>
        <Descriptions.Item label="开始时间">
          {p.started_at ? formatDateTime(p.started_at) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="完成时间">
          {p.completed_at ? formatDateTime(p.completed_at) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="执行时长">
          {p.status === 'running'
            ? formatDuration(dayjs().diff(dayjs(p.started_at), 'second'))
            : formatDuration(p.duration)}
        </Descriptions.Item>
        <Descriptions.Item label="进度">{p.progress}%</Descriptions.Item>
      </Descriptions>

      {/* 进度详情 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 8, fontWeight: 500 }}>执行进度</div>
        <Progress
          percent={p.progress}
          status={p.status === 'failed' ? 'exception' : p.status === 'completed' ? 'success' : p.status === 'skipped' ? 'normal' : 'active'}
          format={(percent) => `${p.processed_items} / ${p.total_items} (${percent}%)`}
        />
      </div>

      {/* 执行时间线 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 8, fontWeight: 500 }}>执行时间线</div>
        <Timeline
          items={[
            { color: 'blue', children: `任务创建 ${formatDateTime(p.started_at)}` },
            ...(p.status === 'running' ? [{ color: 'blue', children: '执行中...' }] : []),
            ...(p.status === 'completed' ? [{ color: 'green', children: `执行完成 ${formatDateTime(p.completed_at)}` }] : []),
            ...(p.status === 'failed' ? [{ color: 'red', children: `执行失败 ${formatDateTime(p.completed_at)}` }] : []),
            ...(p.status === 'cancelled' ? [{ color: 'gray', children: `已取消 ${formatDateTime(p.completed_at)}` }] : []),
            ...(p.status === 'skipped' ? [{ color: 'orange', children: `${p.message || '已静默'} ${formatDateTime(p.completed_at || p.started_at)}` }] : []),
          ]}
        />
      </div>

      {/* 状态消息 */}
      {p.message && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>状态消息</div>
          <div style={{
            padding: 12,
            background: p.status === 'failed' ? '#fff2f0' : p.status === 'skipped' ? '#fffbe6' : '#f6ffed',
            borderRadius: 4,
            border: `1px solid ${p.status === 'failed' ? '#ffccc7' : p.status === 'skipped' ? '#ffe58f' : '#b7eb8f'}`,
            color: p.status === 'failed' ? '#ff4d4f' : undefined,
          }}>
            {p.message}
          </div>
        </div>
      )}

      {/* 错误信息 */}
      {p.error_message && (
        <div>
          <div style={{ marginBottom: 8, fontWeight: 500, color: '#ff4d4f' }}>
            <ExclamationCircleOutlined style={{ marginRight: 4 }} />
            错误信息
          </div>
          <div style={{ padding: 12, background: '#fff2f0', borderRadius: 4, border: '1px solid #ffccc7', color: '#ff4d4f', fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {p.error_message}
          </div>
        </div>
      )}
    </div>
  );

  /** 渲染爬取预约任务详情（供桌面端详情弹窗与移动端折叠面板复用） */
  const renderCrawlDetail = (t: CrawlTask) => (
    <Descriptions bordered column={1} size="small">
      <Descriptions.Item label="任务名称">{t.name}</Descriptions.Item>
      <Descriptions.Item label="爬取范围">
        {t.scope === 'all' ? '全量（所有学期）' : `指定学期 ${t.semester_id || ''}`}
      </Descriptions.Item>
      <Descriptions.Item label="执行方式">
        {t.schedule_type === 'immediate' ? '立即执行' : `预约 ${t.scheduled_at ? formatDateTime(t.scheduled_at) : '-'}`}
      </Descriptions.Item>
      <Descriptions.Item label="状态">{crawlStatusMap[t.status]?.text || t.status}</Descriptions.Item>
      <Descriptions.Item label="创建时间">{t.created_at ? formatDateTime(t.created_at) : '-'}</Descriptions.Item>
      <Descriptions.Item label="开始时间">{t.started_at ? formatDateTime(t.started_at) : '-'}</Descriptions.Item>
      <Descriptions.Item label="完成时间">{t.completed_at ? formatDateTime(t.completed_at) : '-'}</Descriptions.Item>
      <Descriptions.Item label="状态消息">{t.message || '-'}</Descriptions.Item>
      {t.error_message && (
        <Descriptions.Item label="错误信息">
          <span style={{ color: '#ff4d4f', fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {t.error_message}
          </span>
        </Descriptions.Item>
      )}
    </Descriptions>
  );

  /** 移动端折叠面板头部：左侧标题、右侧状态，一行呈现 */
  const collapseHeader = (title: React.ReactNode, extra: React.ReactNode) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, width: '100%' }}>
      <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
      {extra != null && <span style={{ flexShrink: 0 }}>{extra}</span>}
    </div>
  );

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 200 },
    { 
      title: '类型', 
      dataIndex: 'task_type', 
      key: 'task_type', 
      width: 80,
      render: (type: string) => <Tag color={typeMap[type]?.color}>{typeMap[type]?.text || type}</Tag>,
    },
    { 
      title: '状态', 
      dataIndex: 'status', 
      key: 'status', 
      width: 120,
      render: (status: string) => (
        <Badge 
          status={statusMap[status]?.color as any} 
          text={<><span style={{ marginRight: 4 }}>{statusMap[status]?.icon}</span>{statusMap[status]?.text}</>}
        />
      ),
    },
    { 
      title: '进度', 
      dataIndex: 'progress', 
      key: 'progress', 
      width: 150,
      render: (progress: number, record: TaskProcess) => (
        <Tooltip title={`${record.processed_items}/${record.total_items}`}>
          <Progress percent={progress} size="small" status={record.status === 'failed' ? 'exception' : undefined} />
        </Tooltip>
      ),
    },
    { 
      title: '消息', 
      dataIndex: 'message', 
      key: 'message', 
      ellipsis: true,
      render: (text: string) => text || '-',
    },
    { 
      title: '开始时间', 
      dataIndex: 'started_at', 
      key: 'started_at', 
      width: 150,
      render: (time: string) => formatTimeShort(time),
    },
    { 
      title: '时长', 
      dataIndex: 'duration', 
      key: 'duration', 
      width: 100,
      render: (duration: number, record: TaskProcess) => {
        if (record.status === 'running') {
          const runningSeconds = dayjs().diff(dayjs(record.started_at), 'second');
          return formatDuration(runningSeconds);
        }
        return formatDuration(duration);
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_: any, record: TaskProcess) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(record)}>详情</Button>
          {record.status === 'running' && (
            <Popconfirm title="确定停止该进程吗？" onConfirm={() => handleStop(record.id)}>
              <Button type="link" size="small" danger icon={<PauseCircleOutlined />}>停止</Button>
            </Popconfirm>
          )}
          <Popconfirm title="确定删除吗？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 定时任务计划的列
  const scheduledColumns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 200 },
    {
      title: '类型',
      dataIndex: 'trigger_type',
      key: 'trigger_type',
      width: 80,
      render: (type: string) => <Tag color={type === 'cron' ? 'blue' : 'green'}>{type === 'cron' ? '定时' : '间隔'}</Tag>,
    },
    {
      title: '执行频率',
      dataIndex: 'trigger_desc',
      key: 'trigger_desc',
      width: 150,
    },
    {
      title: '下次执行',
      dataIndex: 'next_run',
      key: 'next_run',
      width: 150,
      render: (time: string) => time ? formatTimeShort(time) : '-',
    },
    {
      title: '倒计时',
      key: 'countdown',
      width: 150,
      render: (_: any, record: ScheduledJob) => {
        const countdown = formatCountdown(record.next_run, record.pending);
        const tagColor = countdown === '即将执行' ? 'orange'
          : countdown === '执行中' ? 'processing'
          : countdown === '等待更新' ? 'blue'
          : 'default';
        return countdown ? (
          <Tag color={tagColor}>{countdown}</Tag>
        ) : '-';
      },
    },
  ];

  // 动态规则计划的列
  const dynamicRuleColumns = [
    { title: '规则名称', dataIndex: 'name', key: 'name', width: 200 },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (type: string) => <Tag color={typeMap[type]?.color || 'default'}>{typeMap[type]?.text || type}</Tag>,
    },
    {
      title: '触发条件',
      dataIndex: 'trigger_desc',
      key: 'trigger_desc',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => <Tag color={status === 'enabled' ? 'success' : 'default'}>{status === 'enabled' ? '启用' : '禁用'}</Tag>,
    },
  ];

  return (
    <div>
      {holidayStatus?.active && (
        <Alert
          type="warning"
          showIcon
          icon={<StopOutlined />}
          style={{ marginBottom: 16 }}
          message={`假期模式生效中${holidayStatus.period ? `（${holidayStatus.period.name}）` : ''}·推送已静音`}
          description="当前处于假期区间内，全体面向用户的推送已自动静音；进程历史中的「已静音」记录即由此产生。系统/安全告警不受影响。"
        />
      )}
      <Tabs defaultActiveKey="history" items={[
        {
          key: 'history',
          label: <span><HistoryOutlined /> 执行历史</span>,
          children: (
            <Card
              title={
          <Space>
            任务进程管理
            {runningCount > 0 && <Badge count={runningCount} style={{ backgroundColor: '#52c41a' }} />}
            <Badge count={scheduledJobs.length} style={{ backgroundColor: '#1890ff' }} overflowCount={99} />
          </Space>
        }
      >
        {/* 定时任务计划 */}
        {scheduledJobs.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, color: '#1890ff', fontSize: 14 }}>
              <ScheduleOutlined style={{ marginRight: 6 }} />定时任务计划
            </div>
            <ResponsiveTable
              dataSource={scheduledJobs}
              columns={scheduledColumns}
              rowKey="id"
              pagination={false}
              size="small"
              scroll={{ x: 750 }}
              mobileCollapseHeader={(r: ScheduledJob) => {
                const countdown = formatCountdown(r.next_run, r.pending);
                const tagColor = countdown === '即将执行' ? 'orange'
                  : countdown === '执行中' ? 'processing'
                  : countdown === '等待更新' ? 'blue'
                  : 'default';
                return collapseHeader(r.name, countdown ? <Tag color={tagColor} style={{ marginInlineEnd: 0 }}>{countdown}</Tag> : null);
              }}
              mobileCollapseContent={(r: ScheduledJob) => (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="类型">{r.trigger_type === 'cron' ? '定时' : '间隔'}</Descriptions.Item>
                  <Descriptions.Item label="执行频率">{r.trigger_desc}</Descriptions.Item>
                  <Descriptions.Item label="下次执行">{r.next_run ? formatTimeShort(r.next_run) : '-'}</Descriptions.Item>
                </Descriptions>
              )}
            />
          </div>
        )}

        {/* 动态规则计划 */}
        {dynamicRules.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, color: '#52c41a', fontSize: 14 }}>
              <NotificationOutlined style={{ marginRight: 6 }} />动态规则计划
              <Tooltip title="根据规则动态触发的推送任务">
                <BookOutlined style={{ marginLeft: 4, color: '#999' }} />
              </Tooltip>
            </div>
            <ResponsiveTable
              dataSource={dynamicRules}
              columns={dynamicRuleColumns}
              rowKey="id"
              pagination={false}
              size="small"
              scroll={{ x: 600 }}
              mobileCollapseHeader={(r: DynamicRule) => collapseHeader(
                r.name,
                <Tag color={r.status === 'enabled' ? 'success' : 'default'} style={{ marginInlineEnd: 0 }}>
                  {r.status === 'enabled' ? '启用' : '禁用'}
                </Tag>,
              )}
              mobileCollapseContent={(r: DynamicRule) => (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="类型">
                    <Tag color={typeMap[r.type]?.color || 'default'}>{typeMap[r.type]?.text || r.type}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="触发条件">{r.trigger_desc}</Descriptions.Item>
                </Descriptions>
              )}
            />
          </div>
        )}

        {/* 执行统计卡片 */}
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="总任务数"
                value={stats.total}
                prefix={<ClockCircleOutlined />}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="已完成"
                value={stats.completed}
                valueStyle={{ color: '#52c41a' }}
                prefix={<CheckCircleFilled />}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="失败"
                value={stats.failed}
                valueStyle={{ color: '#ff4d4f' }}
                prefix={<CloseCircleFilled />}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic
                title="平均耗时"
                value={formatDuration(stats.avgDuration)}
                prefix={<ClockCircleFilled />}
              />
            </Card>
          </Col>
        </Row>

        {/* 执行历史 */}
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: 8 
        }}>
          <div style={{ fontWeight: 600, color: '#666', fontSize: 14 }}>
            <HistoryOutlined style={{ marginRight: 6 }} />执行历史
          </div>
          <Space>
            <Select 
              placeholder="状态" 
              allowClear 
              style={{ width: 100 }}
              size="small"
              value={filterStatus || undefined}
              onChange={(value) => { setFilterStatus(value || ''); fetchProcesses(1, value || '', filterTaskType); }}
            >
                    <Option value="running">运行中</Option>
                    <Option value="completed">已完成</Option>
                    <Option value="completed_empty">完成无数据</Option>
                    <Option value="failed">失败</Option>
                    <Option value="cancelled">已取消</Option>
            </Select>
            <Select 
              placeholder="类型" 
              allowClear 
              style={{ width: 100 }}
              size="small"
              value={filterTaskType || undefined}
              onChange={(value) => { setFilterTaskType(value || ''); fetchProcesses(1, filterStatus, value || ''); }}
            >
              <Option value="spider">课表爬虫</Option>
              <Option value="course_full_crawl">全量爬取</Option>
              <Option value="course">课表</Option>
              <Option value="weather">天气</Option>
              <Option value="electricity">电量</Option>
              <Option value="system">系统</Option>
              <Option value="custom">自定义</Option>
            </Select>
            <Select 
              value={autoRefresh ? 'on' : 'off'}
              onChange={(v) => setAutoRefresh(v === 'on')}
              style={{ width: 80 }}
              size="small"
            >
              <Option value="on">自动</Option>
              <Option value="off">手动</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={loading} size="small">刷新</Button>
          </Space>
        </div>
        <ResponsiveTable
          dataSource={processes}
          columns={columns}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1100 }}
          pagination={{
            current: pagination.page,
            pageSize: pagination.per_page,
            total: pagination.total,
            onChange: (page) => fetchProcesses(page),
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条记录`,
            pageSizeOptions: ['10', '20', '50'],
          }}
          mobileCollapseHeader={(r: TaskProcess) => collapseHeader(
            r.name,
            <Badge status={statusMap[r.status]?.color as any} text={statusMap[r.status]?.text || r.status} />,
          )}
          mobileCollapseContent={(r: TaskProcess) => (
            <div>
              {renderProcessDetail(r)}
              <div style={{ marginTop: 12, display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                {r.status === 'running' && (
                  <Popconfirm title="确定停止该进程吗？" onConfirm={() => handleStop(r.id)}>
                    <Button size="small" danger icon={<PauseCircleOutlined />}>停止</Button>
                  </Popconfirm>
                )}
                <Popconfirm title="确定删除吗？" onConfirm={() => handleDelete(r.id)}>
                  <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              </div>
            </div>
          )}
        />
            </Card>
          ),
        },
        {
          key: 'crawl',
          label: <span><ScheduleOutlined /> 爬取预约</span>,
          children: (
            <Card title="爬取预约任务">
              <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Space>
                  <Select
                    placeholder="状态"
                    allowClear
                    style={{ width: 120 }}
                    size="small"
                    value={crawlFilterStatus || undefined}
                    onChange={(v) => { setCrawlFilterStatus(v || ''); fetchCrawlTasks(1, v || ''); }}
                  >
                    <Option value="pending">待执行</Option>
                    <Option value="running">执行中</Option>
                    <Option value="completed">已完成</Option>
                    <Option value="failed">失败</Option>
                    <Option value="cancelled">已取消</Option>
                  </Select>
                  <Button icon={<ReloadOutlined />} onClick={() => fetchCrawlTasks(crawlPagination.page)} size="small">刷新</Button>
                </Space>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCrawlSchedulerVisible(true)}>新建爬取任务</Button>
              </div>
              <ResponsiveTable
                dataSource={crawlTasks}
                rowKey="id"
                loading={crawlLoading}
                scroll={{ x: 900 }}
                pagination={{
                  current: crawlPagination.page,
                  pageSize: crawlPagination.per_page,
                  total: crawlPagination.total,
                  onChange: (p) => fetchCrawlTasks(p),
                  showTotal: (t) => `共 ${t} 条`,
                }}
                columns={[
                  { title: '名称', dataIndex: 'name', key: 'name', width: 200,
                    render: (t: string, r: CrawlTask) => (
                      <a onClick={() => { setSelectedCrawlTask(r); setCrawlDetailVisible(true); }}>{t}</a>
                    ),
                  },
                  { title: '范围', dataIndex: 'scope', key: 'scope', width: 140,
                    render: (s: string, r: CrawlTask) =>
                      s === 'all'
                        ? <Tag color="purple">全量</Tag>
                        : <Tag color="blue">指定学期 {r.semester_id || ''}</Tag>,
                  },
                  { title: '执行方式', dataIndex: 'schedule_type', key: 'schedule_type', width: 160,
                    render: (t: string, r: CrawlTask) =>
                      t === 'immediate'
                        ? <Tag color="green">立即执行</Tag>
                        : <span>预约 {r.scheduled_at ? formatTimeShort(r.scheduled_at) : '-'}</span>,
                  },
                  { title: '状态', dataIndex: 'status', key: 'status', width: 110,
                    render: (st: string) => {
                      const v = crawlStatusMap[st] || { color: 'default', text: st };
                      return <Badge status={v.color as any} text={v.text} />;
                    },
                  },
                  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160,
                    render: (t: string) => formatDateTime(t),
                  },
                  { title: '操作', key: 'action', width: 230, fixed: 'right' as const,
                    render: (_: any, r: CrawlTask) => (
                      <Space size={4}>
                        <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { setSelectedCrawlTask(r); setCrawlDetailVisible(true); }}>详情</Button>
                        {r.status === 'pending' && (
                          <>
                            <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => handleCrawlRun(r.id)}>执行</Button>
                            <Button type="link" size="small" onClick={() => openEdit(r)}>编辑</Button>
                          </>
                        )}
                        {(r.status === 'pending' || r.status === 'running') && (
                          <Popconfirm title="确定取消该任务吗？" onConfirm={() => handleCrawlCancel(r.id)}>
                            <Button type="link" size="small" danger>取消</Button>
                          </Popconfirm>
                        )}
                        <Popconfirm title="确定删除吗？" onConfirm={() => handleCrawlDelete(r.id)}>
                          <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                        </Popconfirm>
                      </Space>
                    ),
                  },
                ]}
                mobileCollapseHeader={(r: CrawlTask) => {
                  const v = crawlStatusMap[r.status] || { color: 'default', text: r.status };
                  return collapseHeader(r.name, <Badge status={v.color as any} text={v.text} />);
                }}
                mobileCollapseContent={(r: CrawlTask) => (
                  <div>
                    {renderCrawlDetail(r)}
                    <div style={{ marginTop: 12, display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                      {r.status === 'pending' && (
                        <>
                          <Button size="small" icon={<PlayCircleOutlined />} onClick={() => handleCrawlRun(r.id)}>执行</Button>
                          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
                        </>
                      )}
                      {(r.status === 'pending' || r.status === 'running') && (
                        <Popconfirm title="确定取消该任务吗？" onConfirm={() => handleCrawlCancel(r.id)}>
                          <Button size="small" danger>取消</Button>
                        </Popconfirm>
                      )}
                      <Popconfirm title="确定删除吗？" onConfirm={() => handleCrawlDelete(r.id)}>
                        <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                      </Popconfirm>
                    </div>
                  </div>
                )}
              />
            </Card>
          ),
        },
      ]} />

      {/* 详情弹窗 */}
      <Modal
        title="任务执行详情"
        open={detailModalVisible}
        onCancel={handleCloseDetail}
        footer={[
          <Button key="close" onClick={handleCloseDetail}>关闭</Button>,
        ]}
        width={700}
      >
        {/* 详情内容抽为 renderProcessDetail，桌面端弹窗与移动端折叠面板复用 */}
        {selectedProcess && renderProcessDetail(selectedProcess)}
      </Modal>

      {/* 爬取预约：新建 */}
      <CrawlScheduler
        visible={crawlSchedulerVisible}
        onClose={() => setCrawlSchedulerVisible(false)}
        onStarted={(taskId) => {
          if (taskId != null) {
            setProcCrawlId(taskId);
            message.success('爬取任务已创建，后台执行中...');
          } else {
            message.success('爬取任务已创建');
          }
        }}
      />

      {/* 爬取预约：详情 */}
      <Modal
        title="爬取预约任务详情"
        open={crawlDetailVisible}
        onCancel={() => setCrawlDetailVisible(false)}
        footer={[<Button key="close" onClick={() => setCrawlDetailVisible(false)}>关闭</Button>]}
        width={640}
      >
        {/* 详情内容抽为 renderCrawlDetail，桌面端弹窗与移动端折叠面板复用 */}
        {selectedCrawlTask && renderCrawlDetail(selectedCrawlTask)}
      </Modal>

      {/* 爬取预约：编辑（仅 pending） */}
      <Modal
        title="编辑爬取预约任务"
        open={editModalVisible}
        onOk={submitEdit}
        onCancel={() => setEditModalVisible(false)}
        confirmLoading={editLoading}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item label="任务名称" name="name" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item label="爬取范围" name="scope">
            <Radio.Group disabled>
              <Radio value="semester">指定学期</Radio>
              <Radio value="all">全量</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="执行方式" name="schedule_type" rules={[{ required: true, message: '请选择执行方式' }]}>
            <Radio.Group>
              <Radio value="immediate">立即执行</Radio>
              <Radio value="scheduled">预约时间</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.schedule_type !== c.schedule_type}>
            {({ getFieldValue }) =>
              getFieldValue('schedule_type') === 'scheduled' ? (
                <Form.Item label="预约执行时间" name="scheduled_at" rules={[{ required: true, message: '请选择预约时间' }]}>
                  <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} disabledDate={(current) => current && current < dayjs().startOf('day')} />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
