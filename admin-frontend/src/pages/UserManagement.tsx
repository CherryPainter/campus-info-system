/**
 * 用户管理页面
 * 仅管理员可访问
 */
import { useState } from 'react';
import {
  Card,
  Button,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Popconfirm,
  Avatar,
  Tooltip,
  App,
  Grid,
  Divider,
  Spin,
} from 'antd';
import { formatDateTime } from '@/utils/datetime';
import ResponsiveTable from '@/components/ResponsiveTable';
import {
  UserAddOutlined,
  EditOutlined,
  DeleteOutlined,
  KeyOutlined,
  UserOutlined,
  CrownOutlined,
  LockOutlined,
} from '@ant-design/icons';
import { userApi } from '@/api/admin';
import type { User } from '@/types/user';
import { useUser } from '@/contexts/UserContext';
import { useIntervalPolling } from '@/hooks/useIntervalPolling';
import { POLL_NORMAL } from '@/hooks/pollIntervals';

const { Option } = Select;

export default function UserManagement() {
  const { user: currentUser, isPrimary } = useUser();
  const { message } = App.useApp();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [passwordForm] = Form.useForm();

  // 加载用户列表
  const loadUsers = async () => {
    setLoading(true);
    try {
      const res = await userApi.getUsers();
      if (res.status === 'success') {
        setUsers(res.data || []);
      }
    } catch (error) {
      message.error('加载用户列表失败');
    } finally {
      setLoading(false);
    }
  };

  useIntervalPolling(loadUsers, POLL_NORMAL);

  // 创建用户
  const handleCreate = async (values: any) => {
    try {
      const res = await userApi.createUser(values);
      if (res.status === 'success') {
        message.success('用户创建成功');
        setCreateModalVisible(false);
        createForm.resetFields();
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '创建失败');
    }
  };

  // 编辑用户
  const handleEdit = async (values: any) => {
    if (!selectedUser) return;
    try {
      const res = await userApi.updateUser(selectedUser.id, values);
      if (res.status === 'success') {
        message.success('用户更新成功');
        setEditModalVisible(false);
        editForm.resetFields();
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '更新失败');
    }
  };

  // 删除用户
  const handleDelete = async (user: User) => {
    try {
      const res = await userApi.deleteUser(user.id);
      if (res.status === 'success') {
        message.success('用户删除成功');
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '删除失败');
    }
  };

  // 重置密码
  const handleResetPassword = async (values: any) => {
    if (!selectedUser) return;
    try {
      const res = await userApi.resetUserPassword(selectedUser.id, values.password);
      if (res.status === 'success') {
        message.success('密码重置成功');
        setPasswordModalVisible(false);
        passwordForm.resetFields();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '重置密码失败');
    }
  };

  // 重置MFA
  const handleResetMfa = async (user: User) => {
    try {
      const res = await userApi.resetUserMfa(user.id);
      if (res.status === 'success') {
        message.success(res.message || 'MFA已重置');
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '重置MFA失败');
    }
  };

  // 打开编辑弹窗
  const openEditModal = (user: User) => {
    setSelectedUser(user);
    editForm.setFieldsValue({
      username: user.username,
      role: user.role,
      is_primary: user.is_primary,
    });
    setEditModalVisible(true);
  };

  // 打开重置密码弹窗
  const openPasswordModal = (user: User) => {
    setSelectedUser(user);
    setPasswordModalVisible(true);
  };

  // 判断是否可以删除用户
  const canDeleteUser = (user: User) => {
    // 不能删除自己
    if (String(user.id) === String(currentUser?.id)) {
      return { canDelete: false, reason: '不能删除自己' };
    }
    // 超级管理员不可被删除
    if (user.is_primary) {
      return { canDelete: false, reason: '超级管理员不可被删除' };
    }
    // 只有超级管理员可以删除其他管理员
    if (user.role === 'admin' && !isPrimary) {
      return { canDelete: false, reason: '只有超级管理员可以删除其他管理员' };
    }
    return { canDelete: true, reason: '' };
  };

  // 判断是否可以编辑用户角色
  const canEditRole = (user: User) => {
    // 超级管理员的角色不可修改
    if (user.is_primary) {
      return false;
    }
    // 只有超级管理员可以修改其他管理员的角色
    if (user.role === 'admin' && !isPrimary) {
      return false;
    }
    return true;
  };

  // 判断是否可以重置用户MFA
  const canResetMfa = (user: User) => {
    // 超级管理员的MFA不可被任何人重置
    if (user.is_primary) {
      return false;
    }
    // 非超级管理员只能重置普通用户的MFA，不能重置其他管理员的MFA
    if (user.role === 'admin' && !isPrimary) {
      return false;
    }
    return true;
  };

  const columns = [
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
      render: (username: string, record: User) => (
        <Space>
          <Avatar size="small" icon={<UserOutlined />} src={record.avatar} />
          <span>{username}</span>
          {record.is_primary && (
            <Tooltip title="主管理员">
              <Tag color="gold" icon={<CrownOutlined />}>主管理员</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'blue' : 'default'}>
          {role === 'admin' ? '管理员' : '普通用户'}
        </Tag>
      ),
    },
    {
      title: 'MFA状态',
      dataIndex: 'mfa_enabled',
      key: 'mfa_enabled',
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'green' : 'default'}>
          {enabled ? '已开启' : '未开启'}
        </Tag>
      ),
    },
    {
      title: '最后登录',
      dataIndex: 'last_login',
      key: 'last_login',
      render: (date: string) => (date ? formatDateTime(date) : '-'),
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => (date ? new Date(date).toLocaleDateString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: User) => {
        const { canDelete, reason } = canDeleteUser(record);
        const editableRole = canEditRole(record);
        return (
          <Space size="small">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEditModal(record)}
            >
              编辑
            </Button>
            <Button
              type="link"
              size="small"
              icon={<KeyOutlined />}
              onClick={() => openPasswordModal(record)}
            >
              重置密码
            </Button>
            {/* 重置MFA：主管理员可重置任何非主管理员用户，非主管理员只能重置普通用户 */}
            {canResetMfa(record) && (
              record.mfa_enabled ? (
                <Popconfirm
                  title="确认重置MFA"
                  description="确定要重置该用户的MFA吗？用户将需要重新设置MFA认证。"
                  onConfirm={() => handleResetMfa(record)}
                  okText="确定"
                  cancelText="取消"
                >
                  <Button type="link" size="small" icon={<LockOutlined />}>
                    重置MFA
                  </Button>
                </Popconfirm>
              ) : (
                <Tooltip title="该用户未开启MFA">
                  <Button type="link" size="small" icon={<LockOutlined />} disabled>
                    重置MFA
                  </Button>
                </Tooltip>
              )
            )}
            {canDelete ? (
              <Popconfirm
                title="确认删除"
                description="确定要删除该用户吗？此操作不可撤销。"
                onConfirm={() => handleDelete(record)}
                okText="确定"
                cancelText="取消"
              >
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            ) : (
              <Tooltip title={reason}>
                <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled>
                  删除
                </Button>
              </Tooltip>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <Card
        title="用户管理"
        extra={
          <Button
            type="primary"
            icon={<UserAddOutlined />}
            onClick={() => setCreateModalVisible(true)}
          >
            新建用户
          </Button>
        }
      >
        {isMobile ? (
          // 手机端：每个用户一张专用卡片，竖向排列，避免横向滚动表格
          users.length === 0 && loading ? (
            <div style={{ textAlign: 'center', padding: '48px 0' }}><Spin /></div>
          ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {users.map((u: User) => {
              const { canDelete, reason } = canDeleteUser(u);
              return (
                <Card key={u.id} size="small" loading={loading && users.length === 0}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Avatar size={42} icon={<UserOutlined />} src={u.avatar} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 15, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{u.username}</span>
                        {u.is_primary && (
                          <Tag color="gold" icon={<CrownOutlined />} style={{ marginInlineEnd: 0 }}>主管理员</Tag>
                        )}
                      </div>
                      <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <Tag color={u.role === 'admin' ? 'blue' : 'default'}>
                          {u.role === 'admin' ? '管理员' : '普通用户'}
                        </Tag>
                        <Tag color={u.mfa_enabled ? 'green' : 'default'}>
                          {u.mfa_enabled ? 'MFA已开启' : 'MFA未开启'}
                        </Tag>
                      </div>
                    </div>
                  </div>
                  <Divider style={{ margin: '10px 0' }} />
                  <div style={{ fontSize: 12, color: '#888', lineHeight: 1.9 }}>
                    <div>最后登录：{u.last_login ? formatDateTime(u.last_login) : '-'}</div>
                    <div>注册时间：{u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '-'}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openEditModal(u)}>编辑</Button>
                    <Button size="small" icon={<KeyOutlined />} onClick={() => openPasswordModal(u)}>密码</Button>
                    {canResetMfa(u) && (
                      u.mfa_enabled ? (
                        <Popconfirm
                          title="确认重置MFA"
                          description="确定要重置该用户的MFA吗？用户将需要重新设置MFA认证。"
                          onConfirm={() => handleResetMfa(u)}
                          okText="确定"
                          cancelText="取消"
                        >
                          <Button size="small" icon={<LockOutlined />}>重置MFA</Button>
                        </Popconfirm>
                      ) : (
                        <Tooltip title="该用户未开启MFA">
                          <Button size="small" icon={<LockOutlined />} disabled>重置MFA</Button>
                        </Tooltip>
                      )
                    )}
                    {canDelete ? (
                      <Popconfirm
                        title="确认删除"
                        description="确定要删除该用户吗？此操作不可撤销。"
                        onConfirm={() => handleDelete(u)}
                        okText="确定"
                        cancelText="取消"
                      >
                        <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                      </Popconfirm>
                    ) : (
                      <Tooltip title={reason}>
                        <Button size="small" danger icon={<DeleteOutlined />} disabled>删除</Button>
                      </Tooltip>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )
        ) : (
          <ResponsiveTable
            columns={columns}
            dataSource={users}
            loading={loading}
            rowKey="id"
            scroll={{ x: 800 }}
          />
        )}
      </Card>

      {/* 创建用户弹窗 */}
      <Modal
        title="新建用户"
        open={createModalVisible}
        onCancel={() => setCreateModalVisible(false)}
        footer={null}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
        >
          <Form.Item
            label="用户名"
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, max: 50, message: '用户名长度应在3-50个字符之间' },
            ]}
          >
            <Input placeholder="请输入用户名" />
          </Form.Item>

          <Form.Item
            label="密码"
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '密码长度至少6个字符' },
            ]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>

          <Form.Item
            label="角色"
            name="role"
            initialValue="user"
            rules={[{ required: true, message: '请选择角色' }]}
          >
            <Select>
              <Option value="user">普通用户</Option>
              {isPrimary && <Option value="admin">管理员</Option>}
            </Select>
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">创建</Button>
              <Button onClick={() => setCreateModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑用户弹窗 */}
      <Modal
        title="编辑用户"
        open={editModalVisible}
        onCancel={() => setEditModalVisible(false)}
        footer={null}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={handleEdit}
        >
          <Form.Item
            label="用户名"
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, max: 50, message: '用户名长度应在3-50个字符之间' },
            ]}
          >
            <Input placeholder="请输入用户名" />
          </Form.Item>

          <Form.Item
            label="角色"
            name="role"
            rules={[{ required: true, message: '请选择角色' }]}
          >
            {selectedUser && !canEditRole(selectedUser) ? (
              <Input
                disabled
                value={selectedUser.role === 'admin' ? '管理员' : '普通用户'}
              />
            ) : (
              <Select>
                <Option value="user">普通用户</Option>
                {isPrimary && <Option value="admin">管理员</Option>}
              </Select>
            )}
          </Form.Item>

          {isPrimary && selectedUser && !selectedUser.is_primary && (
            <Form.Item
              label="主管理员权限"
              name="is_primary"
              valuePropName="checked"
            >
              <Select>
                <Option value={false}>否</Option>
                <Option value={true}>是</Option>
              </Select>
            </Form.Item>
          )}

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">保存</Button>
              <Button onClick={() => setEditModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 重置密码弹窗 */}
      <Modal
        title="重置密码"
        open={passwordModalVisible}
        onCancel={() => setPasswordModalVisible(false)}
        footer={null}
      >
        <Form
          form={passwordForm}
          layout="vertical"
          onFinish={handleResetPassword}
        >
          <Form.Item
            label="新密码"
            name="password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码长度至少6个字符' },
            ]}
          >
            <Input.Password placeholder="请输入新密码" />
          </Form.Item>

          <Form.Item
            label="确认密码"
            name="confirmPassword"
            dependencies={['password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="请确认新密码" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">重置密码</Button>
              <Button onClick={() => setPasswordModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
