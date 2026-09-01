/**
 * 学生名单（预录白名单）管理组件
 *
 * 挂在「用户管理」页第二个 Tab：管理员提前录入合法学生（学校+学号+班级），
 * 小程序登录后提交三项信息命中名单才可绑定身份、查看对应信息（筛除无关人员）。
 *
 * 能力：分页查询/筛选、新建单个、批量导入（CSV/Excel）、编辑（学校/学号只读）、
 * 启用停用、删除。学校选项与小程序绑定页保持一致。
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Popconfirm,
  Switch,
  Upload,
  App,
  Grid,
  Empty,
  Spin,
} from "antd";
import {
  UploadOutlined,
  PlusOutlined,
  ReloadOutlined,
  DownloadOutlined,
  EditOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { formatDateTime } from "@/utils/datetime";
import ResponsiveTable from "@/components/ResponsiveTable";
import { rosterApi } from "@/api/admin";
import type { RosterStudent } from "@/api/admin";

const { Option } = Select;

export default function UserManagementRoster() {
  const { message, modal } = App.useApp();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [items, setItems] = useState<RosterStudent[]>([]);
  const [loading, setLoading] = useState(false);
  const [schools, setSchools] = useState<string[]>([]);
  const [schoolFilter, setSchoolFilter] = useState("");
  const [keyword, setKeyword] = useState("");

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  const [createVisible, setCreateVisible] = useState(false);
  const [editTarget, setEditTarget] = useState<RosterStudent | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const loadSchools = useCallback(async () => {
    try {
      const res = await rosterApi.getSchools();
      if (res.status === "success") {
        // 与小程序绑定页一致：schools 字段在响应顶层（api_success(schools=...) 走 **extra 路径）
        setSchools(res.schools || []);
      }
    } catch {
      // 学校列表拉取失败不阻塞页面
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await rosterApi.getList({
        school: schoolFilter || undefined,
        keyword: keyword || undefined,
        page,
        page_size: pageSize,
      });
      if (res.status === "success") {
        setItems(res.data || []);
        setTotal(res.total ?? 0);
      }
    } catch {
      message.error("加载学生名单失败");
    } finally {
      setLoading(false);
    }
  }, [schoolFilter, keyword, page, pageSize, message]);

  useEffect(() => {
    loadSchools();
    load();
  }, [load, loadSchools]);

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    try {
      const res = await rosterApi.create({
        school: values.school,
        student_number: values.student_number,
        class_name: values.class_name,
        real_name: values.real_name,
        remark: values.remark,
      });
      if (res.status === "success") {
        message.success("已添加");
        setCreateVisible(false);
        createForm.resetFields();
        if (page === 1) load();
        else setPage(1);
      } else {
        message.error(res.message || "添加失败");
      }
    } catch {
      message.error("添加失败");
    }
  };

  const handleEdit = async () => {
    if (!editTarget) return;
    const values = await editForm.validateFields();
    try {
      const res = await rosterApi.update(editTarget.id, {
        class_name: values.class_name,
        real_name: values.real_name,
        remark: values.remark,
        is_active: values.is_active,
      });
      if (res.status === "success") {
        message.success("已保存");
        setEditTarget(null);
        load();
      } else {
        message.error(res.message || "保存失败");
      }
    } catch {
      message.error("保存失败");
    }
  };

  const handleToggle = async (row: RosterStudent) => {
    try {
      const res = await rosterApi.update(row.id, { is_active: !row.is_active });
      if (res.status === "success") {
        message.success(row.is_active ? "已停用（不可再绑定）" : "已启用");
        load();
      }
    } catch {
      message.error("操作失败");
    }
  };

  const handleDelete = async (row: RosterStudent) => {
    try {
      const res = await rosterApi.remove(row.id);
      if (res.status === "success") {
        message.success("已删除");
        // 当前页删空则回退一页
        if (items.length === 1 && page > 1) setPage(page - 1);
        else load();
      }
    } catch {
      message.error("删除失败");
    }
  };

  /** 批量导入：校验文件类型 → 上传 → 结果弹窗（成功数 + 失败明细） */
  const handleImport = (file: File) => {
    const name = (file.name || "").toLowerCase();
    const ok = name.endsWith(".csv") || name.endsWith(".xlsx");
    if (!ok) {
      message.error("仅支持 .csv / .xlsx 文件");
      return false;
    }
    const doImport = async () => {
      try {
        const res = await rosterApi.import(file);
        if (res.status !== "success") {
          message.error(res.message || "导入失败");
          return;
        }
        const { created, failures } = res.data ?? { created: 0, failures: [] };
        if (failures && failures.length > 0) {
          modal.info({
            title: `导入完成：成功 ${created} 条，失败 ${failures.length} 条`,
            width: 520,
            content: (
              <div style={{ maxHeight: 320, overflow: "auto" }}>
                {failures.map((f) => (
                  <div key={f.row} style={{ padding: "4px 0", fontSize: 13 }}>
                    第 {f.row} 行：{f.reason}
                  </div>
                ))}
              </div>
            ),
          });
        } else {
          message.success(`导入成功 ${created} 条`);
        }
        setPage(1);
        load();
      } catch {
        message.error("导入失败，请检查文件格式");
      }
    };
    doImport();
    return false; // 阻止 antd Upload 自动上传
  };

  const columns = [
    {
      title: "学校",
      dataIndex: "school",
      key: "school",
      ellipsis: true,
    },
    {
      title: "学号",
      dataIndex: "student_number",
      key: "student_number",
      ellipsis: true,
    },
    {
      title: "班级",
      dataIndex: "class_name",
      key: "class_name",
      ellipsis: true,
    },
    {
      title: "姓名",
      dataIndex: "real_name",
      key: "real_name",
      render: (v: string | null) => v || "-",
    },
    {
      title: "备注",
      dataIndex: "remark",
      key: "remark",
      ellipsis: true,
      render: (v: string | null) => v || "-",
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 90,
      render: (v: boolean) =>
        v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (v: string | null) => (v ? formatDateTime(v) : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 200,
      render: (_: unknown, record: RosterStudent) => (
        <Space size={4} wrap>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditTarget(record);
              editForm.setFieldsValue({
                class_name: record.class_name,
                real_name: record.real_name,
                remark: record.remark,
                is_active: record.is_active,
              });
            }}
          >
            编辑
          </Button>
          <Button
            size="small"
            onClick={() => handleToggle(record)}
            danger={record.is_active}
          >
            {record.is_active ? "停用" : "启用"}
          </Button>
          <Popconfirm
            title="确认删除"
            description="删除后该学号将无法再绑定身份，确定删除？"
            onConfirm={() => handleDelete(record)}
            okText="确定"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      variant={isMobile ? "borderless" : undefined}
      styles={{ body: { padding: isMobile ? 0 : 24 } }}
    >
      {/* 操作栏：新建 / 批量导入 / 模板 / 刷新 + 筛选 */}
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
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            createForm.resetFields();
            setCreateVisible(true);
          }}
        >
          新建学生
        </Button>
        <Upload
          accept=".csv,.xlsx"
          showUploadList={false}
          beforeUpload={(file) => handleImport(file)}
        >
          <Button icon={<UploadOutlined />}>批量导入</Button>
        </Upload>
        <Button
          icon={<DownloadOutlined />}
          href="/api/admin/roster/template"
          target="_blank"
        >
          下载模板
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
        <Select
          allowClear
          placeholder="全部学校"
          value={schoolFilter || undefined}
          onChange={(v) => {
            setSchoolFilter(v || "");
            setPage(1);
          }}
          style={isMobile ? { flex: "100%", minWidth: 0 } : { width: 180 }}
        >
          {schools.map((s) => (
            <Option key={s} value={s}>
              {s}
            </Option>
          ))}
        </Select>
        <Input
          allowClear
          placeholder="搜索学号/班级/姓名"
          value={keyword}
          onChange={(e) => {
            setKeyword(e.target.value);
            setPage(1);
          }}
          style={isMobile ? { flex: "100%", minWidth: 0 } : { width: 200 }}
        />
      </div>

      {loading && items.length === 0 ? (
        <div style={{ textAlign: "center", padding: "48px 0" }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="暂无名单记录" style={{ padding: "48px 0" }} />
      ) : (
        <ResponsiveTable
          columns={columns}
          dataSource={items}
          loading={loading}
          rowKey="id"
          scroll={{ x: 900 }}
          locale={{ emptyText: "没有符合条件的名单" }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      )}

      {/* 新建学生 */}
      <Modal
        title="新建学生"
        open={createVisible}
        onCancel={() => setCreateVisible(false)}
        footer={null}
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            label="学校"
            name="school"
            rules={[{ required: true, message: "请选择学校" }]}
          >
            <Select placeholder="请选择学校">
              {schools.map((s) => (
                <Option key={s} value={s}>
                  {s}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            label="学号"
            name="student_number"
            rules={[
              { required: true, message: "请输入学号" },
              { max: 30, message: "学号最长 30 个字符" },
            ]}
          >
            <Input placeholder="请输入学号" />
          </Form.Item>
          <Form.Item
            label="班级"
            name="class_name"
            rules={[{ required: true, message: "请输入班级" }]}
          >
            <Input placeholder="请输入班级，如：计算机2301" />
          </Form.Item>
          <Form.Item label="姓名（选填）" name="real_name">
            <Input placeholder="请输入姓名" />
          </Form.Item>
          <Form.Item label="备注（选填）" name="remark">
            <Input placeholder="备注信息" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                添加
              </Button>
              <Button onClick={() => setCreateVisible(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑名单条目 */}
      <Modal
        title="编辑名单条目"
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        footer={null}
      >
        <Form form={editForm} layout="vertical" onFinish={handleEdit}>
          <Form.Item label="学校">
            <Input value={editTarget?.school} disabled />
          </Form.Item>
          <Form.Item label="学号">
            <Input value={editTarget?.student_number} disabled />
          </Form.Item>
          <Form.Item
            label="班级"
            name="class_name"
            rules={[{ required: true, message: "请输入班级" }]}
          >
            <Input placeholder="请输入班级" />
          </Form.Item>
          <Form.Item label="姓名（选填）" name="real_name">
            <Input placeholder="请输入姓名" />
          </Form.Item>
          <Form.Item label="备注（选填）" name="remark">
            <Input placeholder="备注信息" />
          </Form.Item>
          <Form.Item label="启用状态" name="is_active" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
              <Button onClick={() => setEditTarget(null)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
