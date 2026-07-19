/**
 * 网站介绍页面
 * 校园信息聚合与智能推送系统
 * 面向用户的系统介绍，仅描述功能与形态，不暴露内部技术实现细节
 */
import { APP_VERSION } from '@/version';
import {
  Typography,
  Divider,
  Card,
  Row,
  Col,
  Tag,
  List,
  Descriptions,
} from 'antd';
import {
  CloudOutlined,
  ThunderboltOutlined,
  BookOutlined,
  SendOutlined,
  ScheduleOutlined,
  DashboardOutlined,
  SafetyOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

const features = [
  {
    icon: <CloudOutlined style={{ fontSize: 36, color: '#1890ff' }} />,
    title: '天气信息推送',
    desc: '接入和风天气 API，自动获取实时天气、逐小时预报与气象预警，每日晨报经企业微信推送给管理员，暴雨、高温等异常天气主动提醒。',
    tag: '每日自动推送',
  },
  {
    icon: <ThunderboltOutlined style={{ fontSize: 36, color: '#faad14' }} />,
    title: '宿舍电量监控',
    desc: '定时从校园电表系统爬取各宿舍用电记录与剩余电量，低电量自动告警，并生成每日 / 每周 / 每月用电报告（含统计图表）。',
    tag: '低电量预警',
  },
  {
    icon: <BookOutlined style={{ fontSize: 36, color: '#722ed1' }} />,
    title: '课程管理提醒',
    desc: '通过 Playwright 无头浏览器自动爬取教务系统课表，按学期、按周展示；上课前自动推送提醒，「正在上课」状态仅当前教学周亮起，支持手动创建与编辑课程。',
    tag: '上课前提醒',
  },
  {
    icon: <SendOutlined style={{ fontSize: 36, color: '#52c41a' }} />,
    title: '智能消息推送',
    desc: '统一经企业微信 Webhook 推送，支持 Markdown 文本与图片消息；提供自定义推送（文本 / 图片 / 模板）与多 Webhook 管理，满足不同场景触达。',
    tag: '多渠道触达',
  },
  {
    icon: <ScheduleOutlined style={{ fontSize: 36, color: '#eb2f96' }} />,
    title: '定时任务调度',
    desc: '基于 APScheduler 的定时调度，可配置 Cron 表达式，自动执行课表爬取、天气检查、电量巡检等周期任务，确保信息按时送达。',
    tag: '灵活定时策略',
  },
  {
    icon: <DashboardOutlined style={{ fontSize: 36, color: '#13c2c2' }} />,
    title: '可视化仪表盘',
    desc: '管理后台集中展示系统运行状态、模块健康度、推送与任务统计，配合 ECharts 图表，帮助管理员全面掌握系统动态。',
    tag: '数据一目了然',
  },
];

const structureItems = [
  {
    key: 'frontend',
    icon: <AppstoreOutlined style={{ fontSize: 20, color: '#722ed1' }} />,
    title: '前端管理后台',
    desc: '基于现代前端技术构建的响应式管理后台，采用组件化界面与数据可视化，需登录授权后使用，集中管理课程、天气、电量与推送等模块。',
  },
];

const moduleGroups = [
  {
    title: '概览',
    items: '仪表盘（系统状态、任务与推送统计）',
  },
  {
    title: '数据模块',
    items: '课程管理、天气监控、电量管理',
  },
  {
    title: '推送与采集',
    items: '自定义推送、Webhook 管理、爬虫调度',
  },
  {
    title: '运维与安全',
    items: '用户管理、访问控制、任务进程、系统设置',
  },
];

export default function About() {
  return (
    <div style={{ maxWidth: 1000, margin: '40px auto', padding: '0 24px' }}>
      {/* 标题区域 */}
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)', marginBottom: 24 }}>
        <Title level={2} style={{ textAlign: 'center', marginBottom: 4 }}>校园信息聚合与智能推送系统</Title>
        <Paragraph type="secondary" style={{ textAlign: 'center', fontSize: 16, marginBottom: 4 }}>
          Campus Information Aggregation &amp; Smart Push System
        </Paragraph>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <Tag color="blue" style={{ fontSize: 14, padding: '2px 12px' }}>v{APP_VERSION}</Tag>
          <Tag color="green" style={{ fontSize: 14, padding: '2px 12px' }}>稳定运行中</Tag>
        </div>
        <Divider />
        <Paragraph style={{ fontSize: 15, lineHeight: 2, textIndent: '2em' }}>
          校园信息聚合与智能推送系统是一套面向高校内部的信息服务管理工具，
          通过自动化采集、智能分析与统一推送，将天气、电量、课程等校园信息高效送达管理员，
          帮助校园用户随时掌握关键动态。系统以后端 API 服务 + 前端管理后台的形态运行，
          所有功能均在登录授权后使用。
        </Paragraph>
        <Paragraph style={{ fontSize: 15, lineHeight: 2, textIndent: '2em' }}>
          系统围绕「课表推送、天气监控、电量管理」三大核心模块构建，并持续完善推送链路可靠性
          （推送任务持久化、失败重试），
          致力于成为校园日常信息传递的可靠桥梁。
        </Paragraph>
      </Card>

      {/* 核心功能 */}
      <Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>核心功能</Title>
      <Row gutter={[16, 16]}>
        {features.map((item) => (
          <Col xs={24} sm={12} lg={8} key={item.title}>
            <Card
              hoverable
              style={{ borderRadius: 12, height: '100%' }}
              styles={{ body: { padding: 24 } }}
            >
              <div style={{ textAlign: 'center', marginBottom: 16 }}>{item.icon}</div>
              <Title level={5} style={{ textAlign: 'center', marginBottom: 8 }}>{item.title}</Title>
              <Paragraph type="secondary" style={{ fontSize: 13, lineHeight: 1.8, textAlign: 'center' }}>
                {item.desc}
              </Paragraph>
              <div style={{ textAlign: 'center', marginTop: 8 }}>
                <Tag color="blue">{item.tag}</Tag>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 系统结构 */}
      <Title level={3} style={{ textAlign: 'center', margin: '32px 0 24px' }}>系统结构</Title>
      <Row gutter={[16, 16]}>
        {structureItems.map((item) => (
          <Col xs={24} sm={12} key={item.key}>
            <Card style={{ borderRadius: 12, height: '100%' }} styles={{ body: { padding: 20 } }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                {item.icon}
                <Title level={5} style={{ margin: 0 }}>{item.title}</Title>
              </div>
              <Paragraph type="secondary" style={{ fontSize: 13, lineHeight: 1.8, margin: 0 }}>
                {item.desc}
              </Paragraph>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 功能模块 */}
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)', marginTop: 24 }}>
        <Title level={4} style={{ textAlign: 'center', marginBottom: 16 }}>管理后台功能模块</Title>
        <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small">
          {moduleGroups.map((g) => (
            <Descriptions.Item label={g.title} key={g.title}>
              {g.items}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </Card>

      {/* 建站初衷 */}
      <Card bordered={false} style={{ borderRadius: 12, boxShadow: '0 2px 12px rgba(0,0,0,0.06)', marginTop: 24 }}>
        <Title level={4} style={{ textAlign: 'center', marginBottom: 24 }}>建站初衷</Title>
        <Row gutter={[24, 24]}>
          <Col xs={24} sm={12}>
            <div style={{ display: 'flex', gap: 12 }}>
              <BookOutlined style={{ fontSize: 26, color: '#1890ff', flexShrink: 0, marginTop: 2 }} />
              <div>
                <Title level={5} style={{ margin: 0, fontSize: 15 }}>从课程推送开始</Title>
                <Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.7 }}>
                  系统最初的核心目标，是在每天上课前自动把当日课表推送到企业微信，省去反复打开教务系统查询的麻烦。
                </Paragraph>
              </div>
            </div>
          </Col>
          <Col xs={24} sm={12}>
            <div style={{ display: 'flex', gap: 12 }}>
              <ThunderboltOutlined style={{ fontSize: 26, color: '#faad14', flexShrink: 0, marginTop: 2 }} />
              <div>
                <Title level={5} style={{ margin: 0, fontSize: 15 }}>填补信息盲区</Title>
                <Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.7 }}>
                  宿舍突然断电才发现电量不足、暴雨天出门才知有预警——这些校园里的"信息盲区"，正是系统想要填补的地方。
                </Paragraph>
              </div>
            </div>
          </Col>
          <Col xs={24} sm={12}>
            <div style={{ display: 'flex', gap: 12 }}>
              <AppstoreOutlined style={{ fontSize: 26, color: '#722ed1', flexShrink: 0, marginTop: 2 }} />
              <div>
                <Title level={5} style={{ margin: 0, fontSize: 15 }}>从一到多</Title>
                <Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.7 }}>
                  课程提醒上线后，陆续加入电量监控、天气推送等模块。每个模块都因"确实有用"才被加入，而非为堆功能。
                </Paragraph>
              </div>
            </div>
          </Col>
          <Col xs={24} sm={12}>
            <div style={{ display: 'flex', gap: 12 }}>
              <SafetyOutlined style={{ fontSize: 26, color: '#52c41a', flexShrink: 0, marginTop: 2 }} />
              <div>
                <Title level={5} style={{ margin: 0, fontSize: 15 }}>可靠且安全</Title>
                <Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.7 }}>
                  在扩展功能的同时，持续加固账户与系统安全，让每一条信息都恰到好处、每一份数据都更安心。
                </Paragraph>
              </div>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 版本信息 */}
      <div style={{ textAlign: 'center', marginTop: 32, color: '#999', fontSize: 13 }}>
        <Text type="secondary">校园信息聚合与智能推送系统 v{APP_VERSION}</Text>
        <br />
        <Text type="secondary">由 CherryPainter 维护 &nbsp;|&nbsp; © 2026</Text>
      </div>
    </div>
  );
}
