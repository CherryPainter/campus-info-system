/**
 * 任务管理页面
 * 
 * 功能：
 * - 课程爬虫和推送任务管理
 * - 天气任务管理
 * - 电量任务管理
 */
import { useState, useEffect, useRef } from 'react';
import { Card, Row, Col, Button, Tag, Typography, Badge, App } from 'antd';
import { 
  CloudOutlined, ThunderboltOutlined, BookOutlined, SyncOutlined, PlayCircleOutlined, 
  ClockCircleOutlined, WarningOutlined, CheckCircleOutlined, SunOutlined
} from '@ant-design/icons';
import { adminApi, processApi, type SpiderStatus, type TaskProcess } from '@/api/admin';
import { electricityApi } from '@/api/electricity';
import { holidayApi, type HolidayStatus } from '@/api/holiday';
import CrawlScheduler from './CrawlScheduler';
import { useIntervalPolling } from '@/hooks/useIntervalPolling';
import { POLL_SLOW, POLL_FAST } from '@/hooks/pollIntervals';

const { Text, Title } = Typography;

// 任务分类配置
const taskCategories = [
  {
    id: 'course',
    name: '课程任务',
    icon: <BookOutlined />,
    color: '#722ed1',
    bgColor: 'linear-gradient(135deg, #f9f0ff 0%, #f3e8ff 100%)',
    tasks: [
      { key: 'spider', label: '课表爬虫', desc: '获取课程表数据', icon: <SyncOutlined />, priority: 'high', moduleOverride: 'spider' },
      { key: 'full_crawl', label: '全量爬取', desc: '全量爬取课程表（支持选择学期/周次）', icon: <SyncOutlined />, priority: 'high' },
      { key: 'push_daily_schedule', label: '推送今日课表', desc: '发送今日课程安排', icon: <BookOutlined />, priority: 'normal' },
      { key: 'push_weekly_image', label: '推送周课表图片', desc: '发送周课表图片', icon: <BookOutlined />, priority: 'normal' },
    ]
  },
  {
    id: 'weather',
    name: '天气任务',
    icon: <CloudOutlined />,
    color: '#1890ff',
    bgColor: 'linear-gradient(135deg, #e6f7ff 0%, #bae7ff 100%)',
    tasks: [
      { key: 'update_weather_now', label: '更新实时天气', desc: '获取最新天气数据', icon: <CloudOutlined />, priority: 'high' },
      { key: 'update_weather_hourly', label: '更新24h预报', desc: '获取逐时预报数据', icon: <ClockCircleOutlined />, priority: 'normal' },
      { key: 'update_weather_alert', label: '更新预警信息', desc: '检查天气预警', icon: <WarningOutlined />, priority: 'high' },
      { key: 'push_weather_daily', label: '发送每日晨报', desc: '推送天气晨报', icon: <SunOutlined />, priority: 'normal' },
      { key: 'push_weather_analysis', label: '发送天气分析', desc: '分析并推送天气预警', icon: <CloudOutlined />, priority: 'high' },
    ]
  },
  {
    id: 'electricity',
    name: '电量任务',
    icon: <ThunderboltOutlined />,
    color: '#faad14',
    bgColor: 'linear-gradient(135deg, #fffbe6 0%, #fff1b8 100%)',
    tasks: [
      { key: 'push_electricity_daily', label: '发送每日报告', desc: '推送每日用电报告', icon: <ThunderboltOutlined />, priority: 'normal' },
      { key: 'push_electricity_weekly', label: '发送每周报告', desc: '推送每周用电报告', icon: <ThunderboltOutlined />, priority: 'normal' },
      { key: 'push_electricity_monthly', label: '发送每月报告', desc: '推送每月用电报告', icon: <ThunderboltOutlined />, priority: 'low' },
      { key: 'check_cookie_validity', label: '检测Cookie有效性', desc: '检查爬虫Cookie', icon: <CheckCircleOutlined />, priority: 'low' },
      { key: 'fetch_all', label: '电量全量爬取', desc: '全量爬取电量数据（最多50页）', icon: <ThunderboltOutlined />, priority: 'high' },
    ]
  }
];

// 优先级配置
const priorityConfig = {
  high: { color: '#ff4d4f', bg: '#fff2f0', text: '高' },
  normal: { color: '#1890ff', bg: '#e6f7ff', text: '中' },
  low: { color: '#52c41a', bg: '#f6ffed', text: '低' },
};

// 假期静默期间会被后端拦截、需禁用「立即执行」的任务 key 集合。
// 说明：电量采集/校验类（fetch_all、check_cookie_validity）与课程手动推送
// 后端不在假期静默拦截，故不计入，保持可用。
const HOLIDAY_SKIPPED_KEYS = new Set<string>([
  // 爬虫：假期静默 or 非教学周 双条件拦截
  'spider', 'full_crawl',
  // 天气：所有天气任务在假期静默均被拦截
  'update_weather_now', 'update_weather_hourly', 'update_weather_alert', 'push_weather_daily', 'push_weather_analysis',
  // 电量推送：假期静默拦截（采集/校验类不拦截）
  'push_electricity_daily', 'push_electricity_weekly', 'push_electricity_monthly',
]);

export default function Tasks() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [spiderStatus, setSpiderStatus] = useState<SpiderStatus | null>(null);
  // 运行中视觉态（真实感知，不再用伪超时）：
  // - 天气/电量/课表推送/课程全量爬取 类任务，后端都会落 TaskProcess，前端按「进程名」
  //   轮询 task_processes 拿到真实 running/completed/failed 终态（与「进程管理」页面同一套机制）。
  //   full_crawl 的进程名为「课程全量爬取」（course_full_crawl 类型，由 _run_scheduled_crawl
  //   在爬取开始时创建伞进程，整次爬取期间持续 running，终态再翻 completed/failed）。
  // - spider 类（手动触发课程表爬虫）及外部/预约启动的全量爬取，仍以 spider_status 轮询
  //   （isBackendRunning）作为兜底运行信号。
  // - clickFlash：点击瞬间点亮，待真实进程出现或 8s 安全超时后接管/清除。
  const [clickFlash, setClickFlash] = useState<Set<string>>(new Set());
  const [triggerTimeByKey, setTriggerTimeByKey] = useState<Record<string, number>>({});
  const [processStatus, setProcessStatus] = useState<Record<string, TaskProcess | null>>({});
  // 假期模式状态：active 时对应触发按钮会被后端静默拦截，前端同步禁用并提示
  const [holidayStatus, setHolidayStatus] = useState<HolidayStatus | null>(null);
  const [reportedKeys, setReportedKeys] = useState<Set<string>>(new Set());
  const flashTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // 任务 key → 后端 TaskProcess 进程名（与 tasks.py / scheduler.py 中 create_task_process 的 name 严格对应）
  const PROCESS_NAME_BY_TASK: Record<string, string> = {
    update_weather_now: '更新实时天气',
    update_weather_hourly: '更新逐小时预报',
    update_weather_alert: '更新天气预警',
    push_weather_daily: '每日天气晨报',
    push_weather_analysis: '天气分析推送',
    push_electricity_daily: '每日用电报告',
    push_electricity_weekly: '每周用电报告',
    push_electricity_monthly: '每月用电报告',
    check_cookie_validity: 'Cookie有效性检测',
    fetch_all: '电量全量爬取',
    push_daily_schedule: '今日课表推送',
    push_weekly_image: '周课表图片推送',
    full_crawl: '课程全量爬取',
  };

  const removeClickFlash = (key: string) => {
    if (flashTimers.current[key]) {
      clearTimeout(flashTimers.current[key]);
      delete flashTimers.current[key];
    }
    setClickFlash((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };
  const addClickFlash = (key: string) => {
    setClickFlash((prev) => new Set(prev).add(key));
    setTriggerTimeByKey((prev) => ({ ...prev, [key]: Date.now() }));
    // 新一轮触发：重置上报标记，允许本次终态再次提示
    setReportedKeys((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
    if (flashTimers.current[key]) clearTimeout(flashTimers.current[key]);
    flashTimers.current[key] = setTimeout(() => removeClickFlash(key), 8000);
  };
  const [crawlSchedulerVisible, setCrawlSchedulerVisible] = useState(false);

  // 后端真实运行信号（spider_status 轮询）：仅覆盖课表爬虫与全量爬取类任务
  const isBackendRunning = (key: string): boolean => {
    if (key === 'spider') return !!spiderStatus?.running;
    if (key === 'full_crawl') return !!spiderStatus?.running_tasks?.course_full_crawl;
    if (key === 'fetch_all') return !!spiderStatus?.running_tasks?.electricity_full_crawl;
    return false;
  };

  // 轮询真实进程状态（task_processes）：覆盖天气/电量/课表推送类任务的成功失败感知
  useIntervalPolling(async () => {
    // 仅跟踪「刚点击」或「仍在运行」的任务，空闲不发起请求
    const tracked = new Set<string>([
      ...clickFlash,
      ...Object.entries(processStatus)
        .filter(([, v]) => v && (v.status === 'running' || (v.status as string) === 'pending'))
        .map(([k]) => k),
    ]);
    if (tracked.size === 0) return;
    try {
      const { data: list } = await processApi.getList({ per_page: 30 });
      // 同名进程取最近一条（started_at 最大）
      const byName: Record<string, TaskProcess> = {};
      for (const p of list) {
        const cur = byName[p.name];
        if (!cur || (p.started_at && cur.started_at && p.started_at > cur.started_at)) {
          byName[p.name] = p;
        }
      }
      for (const key of tracked) {
        const name = PROCESS_NAME_BY_TASK[key];
        if (!name) continue;
        const t = triggerTimeByKey[key];
        const proc = byName[name];
        if (!proc) continue;
        const started = proc.started_at ? new Date(proc.started_at).getTime() : 0;
        if (t != null && started < t) continue; // 忽略本次点击之前的旧进程
        setProcessStatus((prev) => ({ ...prev, [key]: proc }));
        const st = proc.status as string;
        if (st === 'running' || st === 'pending') {
          if (clickFlash.has(key)) removeClickFlash(key); // 真实进程已接管
        } else {
          // 终态：反馈一次成功/失败
          if (!reportedKeys.has(key)) {
            if (st === 'failed' || st === 'cancelled') {
              message.error(proc.error_message || proc.message || `${name} 执行失败`);
            } else {
              message.success(proc.message || `${name} 执行完成`);
            }
            setReportedKeys((prev) => new Set(prev).add(key));
          }
          if (clickFlash.has(key)) removeClickFlash(key);
        }
      }
    } catch {
      /* 忽略单次查询失败 */
    }
  }, POLL_FAST);

  // 组件卸载时清理所有 clickFlash 定时器，避免内存泄漏/告警
  useEffect(() => () => {
    Object.values(flashTimers.current).forEach(clearTimeout);
  }, []);

  const fetchSpiderStatus = async () => {
    setLoading(true);
    try {
      const res = await adminApi.getSpiderStatus();
      if (res.status === 'success' && res.spider) setSpiderStatus(res.spider);
    } catch (error) { console.error('获取爬虫状态失败:', error); }
    finally { setLoading(false); }
  };

  // 爬虫状态每 30s 刷新一次（统一轮询 Hook）
  useIntervalPolling(fetchSpiderStatus, POLL_SLOW);

  // 挂载时拉取假期模式状态，用于同步禁用触发按钮
  useEffect(() => {
    holidayApi.getStatus()
      .then((res) => { if (res.status === 'success' && res.data) setHolidayStatus(res.data); })
      .catch(() => {});
  }, []);

  const handleTrigger = async (taskType: string, module: 'weather' | 'electricity' | 'spider' | 'course') => {
    addClickFlash(taskType); // 点击立即点亮「运行中」样式，待真实进程接管
    try {
      let response;
      if (module === 'spider') response = await adminApi.triggerSpider();
      else if (module === 'weather') response = await adminApi.triggerWeather(taskType);
      else if (module === 'electricity') {
        // 电量全量爬取走独立端点（不在 /admin/electricity/trigger 体系内）
        if (taskType === 'fetch_all') response = await electricityApi.triggerFetchAll();
        else response = await adminApi.triggerElectricity(taskType);
      }
      else if (module === 'course') response = await adminApi.triggerCourse(taskType);

      // 假期静默 / 非教学周拦截：后端返回 skipped，提示已跳过且不点亮运行态
      if ((response as any)?.skipped) {
        message.warning((response as any).message || '假期静默中，已跳过');
        removeClickFlash(taskType);
        return;
      }

      if (response?.status === 'success') {
        message.success(response.message || '任务触发成功');
      } else if (response?.status === 'error') {
        message.error(response.message || '任务触发失败');
      }

      fetchSpiderStatus();
    } catch (error: any) {
      console.error('触发任务失败:', error);
      message.error(error?.response?.data?.message || error?.message || '网络错误，无法触发任务');
      removeClickFlash(taskType); // 触发失败，立即取消运行中样式
    }
  };

  // 渲染任务卡片（统一样式）
  const renderTaskCard = (task: typeof taskCategories[0]['tasks'][0], module: string) => {
    const priority = priorityConfig[task.priority as keyof typeof priorityConfig];
    const isRunning = isBackendRunning(task.key);
    const proc = processStatus[task.key];
    const procRunning = !!proc && (proc.status === 'running' || (proc.status as string) === 'pending');
    const visualRunning = isRunning || procRunning || clickFlash.has(task.key);
    // 优先使用任务自身的 moduleOverride（如课程分类下的爬虫任务需走 spider 分支）
    const effectiveModule = ('moduleOverride' in task && task.moduleOverride) ? task.moduleOverride : module;

    // 全量爬取任务：打开 CrawlScheduler 对话框；运行中态走统一 TaskProcess 通道
    if (task.key === 'full_crawl') {
      const proc = processStatus['full_crawl'];
      const procRunning = !!proc && (proc.status === 'running' || (proc.status as string) === 'pending');
      const visualRunning = isBackendRunning('full_crawl') || procRunning || clickFlash.has('full_crawl');
      return (
        <Card
          hoverable
          style={{
            borderRadius: 12,
            border: visualRunning ? '1px solid #ffccc7' : '1px solid #e8e8e8',
            boxShadow: visualRunning ? '0 2px 12px rgba(255, 77, 79, 0.15)' : '0 2px 8px rgba(0,0,0,0.04)',
            transition: 'all 0.3s ease',
            background: visualRunning ? '#fff5f5' : undefined,
          }}
          styles={{ body: { padding: 16 } }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <div style={{
              width: 44,
              height: 44,
              borderRadius: 10,
              backgroundColor: `${priority.color}12`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}>
              <span style={{ fontSize: 20, color: priority.color }}>{task.icon}</span>
            </div>
            <div style={{ flex: 1 }}>
              <Title level={5} style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{task.label}</Title>
              <Text type="secondary" style={{ fontSize: 12 }}>{task.desc}</Text>
            </div>
            {visualRunning && (
              <Badge status="processing" text="运行中" style={{ fontSize: 11 }} />
            )}
          </div>

          <Button
            type="primary"
            ghost
            icon={<PlayCircleOutlined />}
            onClick={() => setCrawlSchedulerVisible(true)}
            block
            size="small"
            loading={visualRunning}
            disabled={visualRunning || (!!holidayStatus?.active && HOLIDAY_SKIPPED_KEYS.has(task.key))}
          >
            {visualRunning ? '运行中...' : '立即执行'}
          </Button>
        </Card>
      );
    }

    return (
      <Card
        hoverable
        style={{
          borderRadius: 12,
          border: visualRunning ? '1px solid #ffccc7' : '1px solid #e8e8e8',
          boxShadow: visualRunning ? '0 2px 12px rgba(255, 77, 79, 0.15)' : '0 2px 8px rgba(0,0,0,0.04)',
          transition: 'all 0.3s ease',
          background: visualRunning ? '#fff5f5' : undefined,
        }}
        styles={{ body: { padding: 16 } }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          <div style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            backgroundColor: `${priority.color}12`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <span style={{ fontSize: 20, color: priority.color }}>{task.icon}</span>
          </div>
          <div style={{ flex: 1 }}>
            <Title level={5} style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{task.label}</Title>
            <Text type="secondary" style={{ fontSize: 12 }}>{task.desc}</Text>
          </div>
          {visualRunning && (
            <Badge status="processing" text="运行中" style={{ fontSize: 11 }} />
          )}
        </div>

        <Button
          type="primary"
          ghost
          icon={<PlayCircleOutlined />}
          loading={visualRunning}
          onClick={() => handleTrigger(task.key, effectiveModule as any)}
          block
          size="small"
          disabled={visualRunning || (!!holidayStatus?.active && HOLIDAY_SKIPPED_KEYS.has(task.key))}
          className="task-action-btn"
        >
          {visualRunning ? '运行中...' : '立即执行'}
        </Button>
      </Card>
    );
  };

  // 渲染模块头部
  const renderModuleHeader = (category: typeof taskCategories[0]) => (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      marginBottom: 20,
    }}>
      <div style={{
        width: 40,
        height: 40,
        borderRadius: 10,
        background: category.bgColor,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <span style={{ fontSize: 20, color: category.color }}>{category.icon}</span>
      </div>
      <div>
        <Title level={4} style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
          {category.name}
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {category.tasks.length} 个任务
        </Text>
      </div>
    </div>
  );

  return (
    // 页面标题由 PageContainer（ProLayout 根据菜单名自动生成）统一提供，
    // 此处不再重复渲染"任务管理"标题，避免标题重复。
    <div className="tasks-page">
      {taskCategories.map((category) => (
        <Card
          key={category.id}
          style={{
            marginBottom: 24,
            borderRadius: 16,
            border: 'none',
            boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
          }}
          styles={{ body: { padding: 24 } }}
        >
          {renderModuleHeader(category)}
          
          <Row gutter={[16, 16]}>
            {category.tasks.map((task) => (
              <Col xs={24} sm={12} md={6} key={task.key}>
                {renderTaskCard(task, category.id)}
              </Col>
            ))}
          </Row>
        </Card>
      ))}

      {/* 课程爬取调度对话框 */}
      <CrawlScheduler
        visible={crawlSchedulerVisible}
        onClose={() => setCrawlSchedulerVisible(false)}
        onStarted={() => { addClickFlash('full_crawl'); }}
      />
    </div>
  );
}
