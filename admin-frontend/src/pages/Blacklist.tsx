/**
 * IP 黑名单管理页面
 * 提供黑名单列表的增删改查、启停、清理过期，以及安全事件查看
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Tabs,
  Tag,
  Button,
  Space,
  Switch,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Popconfirm,
  Tooltip,
  Typography,
  Empty,
  Grid,
  Divider,
  Spin,
  Pagination,
  Drawer,
} from 'antd';
import ResponsiveTable from '@/components/ResponsiveTable';
import {
  PlusOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SafetyOutlined,
  UnlockOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import { formatDateTime } from '@/utils/datetime';
import ipBlacklistApi, {
  type IPBlacklistRecord,
  type IPSecurityEvent,
  SOURCE_CN,
  EVENT_TYPE_CN,
} from '@/api/ipBlacklist';
import { IP_SOURCE_STYLE } from '@/constants/statusMaps';
import { useMessage, showApiError } from '@/utils/message';

const { Text } = Typography;

/** 格式化时间 */
const fmtTime = (s: string | null) => (s ? formatDateTime(s) : '—');

/** 严重程度颜色 */
const sevColor = (s: string) =>
  s === 'critical' ? 'red' : s === 'warning' ? 'orange' : 'blue';

/** 来源颜色（优先用 IP_SOURCE_STYLE 映射） */
const sourceColor = (s: string) => (IP_SOURCE_STYLE[s]?.color || 'default');

/** 来源图标名 */
const sourceIcon = (s: string) => IP_SOURCE_STYLE[s]?.icon;

/** IP 格式校验 */
const validateIp = (_: unknown, value: string) => {
  const v = (value || '').trim();
  if (!v) return Promise.reject(new Error('请输入 IP 地址'));
  if (v.includes(':')) return Promise.resolve(); // IPv6 交由后端精校
  if (!/^(\d{1,3}\.){3}\d{1,3}$/.test(v)) {
    return Promise.reject(new Error('IPv4 格式不正确'));
  }
  if (v.split('.').some((n) => Number(n) > 255)) {
    return Promise.reject(new Error('IPv4 每段不能超过 255'));
  }
  return Promise.resolve();
};

const EVENT_TYPE_OPTIONS = Object.entries(EVENT_TYPE_CN).map(([value, label]) => ({
  value,
  label,
}));

const SEVERITY_OPTIONS = [
  { value: 'info', label: '提示' },
  { value: 'warning', label: '警告' },
  { value: 'critical', label: '严重' },
];

export default function Blacklist() {
  // 黑名单列表状态
  const [records, setRecords] = useState<IPBlacklistRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [onlyActive, setOnlyActive] = useState(true);
  const [loading, setLoading] = useState(false);

  // 添加模态框
  const [addVisible, setAddVisible] = useState(false);
  const [addLoading, setAddLoading] = useState(false);
  const [form] = Form.useForm();

  // 编辑抽屉（修改已有黑名单记录的期限/备注/原因）
  const [editVisible, setEditVisible] = useState(false);
  const [editRecord, setEditRecord] = useState<IPBlacklistRecord | null>(null);
  const [editLoading, setEditLoading] = useState(false);
  const [editForm] = Form.useForm();

  // 安全事件状态
  const [events, setEvents] = useState<IPSecurityEvent[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventPage, setEventPage] = useState(1);
  const [eventType, setEventType] = useState<string | undefined>(undefined);
  const [severity, setSeverity] = useState<string | undefined>(undefined);
  const [onlyPending, setOnlyPending] = useState(true); // 仅显示未处理事件
  const [eventLoading, setEventLoading] = useState(false);
  const [actingEventId, setActingEventId] = useState<number | null>(null); // 正在处置（忽略/封禁）的事件
  const [activeTab, setActiveTab] = useState<string>('list'); // 当前激活的 Tab
  const [togglingIp, setTogglingIp] = useState<string | null>(null); // 正在切换启停的 IP
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const message = useMessage();

  /** 加载黑名单列表 */
  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await ipBlacklistApi.getList({
        page,
        per_page: perPage,
        only_active: onlyActive,
      });
      setRecords(res.data);
      setTotal(res.pagination.total);
    } catch (e: any) {
      message.error(showApiError(e, '加载黑名单失败'));
    } finally {
      setLoading(false);
    }
  }, [page, perPage, onlyActive]);

  /** 加载安全事件 */
  const loadEvents = useCallback(async () => {
    setEventLoading(true);
    try {
      const res = await ipBlacklistApi.getEvents({
        page: eventPage,
        per_page: perPage,
        event_type: eventType,
        severity,
        only_pending: onlyPending,
      });
      setEvents(res.data);
      setEventTotal(res.pagination.total);
    } catch (e: any) {
      message.error(showApiError(e, '加载安全事件失败'));
    } finally {
      setEventLoading(false);
    }
  }, [eventPage, perPage, eventType, severity]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  /** 提交添加 */
  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      setAddLoading(true);
      const res = await ipBlacklistApi.add({
        ip_address: values.ip_address.trim(),
        reason: values.reason,
        duration_hours: values.duration_hours ?? null,
        note: values.note,
      });
      if (res.status === 'success') {
        message.success(`IP ${values.ip_address} 已加入黑名单`);
        setAddVisible(false);
        form.resetFields();
        setPage(1);
        loadList();
      } else {
        message.error(res.message || '添加失败');
      }
    } catch (e: any) {
      if (e?.response?.status === 400) {
        message.error(showApiError(e, 'IP 格式不正确'));
      } else {
        message.error(showApiError(e, '添加失败'));
      }
    } finally {
      setAddLoading(false);
    }
  };

  /** 启停切换 */
  const handleToggle = async (record: IPBlacklistRecord, active: boolean) => {
    // 防止重复点击
    if (togglingIp === record.ip_address) return;
    setTogglingIp(record.ip_address);
    try {
      const res = await ipBlacklistApi.toggle(record.ip_address, active);
      if (res.status === 'success') {
        message.success(`IP ${record.ip_address} 已${active ? '启用' : '禁用'}`);
        // 乐观更新当前行
        setRecords((prev) =>
          prev.map((r) => (r.ip_address === record.ip_address ? { ...r, is_active: active } : r)),
        );
      } else {
        message.error(res.message || '操作失败');
      }
    } catch (e: any) {
      message.error(showApiError(e, '操作失败'));
    } finally {
      setTogglingIp(null);
    }
  };

  /** 删除（彻底移除） */
  const handleRemove = async (record: IPBlacklistRecord) => {
    try {
      const res = await ipBlacklistApi.remove(record.ip_address);
      if (res.status === 'success') {
        message.success(`IP ${record.ip_address} 已从黑名单移除`);
        loadList();
      } else {
        message.error(res.message || '移除失败');
      }
    } catch (e: any) {
      message.error(showApiError(e, '移除失败'));
    }
  };

  /** 一键解封（显式 unblock，区别于 toggle 禁用） */
  const handleUnblock = async (record: IPBlacklistRecord) => {
    try {
      const res = await ipBlacklistApi.remove(record.ip_address);
      if (res.status === 'success') {
        message.success(`IP ${record.ip_address} 已解封，恢复访问权限`);
        loadList();
      } else {
        message.error(res.message || '解封失败');
      }
    } catch (e: any) {
      message.error(showApiError(e, '解封失败'));
    }
  };

  /** 打开编辑抽屉 */
  const handleEdit = (record: IPBlacklistRecord) => {
    setEditRecord(record);
    editForm.setFieldsValue({
      reason: record.reason || '',
      duration_hours: record.expires_at
        ? Math.max(1, Math.round((new Date(record.expires_at).getTime() - Date.now()) / 3600000))
        : 0,
      note: record.note || '',
      is_active: record.is_active,
    });
    setEditVisible(true);
  };

  /** 提交编辑 */
  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields();
      if (!editRecord) return;
      setEditLoading(true);
      const res = await ipBlacklistApi.update(editRecord.ip_address, {
        reason: values.reason,
        duration_hours: values.duration_hours === 0 ? null : values.duration_hours,
        note: values.note,
        is_active: values.is_active,
      });
      if (res.status === 'success') {
        message.success(`IP ${editRecord.ip_address} 已更新`);
        setEditVisible(false);
        setEditRecord(null);
        loadList();
      } else {
        message.error(res.message || '更新失败');
      }
    } catch (e: any) {
      if (e?.response?.status !== 400) {
        message.error(showApiError(e, '更新失败'));
      }
    } finally {
      setEditLoading(false);
    }
  };

  /** 清理过期 */
  const handleCleanup = async () => {
    try {
      const res = await ipBlacklistApi.cleanup();
      if (res.status === 'success') {
        const count = res.data?.cleaned_count ?? 0;
        message.success(`已清理 ${count} 条过期记录`);
        loadList();
      } else {
        message.error(res.message || '清理失败');
      }
    } catch (e: any) {
      message.error(showApiError(e, '清理失败'));
    }
  };

  /** 忽略安全事件（标记为已处理，不封禁） */
  const handleIgnore = async (ev: IPSecurityEvent) => {
    setActingEventId(ev.id);
    try {
      const res = await ipBlacklistApi.ignoreEvent(ev.id);
      if (res.status === 'success') {
        message.success(`事件 ${ev.id} 已忽略`);
        loadEvents();
      } else {
        message.error(res.message || '操作失败');
      }
    } catch (e: any) {
      message.error(showApiError(e, '操作失败'));
    } finally {
      setActingEventId(null);
    }
  };

  /** 封禁安全事件对应的 IP */
  const handleBan = async (ev: IPSecurityEvent) => {
    setActingEventId(ev.id);
    try {
      const res = await ipBlacklistApi.banEvent(ev.id);
      if (res.status === 'success') {
        message.success(res.message || `IP ${ev.ip_address} 已加入黑名单`);
        loadEvents();
      } else {
        message.error(res.message || '操作失败');
      }
    } catch (e: any) {
      message.error(showApiError(e, '操作失败'));
    } finally {
      setActingEventId(null);
    }
  };

  // ============ 表格列定义 ============
  const blacklistColumns = [
    {
      title: 'IP 地址',
      dataIndex: 'ip_address',
      key: 'ip_address',
      width: 160,
      render: (ip: string, row: IPBlacklistRecord) => (
        <Space>
          <Text strong>{ip}</Text>
          <Tag color={row.is_active ? 'green' : 'default'}>
            {row.is_active ? '生效' : '禁用'}
          </Tag>
          {/* 登录安全信号来源高亮（撞库/枚举/限流等） */}
          {['brute', 'enum', 'rate_limit'].some((k) => row.source?.includes(k)) && (
            <Tag color="red" icon={<ExclamationCircleOutlined />}>登录风险</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '原因',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true,
      render: (v: string | null) => v || <Text type="secondary">—</Text>,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 150,
      render: (s: string) => {
        const style = IP_SOURCE_STYLE[s];
        const isLoginRisk = ['brute', 'enum', 'rate_limit'].some((k) => s?.includes(k));
        return (
          <Tooltip title={isLoginRisk ? '登录安全自动处置' : `来源: ${s}`}>
            <Tag
              color={style?.color || 'default'}
              style={isLoginRisk ? { fontWeight: 600 } : undefined}
            >
              {SOURCE_CN[s] || s}
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '封禁时间',
      dataIndex: 'blocked_at',
      key: 'blocked_at',
      width: 165,
      render: (v: string | null) => fmtTime(v),
    },
    {
      title: '过期时间',
      dataIndex: 'expires_at',
      key: 'expires_at',
      width: 165,
      render: (v: string | null) =>
        v ? fmtTime(v) : <Tag color="purple">永久</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      fixed: 'right' as const,
      render: (_: unknown, row: IPBlacklistRecord) => (
        <Space size={4} wrap>
          {/* 一键解封（显式，区别于 toggle 禁用） */}
          {row.is_active && (
            <Popconfirm
              title="确认解封该 IP？"
              description="解封后该 IP 将立即恢复访问权限"
              okText="解封"
              cancelText="取消"
              okButtonProps={{ danger: false }}
              onConfirm={() => handleUnblock(row)}
            >
              <Button size="small" icon={<UnlockOutlined />}>
                解封
              </Button>
            </Popconfirm>
          )}
          {/* 编辑（期限/备注/原因） */}
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(row)}
          >
            编辑
          </Button>
          {/* 启停开关 */}
          <Tooltip title={row.is_active ? '点击禁用（保留记录）' : '点击启用'}>
            <Switch
              checked={row.is_active}
              size="small"
              loading={togglingIp === row.ip_address}
              onChange={(checked) => handleToggle(row, checked)}
            />
          </Tooltip>
          {/* 彻底删除 */}
          <Popconfirm
            title="确认彻底移除？"
            description="将从黑名单中永久删除该记录"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleRemove(row)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const eventColumns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string | null) => fmtTime(v),
    },
    {
      title: 'IP 地址',
      dataIndex: 'ip_address',
      key: 'ip_address',
      width: 150,
      render: (ip: string) => <Text strong>{ip}</Text>,
    },
    {
      title: '事件类型',
      dataIndex: 'event_type',
      key: 'event_type',
      width: 140,
      render: (t: string) => <Tag color="geekblue">{EVENT_TYPE_CN[t] || t}</Tag>,
    },
    {
      title: '严重程度',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (s: string) => <Tag color={sevColor(s)}>{s}</Tag>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      key: 'path',
      ellipsis: true,
      render: (p: string | null) => p || <Text type="secondary">—</Text>,
    },
    {
      title: '方法',
      dataIndex: 'method',
      key: 'method',
      width: 80,
      render: (m: string | null) => m || '—',
    },
    {
      title: '是否封禁',
      dataIndex: 'is_blocked',
      key: 'is_blocked',
      width: 100,
      render: (b: boolean) =>
        b ? <Tag color="red">已封禁</Tag> : <Tag>未封禁</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 170,
      fixed: 'right' as const,
      render: (_: unknown, row: IPSecurityEvent) => {
        if (row.is_blocked) return <Tag color="red">已封禁</Tag>;
        if (row.is_ignored) return <Tag>已忽略</Tag>;
        const loading = actingEventId === row.id;
        return (
          <Space>
            <Button size="small" loading={loading} onClick={() => handleIgnore(row)}>
              忽略
            </Button>
            <Popconfirm
              title="确认封禁该 IP？"
              description={`将把 ${row.ip_address} 加入黑名单`}
              okText="封禁"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleBan(row)}
            >
              <Button danger size="small" loading={loading}>封禁</Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  const listTab = (
    <Card
      extra={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'nowrap', gap: 6, overflow: 'hidden' }}>
          <Space size={4}>
          <Tooltip title="仅显示生效中的记录">
            <span style={{ display: 'inline-flex', alignItems: 'center', whiteSpace: 'nowrap', gap: 4 }}>
              <Switch
                checked={onlyActive}
                size="small"
                onChange={(v) => {
                  setOnlyActive(v);
                  setPage(1);
                }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>仅生效</Text>
            </span>
            </Tooltip>
            <Button size="small" icon={<ReloadOutlined />} onClick={loadList} loading={loading}>
              刷新
            </Button>
            <Popconfirm
              title="清理过期记录？"
              description="将删除所有已过期的黑名单记录"
              okText="清理"
              cancelText="取消"
              onConfirm={handleCleanup}
            >
              <Button size="small">清理过期</Button>
            </Popconfirm>
          </Space>
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
            添加黑名单
          </Button>
        </div>
      }
    >
      {isMobile ? (
        // 手机端：每个 IP 一张专用卡片
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {loading && records.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>
              <Spin />
            </div>
          ) : records.length === 0 ? (
            <Empty description="暂无黑名单记录" />
          ) : (
            records.map((rec) => (
              <Card key={rec.ip_address} size="small">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space size={6}>
                    <Text strong>{rec.ip_address}</Text>
                    <Tag color={rec.is_active ? 'green' : 'default'}>{rec.is_active ? '生效' : '禁用'}</Tag>
                    {['brute', 'enum', 'rate_limit'].some((k) => rec.source?.includes(k)) && <Tag color="red" icon={<ExclamationCircleOutlined />}>登录风险</Tag>}
                  </Space>
                  <Tag color={sourceColor(rec.source)}>{SOURCE_CN[rec.source] || rec.source}</Tag>
                </div>
                <Divider style={{ margin: '8px 0' }} />
                <div style={{ fontSize: 12, color: '#666', lineHeight: '20px' }}>
                  <div>原因：{rec.reason || '—'}</div>
                  <div>封禁时间：{fmtTime(rec.blocked_at)}</div>
                  <div>过期时间：{rec.expires_at ? fmtTime(rec.expires_at) : <Tag color="purple">永久</Tag>}</div>
                  {rec.note && <div>备注：{rec.note}</div>}
                </div>
                <div style={{ marginTop: 10, display: 'flex', justifyContent: 'flex-end', gap: 8, flexWrap: 'wrap' }}>
                  {rec.is_active && (
                    <Button size="small" icon={<UnlockOutlined />} onClick={() => handleUnblock(rec)}>
                      解封
                    </Button>
                  )}
                  <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(rec)}>编辑</Button>
                  <Tooltip title={rec.is_active ? '禁用（保留记录）' : '启用'}>
                    <Switch
                      checked={rec.is_active}
                      size="small"
                      loading={togglingIp === rec.ip_address}
                      onChange={(c) => handleToggle(rec, c)}
                    />
                  </Tooltip>
                  <Popconfirm title="确认彻底移除？" description="将从黑名单永久删除"
                    okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                    onConfirm={() => handleRemove(rec)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </div>
              </Card>
            ))
          )}
          {records.length > 0 && (
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Pagination
                size="small"
                simple
                current={page}
                pageSize={perPage}
                total={total}
                onChange={(p) => setPage(p)}
              />
            </div>
          )}
        </div>
      ) : (
        <ResponsiveTable<IPBlacklistRecord>
          rowKey="ip_address"
          columns={blacklistColumns}
          dataSource={records}
          loading={loading}
          scroll={{ x: Math.max(900, blacklistColumns.reduce((sum, c) => sum + (c.width || 150), 0)) }}
          pagination={{
            current: page,
            pageSize: perPage,
            total,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => setPage(p),
          }}
          size="middle"
          locale={{ emptyText: <Empty description="暂无黑名单记录" /> }}
        />
      )}
    </Card>
  );

  const eventTab = (
    <Card
      extra={
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'nowrap', gap: 6, overflow: 'hidden' }}>
          <Select
            placeholder="事件类型"
            allowClear
            size="small"
            style={{ width: 130 }}
            options={EVENT_TYPE_OPTIONS}
            value={eventType}
            onChange={(v) => {
              setEventType(v);
              setEventPage(1);
            }}
          />
          <Select
            placeholder="严重程度"
            allowClear
            size="small"
            style={{ width: 100 }}
            options={SEVERITY_OPTIONS}
            value={severity}
            onChange={(v) => {
              setSeverity(v);
              setEventPage(1);
            }}
          />
          <Tooltip title="仅显示未封禁且未忽略的事件">
            <span style={{ display: 'inline-flex', alignItems: 'center', whiteSpace: 'nowrap', gap: 4 }}>
              <Switch
                checked={onlyPending}
                size="small"
                onChange={(v) => {
                  setOnlyPending(v);
                  setEventPage(1);
                }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>待处置</Text>
            </span>
          </Tooltip>
          <Button size="small" icon={<ReloadOutlined />} onClick={loadEvents} loading={eventLoading}>
            刷新
          </Button>
        </div>
      }
    >
      {isMobile ? (
        // 手机端：每条安全事件一张专用卡片
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {eventLoading && events.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>
              <Spin />
            </div>
          ) : events.length === 0 ? (
            <Empty description="暂无安全事件" />
          ) : (
            events.map((ev) => (
              <Card key={ev.id} size="small">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space size={6}>
                    <Text strong>{ev.ip_address}</Text>
                    {ev.is_blocked ? <Tag color="red">已封禁</Tag> : <Tag>未封禁</Tag>}
                  </Space>
                  <Tag color={sevColor(ev.severity)}>{ev.severity}</Tag>
                </div>
                <Divider style={{ margin: '10px 0' }} />
                <div style={{ fontSize: 12, color: '#666', lineHeight: '20px' }}>
                  <div>时间：{fmtTime(ev.created_at)}</div>
                  <div>事件类型：<Tag color="geekblue">{EVENT_TYPE_CN[ev.event_type] || ev.event_type}</Tag></div>
                  <div>方法：{ev.method || '—'}</div>
                  <div>路径：{ev.path || '—'}</div>
                </div>
                {ev.detail && (
                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>请求详情：</Text>
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 11, color: '#999', background: '#fafafa', padding: 8, borderRadius: 4 }}>
                      {ev.detail}
                    </pre>
                  </div>
                )}
                {!ev.is_blocked && !ev.is_ignored && (
                  <div style={{ marginTop: 10, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                    <Button size="small" loading={actingEventId === ev.id} onClick={() => handleIgnore(ev)}>
                      忽略
                    </Button>
                    <Popconfirm
                      title="确认封禁该 IP？"
                      description={`将把 ${ev.ip_address} 加入黑名单`}
                      okText="封禁"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleBan(ev)}
                    >
                      <Button danger size="small" loading={actingEventId === ev.id}>封禁</Button>
                    </Popconfirm>
                  </div>
                )}
              </Card>
            ))
          )}
          {events.length > 0 && (
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Pagination
                size="small"
                simple
                current={eventPage}
                pageSize={perPage}
                total={eventTotal}
                onChange={(p) => setEventPage(p)}
              />
            </div>
          )}
        </div>
      ) : (
        <ResponsiveTable<IPSecurityEvent>
          rowKey="id"
          columns={eventColumns}
          dataSource={events}
          loading={eventLoading}
          scroll={{ x: Math.max(900, eventColumns.reduce((sum, c) => sum + (c.width || 120), 0)) }}
          pagination={{
            current: eventPage,
            pageSize: perPage,
            total: eventTotal,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => setEventPage(p),
          }}
          size="middle"
          locale={{ emptyText: <Empty description="暂无安全事件" /> }}
          expandable={{
            expandedRowRender: (row) => (
              <div style={{ padding: '8px 0' }}>
                <Text type="secondary">请求详情：</Text>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {row.detail || '无'}
                </pre>
              </div>
            ),
          }}
        />
      )}
    </Card>
  );

  return (
    <div style={{ overflowX: 'hidden' }}>
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key);
          if (key === 'events' && events.length === 0) {
            loadEvents();
          }
        }}
        items={[
          { key: 'list', label: '黑名单列表', children: listTab },
          { key: 'events', label: '安全事件', children: eventTab },
        ]}
      />

      {/* 添加黑名单模态框 */}
      <Modal
        title="添加 IP 到黑名单"
        open={addVisible}
        onOk={handleAdd}
        confirmLoading={addLoading}
        onCancel={() => {
          setAddVisible(false);
          form.resetFields();
        }}
        okText="加入黑名单"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ reason: '手动封禁', duration_hours: 0 }}>
          <Form.Item
            label="IP 地址"
            name="ip_address"
            rules={[{ validator: validateIp }]}
            extra="支持 IPv4 / IPv6，例如 192.168.1.1"
          >
            <Input placeholder="请输入要封禁的 IP" />
          </Form.Item>
          <Form.Item label="封禁原因" name="reason">
            <Input placeholder="例如：恶意爬虫 / 攻击来源" />
          </Form.Item>
          <Form.Item
            label="封禁时长（小时）"
            name="duration_hours"
            extra="0 表示永久封禁"
          >
            <InputNumber min={0} max={87600} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="备注" name="note">
            <Input.TextArea rows={3} placeholder="可选备注信息" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑黑名单抽屉 */}
      <Drawer
        title={`编辑封禁记录 — ${editRecord?.ip_address || ''}`}
        open={editVisible}
        onClose={() => {
          setEditVisible(false);
          setEditRecord(null);
          editForm.resetFields();
        }}
        width={420}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => { setEditVisible(false); setEditRecord(null); }}>取消</Button>
            <Button type="primary" loading={editLoading} onClick={handleEditSubmit}>
              保存修改
            </Button>
          </Space>
        }
      >
        {editRecord && (
          <>
            <div style={{ marginBottom: 16, padding: '8px 12px', background: '#fafafa', borderRadius: 6, fontSize: 12 }}>
              <Space direction="vertical" size={4}>
                <Text><Text strong>IP：</Text>{editRecord.ip_address}</Text>
                <Text><Text strong>当前来源：</Text>
                  <Tag color={sourceColor(editRecord.source)}>{SOURCE_CN[editRecord.source] || editRecord.source}</Tag>
                </Text>
                <Text><Text strong>封禁时间：</Text>{fmtTime(editRecord.blocked_at)}</Text>
              </Space>
            </div>
            <Form form={editForm} layout="vertical">
              <Form.Item label="封禁原因" name="reason">
                <Input placeholder="例如：恶意爬虫 / 攻击来源 / 暴力破解" />
              </Form.Item>
              <Form.Item
                label="封禁时长（小时）"
                name="duration_hours"
                extra="0 = 永久封禁；修改后从当前时间重新计算过期时间"
              >
                <InputNumber min={0} max={87600} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="备注" name="note">
                <Input.TextArea rows={3} placeholder="可选备注信息（如误封原因、处置说明等）" />
              </Form.Item>
              <Form.Item label="状态" name="is_active" valuePropName="checked">
                <Switch checkedChildren="生效" unCheckedChildren="禁用" />
              </Form.Item>
            </Form>
          </>
        )}
      </Drawer>
    </div>
  );
}
