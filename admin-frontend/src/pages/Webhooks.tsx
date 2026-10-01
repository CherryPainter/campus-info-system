/**
 * Webhook 管理页面
 *
 * 设计要点（2026-09-30）：
 * - 列表用 antd Table：名称 / URL / 模块 / 接收范围 / 来源 / 状态 / 测试 / 创建时间 / 操作。
 * - 新增 / 编辑用右侧 Drawer（底部固定 取消 / 保存）。
 * - 接收范围(scope) 候选项来自「用户与权限」体系：学生来自学生名单(rosterApi)，
 *   宿舍来自学生宿舍枚举 adminApi.getDorms()，与该页同源。
 * - scope 语义：「这份数据给谁」，与 webhook 地址（发到哪个群）正交。
 * - 课表/天气/系统是全站同一份内容，没有逐人维度 —— 全局是它们的**默认行为**，
 *   无需也不需要给用户选，因此选了这些模块时**不渲染**接收范围。
 * - 电量含各人隐私数据（每宿舍独立电表、各学生自配 Cookie 采集），把多人数据
 *   汇成一条发进同一个群即为隐私泄露，故**只允许「指定宿舍 / 指定学生」，不提供「全局」**。
 * - 学生目标下拉改为**服务端关键字搜索**（防抖 300ms）：/admin/roster/students 的
 *   page_size 硬上限 100，千人名单既会被静默截断、又卡顿，不能整表拉进下拉。
 * - 列表「接收范围」列展示的学生姓名由后端随列表返回（scope_target_names）。
 */
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  Card,
  Button,
  Space,
  Tag,
  Table,
  Drawer,
  Form,
  Input,
  Select,
  Switch,
  Popconfirm,
  Tooltip,
  Badge,
  Alert,
  Grid,
  Divider,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SendOutlined,
  WarningOutlined,
  HomeOutlined,
  TeamOutlined,
  GlobalOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { webhookApi, rosterApi, adminApi } from "@/api/admin";
import type { Webhook } from "@/api/admin";
import dayjs from "dayjs";
import { WEBHOOK_TEST_STATUS_MAP } from "@/constants/statusMaps";
import { useMessage, showApiError } from "@/utils/message";

const { TextArea } = Input;

const MODULE_MAP: Record<string, { label: string; color: string }> = {
  all: { label: "全局", color: "gold" },
  course: { label: "课表", color: "blue" },
  weather: { label: "天气", color: "cyan" },
  electricity: { label: "电量", color: "orange" },
  system: { label: "系统", color: "red" },
};

/** 接收范围展示配置 */
const SCOPE_MAP: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  global: { label: "全局", color: "gold", icon: <GlobalOutlined /> },
  student: { label: "指定学生", color: "green", icon: <TeamOutlined /> },
  dorm: { label: "指定宿舍", color: "blue", icon: <HomeOutlined /> },
};

/**
 * 模块与「接收范围」的关系
 *
 * 投递层（app/services/webhook_push_service.py）：
 * - `send_module_report`：按 webhook 的 scope 过滤聚合电量等「逐人维度」报告；
 * - `fanout_broadcast_webhooks`：把课表 / 天气的广播副本补发给 scope=student / dorm 的
 *   定向 webhook（delivery_service 仅对 course/weather 调用）。
 *
 * 因此**除系统告警（system）外**，所有模块都允许管理员指定接收范围（指定学生 / 宿舍）；
 * system 刻意不开放定向（delivery_service 不补发，订阅 system 的 webhook 一律走 adapter
 * 全局广播），配置了也是无效配置，故管理端不给受众选项。
 *
 * 唯一「强制必须指定受众」的是电量 / 全部：含逐人隐私数据，绝不允许汇总进一个群。
 */
const MODULE_SCOPE_KIND: Record<string, "filter" | "broadcast"> = {
  course: "broadcast",
  weather: "broadcast",
  electricity: "filter",
  system: "broadcast",
};

/** 所选模块中除 system 外是否允许配置接收范围（决定「接收范围」区块是否出现） */
function hasFilterableModule(mods?: string[] | null): boolean {
  return (mods || []).some((m) => m !== "system");
}

/** 是否**强制**必须指定受众：含电量（或「全部」），含逐人隐私数据，绝不允许全局。 */
function requiresAudience(mods?: string[] | null): boolean {
  return (mods || []).some((m) => m === "all" || m === "electricity");
}

/**
 * 拆分宿舍字符串，**仅供下拉分组展示**
 *
 * 真实数据形态（见 `admin_roster_routes.py` 导入模板与测试用例）：
 *   `31栋512` → 楼栋 `31栋`、房号 `512`（首位 5 = 楼层）
 *   `A栋305`  → 楼栋 `A栋`、房号 `305`（首位 3 = 楼层）
 *
 * 关键约束：**只用于展示分组，绝不参与写库** —— 下拉叶子项与提交值始终是
 * `student_rosters.dorm` 的原始字符串。解析不出来就归到「未识别格式」组，
 * 保证脏数据也能被选中，不会因为正则不匹配而丢选项或改写值。
 */
function parseDorm(dorm: string): { building: string; floor: string; roomNo: string } {
  const s = (dorm || "").trim();
  const m = s.match(/^(.*?栋)(\d+)(.*)$/);
  if (!m) return { building: "未识别格式", floor: "", roomNo: s };
  return {
    building: m[1],
    floor: m[2].charAt(0),
    // 房号保留完整数字（含楼层位），如 `512` / `305` —— 用户要求选项里带上楼层
    roomNo: `${m[2]}${m[3] || ""}`.trim(),
  };
}

export default function Webhooks() {
  const message = useMessage();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);

  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [editingWebhook, setEditingWebhook] = useState<Webhook | null>(null);
  const [form] = Form.useForm();

  // 范围受众可选项：
  // - 宿舍：一次拉全（宿舍量级远小于人数），再按「楼栋 · 楼层」分组展示。
  // - 学生：改为**服务端关键字搜索**，不预拉全量名单 —— /admin/roster/students 的
  //   page_size 上限是 100，千人名单会被静默截断、下拉还卡（旧实现 page_size:1000 即此坑）。
  const [studentOptions, setStudentOptions] = useState<{ value: number; label: string }[]>([]);
  const [dorms, setDorms] = useState<string[]>([]);
  const [dormLoading, setDormLoading] = useState(false);
  const [studentSearching, setStudentSearching] = useState(false);
  // 已选学生的 id->姓名 缓存：搜索结果会被替换，靠它保证已选标签始终显示姓名而非 #id
  const [pickedStudents, setPickedStudents] = useState<Record<number, string>>({});
  const searchTimer = useRef<number | null>(null);

  /** 宿舍下拉：按「楼栋 · 楼层」分组，组内列出完整房号（叶子 value 仍是原始宿舍字符串） */
  const dormOptionGroups = useMemo(() => {
    const groups = new Map<
      string,
      { value: string; label: string; title: string; searchKey: string }[]
    >();
    dorms.forEach((dorm) => {
      const { building, floor, roomNo } = parseDorm(dorm);
      const groupKey = floor ? `${building} · ${floor}层` : building;
      if (!groups.has(groupKey)) groups.set(groupKey, []);
      groups.get(groupKey)!.push({
        value: dorm,
        // 选项显示完整房号（含楼层位，如 512），组标题再给楼栋 + 楼层便于定位
        label: roomNo,
        // 鼠标悬停 / 无障碍朗读给出全称
        title: dorm,
        // 搜「31栋 / 5层 / 512 / 12」都能命中
        searchKey: `${dorm} ${building} ${floor ? `${floor}层` : ""} ${
          roomNo && floor ? roomNo.slice(1) : ""
        }`,
      });
    });
    const collator = new Intl.Collator("zh-Hans-CN", { numeric: true });
    return Array.from(groups.entries())
      .sort((a, b) => collator.compare(a[0], b[0]))
      .map(([label, options]) => ({
        label,
        options: options.sort((a, b) => collator.compare(a.label, b.label)),
      }));
  }, [dorms]);

  // ---- 范围随模块联动 ----
  const watchedModules = Form.useWatch<string[]>("modules", form);
  const watchedScope = Form.useWatch<string>("scope", form);

  // useWatch 在表单挂载前为 undefined，回落到当前编辑对象，避免打开抽屉时闪一下错误选项
  const effectiveModules = watchedModules ?? editingWebhook?.module_list ?? ["course"];
  const scopeValue = watchedScope ?? editingWebhook?.scope ?? "global";
  // 只有勾了电量（或「全部」）才需要配置受众
  const scopeFilterable = hasFilterableModule(effectiveModules);

  /** 学生下拉 options = 搜索结果 + 已选（保证标签不丢） */
  const studentSelectOptions = useMemo(() => {
    const merged = new Map<number, { value: number; label: string }>();
    studentOptions.forEach((o) => merged.set(o.value, o));
    Object.entries(pickedStudents).forEach(([id, label]) =>
      merged.set(Number(id), { value: Number(id), label })
    );
    return Array.from(merged.values());
  }, [studentOptions, pickedStudents]);

  const fetchWebhooks = useCallback(
    async (p: number, ps: number) => {
      setLoading(true);
      try {
        const res = await webhookApi.getList({ page: p, page_size: ps });
        if (res.status === "success") {
          setWebhooks(((res.data as Webhook[]) || []).slice());
          setTotal((res as any).total ?? 0);
        }
      } catch (error) {
        message.error(showApiError(error, "加载 webhook 列表失败"));
      } finally {
        setLoading(false);
      }
    },
    [message]
  );

  /** 加载宿舍枚举（一次拉全；宿舍量级远小于人数） */
  useEffect(() => {
    let alive = true;
    (async () => {
      setDormLoading(true);
      try {
        const res = await adminApi.getDorms();
        const list = ((res as any)?.data as { dorms?: string[] } | undefined)?.dorms || [];
        if (alive) setDorms(list);
      } catch (error) {
        // 静默失败：下拉留空，不影响主列表
      } finally {
        if (alive) setDormLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  /** 学生搜索（服务端按关键字查，仅已绑定账号的可作为定向目标） */
  const runStudentSearch = useCallback(async (keyword: string) => {
    setStudentSearching(true);
    try {
      const res = await rosterApi.getList({
        keyword: keyword || undefined,
        page: 1,
        page_size: 50,
      });
      if (res.status === "success" && res.data) {
        setStudentOptions(
          (res.data as any[])
            .filter((s) => s.bound_user_id)
            .map((s) => ({
              value: s.bound_user_id as number,
              label: `${s.real_name || s.student_number}${
                s.class_name ? `（${s.class_name}）` : ""
              }`,
            }))
        );
      }
    } catch (error) {
      // 静默失败：下拉留空
    } finally {
      setStudentSearching(false);
    }
  }, []);

  /** 输入防抖 300ms，避免逐字打请求 */
  const handleStudentSearch = useCallback(
    (keyword: string) => {
      if (searchTimer.current) window.clearTimeout(searchTimer.current);
      searchTimer.current = window.setTimeout(() => runStudentSearch(keyword), 300);
    },
    [runStudentSearch]
  );

  useEffect(() => {
    fetchWebhooks(page, pageSize);
  }, [page, pageSize, fetchWebhooks]);

  // 抽屉打开时：编辑 -> 回填；新增 -> 重置为默认值（避免带出上一条数据）
  useEffect(() => {
    if (!isDrawerOpen) return;
    if (editingWebhook) {
      const mods = editingWebhook.module_list || [];
      const filterable = hasFilterableModule(mods);
      const audienceRequired = requiresAudience(mods);
      // 不开放范围（system）：一律 global。
      // 开放范围：尊重原记录的 scope（student / dorm / 历史 global）；
      // 电量类（强制受众）的历史遗留 global 收敛为「指定宿舍」。
      let nextScope: string;
      if (!filterable) nextScope = "global";
      else if (editingWebhook.scope === "student") nextScope = "student";
      else if (editingWebhook.scope === "dorm") nextScope = "dorm";
      else nextScope = audienceRequired ? "dorm" : "global";
      form.setFieldsValue({
        name: editingWebhook.name,
        url: editingWebhook.url,
        modules: mods,
        scope: nextScope,
        scope_target: filterable ? editingWebhook.scope_target || [] : [],
        is_enabled: editingWebhook.is_enabled,
        description: editingWebhook.description,
      });
      // 已选学生姓名由后端随列表返回（scope_target_names），保证编辑时标签显示姓名而非 #id
      if (filterable && nextScope === "student" && editingWebhook.scope_target) {
        const names = editingWebhook.scope_target_names || [];
        const seed: Record<number, string> = {};
        (editingWebhook.scope_target as (number | string)[]).forEach((v, i) => {
          const id = Number(v);
          if (!Number.isNaN(id)) seed[id] = names[i] || `用户${id}`;
        });
        setPickedStudents(seed);
      } else {
        setPickedStudents({});
      }
    } else {
      form.resetFields();
      setPickedStudents({});
    }
  }, [isDrawerOpen, editingWebhook, form]);

  /** 表单联动：模块决定是否要配受众；切换受众类型时清空上一类的目标 */
  const handleFormValuesChange = (changed: Record<string, any>) => {
    // 切受众类型（宿舍是字符串、学生是 user_id，混用会写错库）
    if ("scope" in changed) {
      form.setFieldsValue({ scope_target: [] });
      setStudentOptions([]);
      setPickedStudents({});
      return;
    }
    if ("modules" in changed) {
      if (hasFilterableModule(changed.modules)) {
        if (requiresAudience(changed.modules)) {
          // 含电量：强制受众，默认「指定宿舍」，不允许 global
          if (!["student", "dorm"].includes(form.getFieldValue("scope"))) {
            form.setFieldsValue({ scope: "dorm", scope_target: [] });
          }
        } else {
          // 课表 / 天气：允许全局广播，默认 global（不强制定向）
          if (!["global", "student", "dorm"].includes(form.getFieldValue("scope"))) {
            form.setFieldsValue({ scope: "global", scope_target: [] });
          }
        }
      } else {
        form.setFieldsValue({ scope: "global", scope_target: [] });
        setPickedStudents({});
      }
    }
    // 记住已选学生姓名（搜索结果会被替换，标签不能丢）
    if ("scope_target" in changed && form.getFieldValue("scope") === "student") {
      const values: (number | string)[] = Array.isArray(changed.scope_target)
        ? changed.scope_target
        : [];
      setPickedStudents((prev) => {
        const next = { ...prev };
        values.forEach((v) => {
          const id = Number(v);
          if (Number.isNaN(id)) return;
          const hit = studentOptions.find((o) => o.value === id);
          if (hit) next[id] = hit.label;
          else if (!next[id]) next[id] = `用户${id}`;
        });
        return next;
      });
    }
  };

  const openAdd = () => {
    setEditingWebhook(null);
    setIsDrawerOpen(true);
  };

  const openEdit = (record: Webhook) => {
    setEditingWebhook(record);
    setIsDrawerOpen(true);
  };

  const closeDrawer = () => {
    setIsDrawerOpen(false);
    setEditingWebhook(null);
  };

  const handleSave = async (values: any) => {
    try {
      const scope = values.scope || "global";
      const data: any = {
        ...values,
        modules: Array.isArray(values.modules) ? values.modules.join(",") : values.modules,
        scope,
        scope_target: scope === "global" ? null : values.scope_target || [],
      };

      const res = editingWebhook
        ? await webhookApi.update(editingWebhook.id, data)
        : await webhookApi.create(data);
      if (res.status === "success") {
        message.success(editingWebhook ? "Webhook 更新成功" : "Webhook 创建成功");
        closeDrawer();
        fetchWebhooks(page, pageSize);
      }
    } catch (error) {
      // 用后端返回的具体原因（如服务端围栏拒绝「电量+全局」的提示），而不是笼统的「保存失败」
      message.error(showApiError(error, "保存失败"));
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await webhookApi.delete(id);
      if (res.status === "success") {
        message.success("Webhook 已删除");
        // 删掉当前页最后一条且不在第一页时，回退一页
        const nextPage = webhooks.length === 1 && page > 1 ? page - 1 : page;
        if (nextPage !== page) setPage(nextPage);
        else fetchWebhooks(page, pageSize);
      }
    } catch (error) {
      message.error(showApiError(error, "删除失败"));
    }
  };

  const handleTest = async (record: Webhook) => {
    setTestingId(record.id);
    try {
      const res = await webhookApi.test(record.id);
      if (res.status === "success") {
        message.success("测试消息发送成功");
      } else {
        message.error(res.message || "测试失败");
      }
      fetchWebhooks(page, pageSize);
    } catch (error) {
      message.error(showApiError(error, "测试失败"));
    } finally {
      setTestingId(null);
    }
  };

  const handleToggleEnabled = async (record: Webhook) => {
    try {
      const res = await webhookApi.update(record.id, {
        is_enabled: !record.is_enabled,
      });
      if (res.status === "success") {
        message.success(record.is_enabled ? "已禁用" : "已启用");
        fetchWebhooks(page, pageSize);
      }
    } catch (error) {
      message.error(showApiError(error, "操作失败"));
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      const res = await webhookApi.reload();
      if (res.status === "success") {
        message.success("适配器配置已重载");
      }
    } catch (error) {
      message.error(showApiError(error, "重载失败"));
    } finally {
      setReloading(false);
    }
  };

  /** 「接收范围」列：范围标签 + 目标名称摘要 */
  const renderScope = (scope: string, record: Webhook) => {
    const meta = SCOPE_MAP[scope] || SCOPE_MAP.global;
    if (scope === "global" || !scope) {
      return (
        <Tag color={meta.color} icon={meta.icon}>
          {meta.label}
        </Tag>
      );
    }
    const targets: (number | string)[] = record.scope_target || [];
    // 学生范围：姓名由后端随列表返回（scope_target_names），无需前端持有全量名单；
    // 宿舍范围：scope_target 里存的就是宿舍名本身。
    const names =
      scope === "student"
        ? (record.scope_target_names || []).length
          ? (record.scope_target_names as string[])
          : targets.map((id) => `#${id}`)
        : targets.map((v) => String(v));
    const shown = names.slice(0, 2).join("、");
    const extra = names.length > 2 ? ` 等 ${names.length} 个` : "";
    return (
      <Space size={4} wrap>
        <Tag color={meta.color} icon={meta.icon}>
          {meta.label}
        </Tag>
        <span style={{ fontSize: 12, color: "#555" }}>
          {targets.length === 0 ? "(未指定)" : `${shown}${extra}`}
        </span>
      </Space>
    );
  };

  /** 「测试」列 */
  const renderTestStatus = (record: Webhook) => {
    if (testingId === record.id) return <Badge status="processing" text="测试中" />;
    const needsTest =
      !record.last_test_time || dayjs(record.updated_at).isAfter(dayjs(record.last_test_time));
    if (needsTest) {
      return (
        <Tooltip title="配置已更新，建议重新发送测试以确认可用性">
          <Tag color="warning" icon={<WarningOutlined />}>
            须测试
          </Tag>
        </Tooltip>
      );
    }
    if (!record.last_test_status) {
      return <span style={{ fontSize: 12, color: "#999" }}>未测试</span>;
    }
    const meta = WEBHOOK_TEST_STATUS_MAP[record.last_test_status];
    const tagColor =
      record.last_test_status === "success"
        ? "success"
        : record.last_test_status === "failed"
        ? "error"
        : "processing";
    return (
      <Space size={4}>
        <Tag color={tagColor}>{meta?.text || record.last_test_status}</Tag>
        {record.last_test_time && (
          <span style={{ fontSize: 11, color: "#999" }}>
            {dayjs(record.last_test_time).format("MM-DD")}
          </span>
        )}
      </Space>
    );
  };

  /** 「来源」列：系统级 / 学生自建 */
  const renderSource = (record: Webhook) => {
    if (!record.owner_user_id) return <Tag>系统</Tag>;
    return (
      <Tooltip title={`用户ID：${record.owner_user_id}`}>
        <Tag color="purple" icon={<UserOutlined />}>
          学生（{record.owner_name || record.owner_user_id}）
        </Tag>
      </Tooltip>
    );
  };

  const columns: ColumnsType<Webhook> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      width: 160,
      fixed: "left",
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600, color: "#1f1f1f" }}>{record.name}</div>
          {record.description && (
            <div style={{ fontSize: 12, color: "#999", marginTop: 2 }}>
              {record.description}
            </div>
          )}
        </div>
      ),
    },
    {
      title: "URL",
      dataIndex: "url",
      key: "url",
      width: 200,
      render: (url: string) => (
        <Tooltip title={url}>
          <span
            style={{
              display: "inline-block",
              maxWidth: 180,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              verticalAlign: "middle",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
              fontSize: 12,
              color: "#666",
            }}
          >
            {url}
          </span>
        </Tooltip>
      ),
    },
    {
      title: "模块",
      dataIndex: "module_list",
      key: "module_list",
      width: 170,
      render: (list: string[]) => (
        <Space size={4} wrap>
          {(list || []).map((m) => {
            const meta = MODULE_MAP[m] || { label: m, color: "default" };
            return (
              <Tag key={m} color={meta.color}>
                {meta.label}
              </Tag>
            );
          })}
        </Space>
      ),
    },
    {
      title: "接收范围",
      dataIndex: "scope",
      key: "scope",
      width: 190,
      render: (_, record) => renderScope(record.scope, record),
    },
    {
      title: "来源",
      dataIndex: "owner_user_id",
      key: "owner_user_id",
      width: 130,
      render: (_, record) => renderSource(record),
    },
    {
      title: "状态",
      dataIndex: "is_enabled",
      key: "is_enabled",
      width: 90,
      render: (_, record) => (
        <Switch
          size="small"
          checked={record.is_enabled}
          onChange={() => handleToggleEnabled(record)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
    {
      title: "测试",
      key: "test",
      width: 150,
      render: (_, record) => renderTestStatus(record),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 120,
      render: (v: string) => (v ? dayjs(v).format("YYYY-MM-DD") : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 130,
      fixed: "right",
      render: (_, record) => (
        <Space size={0}>
          <Tooltip title="发送测试消息">
            <Button
              size="small"
              type="text"
              icon={<SendOutlined />}
              loading={testingId === record.id}
              onClick={() => handleTest(record)}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              onClick={() => openEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除此 webhook？"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="删除">
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* 顶部：统计 + 操作 */}
      <Card styles={{ body: { padding: isMobile ? 14 : 18 } }} style={{ marginBottom: 14 }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
          }}
        >
          <span style={{ fontSize: 13, color: "#888" }}>
            共 <b style={{ color: "#1f1f1f" }}>{total}</b> 个
          </span>
          <Space wrap>
            <Button icon={<ReloadOutlined />} loading={reloading} onClick={handleReload}>
              重载配置
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
              添加 Webhook
            </Button>
          </Space>
        </div>
      </Card>

      {/* 简要说明 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14, borderRadius: 8 }}
        message="Webhook 地址决定消息发到哪个群；「接收范围」决定把消息发给谁。课表 / 天气默认全局广播，也可指定宿舍或学生；系统仅全局告警；电量含各人隐私，必须指定受众，不会把全站电量汇总进一个群。修改后点「重载配置」生效。"
      />

      {/* 列表 */}
      <Table<Webhook>
        rowKey="id"
        columns={columns}
        dataSource={webhooks}
        loading={loading}
        scroll={{ x: 1100 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ["10", "20", "50"],
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      {/* 新增 / 编辑抽屉 */}
      <Drawer
        title={editingWebhook ? "编辑 Webhook" : "添加 Webhook"}
        open={isDrawerOpen}
        onClose={closeDrawer}
        width={isMobile ? "100%" : 560}
        destroyOnClose
        footer={
          <div style={{ textAlign: "right" }}>
            <Space>
              <Button onClick={closeDrawer}>取消</Button>
              <Button type="primary" onClick={() => form.submit()}>
                保存
              </Button>
            </Space>
          </div>
        }
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          onValuesChange={handleFormValuesChange}
          initialValues={{
            modules: ["course"],
            is_enabled: true,
            scope: "global",
            scope_target: [],
          }}
        >
          <Divider orientation="left" plain style={{ fontSize: 13 }}>
            基本信息
          </Divider>

          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="如：班级群、测试群" />
          </Form.Item>

          <Form.Item
            name="url"
            label="Webhook URL"
            rules={[
              { required: true, message: "请输入 URL" },
              { pattern: /^https:/, message: "URL 必须以 https:// 开头" },
            ]}
          >
            <Input.TextArea
              rows={2}
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
            />
          </Form.Item>

          <Form.Item
            name="modules"
            label="所属模块"
            rules={[{ required: true, message: "请选择至少一个模块" }]}
            extra="课表 / 天气 / 系统默认全局广播；如想只发给指定学生 / 宿舍，在下方的接收范围里指定受众。电量含逐人隐私，必须指定受众"
          >
            <Select mode="multiple" placeholder="选择此 webhook 接收哪些模块的消息">
              <Select.Option value="all">全局（接收所有推送）</Select.Option>
              <Select.Option value="course">课表（课程推送、上课提醒）</Select.Option>
              <Select.Option value="weather">天气（天气晨报、预警通知）</Select.Option>
              <Select.Option value="electricity">电量（电量日报、低电量告警）</Select.Option>
              <Select.Option value="system">系统（爬虫失败、系统异常）</Select.Option>
            </Select>
          </Form.Item>

          {/* 接收范围对除 system 外所有模块开放：
              课表 / 天气允许「全局」广播或定向到指定学生 / 宿舍；
              电量含逐人隐私，强制必须指定受众，不提供「全局」；
              system 不开放（投递层不补发，仅全局广播）。 */}
          {scopeFilterable && (
            <>
              <Divider orientation="left" plain style={{ fontSize: 13 }}>
                接收范围
              </Divider>

              <Form.Item
                name="scope"
                label="接收范围"
                rules={[{ required: true, message: "请选择接收范围" }]}
              >
                <Select
                  placeholder={
                    requiresAudience(effectiveModules)
                      ? "选择把谁的数据发到这个群"
                      : "选择把消息发给谁（默认全局广播）"
                  }
                  options={[
                    ...(requiresAudience(effectiveModules)
                      ? []
                      : [{ value: "global", label: "全局（所有群 / 人）" }]),
                    { value: "dorm", label: "指定宿舍（该宿舍已配 Cookie 的学生）" },
                    { value: "student", label: "指定学生（仅这些学生）" },
                  ]}
                />
              </Form.Item>

              <Form.Item noStyle shouldUpdate={(prev, cur) => prev.scope !== cur.scope}>
                {({ getFieldValue }) => {
                  const scopeVal = getFieldValue("scope");
                  if (scopeVal === "student") {
                    return (
                      <Form.Item
                        name="scope_target"
                        label="指定学生"
                        rules={[{ required: true, message: "请至少选择一名学生" }]}
                        extra="输入姓名或学号搜索；仅已绑定账号的学生可作目标"
                      >
                        <Select
                          mode="multiple"
                          allowClear
                          showSearch
                          filterOption={false}
                          onSearch={handleStudentSearch}
                          loading={studentSearching}
                          placeholder="输入姓名或学号搜索"
                          options={studentSelectOptions}
                          notFoundContent="输入姓名或学号搜索"
                        />
                      </Form.Item>
                    );
                  }
                  if (scopeVal === "dorm") {
                    return (
                      <Form.Item
                        name="scope_target"
                        label="指定宿舍"
                        rules={[{ required: true, message: "请至少选择一个宿舍" }]}
                        extra="按「楼栋 · 楼层」分组，组内为宿舍号；可直接搜楼栋 / 楼层 / 宿舍号"
                      >
                        <Select
                          mode="multiple"
                          allowClear
                          loading={dormLoading}
                          placeholder="按楼栋 / 楼层 / 宿舍号搜索"
                          options={dormOptionGroups}
                          showSearch
                          optionFilterProp="searchKey"
                          // 分组里显示的是「12」，标签必须带全称，否则看不出是哪栋
                          tagRender={({ value, closable, onClose }) => (
                            <Tag
                              closable={closable}
                              onClose={onClose}
                              style={{ marginInlineEnd: 4 }}
                            >
                              {String(value)}
                            </Tag>
                          )}
                        />
                      </Form.Item>
                    );
                  }
                  return null;
                }}
              </Form.Item>
            </>
          )}

          <Divider orientation="left" plain style={{ fontSize: 13 }}>
            其他
          </Divider>

          <Form.Item name="is_enabled" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item name="description" label="描述（可选）">
            <TextArea rows={2} placeholder="可选的描述信息" />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
