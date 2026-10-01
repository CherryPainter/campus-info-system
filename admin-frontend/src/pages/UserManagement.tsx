/**
 * 用户管理页面
 * 仅管理员可访问
 */
import { useMemo, useState } from "react";
import {
  Card,
  Button,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Popconfirm,
  Avatar,
  Tooltip,
  App,
  Grid,
  Divider,
  Spin,
  Empty,
} from "antd";
import { formatDateTime } from "@/utils/datetime";
import ResponsiveTable from "@/components/ResponsiveTable";
import {
  UserAddOutlined,
  EditOutlined,
  DeleteOutlined,
  KeyOutlined,
  UserOutlined,
  CrownOutlined,
  LockOutlined,
} from "@ant-design/icons";
import { userApi } from "@/api/admin";
import type { User } from "@/types/user";
import { useUser } from "@/contexts/UserContext";
import { useIntervalPolling } from "@/hooks/useIntervalPolling";
import { POLL_NORMAL } from "@/hooks/pollIntervals";

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

  // 用户列表筛选：来源 / 角色 / MFA / 关键字
  const [sourceFilter, setSourceFilter] = useState<"all" | "wechat" | "web">("all");
  const [roleFilter, setRoleFilter] = useState<"all" | "admin" | "user">("all");
  const [mfaFilter, setMfaFilter] = useState<"all" | "enabled" | "disabled">("all");
  const [keyword, setKeyword] = useState("");

  // 加载用户列表
  const loadUsers = async () => {
    setLoading(true);
    try {
      const res = await userApi.getUsers();
      if (res.status === "success") {
        setUsers(res.data || []);
      }
    } catch (error) {
      message.error("加载用户列表失败");
    } finally {
      setLoading(false);
    }
  };

  useIntervalPolling(loadUsers, POLL_NORMAL);

  // 创建用户
  const handleCreate = async (values: any) => {
    try {
      const res = await userApi.createUser(values);
      if (res.status === "success") {
        message.success("用户创建成功");
        setCreateModalVisible(false);
        createForm.resetFields();
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "创建失败");
    }
  };

  // 编辑用户
  const handleEdit = async (values: any) => {
    if (!selectedUser) return;
    try {
      const res = await userApi.updateUser(selectedUser.id, values);
      if (res.status === "success") {
        message.success("用户更新成功");
        setEditModalVisible(false);
        editForm.resetFields();
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "更新失败");
    }
  };

  // 删除用户
  const handleDelete = async (user: User) => {
    try {
      const res = await userApi.deleteUser(user.id);
      if (res.status === "success") {
        message.success("用户删除成功");
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "删除失败");
    }
  };

  // 重置密码
  const handleResetPassword = async (values: any) => {
    if (!selectedUser) return;
    try {
      const res = await userApi.resetUserPassword(selectedUser.id, values.password);
      if (res.status === "success") {
        message.success("密码重置成功");
        setPasswordModalVisible(false);
        passwordForm.resetFields();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "重置密码失败");
    }
  };

  // 重置MFA
  const handleResetMfa = async (user: User) => {
    try {
      const res = await userApi.resetUserMfa(user.id);
      if (res.status === "success") {
        message.success(res.message || "MFA已重置");
        loadUsers();
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || "重置MFA失败");
    }
  };

  // 打开编辑弹窗
  const openEditModal = (user: User) => {
    setSelectedUser(user);
    editForm.setFieldsValue({
      username: user.username,
      role: user.role,
      is_primary: user.is_primary,
      is_active: user.is_active,
    });
    setEditModalVisible(true);
  };

  // 能否切换账号启用状态：主管理员不可被禁用（避免锁死管理入口），
  // 当前登录者不可禁用自己；其余用户（含微信端学生）均可禁用/启用。
  const canToggleActive = (user: User | null) => {
    if (!user) return false;
    if (user.is_primary) return false;
    if (String(user.id) === String(currentUser?.id)) return false;
    return true;
  };

  // 打开重置密码弹窗
  const openPasswordModal = (user: User) => {
    setSelectedUser(user);
    setPasswordModalVisible(true);
  };

  // 微信端用户：openid 登录，无账号密码/MFA 概念，相关操作不展示
  const isWechatUser = (user: User) => user.source === "wechat" || user.role === "student";

  // 按来源/角色/MFA/关键字筛选后的用户列表
  const filteredUsers = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return users.filter((u) => {
      const isWechat = u.source === "wechat" || u.role === "student";
      if (sourceFilter === "wechat" && !isWechat) return false;
      if (sourceFilter === "web" && isWechat) return false;
      if (roleFilter !== "all" && u.role !== roleFilter) return false;
      if (mfaFilter === "enabled" && !u.mfa_enabled) return false;
      if (mfaFilter === "disabled" && u.mfa_enabled) return false;
      if (kw && !u.username.toLowerCase().includes(kw)) return false;
      return true;
    });
  }, [users, sourceFilter, roleFilter, mfaFilter, keyword]);

  // 判断是否可以删除用户
  const canDeleteUser = (user: User) => {
    // 不能删除自己
    if (String(user.id) === String(currentUser?.id)) {
      return { canDelete: false, reason: "不能删除自己" };
    }
    // 超级管理员不可被删除
    if (user.is_primary) {
      return { canDelete: false, reason: "超级管理员不可被删除" };
    }
    // 只有超级管理员可以删除其他管理员
    if (user.role === "admin" && !isPrimary) {
      return { canDelete: false, reason: "只有超级管理员可以删除其他管理员" };
    }
    return { canDelete: true, reason: "" };
  };

  // 判断是否可以编辑用户角色
  const canEditRole = (user: User) => {
    // 超级管理员的角色不可修改
    if (user.is_primary) {
      return false;
    }
    // 只有超级管理员可以修改其他管理员的角色
    if (user.role === "admin" && !isPrimary) {
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
    if (user.role === "admin" && !isPrimary) {
      return false;
    }
    return true;
  };

  const columns = [
    {
      title: "用户名",
      dataIndex: "username",
      key: "username",
      render: (username: string, record: User) => (
        <Space>
          <Avatar size="small" icon={<UserOutlined />} src={record.avatar} />
          <span>{username}</span>
          {record.is_primary && (
            <Tooltip title="主管理员">
              <Tag color="gold" icon={<CrownOutlined />}>
                主管理员
              </Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: "角色",
      dataIndex: "role",
      key: "role",
      render: (role: string) => (
        <Tag color={role === "admin" ? "blue" : "default"}>
          {role === "admin" ? "管理员" : "普通用户"}
        </Tag>
      ),
    },
    {
      title: "来源",
      dataIndex: "source",
      key: "source",
      render: (_: string, record: User) =>
        isWechatUser(record) ? <Tag color="green">微信端</Tag> : <Tag>网页端</Tag>,
    },
    {
      title: "MFA状态",
      dataIndex: "mfa_enabled",
      key: "mfa_enabled",
      render: (enabled: boolean) => (
        <Tag color={enabled ? "green" : "default"}>{enabled ? "已开启" : "未开启"}</Tag>
      ),
    },
    {
      title: "最后登录",
      dataIndex: "last_login",
      key: "last_login",
      render: (date: string) => (date ? formatDateTime(date) : "-"),
    },
    {
      title: "注册时间",
      dataIndex: "created_at",
      key: "created_at",
      render: (date: string) => (date ? new Date(date).toLocaleDateString("zh-CN") : "-"),
    },
    {
      title: "操作",
      key: "actions",
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
            {/* 微信端用户无账号密码，隐藏重置密码 */}
            {!isWechatUser(record) && (
              <Button
                type="link"
                size="small"
                icon={<KeyOutlined />}
                onClick={() => openPasswordModal(record)}
              >
                重置密码
              </Button>
            )}
            {/* 重置MFA：主管理员可重置任何非主管理员用户，非主管理员只能重置普通用户；微信端用户无 MFA */}
            {!isWechatUser(record) &&
              canResetMfa(record) &&
              (record.mfa_enabled ? (
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
              ))}
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
                  // 移动端消除外层白色容器：borderless 去边框 + body padding 0 让内容直接贴 Tabs 边缘，
                  // 避免"Card 进一步限制"导致用户卡片被挤窄，桌面端保持默认 outlined/24px padding
                  variant={isMobile ? "borderless" : undefined}
                  styles={{ body: { padding: isMobile ? 0 : 24 } }}
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
        {/* 筛选栏：来源/角色/MFA/关键字，桌面与移动端通用 */}
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "center",
            marginBottom: 16,
            padding: isMobile ? "12px 12px 0" : 0,
          }}
        >
          <Select
            value={sourceFilter}
            onChange={setSourceFilter}
            style={isMobile ? { flex: 1, minWidth: 0 } : { width: 120 }}
            options={[
              { value: "all", label: "全部来源" },
              { value: "wechat", label: "微信端" },
              { value: "web", label: "网页端" },
            ]}
          />
          <Select
            value={roleFilter}
            onChange={setRoleFilter}
            style={isMobile ? { flex: 1, minWidth: 0 } : { width: 120 }}
            options={[
              { value: "all", label: "全部角色" },
              { value: "admin", label: "管理员" },
              { value: "user", label: "普通用户" },
            ]}
          />
          <Select
            value={mfaFilter}
            onChange={setMfaFilter}
            style={isMobile ? { flex: 1, minWidth: 0 } : { width: 120 }}
            options={[
              { value: "all", label: "全部MFA" },
              { value: "enabled", label: "已开启" },
              { value: "disabled", label: "未开启" },
            ]}
          />
          <Input
            allowClear
            placeholder="搜索用户名"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={isMobile ? { flex: "100%", minWidth: 0 } : { width: 200 }}
          />
        </div>

        {isMobile ? (
          // 手机端：每个用户一张专用卡片，竖向排列，避免横向滚动表格
          users.length === 0 && loading ? (
            <div style={{ textAlign: "center", padding: "48px 0" }}>
              <Spin />
            </div>
          ) : filteredUsers.length === 0 ? (
            <Empty description="没有符合条件的用户" style={{ padding: "48px 0" }} />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {filteredUsers.map((u: User) => {
                const { canDelete, reason } = canDeleteUser(u);
                return (
                  <Card key={u.id} size="small" loading={loading && users.length === 0}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <Avatar size={42} icon={<UserOutlined />} src={u.avatar} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontWeight: 600,
                            fontSize: 15,
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            flexWrap: "wrap",
                          }}
                        >
                          <span
                            style={{
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {u.username}
                          </span>
                          {u.is_primary && (
                            <Tag
                              color="gold"
                              icon={<CrownOutlined />}
                              style={{ marginInlineEnd: 0 }}
                            >
                              主管理员
                            </Tag>
                          )}
                        </div>
                        <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <Tag color={u.role === "admin" ? "blue" : "default"}>
                            {u.role === "admin" ? "管理员" : "普通用户"}
                          </Tag>
                          <Tag color={isWechatUser(u) ? "green" : undefined}>
                            {isWechatUser(u) ? "微信端" : "网页端"}
                          </Tag>
                          <Tag color={u.mfa_enabled ? "green" : "default"}>
                            {u.mfa_enabled ? "MFA已开启" : "MFA未开启"}
                          </Tag>
                        </div>
                      </div>
                    </div>
                    <Divider style={{ margin: "10px 0" }} />
                    <div style={{ fontSize: 12, color: "#888", lineHeight: 1.9 }}>
                      <div>最后登录：{u.last_login ? formatDateTime(u.last_login) : "-"}</div>
                      <div>
                        注册时间：
                        {u.created_at ? new Date(u.created_at).toLocaleDateString("zh-CN") : "-"}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                      <Button size="small" icon={<EditOutlined />} onClick={() => openEditModal(u)}>
                        编辑
                      </Button>
                      {!isWechatUser(u) && (
                        <Button
                          size="small"
                          icon={<KeyOutlined />}
                          onClick={() => openPasswordModal(u)}
                        >
                          密码
                        </Button>
                      )}
                      {!isWechatUser(u) &&
                        canResetMfa(u) &&
                        (u.mfa_enabled ? (
                          <Popconfirm
                            title="确认重置MFA"
                            description="确定要重置该用户的MFA吗？用户将需要重新设置MFA认证。"
                            onConfirm={() => handleResetMfa(u)}
                            okText="确定"
                            cancelText="取消"
                          >
                            <Button size="small" icon={<LockOutlined />}>
                              重置MFA
                            </Button>
                          </Popconfirm>
                        ) : (
                          <Tooltip title="该用户未开启MFA">
                            <Button size="small" icon={<LockOutlined />} disabled>
                              重置MFA
                            </Button>
                          </Tooltip>
                        ))}
                      {canDelete ? (
                        <Popconfirm
                          title="确认删除"
                          description="确定要删除该用户吗？此操作不可撤销。"
                          onConfirm={() => handleDelete(u)}
                          okText="确定"
                          cancelText="取消"
                        >
                          <Button size="small" danger icon={<DeleteOutlined />}>
                            删除
                          </Button>
                        </Popconfirm>
                      ) : (
                        <Tooltip title={reason}>
                          <Button size="small" danger icon={<DeleteOutlined />} disabled>
                            删除
                          </Button>
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
            dataSource={filteredUsers}
            loading={loading}
            rowKey="id"
            scroll={{ x: 800 }}
            locale={{ emptyText: "没有符合条件的用户" }}
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
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            label="用户名"
            name="username"
            rules={[
              { required: true, message: "请输入用户名" },
              { min: 3, max: 50, message: "用户名长度应在3-50个字符之间" },
            ]}
          >
            <Input placeholder="请输入用户名" />
          </Form.Item>

          <Form.Item
            label="密码"
            name="password"
            rules={[
              { required: true, message: "请输入密码" },
              { min: 8, message: "密码长度不能少于8位" },
            ]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>

          <Form.Item
            label="角色"
            name="role"
            initialValue="user"
            rules={[{ required: true, message: "请选择角色" }]}
          >
            <Select>
              <Option value="user">普通用户</Option>
              {isPrimary && <Option value="admin">管理员</Option>}
            </Select>
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
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
        <Form form={editForm} layout="vertical" onFinish={handleEdit}>
          <Form.Item
            label="用户名"
            name="username"
            rules={[
              { required: true, message: "请输入用户名" },
              { min: 3, max: 50, message: "用户名长度应在3-50个字符之间" },
            ]}
          >
            {selectedUser && isWechatUser(selectedUser) ? (
              <Input disabled value={selectedUser.username} />
            ) : (
              <Input placeholder="请输入用户名" />
            )}
          </Form.Item>

          <Form.Item label="角色" name="role" rules={[{ required: true, message: "请选择角色" }]}>
            {selectedUser && (isWechatUser(selectedUser) || !canEditRole(selectedUser)) ? (
              <Input
                disabled
                value={
                  isWechatUser(selectedUser)
                    ? "微信端用户"
                    : selectedUser.role === "admin"
                      ? "管理员"
                      : "普通用户"
                }
              />
            ) : (
              <Select>
                <Option value="user">普通用户</Option>
                {isPrimary && <Option value="admin">管理员</Option>}
              </Select>
            )}
          </Form.Item>

          {isPrimary && selectedUser && !selectedUser.is_primary && !isWechatUser(selectedUser) && (
            <Form.Item label="主管理员权限" name="is_primary" valuePropName="checked">
              <Select>
                <Option value={false}>否</Option>
                <Option value={true}>是</Option>
              </Select>
            </Form.Item>
          )}

          {/* 启用状态：禁用账号使其立即无法登录（含吊销全部会话），重新开启即可恢复。
              放在编辑弹窗内，不占列表列宽。主管理员与当前登录者自身不可禁用，避免锁死管理入口。 */}
          {selectedUser && canToggleActive(selectedUser) && (
            <Form.Item
              label="启用状态"
              name="is_active"
              valuePropName="checked"
              tooltip="关闭后该账号立即被禁用（含吊销其全部活跃会话），无法再登录；重新开启即可恢复"
            >
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          )}

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
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
        <Form form={passwordForm} layout="vertical" onFinish={handleResetPassword}>
          <Form.Item
            label="新密码"
            name="password"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 8, message: "密码长度不能少于8位" },
            ]}
          >
            <Input.Password placeholder="请输入新密码" />
          </Form.Item>

          <Form.Item
            label="确认密码"
            name="confirmPassword"
            dependencies={["password"]}
            rules={[
              { required: true, message: "请确认新密码" },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("password") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error("两次输入的密码不一致"));
                },
              }),
            ]}
          >
            <Input.Password placeholder="请确认新密码" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                重置密码
              </Button>
              <Button onClick={() => setPasswordModalVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
