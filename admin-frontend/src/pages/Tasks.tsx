/**
 * 任务管理页面
 * 
 * 功能：
 * - 课程爬虫和推送任务管理
 * - 天气任务管理
 * - 电量任务管理
 */
import { useState } from 'react';
import { Card, Row, Col, Button, Tag, Typography, Badge, App } from 'antd';
import { 
  CloudOutlined, ThunderboltOutlined, BookOutlined, SyncOutlined, PlayCircleOutlined, 
  ClockCircleOutlined, WarningOutlined, CheckCircleOutlined, SunOutlined
} from '@ant-design/icons';
import { adminApi, type SpiderStatus } from '@/api/admin';
import { electricityApi } from '@/api/electricity';
import { courseApi, type CrawlTask } from '@/api/course';
import CrawlScheduler from './CrawlScheduler';
import { useIntervalPolling } from '@/hooks/useIntervalPolling';
import { useTaskPolling } from '@/hooks/useTaskPolling';
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

export default function Tasks() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [spiderStatus, setSpiderStatus] = useState<SpiderStatus | null>(null);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [crawlSchedulerVisible, setCrawlSchedulerVisible] = useState(false);
  // 爬取任务按 id 轮询（统一任务模型 Hook），完成即刷新爬虫状态卡
  const [tasksCrawlId, setTasksCrawlId] = useState<number | null>(null);
  useTaskPolling<CrawlTask>(tasksCrawlId, {
    fetcher: (id) => courseApi.crawlTasks.get(id),
    resolve: (d) => ({ status: d.status, message: d.message ?? d.error_message ?? undefined }),
    onDone: () => {
      fetchSpiderStatus();
      message.success('课程爬取任务已完成');
    },
    onFailed: (d) => message.error(d.error_message || '课程爬取任务失败'),
  });

  // 全量爬取运行态：除 admin 接口的 running_tasks.course_full_crawl（30s）外，
  // 额外以 2s 频率直接查爬取任务列表（running/pending），确保卡片在爬取开始时即时点亮，
  // 不再依赖较慢的 admin 轮询窗口（单学期全量爬取约 50s，30s 轮询易错过）。
  const [crawlTaskActive, setCrawlTaskActive] = useState(false);
  useIntervalPolling(async () => {
    try {
      const res = await courseApi.crawlTasks.list({ per_page: 20 });
      const active = (res.data || []).some(
        (t: CrawlTask) => t.status === 'running' || t.status === 'pending',
      );
      setCrawlTaskActive(active);
    } catch {
      /* 忽略单次查询失败 */
    }
  }, POLL_FAST);

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

  const handleTrigger = async (taskType: string, module: 'weather' | 'electricity' | 'spider' | 'course') => {
    setTriggering(taskType);
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
      
      if (response?.status === 'success') {
        message.success(response.message || '任务触发成功');
      } else if (response?.status === 'error') {
        message.error(response.message || '任务触发失败');
      }
      
      fetchSpiderStatus();
    } catch (error: any) {
      console.error('触发任务失败:', error);
      message.error(error?.response?.data?.message || error?.message || '网络错误，无法触发任务');
    } finally {
      setTriggering(null);
    }
  };

  // 渲染任务卡片（统一样式）
  const renderTaskCard = (task: typeof taskCategories[0]['tasks'][0], module: string) => {
    const priority = priorityConfig[task.priority as keyof typeof priorityConfig];
    const isRunning = (task.key === 'spider' && spiderStatus?.running)
      || (task.key === 'full_crawl' && (spiderStatus?.running_tasks?.course_full_crawl || crawlTaskActive))
      || (task.key === 'fetch_all' && spiderStatus?.running_tasks?.electricity_full_crawl);
    // 优先使用任务自身的 moduleOverride（如课程分类下的爬虫任务需走 spider 分支）
    const effectiveModule = ('moduleOverride' in task && task.moduleOverride) ? task.moduleOverride : module;

    // 全量爬取任务：打开 CrawlScheduler 对话框
    if (task.key === 'full_crawl') {
      return (
        <Card
          hoverable
          style={{
            borderRadius: 12,
            border: '1px solid #e8e8e8',
            boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
            transition: 'all 0.3s ease',
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
          </div>

          <Button
            type="primary"
            ghost
            icon={<PlayCircleOutlined />}
            onClick={() => setCrawlSchedulerVisible(true)}
            block
            size="small"
          >
            立即执行
          </Button>
        </Card>
      );
    }

    return (
      <Card
        hoverable
        style={{
          borderRadius: 12,
          border: isRunning ? '1px solid #ffccc7' : '1px solid #e8e8e8',
          boxShadow: isRunning ? '0 2px 12px rgba(255, 77, 79, 0.15)' : '0 2px 8px rgba(0,0,0,0.04)',
          transition: 'all 0.3s ease',
          background: isRunning ? '#fff5f5' : undefined,
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
          {isRunning && (
            <Badge status="error" text="运行中" style={{ fontSize: 11 }} />
          )}
        </div>

        <Button
          type="primary"
          ghost
          icon={<PlayCircleOutlined />}
          loading={triggering === task.key}
          onClick={() => handleTrigger(task.key, effectiveModule as any)}
          block
          size="small"
          disabled={isRunning}
          className="task-action-btn"
        >
          {isRunning ? '运行中...' : '立即执行'}
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
        onStarted={(taskId) => { if (taskId != null) setTasksCrawlId(taskId); }}
      />
    </div>
  );
}
