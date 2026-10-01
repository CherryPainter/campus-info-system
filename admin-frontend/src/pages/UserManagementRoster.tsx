/**
 * 学生身份管理组件（v6.17：组织树 + 名单 + 一次性绑定码）
 *
 * 组织维度改为树形维护：学校→学院→专业→班级 各建一次，学生名单只挂到
 * 「班级」节点，学校/学院/专业/班级名由树继承（录入无需重复填写），
 * 学校选项同步动态化（小程序绑定页同样取自该树）。
 *
 * 绑定门禁升级：管理端为学生生成一次性绑定码（8 位，绑定成功即作废），
 * 学生凭「学校+学号+码」绑定，杜绝"知道学号就抢先绑定"。
 *
 * 能力：
 * - 组织树：新建学校/学院/专业/班级、重命名、删除（有子/有学生引用拒绝）
 * - 名单：按班级过滤/关键字搜索、新建（级联选班级）、编辑、停用、删除、批量导入
 * - 绑定码：单个生成展示（仅一次）/ 勾选批量生成导出
 * - 绑定状态列：已认领显示用户名与时间
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Card,
  Space,
  Tag,
  Divider,
  Modal,
  Form,
  Input,
  Select,
  Cascader,
  Popconfirm,
  Switch,
  Upload,
  App,
  Grid,
  Empty,
  Spin,
  Tree,
  Typography,
  Tooltip,
} from "antd";
import type { DataNode } from "antd/es/tree";
import {
  UploadOutlined,
  PlusOutlined,
  ReloadOutlined,
  DownloadOutlined,
  EditOutlined,
  DeleteOutlined,
  KeyOutlined,
  ApartmentOutlined,
  DownOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { formatDateTime } from "@/utils/datetime";
import ResponsiveTable from "@/components/ResponsiveTable";
import { rosterApi, orgApi } from "@/api/admin";
import type { OrgUnit, RosterStudent } from "@/api/admin";

const { Text } = Typography;
const { Option } = Select;

const NODE_LABEL: Record<string, string> = {
  school: "学校",
  college: "学院",
  major: "专业",
  class: "班级",
};

/** 各层可新建的下级类型 */
const CHILD_TYPE: Record<string, string> = {
  school: "college",
  college: "major",
  major: "class",
};

/** 级联选项（带 node_type 便于校验末层必须是班级） */
interface CascaderOption {
  value: number;
  label: string;
  node_type: string;
  children?: CascaderOption[];
}

function toCascader(nodes: OrgUnit[]): CascaderOption[] {
  return (nodes || []).map((n) => ({
    value: n.id,
    label: n.name,
    node_type: n.node_type,
    children: n.children?.length ? toCascader(n.children) : undefined,
  }));
}

export default function UserManagementRoster() {
  const { message, modal } = App.useApp();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // ---- 组织树 ----
  const [tree, setTree] = useState<OrgUnit[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedClassId, setSelectedClassId] = useState<number | null>(null);
  // 组织树展开状态（受控）：单一学校时默认展开到「专业」层，增删改不必反复手动展开
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);
  const [orgModal, setOrgModal] = useState<{
    mode: "create" | "rename";
    nodeType?: string; // create 时新建的类型
    parent?: OrgUnit; // create 时上级节点
    target?: OrgUnit; // rename 时目标
  } | null>(null);
  const [orgForm] = Form.useForm();

  // ---- 名单 ----
  const [items, setItems] = useState<RosterStudent[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [selectedRowKeys, setSelectedRowKeys] = useState<number[]>([]);

  // 组织架构面板折叠状态（持久化到 localStorage，避免每次重新进入恢复默认）
  const ORG_PANEL_KEY = "push:roster:org-panel-expanded";
  const [orgPanelExpanded, setOrgPanelExpanded] = useState(() => {
    try {
      return localStorage.getItem(ORG_PANEL_KEY) !== "false";
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(ORG_PANEL_KEY, String(orgPanelExpanded));
    } catch {}
  }, [orgPanelExpanded]);

  const [createVisible, setCreateVisible] = useState(false);
  const [editTarget, setEditTarget] = useState<RosterStudent | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  // ---- 绑定码 ----
  const [codeModal, setCodeModal] = useState<{
    rosterId: number | null;
    code: string | null;
    loading: boolean;
  }>({ rosterId: null, code: null, loading: false });

  const cascaderOptions = useMemo(() => toCascader(tree), [tree]);

  const loadTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const res = await orgApi.tree();
      if (res.status === "success") {
        setTree(res.tree || []);
        // 选中班级被删时清空过滤
        setSelectedClassId((cur) => {
          if (cur === null) return cur;
          return findNode(res.tree || [], cur) ? cur : null;
        });
      }
    } catch {
      message.error("加载组织树失败");
    } finally {
      setTreeLoading(false);
    }
  }, [message]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await rosterApi.getList({
        class_id: selectedClassId || undefined,
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
  }, [selectedClassId, keyword, page, pageSize, message]);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  useEffect(() => {
    load();
  }, [load]);

  // 左栏与右栏等高：实时测量右栏高度作为左栏 maxHeight，
  // 左栏内容超出该高度时内部滚动（右栏翻页/筛选导致高度变化时自动跟随）。
  const rightRef = useRef<HTMLDivElement>(null);
  const [leftMaxHeight, setLeftMaxHeight] = useState<number | undefined>(undefined);
  useEffect(() => {
    const el = rightRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const sync = () => setLeftMaxHeight(el.offsetHeight);
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 只有一个学校时默认展开到「专业」层（展开学校 + 各学院），
  // 班级层不自动展开，避免一次性铺开过长。仅首次加载时自动应用，
  // 之后完全交由用户手动展开/收起（受控）。
  const autoExpandedRef = useRef(false);
  useEffect(() => {
    if (treeLoading || tree.length === 0 || autoExpandedRef.current) return;
    autoExpandedRef.current = true;
    if (tree.length === 1) {
      const keys: React.Key[] = [tree[0].id];
      (tree[0].children || []).forEach((c) => keys.push(c.id));
      setExpandedKeys(keys);
    }
  }, [tree, treeLoading]);

  // ---- 组织树操作 ----
  const handleOrgOk = async () => {
    if (!orgModal) return;
    const values = await orgForm.validateFields();
    try {
      if (orgModal.mode === "create") {
        const res = await orgApi.create({
          node_type: orgModal.nodeType as OrgUnit["node_type"],
          name: values.name,
          parent_id: orgModal.parent?.id ?? null,
        });
        if (res.status === "success") {
          message.success("已创建");
          // 新建后自动展开父节点，保证新节点立即可见（不必再手动展开）
          const parentId = orgModal.parent?.id;
          if (parentId != null) {
            setExpandedKeys((prev) =>
              prev.includes(parentId) ? prev : [...prev, parentId]
            );
          }
          setOrgModal(null);
          orgForm.resetFields();
          loadTree();
        } else {
          message.error(res.message || "创建失败");
        }
      } else if (orgModal.target) {
        const res = await orgApi.rename(orgModal.target.id, values.name);
        if (res.status === "success") {
          message.success("已保存（关联名单组织名已同步刷新）");
          setOrgModal(null);
          orgForm.resetFields();
          loadTree();
          load();
        } else {
          message.error(res.message || "保存失败");
        }
      }
    } catch {
      message.error("操作失败");
    }
  };

  const handleOrgDelete = async (node: OrgUnit) => {
    try {
      const res = await orgApi.remove(node.id);
      if (res.status === "success") {
        message.success("已删除");
        loadTree();
      } else {
        message.error(res.message || "删除失败");
      }
    } catch {
      message.error("删除失败");
    }
  };

  // 组织树节点渲染：名称 + 操作（+ 建下级 / 重命名 / 删除）
  const renderTreeTitle = (node: OrgUnit) => {
    const childType = CHILD_TYPE[node.node_type];
    return (
      <Space size={2} style={{ flexWrap: "nowrap" }}>
        <Text style={{ fontSize: 13 }}>{node.name}</Text>
        {childType && (
          <Tooltip title={`新建${NODE_LABEL[childType]}`}>
            <Button
              type="text"
              size="small"
              icon={<PlusOutlined />}
              style={{ height: 20, width: 20, minWidth: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                setOrgModal({
                  mode: "create",
                  nodeType: childType,
                  parent: node,
                });
                orgForm.resetFields();
              }}
            />
          </Tooltip>
        )}
        <Tooltip title="重命名">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            style={{ height: 20, width: 20, minWidth: 0 }}
            onClick={(e) => {
              e.stopPropagation();
              setOrgModal({ mode: "rename", target: node });
              orgForm.setFieldsValue({ name: node.name });
            }}
          />
        </Tooltip>
        <Popconfirm
          title={`删除${NODE_LABEL[node.node_type]}「${node.name}」`}
          description="需先删除其下子节点/学生；删除后不可恢复"
          okText="确定"
          cancelText="取消"
          onConfirm={(e) => {
            e?.stopPropagation();
            handleOrgDelete(node);
          }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            style={{ height: 20, width: 20, minWidth: 0 }}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>
      </Space>
    );
  };

  const treeData: DataNode[] = (tree || []).map((n) => ({
    key: n.id,
    title: renderTreeTitle(n),
    children: (n.children || []).map((c) => ({
      key: c.id,
      title: renderTreeTitle(c),
      children: (c.children || []).map((g) => ({
        key: g.id,
        title: renderTreeTitle(g),
        children: (g.children || []).map((k) => ({
          key: k.id,
          title: renderTreeTitle(k),
        })),
      })),
    })),
  }));

  // 选中班级 → 过滤名单；选中非班级节点不参与过滤（展示全校）
  const handleTreeSelect = (keys: React.Key[]) => {
    const id = keys[0] ? Number(keys[0]) : null;
    const node = findNode(tree, id);
    setSelectedClassId(node && node.node_type === "class" ? id : null);
    setPage(1);
  };

  // ---- 学生操作 ----
  const handleCreate = async () => {
    const values = await createForm.validateFields();
    const path = (values.class_path || []) as number[];
    const classId = path[path.length - 1];
    const clsNode = findNode(tree, classId);
    if (!clsNode || clsNode.node_type !== "class") {
      message.error("请选择到具体的班级");
      return;
    }
    try {
      const res = await rosterApi.create({
        class_id: classId,
        student_number: values.student_number,
        real_name: values.real_name,
        dorm: values.dorm,
        remark: values.remark,
      });
      if (res.status === "success") {
        message.success("已添加（请为该生生成绑定码后发放）");
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
    const path = (values.class_path || []) as number[];
    let classId: number | null = null;
    if (path.length) {
      const clsNode = findNode(tree, path[path.length - 1]);
      if (!clsNode || clsNode.node_type !== "class") {
        message.error("请选择到具体的班级");
        return;
      }
      classId = clsNode.id;
    }
    try {
      const res = await rosterApi.update(editTarget.id, {
        class_id: classId ?? undefined,
        real_name: values.real_name,
        dorm: values.dorm,
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
        if (items.length === 1 && page > 1) setPage(page - 1);
        else load();
      }
    } catch {
      message.error("删除失败");
    }
  };

  // ---- 解绑/收回身份 ----
  const handleUnbind = async (row: RosterStudent) => {
    try {
      const res = await rosterApi.unbind(row.id);
      if (res.status === "success") {
        message.success("已收回身份，学生可重新绑定");
        // 复用绑定码弹窗展示新码，方便管理员立即私下发放
        setCodeModal({ rosterId: row.id, code: res.data?.code || "", loading: false });
        load(); // 刷新绑定状态（bound_user_id 置空、has_bind_code 置真）
      } else {
        message.error(res.message || "解绑失败");
      }
    } catch {
      message.error("解绑失败");
    }
  };

  // ---- 绑定码 ----
  const handleGenerateCode = async (row: RosterStudent) => {
    setCodeModal({ rosterId: row.id, code: null, loading: true });
    try {
      const res = await rosterApi.generateBindCode(row.id);
      if (res.status === "success") {
        setCodeModal({ rosterId: row.id, code: res.data?.code || "", loading: false });
        load(); // 刷新 has_bind_code
      } else {
        setCodeModal({ rosterId: null, code: null, loading: false });
        message.error(res.message || "生成失败");
      }
    } catch {
      setCodeModal({ rosterId: null, code: null, loading: false });
      message.error("生成失败");
    }
  };

  const handleBatchCodes = async () => {
    if (!selectedRowKeys.length) return;
    try {
      const res = await rosterApi.generateBindCodes(selectedRowKeys);
      if (res.status === "success") {
        const codes = res.data?.codes || [];
        if (!codes.length) {
          message.error("未生成任何绑定码");
          return;
        }
        // CSV 导出（学号,姓名,绑定码），用浏览器 Blob + URL 触发下载
        const exportCodesCsv = () => {
          const lines = ["学号,姓名,绑定码"];
          codes.forEach((c) => {
            const name = (c.real_name || "").replace(/,/g, " ");
            lines.push(`${c.student_number || ""},${name},${c.code || ""}`);
          });
          const blob = new Blob(["\uFEFF" + lines.join("\n")], {
            type: "text/csv;charset=utf-8",
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `绑定码_${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "")}.csv`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        };
        modal.info({
          title: `已生成 ${codes.length} 个绑定码（仅本次可见）`,
          width: 560,
          content: (
            <div style={{ maxHeight: 360, overflow: "auto" }}>
              {codes.map((c) => (
                <div
                  key={c.roster_id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "6px 0",
                    borderBottom: "1px solid rgba(128,128,128,0.15)",
                    fontSize: 13,
                  }}
                >
                  <span>
                    {c.student_number}
                    {c.real_name ? `（${c.real_name}）` : ""}
                  </span>
                  <Text strong style={{ fontFamily: "monospace", letterSpacing: 1 }}>
                    {c.code}
                  </Text>
                </div>
              ))}
              <div style={{ paddingTop: 8, color: "#888" }}>
                请复制后私下发放给对应学生；绑定成功即失效，再次生成将作废旧码
              </div>
              <div style={{ paddingTop: 12 }}>
                <Button
                  size="small"
                  type="primary"
                  icon={<DownloadOutlined />}
                  onClick={exportCodesCsv}
                >
                  导出 CSV
                </Button>
              </div>
            </div>
          ),
        });
        setSelectedRowKeys([]);
        load();
      } else {
        message.error(res.message || "生成失败");
      }
    } catch {
      message.error("生成失败");
    }
  };

  const copyCode = async () => {
    if (!codeModal.code) return;
    try {
      await navigator.clipboard.writeText(codeModal.code);
      message.success("已复制，请私下发放给学生");
    } catch {
      message.error("复制失败，请手动复制");
      return;
    }
    // 复制成功后关闭弹窗（按钮文案"复制并关闭"承诺的语义）
    setCodeModal({ rosterId: null, code: null, loading: false });
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

  /** 导出名单 CSV（按当前筛选 school/class_id/keyword 全量导出不分页） */
  const handleExport = async () => {
    try {
      const blob = (await rosterApi.exportStudents({
        class_id: selectedClassId ?? undefined,
        keyword: keyword || undefined,
      })) as unknown as Blob;
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `学生名单_${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "")}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      message.success("已导出当前筛选下的全部名单");
    } catch {
      message.error("导出失败，请稍后重试");
    }
  };

  const columns = [
    {
      title: "学号",
      dataIndex: "student_number",
      key: "student_number",
      ellipsis: true,
      fixed: "left" as const,
      width: 130,
    },
    {
      title: "姓名",
      dataIndex: "real_name",
      key: "real_name",
      width: 100,
      render: (v: string | null) => v || "-",
    },
    {
      title: "宿舍",
      dataIndex: "dorm",
      key: "dorm",
      width: 110,
      ellipsis: true,
      render: (v: string | null) => v || "-",
    },
    {
      title: "学校",
      dataIndex: "school",
      key: "school",
      ellipsis: true,
      width: 150,
    },
    {
      title: "学院",
      dataIndex: "college",
      key: "college",
      ellipsis: true,
      render: (v: string | null) => v || "-",
    },
    {
      title: "专业",
      dataIndex: "major",
      key: "major",
      ellipsis: true,
      render: (v: string | null) => v || "-",
    },
    {
      title: "班级",
      dataIndex: "class_name",
      key: "class_name",
      ellipsis: true,
      width: 120,
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
      width: 80,
      render: (v: boolean) =>
        v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: "绑定状态",
      key: "binding",
      width: 180,
      ellipsis: true,
      render: (_: unknown, record: RosterStudent) =>
        record.bound_username ? (
          <Tag color="blue" title={record.bound_at ? `绑定于 ${record.bound_at}` : undefined}>
            已认领：{record.bound_username}
          </Tag>
        ) : record.has_bind_code ? (
          <Tag color="orange">已发码未绑定</Tag>
        ) : (
          <Tag color="default">未绑定</Tag>
        ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 150,
      render: (v: string | null) => (v ? formatDateTime(v) : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 230,
      fixed: "right" as const,
      render: (_: unknown, record: RosterStudent) => (
        <Space size={4} wrap>
          <Button
            size="small"
            icon={<KeyOutlined />}
            onClick={() => handleGenerateCode(record)}
            disabled={!!record.bound_username}
            title={record.bound_username ? "已绑定无需再发码" : undefined}
          >
            {record.has_bind_code ? "重新发码" : "生成码"}
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditTarget(record);
              editForm.setFieldsValue({
                real_name: record.real_name,
                dorm: record.dorm,
                remark: record.remark,
                is_active: record.is_active,
              });
              // 班级级联默认值：按学校/学院/专业/班级 名称路径回填
              const path = findClassPath(tree, record);
              editForm.setFieldsValue({ class_path: path });
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
          {record.bound_user_id ? (
            <Popconfirm
              title="收回身份"
              description="将清空该学生已绑定的身份并强制其重新登录，名单保留且自动重发绑定码。确定？"
              onConfirm={() => handleUnbind(record)}
              okText="确定"
              cancelText="取消"
            >
              <Button size="small">解绑</Button>
            </Popconfirm>
          ) : null}
          <Popconfirm
            title="确认删除"
            description="删除名单后，已绑定该身份的学生仍将保留原身份且无法自行解绑；若要让学生重新绑定，请改用「解绑」。确定删除名单？"
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

  /** 按名单的学校/学院/专业/班级名在树上定位 id 路径（编辑回填用） */
  const findClassPath = (nodes: OrgUnit[], row: RosterStudent): number[] => {
    for (const school of nodes || []) {
      if (school.name !== row.school) continue;
      for (const college of school.children || []) {
        if (college.name !== row.college) continue;
        for (const major of college.children || []) {
          if (major.name !== row.major) continue;
          for (const cls of major.children || []) {
            if (cls.name === row.class_name) {
              return [school.id, college.id, major.id, cls.id];
            }
          }
        }
      }
    }
    return [];
  };

  const classFilterTag = (() => {
    const node = selectedClassId ? findNode(tree, selectedClassId) : undefined;
    return node ? (
      <Tag icon={<ApartmentOutlined />} color="blue" closable onClose={() => setSelectedClassId(null)}>
        {node.name}
      </Tag>
    ) : null;
  })();

  return (
    <Card
      variant={isMobile ? "borderless" : undefined}
      styles={{ body: { padding: isMobile ? 0 : 24 } }}
    >
      <div
        style={{
          display: "flex",
          gap: 16,
          // 桌面端并排等高；移动端纵向堆叠（否则左栏 width:100% 会把右栏挤没）
          flexDirection: isMobile ? "column" : "row",
          alignItems: "stretch",
        }}
      >
        {orgPanelExpanded && (
          <>
            {/* 左：组织树 */}
            <Card
          size="small"
          title={
            // 标题不再作为折叠触发；折叠入口只下放到右侧箭头（旋转动画）
            <Tooltip title="组织架构：学校 → 学院 → 专业 → 班级">
              <Space size={6}>
                <ApartmentOutlined />
                组织架构
                <Tooltip title={orgPanelExpanded ? "收起组织架构" : "展开组织架构"}>
                  <span
                    onClick={() => setOrgPanelExpanded((v) => !v)}
                    style={{
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      padding: "0 4px",
                      borderRadius: 2,
                      transition: "transform 0.25s ease",
                      // 仅旋转作为折叠状态的可见反馈（面板整体仍按上次决定的"整个收起"）
                      transform: orgPanelExpanded ? "rotate(0deg)" : "rotate(180deg)",
                    }}
                  >
                    <DownOutlined style={{ fontSize: 12, color: "rgba(128,128,128,0.9)" }} />
                  </span>
                </Tooltip>
              </Space>
            </Tooltip>
          }
          extra={
            <Button
              type="link"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => {
                setOrgModal({ mode: "create", nodeType: "school" });
                orgForm.resetFields();
              }}
            >
              新建学校
            </Button>
          }
          style={{
            width: isMobile ? "100%" : 300,
            flexShrink: 0,
            // 与右栏等高：stretch 拉伸 + 以右栏实测高度封顶（溢出则内部滚动）
            display: "flex",
            flexDirection: "column",
            maxHeight: isMobile ? undefined : leftMaxHeight,
          }}
          styles={{ body: { padding: 8, flex: 1, minHeight: 0, overflow: "auto" } }}
        >
          {treeLoading ? (
            <div style={{ textAlign: "center", padding: 24 }}>
              <Spin />
            </div>
          ) : treeData.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有任何组织"
              style={{ padding: "8px 0 4px" }}
            >
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                onClick={() => {
                  setOrgModal({ mode: "create", nodeType: "school" });
                  orgForm.resetFields();
                }}
              >
                新建学校
              </Button>
            </Empty>
          ) : (
            <Tree
              treeData={treeData}
              expandedKeys={expandedKeys}
              onExpand={(keys) => setExpandedKeys(keys)}
              showLine
              blockNode
              selectedKeys={selectedClassId ? [selectedClassId] : []}
              onSelect={handleTreeSelect}
            />
          )}
        </Card>

        {/* 左右分栏：非移动端显示竖向分隔线（移动端为上下堆叠，靠 gap 分隔） */}
        {!isMobile && (
          <Divider
            type="vertical"
            style={{
              height: "auto",
              alignSelf: "stretch",
              margin: "0 4px",
              borderColor: "rgba(0,0,0,0.06)",
            }}
          />
        )}
          </>
        )}

        {/* 右：名单 */}
        <div ref={rightRef} style={{ flex: 1, minWidth: 0 }}>
          {/* 操作栏 */}
          <div
            style={{
              display: "flex",
              gap: 8,
              flexWrap: "wrap",
              alignItems: "center",
              marginBottom: 16,
            }}
          >
            <Tooltip title={orgPanelExpanded ? "折叠组织架构" : "展开组织架构"}>
              <Button
                type="text"
                icon={orgPanelExpanded ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
                onClick={() => setOrgPanelExpanded((v) => !v)}
              />
            </Tooltip>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                createForm.resetFields();
                // 左侧选中班级时预填
                if (selectedClassId) {
                  const path = classPathOfId(tree, selectedClassId);
                  createForm.setFieldsValue({ class_path: path });
                }
                setCreateVisible(true);
              }}
            >
              添加学生
            </Button>
            <Button
              icon={<KeyOutlined />}
              onClick={handleBatchCodes}
              disabled={!selectedRowKeys.length}
              title="为勾选学生批量生成一次性绑定码"
            >
              批量生成码（{selectedRowKeys.length}）
            </Button>
            <Upload
              accept=".csv,.xlsx"
              showUploadList={false}
              beforeUpload={(file) => handleImport(file)}
            >
              <Button icon={<UploadOutlined />}>批量导入</Button>
            </Upload>
            <Button icon={<DownloadOutlined />} onClick={handleExport}>
              导出名单
            </Button>
            <Button icon={<DownloadOutlined />} href="/api/admin/roster/template" target="_blank">
              下载模板
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Input
              allowClear
              placeholder="搜索学号/姓名"
              value={keyword}
              onChange={(e) => {
                setKeyword(e.target.value);
                setPage(1);
              }}
              style={isMobile ? { flex: "100%", minWidth: 0 } : { width: 180 }}
            />
            {classFilterTag}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 12,
              color: tree.length === 0 ? "#d46b08" : "rgba(128,128,128,0.9)",
              fontSize: 12,
            }}
          >
            {tree.length === 0 ? (
              <span>
                {orgPanelExpanded
                  ? "请先在「组织架构」中点击「新建学校」，逐级创建 学院 → 专业 → 班级 后，再来添加学生名单。"
                  : "请先点击工具栏最左侧的「展开组织架构」按钮，然后新建学校并逐级创建 学院 → 专业 → 班级。"}
              </span>
            ) : (
              <span>
                在组织架构中选中班级可只看该班学生；添加学生时选好班级，学校 / 学院 / 专业由组织树自动继承，无需填写。
              </span>
            )}
          </div>

          {loading && items.length === 0 ? (
            <div style={{ textAlign: "center", padding: "48px 0" }}>
              <Spin />
            </div>
          ) : items.length === 0 ? (
            <Empty
              description={
                tree.length === 0
                  ? "尚未创建组织，暂无法添加学生"
                  : selectedClassId
                  ? "该班级暂无学生名单"
                  : "暂无学生名单记录"
              }
              style={{ padding: "48px 0" }}
            />
          ) : (
            <ResponsiveTable
              columns={columns}
              dataSource={items}
              loading={loading}
              rowKey="id"
              scroll={{ x: 1300 }}
              rowSelection={{
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys as number[]),
                getCheckboxProps: (r: RosterStudent) => ({
                  disabled: !!r.bound_username, // 已绑定无需发码
                }),
              }}
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
        </div>
      </div>

      {/* 新建学校/学院/专业/班级 / 重命名 */}
      <Modal
        title={
          orgModal?.mode === "create"
            ? `新建${NODE_LABEL[orgModal.nodeType || "school"]}${
                orgModal.parent ? `（位于「${orgModal.parent.name}」下）` : ""
              }`
            : "重命名"
        }
        open={!!orgModal}
        onCancel={() => setOrgModal(null)}
        footer={null}
      >
        <Form form={orgForm} layout="vertical" onFinish={handleOrgOk}>
          <Form.Item
            label="名称"
            name="name"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="请输入名称" maxLength={100} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {orgModal?.mode === "create" ? "创建" : "保存"}
              </Button>
              <Button onClick={() => setOrgModal(null)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建学生 */}
      <Modal
        title="添加学生"
        open={createVisible}
        onCancel={() => setCreateVisible(false)}
        footer={null}
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            label="班级"
            name="class_path"
            rules={[{ required: true, message: "请选择班级（学校→学院→专业→班级）" }]}
          >
            <Cascader
              options={cascaderOptions}
              placeholder="请选择学校 → 学院 → 专业 → 班级"
              showSearch
              expandTrigger="hover"
            />
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
          <Form.Item label="姓名（选填）" name="real_name">
            <Input placeholder="请输入姓名" />
          </Form.Item>
          <Form.Item label="宿舍（选填）" name="dorm">
            <Input placeholder="如 A栋305，同宿舍学生将自动编组用于电量推送" />
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
          <Form.Item label="学号">
            <Input value={editTarget?.student_number} disabled />
          </Form.Item>
          <Form.Item label="班级（可换班）" name="class_path">
            <Cascader
              options={cascaderOptions}
              placeholder="选择学校 → 学院 → 专业 → 班级"
              showSearch
              expandTrigger="hover"
              allowClear
            />
          </Form.Item>
          <Form.Item label="姓名（选填）" name="real_name">
            <Input placeholder="请输入姓名" />
          </Form.Item>
          <Form.Item label="宿舍（选填）" name="dorm">
            <Input placeholder="如 A栋305，同宿舍学生将自动编组用于电量推送" />
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

      {/* 单个绑定码展示（仅一次） */}
      <Modal
        title={`绑定码 · ${(() => {
          const row = items.find((i) => i.id === codeModal.rosterId);
          return row ? `${row.student_number}${row.real_name ? `（${row.real_name}）` : ""}` : "";
        })()}`}
        open={codeModal.rosterId !== null}
        onCancel={() => setCodeModal({ rosterId: null, code: null, loading: false })}
        footer={
          codeModal.code
            ? [
                <Button key="copy" type="primary" icon={<KeyOutlined />} onClick={copyCode}>
                  复制并关闭
                </Button>,
              ]
            : null
        }
      >
        {codeModal.loading ? (
          <div style={{ textAlign: "center", padding: 24 }}>
            <Spin />
          </div>
        ) : codeModal.code ? (
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <div style={{ fontSize: 32, letterSpacing: 6, fontFamily: "monospace" }}>
              {codeModal.code}
            </div>
            <Text type="secondary" style={{ display: "block", marginTop: 12 }}>
              仅本次可见，请立即复制并私下发放给学生本人；
              <br />
              绑定成功即失效，重新生成将作废旧码
            </Text>
          </div>
        ) : null}
      </Modal>
    </Card>
  );
}

/** 按 id 找组织节点 */
function findNode(nodes: OrgUnit[], id: number | null): OrgUnit | undefined {
  if (!id) return undefined;
  for (const n of nodes || []) {
    if (n.id === id) return n;
    const hit = findNode(n.children || [], id);
    if (hit) return hit;
  }
  return undefined;
}

/** 由班级节点 id 反查 [school,college,major,class] 的 id 路径（预填表单用） */
function classPathOfId(nodes: OrgUnit[], classId: number): number[] {
  for (const school of nodes || []) {
    for (const college of school.children || []) {
      for (const major of college.children || []) {
        for (const cls of major.children || []) {
          if (cls.id === classId) return [school.id, college.id, major.id, cls.id];
        }
      }
    }
  }
  return [];
}
