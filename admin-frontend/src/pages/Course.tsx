/**
 * 课程管理页面
 * 包含：图形化课程表展示 + 课程CRUD操作
 * 支持：连续课程合并、实时拆分当前课程、高亮显示
 */
import { useState, useEffect, useMemo, useRef } from "react";
import {
  Card,
  Button,
  Table,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Spin,
  Popconfirm,
  Space,
  Tag,
  Row,
  Col,
  Badge,
  Switch,
  Alert,
  App,
  Progress,
  Grid,
} from "antd";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ImportOutlined,
  ReloadOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  UserOutlined,
  EnvironmentOutlined,
  LoadingOutlined,
  ScheduleOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  courseApi,
  WEEK_DAY_MAP,
  PERIOD_MAP,
  BUILDINGS,
  FIRST_SCHEDULE,
  SECOND_SCHEDULE,
  getScheduleByBuilding,
  type Course,
  type TimetableData,
  type SemesterInfo,
  type CrawlTask,
} from "@/api/course";
import HolidayCourseView from "@/components/HolidayCourseView";
import { holidayApi, type HolidayStatus } from "@/api/holiday";

// 中文数字 → 阿拉伯数字映射
const CN_NUM: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
  十一: 11,
  十二: 12,
};

/** 将 period_name 中的中文数字统一转为阿拉伯数字，如 "第七、八节" → "第7、8节" */
function normalizePeriodName(name: string): string {
  return name.replace(/[一二三四五六七八九十]+/g, (m) => String(CN_NUM[m] ?? m));
}

/**
 * 按 course_weeks 真实日期区间计算某周某天的表头日期（MM-DD），保证与后端一致。
 * 优先用后端 available_weeks 中该周的 start_date 推算；缺数据时回退到写死的学期开学日。
 */
function getWeekDateLabel(
  weekNumber: number,
  weekDay: number,
  availableWeeks?: { week_number: number; start_date?: string | null; end_date?: string | null }[]
): string {
  const wk = availableWeeks?.find((w) => w.week_number === weekNumber);
  if (wk?.start_date) {
    const parts = wk.start_date.split("-").map(Number);
    if (parts.length === 3 && parts.every((n) => !Number.isNaN(n))) {
      const dt = new Date(parts[0], parts[1] - 1, parts[2]);
      dt.setDate(dt.getDate() + (weekDay - 1));
      const m = String(dt.getMonth() + 1).padStart(2, "0");
      const d = String(dt.getDate()).padStart(2, "0");
      return `${m}-${d}`;
    }
  }
  return getWeekDate(weekNumber, weekDay, undefined);
}

/** 解析 'YYYY-MM-DD' 为本地 0 点 Date，非法返回 null */
function parseYmd(s?: string | null): Date | null {
  if (!s) return null;
  const p = s.split("-").map(Number);
  if (p.length !== 3 || p.some((n) => Number.isNaN(n))) return null;
  return new Date(p[0], p[1] - 1, p[2]);
}

import { adminApi, processApi, type TaskProcess } from "@/api/admin";
import { useTaskPolling } from "@/hooks/useTaskPolling";
import { useIntervalPolling } from "@/hooks/useIntervalPolling";
import { POLL_FAST } from "@/hooks/pollIntervals";
import { useUser } from "@/contexts/UserContext";
import CrawlScheduler from "./CrawlScheduler";
import { useSemester } from "@/hooks/useSemester";
import { getWeekDate, getSemesterStartDate } from "@/utils/semester";

const { Option } = Select;

/** 课程颜色映射 */
const COURSE_COLORS = [
  "#1890ff",
  "#52c41a",
  "#faad14",
  "#ff4d4f",
  "#722ed1",
  "#13c2c2",
  "#eb2f96",
  "#f5222d",
  "#fa541c",
  "#fa8c16",
];

/** 根据课程名生成稳定的颜色索引 */
function getCourseColorIndex(courseName: string): number {
  let hash = 0;
  for (let i = 0; i < courseName.length; i++) {
    hash = courseName.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % COURSE_COLORS.length;
}

// 状态计算已移至后端，前端只负责展示

export default function Course() {
  const { isAdmin } = useUser();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [timetableData, setTimetableData] = useState<TimetableData | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingCourse, setEditingCourse] = useState<Course | null>(null);
  const [form] = Form.useForm();
  const [activeView, setActiveView] = useState<"timetable" | "list">("timetable");
  const [currentTime, setCurrentTime] = useState(new Date());
  const [selectedWeek, setSelectedWeek] = useState<number | undefined>(undefined);
  const [currentWeek, setCurrentWeek] = useState<number | undefined>(undefined);
  const [isPolling, setIsPolling] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [spiderRunning, setSpiderRunning] = useState(false); // 爬虫是否正在运行
  const [spiderMessage, setSpiderMessage] = useState(""); // 爬虫状态提示
  const [pushEnabled, setPushEnabled] = useState(true); // 新增：本地状态管理推送开关
  const [crawlModalVisible, setCrawlModalVisible] = useState(false); // 爬取调度弹窗
  const [isFullCrawl, setIsFullCrawl] = useState(false); // 是否全量爬取
  // 学期列表与选中项统一由 useSemester Hook 管理（避免与 CrawlScheduler 重复实现）
  const {
    semesters: semesterList,
    selectedSemester,
    setSelectedSemester,
    currentSemesterId,
  } = useSemester();
  // 假期模式状态（管理员配置，作为课程页假期视图的权威来源；未配置时回退 course_weeks 判定）
  const [holidayStatus, setHolidayStatus] = useState<HolidayStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    holidayApi
      .getStatus()
      .then((res) => {
        if (!cancelled && res.status === "success" && res.data) setHolidayStatus(res.data);
      })
      .catch(() => {
        /* 接口异常不阻断课表加载，回退到 course_weeks 判定 */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  // 统一轮询 Hook 的启用开关（替代原先散落的 setInterval 定时器引用）
  const [spiderPolling, setSpiderPolling] = useState(false);
  const [listPolling, setListPolling] = useState(false);
  const [crawlPollId, setCrawlPollId] = useState<number | null>(null);
  const spiderElapsedRef = useRef(0);

  // 移动端适配：屏幕 < md(768px) 视为手机端
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // 监听教学楼变化，用于动态显示节次时间
  const selectedBuilding = Form.useWatch("building", form);

  // 每分钟更新当前时间（统一轮询 Hook）
  useIntervalPolling(() => setCurrentTime(new Date()), 60000);

  /** 获取课程表数据，返回后端解析出的实际周次（供列表同步使用） */
  const fetchTimetable = async (
    weekNumber?: number,
    semesterId?: number
  ): Promise<number | undefined> => {
    const sem = semesterId ?? selectedSemester;
    setLoading(true);
    try {
      const res = await courseApi.getTimetable(weekNumber, sem);
      if (res.status === "success" && res.data) {
        setTimetableData(res.data);
        // 如果没有指定周次，使用后端自动判断的周（本学期=当前周，非本学期=第一个有课的周）
        if (weekNumber === undefined && res.data.week_number) {
          setSelectedWeek(res.data.week_number);
        }
        // 记录后端判断的本周（只在首次加载时设置，避免切换后被覆盖）
        if (currentWeek === undefined && res.data.week_number) {
          setCurrentWeek(res.data.week_number);
        }
        return res.data.week_number;
      }
    } catch (error) {
      message.error("加载课程表失败");
    } finally {
      setLoading(false);
    }
    return weekNumber;
  };

  /** 获取课程列表 */
  const fetchCourses = async (weekNumber?: number, semesterId?: number) => {
    const sem = semesterId ?? selectedSemester;
    setLoading(true);
    try {
      const res = await courseApi.getList({
        week_number: weekNumber || selectedWeek,
        semester_id: sem,
      });
      if (res.status === "success" && res.data) {
        setCourses(res.data);
      }
    } catch (error) {
      message.error("加载课程列表失败");
    } finally {
      setLoading(false);
    }
  };

  // 检查运行中的课程任务
  const checkRunningTasks = async () => {
    try {
      const res = await processApi.getRunning();
      if (res.status === "success" && res.data?.data) {
        // 同时检查爬虫任务(spider)和课程任务(course)
        const runningTasks = res.data.data.filter(
          (t: TaskProcess) => t.task_type === "course" || t.task_type === "spider"
        );
        if (runningTasks.length > 0) {
          setIsPolling(true);
          setListPolling(true);
          return runningTasks;
        }
      }
      // 同时检查「爬取预约任务」(scheduled_crawl_tasks) 的运行态
      // immediate 任务创建时为 pending，后台线程稍后翻为 running；两者都应视为"运行中"
      const crawlRes = await courseApi.crawlTasks.list({ per_page: 50 });
      const crawlTasks = crawlRes.data.filter(
        (t) => t.status === "running" || t.status === "pending"
      );
      if (crawlTasks.length > 0) {
        // 记录初始运行中的 id，避免挂载时误报「完成」
        crawlRunningIdsRef.current = new Set(crawlTasks.map((t) => t.id));
        setIsPolling(true);
        setListPolling(true);
        return [];
      }
      setIsPolling(false);
      return [];
    } catch (error) {
      console.error("检查任务状态失败:", error);
      setIsPolling(false);
      return [];
    }
  };

  // 任务完成后刷新数据
  const refreshAllData = () => {
    fetchTimetable(selectedWeek);
    fetchCourses(selectedWeek);
  };

  // 开始任务列表轮询（启用统一轮询 Hook）
  const startPolling = () => {
    setIsPolling(true);
    setListPolling(true);
  };

  // 停止所有轮询（交由统一 Hook 自动清理定时器）
  const stopPolling = () => {
    setIsPolling(false);
    setListPolling(false);
    setSpiderPolling(false);
    setCrawlPollId(null);
    setSpiderRunning(false);
    setSpiderMessage("");
    setRunningTasks([]);
    setCrawlRunning([]);
  };

  // 按爬取任务 id 轮询（全量/指定学期爬取专用）
  // 交由 useTaskPolling Hook 跟踪 pending→running→completed/completed_empty/failed 全生命周期
  const startCrawlTaskPolling = (taskId: number) => {
    setIsPolling(true);
    setCrawlPollId(taskId);
  };

  // 由统一 Hook 跟踪爬取任务全生命周期（替代原先按 id 的 setInterval 轮询）
  useTaskPolling<CrawlTask>(crawlPollId, {
    fetcher: (id) => courseApi.crawlTasks.get(id),
    resolve: (d) => ({ status: d.status, message: d.message ?? d.error_message ?? undefined }),
    terminalStatuses: ["completed", "completed_empty", "failed", "cancelled"],
    intervalMs: POLL_FAST,
    onDone: (d) => {
      stopPolling();
      if (d.status === "completed_empty") {
        message.warning(d.message || "爬取完成，但未获取到任何课程数据（可能尚未排课）");
      } else {
        message.success("爬取任务完成！正在刷新数据...");
      }
      refreshAllData();
    },
    onFailed: (d) => {
      stopPolling();
      message.error(`爬取任务失败: ${d.error_message || "未知错误"}`);
    },
  });

  // 获取运行中任务的实时状态
  const [runningTasks, setRunningTasks] = useState<TaskProcess[]>([]);

  // 全量/预约爬取任务（scheduled_crawl_tasks）的运行态，需与上方 task_process 体系一并展示
  const [crawlRunning, setCrawlRunning] = useState<CrawlTask[]>([]);
  const crawlRunningIdsRef = useRef<Set<number>>(new Set());

  const fetchRunningTasks = async () => {
    try {
      const res = await processApi.getRunning();
      if (res.status === "success" && res.data?.data) {
        const processTasks = res.data.data.filter(
          (t: TaskProcess) => t.task_type === "course" || t.task_type === "spider"
        );
        setRunningTasks(processTasks);
        // 同时查询爬取预约任务(scheduled_crawl_tasks)的运行态
        const crawlTasks = await fetchCrawlRunning();
        setCrawlRunning(crawlTasks);

        // 如果没有运行中的任务，停止轮询并刷新数据
        if (processTasks.length === 0 && crawlTasks.length === 0 && isPolling) {
          stopPolling();
          message.success("任务已完成，数据已刷新");
          refreshAllData();
        }
      }
    } catch (error) {
      console.error("获取运行中任务失败:", error);
    }
  };

  // 任务列表轮询：由统一 Hook 驱动（listPolling 控制启停）
  useIntervalPolling(fetchRunningTasks, POLL_FAST, listPolling);

  // 查询爬取预约任务(scheduled_crawl_tasks)的运行态，并处理「完成提示」
  async function fetchCrawlRunning(): Promise<CrawlTask[]> {
    try {
      // immediate 任务创建时为 pending，后台线程稍后翻为 running；两者都视为"运行中"
      const res = await courseApi.crawlTasks.list({ per_page: 50 });
      const active = res.data.filter((t) => t.status === "running" || t.status === "pending");
      const curIds = new Set(active.map((t) => t.id));
      // 上一轮在跑、本轮不在 → 视为已完成，查询最终状态给出分级提示
      const finishedIds = [...crawlRunningIdsRef.current].filter((id) => !curIds.has(id));
      for (const id of finishedIds) {
        try {
          const r = await courseApi.crawlTasks.get(id);
          const st = r.data?.status;
          const msg = r.data?.message || r.data?.error_message || "";
          if (st === "completed") message.success(`爬取任务完成：${msg || "已导入课程"}`);
          else if (st === "completed_empty")
            message.warning(msg || "爬取完成，但未获取到任何课程数据（可能尚未排课）");
          else if (st === "failed") message.error(`爬取任务失败：${msg}`);
        } catch {
          /* 忽略单条查询失败 */
        }
      }
      crawlRunningIdsRef.current = curIds;
      return active;
    } catch (error) {
      console.error("查询爬取任务状态失败:", error);
    }
    return [];
  }

  // 爬虫专用轮询：只检查 _spider_running 状态，确认爬虫真正结束才刷新。
  // 触发时仅置位状态开关，实际轮询交由下方 useIntervalPolling Hook 驱动。
  const startSpiderPolling = () => {
    spiderElapsedRef.current = 0;
    setIsPolling(true);
    setSpiderRunning(true);
    setSpiderMessage("爬虫启动中...");
    setSpiderPolling(true);
  };

  // 爬虫状态轮询：由 spiderPolling 开关驱动（替代原先散落的 setInterval）
  useIntervalPolling(
    async () => {
      spiderElapsedRef.current += 2;
      try {
        const res = await adminApi.getSpiderStatus();
        if (res.status === "success" && res.spider) {
          const { running, last_result, last_error } = res.spider;
          if (running) {
            setSpiderRunning(true);
            setSpiderMessage(`正在爬取... (已耗时 ${spiderElapsedRef.current}s)`);
          } else {
            // 爬虫已停止：关闭本轮询开关并给出分级提示
            setSpiderRunning(false);
            setSpiderMessage("");
            setSpiderPolling(false);
            setIsPolling(false);

            if (last_result === "success") {
              message.success("课程表爬取成功，数据已刷新");
              refreshAllData();
            } else if (last_result === "failed") {
              message.error(`爬取失败: ${last_error || "未知错误"}`);
            } else {
              // last_result 为 null（首次加载）或 running 已清除，视为完成
              message.success("课程表爬取完成，数据已刷新");
              refreshAllData();
            }
          }
        }
      } catch {
        // 接口异常不中断轮询
        console.error("获取爬虫状态失败");
      }
      // immediate=false：触发后延迟一个周期再首检，避开后端 _spider_running 尚未置位的竞态
    },
    POLL_FAST,
    spiderPolling,
    false
  );

  // 触发课程任务
  const handleTrigger = async (taskType: string) => {
    try {
      if (taskType === "sync_schedule") {
        // 同步课表 = 触发爬虫 → 用爬虫专用轮询确认真正完成
        const res = await adminApi.triggerSpider();
        // 假期静默 / 非教学周拦截：后端返回 skipped，提示并跳过轮询
        if ((res as any).skipped) {
          message.warning(res.message || "假期静默中，已跳过课表爬取");
          return;
        }
        message.success(res.message || "爬虫任务已触发");
        startSpiderPolling();
      } else {
        // 其他课程任务（推送等）
        const res = await adminApi.triggerCourse(taskType);
        message.success(res.message || "任务已触发");
        startPolling();
      }
    } catch (error) {
      message.error("触发任务失败");
    }
  };

  /** 导入课程 */
  const handleImport = async () => {
    setLoading(true);
    try {
      const res = await courseApi.import();
      if (res.status === "success") {
        message.success(`成功导入 ${res.data?.imported_count} 门课程`);
        fetchTimetable();
        fetchCourses();
      }
    } catch (error) {
      message.error("导入失败");
    } finally {
      setLoading(false);
    }
  };

  /** 打开编辑弹窗 */
  const handleEdit = (course: Course) => {
    setEditingCourse(course);
    // 只使用当前记录的 periods，不合并同名的其他记录
    // 因为同名但教室不同的课程是独立的（如PHP框架应用在不同教室）
    const periodsData = (course as any).periods;
    let periodArray: number[] = [];
    if (Array.isArray(periodsData)) {
      periodArray = periodsData.map(Number).filter((n: number) => n >= 1 && n <= 12);
    } else if (typeof periodsData === "string") {
      periodArray = periodsData
        .split(",")
        .map(Number)
        .filter((n: number) => n >= 1 && n <= 12);
    } else {
      periodArray = [course.period_idx].filter((n: number) => n >= 1 && n <= 12);
    }

    const initialPushEnabled = (course as any).push_enabled === false ? false : true;
    setPushEnabled(initialPushEnabled);

    form.setFieldsValue({
      ...course,
      period_idx: periodArray,
    });
    setModalVisible(true);
  };

  /** 打开新增弹窗 */
  const handleAdd = (weekDay?: number, periodIdx?: number) => {
    setEditingCourse(null);
    form.resetFields();
    // 默认填充当前周次
    const defaultWeek = selectedWeek || timetableData?.week_number || 1;
    if (weekDay && periodIdx) {
      form.setFieldsValue({
        week_day: weekDay,
        period_idx: [periodIdx],
        week_number: defaultWeek,
        start_time: SECOND_SCHEDULE[periodIdx]?.start,
        end_time: SECOND_SCHEDULE[periodIdx]?.end,
      });
    } else {
      form.setFieldsValue({
        week_number: defaultWeek,
      });
    }
    setModalVisible(true);
  };

  /** 保存课程 */
  const handleSave = async (values: any) => {
    // 如果正在删除中，不执行保存操作
    if (isDeleting) {
      return;
    }

    try {
      // 节次多选，转为逗号分隔字符串
      const periodIndices = values.period_idx;
      const periodsStr = Array.isArray(periodIndices)
        ? periodIndices.join(",")
        : String(periodIndices);

      // 根据楼栋选择时间表
      const schedule = getScheduleByBuilding(values.building || "");

      // 获取第一节的时间作为开始时间，最后一节的时间作为结束时间
      const firstPeriod = periodIndices[0];
      const lastPeriod = periodIndices[periodIndices.length - 1];
      const firstPeriodInfo = schedule[firstPeriod];
      const lastPeriodInfo = schedule[lastPeriod];

      // 保存时使用的周次
      const weekToSave = values.week_number || selectedWeek || 1;

      const data = {
        ...values,
        period_idx: periodsStr,
        periods: periodsStr,
        start_time: firstPeriodInfo?.start || "",
        end_time: lastPeriodInfo?.end || "",
        week_number: weekToSave,
        semester_id: selectedSemester, // 把课程挂到当前查看的学期，避免自建课程因学期错配而不显示
        push_enabled: pushEnabled, // 使用本地状态
        is_edit: !!editingCourse, // 标记是否是编辑模式
        old_course_id: editingCourse?.id, // 传递原课程ID
      };

      await courseApi.create(data);
      message.success(editingCourse ? "课程更新成功" : "课程创建成功");
      setModalVisible(false);
      setEditingCourse(null);
      form.resetFields();
      // 使用保存时选择的周次刷新
      fetchTimetable(weekToSave);
      fetchCourses(weekToSave);
    } catch (error) {
      message.error("保存失败");
    }
  };

  /** 删除课程 */
  const handleDelete = async (course: Course) => {
    try {
      setIsDeleting(true);

      // 先关闭编辑弹窗，重置状态，防止删除后触发意外的保存
      setEditingCourse(null);
      setModalVisible(false);
      form.resetFields();

      // 先删除当前点击的课程
      await courseApi.delete(course.id);

      // 从两个数据源（timetableData 和 courses）中查找同一课程的其他记录
      const allCourses = [...(timetableData?.courses || []), ...(courses || [])];

      // 去重（通过 id）
      const uniqueCourses = Array.from(new Map(allCourses.map((c) => [c.id, c])).values());

      // 筛选出同一天、同一课程名、同一教室的其他记录（排除当前已删除的）
      const sameCourses = uniqueCourses.filter(
        (c) =>
          c.id !== course.id &&
          c.week_day === course.week_day &&
          c.course_name === course.course_name &&
          c.classroom === course.classroom &&
          (c.week_number ?? -1) === (course.week_number ?? -1)
      );

      for (const c of sameCourses) {
        await courseApi.delete(c.id);
      }

      message.success("课程删除成功");
      fetchTimetable(selectedWeek);
      fetchCourses(selectedWeek);
    } catch (error) {
      console.error("删除失败:", error);
      message.error("删除失败");
    } finally {
      setIsDeleting(false);
    }
  };

  // 不再需要 handleTogglePush 函数，推送状态通过 Form 管理

  /** 楼栋选择变化时自动更新节次选项 */
  const handleBuildingChange = (building: string) => {
    form.setFieldsValue({ building });
    // 清空节次选择，触发节次选项更新
    form.setFieldsValue({ period_idx: undefined });
  };

  /** 节次多选变化时自动填充时间 */
  const handlePeriodChange = (periodIndices: number[]) => {
    if (periodIndices.length > 0) {
      // 根据当前楼栋选择时间表
      const building = form.getFieldValue("building") || "";
      const schedule = getScheduleByBuilding(building);

      const firstPeriod = periodIndices[0];
      const lastPeriod = periodIndices[periodIndices.length - 1];
      const firstPeriodInfo = schedule[firstPeriod];
      const lastPeriodInfo = schedule[lastPeriod];
      form.setFieldsValue({
        start_time: firstPeriodInfo?.start || "",
        end_time: lastPeriodInfo?.end || "",
      });
    }
  };

  /** 同步当前周课程 */
  const handleSyncCurrentWeek = async () => {
    try {
      const res = await adminApi.triggerSpider();
      // 假期静默 / 非教学周拦截：后端返回 skipped，提示并跳过轮询
      if ((res as any).skipped) {
        message.warning(res.message || "假期静默中，已跳过课表爬取");
        return;
      }
      if (res?.status === "success") {
        message.success("同步任务已启动，正在后台执行...");
        startPolling();
      } else {
        message.error(res?.message || "启动同步任务失败");
      }
    } catch (error: any) {
      console.error("启动同步任务失败:", error);
      message.error(error?.response?.data?.message || error?.message || "网络错误");
    }
  };

  // 组件卸载时清除轮询
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, []);

  // 检查是否有运行中的任务
  useEffect(() => {
    checkRunningTasks();
  }, []);

  // 注意：以下两种「列表轮询」路径的完成判定已由各自轮询逻辑内部处理，
  // 不要再用「runningTasks/crawlRunning 为空 + isPolling」做全局兜底 —— 那样会在
  // 爬取任务走 crawlPollId 路径（listPolling=false，两列表恒为空）时误判「已完成」，
  // 导致 useTaskPolling 被立即 stopPolling 关掉，出现「不等程序跑完就刷新」的假完成。
  //   - startPolling 路径：useIntervalPolling(fetchRunningTasks) 内部在双列表空时 stopPolling+刷新
  //   - 爬取任务路径：useTaskPolling 在终态时 onDone/onFailed 内 stopPolling+刷新
  //   - 同步课表路径：useIntervalPolling(..., spiderPolling) 在爬虫停止时刷新

  useEffect(() => {
    fetchTimetable();
    fetchCourses();
  }, []);

  /** 切换周次 */
  const handleWeekChange = (week: number) => {
    setSelectedWeek(week);
    fetchTimetable(week);
    fetchCourses(week);
  };

  /** 切换学期 */
  const handleSemesterChange = (semesterId: number) => {
    if (semesterId === selectedSemester) return;
    setSelectedSemester(semesterId);
    // 不沿用当前周：让后端决定默认周（本学期=当前周，非本学期=第一个有课的周）
    setSelectedWeek(undefined);
    fetchTimetable(undefined, semesterId).then((week) => {
      fetchCourses(week, semesterId);
    });
  };

  /** 当前状态 - 从后端获取 */
  const currentStatus = useMemo(() => {
    if (!timetableData?.current_status) {
      return { currentPeriod: 0, isOngoing: false, hasCurrentCourse: false, currentWeekDay: 0 };
    }
    return {
      currentPeriod: timetableData.current_status.current_period,
      isOngoing: timetableData.current_status.is_ongoing,
      hasCurrentCourse: (timetableData.current_status as any).has_current_course || false,
      currentWeekDay: timetableData.current_status.current_week_day,
      isTeachingWeek: (timetableData.current_status as any).is_teaching_week !== false, // 后端缺字段时默认 true（向后兼容）
    };
  }, [timetableData]);

  /**
   * 构建课程表格映射
   * 1. 先将同一天、同一课程名、相邻节次的记录合并成一条虚拟记录
   * 2. 再根据 periods 字段构建 cellMap
   */
  const cellMap = useMemo(() => {
    if (!timetableData) return null;

    const map: Record<
      number,
      Record<
        number,
        {
          course: Course;
          rowSpan: number;
          render: boolean;
          isOngoing?: boolean;
          isPast?: boolean;
        }
      >
    > = {};

    const { currentPeriod, isOngoing, currentWeekDay } = currentStatus;
    const courseList = timetableData.courses || [];

    // 实时状态（正在上课/已结束）仅在「查看真实当前学期的当前周」时生效，
    // 否则其他周次/历史学期中同星期的课程会在当下时段被误标为「正在上课」
    const isRealCurrentWeek =
      selectedSemester !== undefined &&
      semesterList.find((s: SemesterInfo) => s.is_current)?.id === selectedSemester &&
      selectedWeek !== undefined &&
      selectedWeek === currentWeek;

    // 初始化空表格
    for (let day = 1; day <= 7; day++) {
      map[day] = {};
    }

    // 第一步：按天分组，然后合并相邻的同名课程
    const byDay: Record<number, typeof courseList> = {};
    for (const c of courseList) {
      const d = c.week_day;
      if (d < 1 || d > 7) continue;
      if (!byDay[d]) byDay[d] = [];
      byDay[d].push(c);
    }

    // 解析节次信息，支持多种格式
    function parseCN(s: string): number {
      return CN_NUM[s] ?? parseInt(s, 10);
    }

    // 将 period_name 中的中文数字统一转为阿拉伯数字，如 "第七、八节"→"第7、8节"
    function normalizePeriodName(name: string): string {
      return name.replace(/[一二三四五六七八九十]+/g, (m) => String(CN_NUM[m] ?? m));
    }

    function parsePeriods(course: Course): number[] {
      // 优先使用 periods 字段（支持 JSON 数组格式和旧字符串格式）
      const periodsData = (course as any).periods;
      if (periodsData) {
        if (Array.isArray(periodsData)) {
          return periodsData.map(Number).filter((n: number) => n >= 1 && n <= 12);
        } else if (typeof periodsData === "string") {
          return periodsData
            .split(",")
            .map(Number)
            .filter((n: number) => n >= 1 && n <= 12);
        }
      }

      // 其次尝试解析 period_name 字段
      const periodName = (course as any).period_name;
      if (periodName) {
        // 阿拉伯数字范围，如 "第9-10节"
        const rangeMatch = periodName.match(/第(\d+)[-~～](\d+)节/);
        if (rangeMatch) {
          const first = parseInt(rangeMatch[1], 10);
          const second = parseInt(rangeMatch[2], 10);
          if (!isNaN(first) && !isNaN(second) && first <= second) {
            return Array.from({ length: second - first + 1 }, (_, i) => first + i);
          }
        }
        // 阿拉伯数字顿号，如 "第7、8节"
        const dotMatch = periodName.match(/第(\d+)、(\d+)节/);
        if (dotMatch) {
          const first = parseInt(dotMatch[1], 10);
          const second = parseInt(dotMatch[2], 10);
          if (!isNaN(first) && !isNaN(second) && first <= second) {
            return Array.from({ length: second - first + 1 }, (_, i) => first + i);
          }
        }
        // 中文数字顿号，如 "第七、八节"
        const cnDotMatch = periodName.match(
          /第([一二三四五六七八九十]+)、([一二三四五六七八九十]+)节/
        );
        if (cnDotMatch) {
          const first = parseCN(cnDotMatch[1]);
          const second = parseCN(cnDotMatch[2]);
          if (!isNaN(first) && !isNaN(second) && first <= second) {
            return Array.from({ length: second - first + 1 }, (_, i) => first + i);
          }
        }
        // 单节阿拉伯数字，如 "第2节"
        const singleMatch = periodName.match(/第(\d+)节/);
        if (singleMatch) {
          const num = parseInt(singleMatch[1], 10);
          if (!isNaN(num)) return [num];
        }
        // 单节中文数字，如 "第二节"
        const cnSingleMatch = periodName.match(/第([一二三四五六七八九十]+)节/);
        if (cnSingleMatch) {
          const num = parseCN(cnSingleMatch[1]);
          if (!isNaN(num)) return [num];
        }
      }

      // 最后使用 period_idx 字段
      return [course.period_idx].filter((n: number) => n >= 1 && n <= 12);
    }

    // 合并函数：将相邻的同名课程合并成一条
    function mergeAdjacentCourses(dayCourses: typeof courseList) {
      // 先解析每条记录的节次，按首节升序排序
      const withPeriods = dayCourses
        .map((c) => ({ course: c, periods: parsePeriods(c) }))
        .filter((x) => x.periods.length > 0);
      withPeriods.sort((a, b) => a.periods[0] - b.periods[0]);

      const merged: { course: Course; allPeriods: number[] }[] = [];

      for (const { course: c, periods } of withPeriods) {
        const last = merged[merged.length - 1];
        const lastEnd = last ? last.allPeriods[last.allPeriods.length - 1] : -999;

        // 合并条件辅助函数：两个字段都非空时才严格要求相等，任一为空则视为匹配
        // （解决后端教师/教室字段部分为空导致同门课无法合并的问题）
        function fieldsMatch(a: any, b: any): boolean {
          const aEmpty = a === null || a === undefined || a === "";
          const bEmpty = b === null || b === undefined || b === "";
          return aEmpty || bEmpty || a === b;
        }

        // 合并条件：同名、同教师（空值兼容）、同教室（空值兼容），且当前课程首节 === 上一课末节+1（严格相邻，不允许重叠）
        const canMerge =
          last &&
          last.course.course_name === c.course_name &&
          fieldsMatch(last.course.teacher, c.teacher) &&
          fieldsMatch(last.course.classroom, c.classroom) &&
          periods[0] === lastEnd + 1;

        if (canMerge) {
          // 严格相邻合并，直接追加（已排序不会有重叠）
          last.allPeriods = [...last.allPeriods, ...periods];
          last.course = {
            ...last.course,
            end_time: c.end_time,
            periods: last.allPeriods.join(","),
          } as any;
        } else {
          merged.push({ course: { ...c }, allPeriods: [...periods] });
        }
      }
      return merged;
    }

    // 第二步：为每天的合并后课程构建 cellMap
    for (let day = 1; day <= 7; day++) {
      const dayCourses = byDay[day] || [];
      const merged = mergeAdjacentCourses(dayCourses);

      for (const { course, allPeriods } of merged) {
        const startPeriod = allPeriods[0];
        const endPeriod = allPeriods[allPeriods.length - 1];
        const rowSpan = endPeriod - startPeriod + 1;

        // 判断课程是否正在上课：用课程自身 start_time/end_time，兼容两套时间表
        const now = new Date();
        const currentMinutes = now.getHours() * 60 + now.getMinutes();

        // 解析课程时间范围（使用合并后的首节 start_time 和末节 end_time）
        let courseIsOngoing = false;
        let courseIsPast = false;
        if (isRealCurrentWeek && day === currentWeekDay && course.start_time && course.end_time) {
          const [sh, sm] = course.start_time.split(":").map(Number);
          const [eh, em] = course.end_time.split(":").map(Number);
          if (!isNaN(sh) && !isNaN(eh)) {
            const startMin = sh * 60 + sm;
            const endMin = eh * 60 + em;
            courseIsOngoing = currentMinutes >= startMin && currentMinutes <= endMin;
            courseIsPast = currentMinutes > endMin;
          }
        }

        // 不再拆分课程卡片，整张卡片统一高亮 isOngoing
        map[day][startPeriod] = {
          course,
          rowSpan,
          render: true,
          isPast: courseIsPast,
          isOngoing: courseIsOngoing,
        };
        for (let p = startPeriod + 1; p <= endPeriod; p++) {
          map[day][p] = { course, rowSpan: 1, render: false, isOngoing: false };
        }
      }
    }

    return map;
  }, [timetableData, currentStatus, selectedWeek, currentWeek, selectedSemester, semesterList]);

  // 移动端列显示策略（仅针对周六/周日，周一~周五始终显示）：
  // 周一~周五(1-5) 恒显示；周六(6)/周日(7) 仅当整列有课时才显示，无课则隐藏，
  // 把屏幕宽度让给工作日。桌面端恒为完整 7 天。
  const renderDayList = useMemo(() => {
    if (!isMobile || !cellMap) return [1, 2, 3, 4, 5, 6, 7];
    const list: number[] = [];
    for (let d = 1; d <= 7; d++) {
      if (d <= 5) {
        list.push(d); // 工作日始终显示
      } else if (cellMap[d] && Object.keys(cellMap[d]).length > 0) {
        list.push(d); // 周末仅在有课时显示
      }
    }
    return list;
  }, [isMobile, cellMap]);

  /** 渲染课程表单元格 */
  const renderCourseCell = (day: number, period: number) => {
    if (!cellMap) return null;

    const cellInfo = cellMap[day]?.[period];

    // 没有课程数据，渲染空白
    if (!cellInfo) {
      return (
        <td
          key={`${day}-${period}`}
          style={{
            padding: isMobile ? "2px" : "4px",
            border: "1px solid #f0f0f0",
            verticalAlign: "top",
          }}
        >
          <div
            style={{
              height: isMobile ? "44px" : "76px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "#fafafa",
              borderRadius: "4px",
              cursor: isAdmin ? "pointer" : "default",
            }}
            onClick={() => isAdmin && handleAdd(day, period)}
          >
            {!isMobile && <PlusOutlined style={{ color: "#d9d9d9" }} />}
          </div>
        </td>
      );
    }

    // 被合并的节次，不渲染
    if (!cellInfo.render) return null;

    const { course, rowSpan, isOngoing } = cellInfo;
    // 只使用 cellInfo.isOngoing 判断是否正在上课（由前端合并逻辑设置）
    const isCurrentCourse = isOngoing;
    const pushEnabled = (course as any).push_enabled !== false; // 默认开启
    const colorIndex = getCourseColorIndex(course.course_name);
    const baseColor = COURSE_COLORS[colorIndex];
    const isDisabled = !pushEnabled; // 关闭推送时变灰

    // 计算上课进度（0-1），用于渐进式高亮
    let classProgress = 0;
    if (isCurrentCourse && course.start_time && course.end_time) {
      const now = currentTime;
      const [sh, sm] = course.start_time.split(":").map(Number);
      const [eh, em] = course.end_time.split(":").map(Number);
      const startMin = sh * 60 + sm;
      const endMin = eh * 60 + em;
      const nowMin = now.getHours() * 60 + now.getMinutes();
      const total = endMin - startMin;
      if (total > 0) {
        classProgress = Math.min(1, Math.max(0, (nowMin - startMin) / total));
      }
    }

    // 正在上课时的样式
    const activeBgColor = isCurrentCourse
      ? `linear-gradient(to bottom, #fff1f0 ${classProgress * 100}%, ${baseColor}15 ${classProgress * 100}%)`
      : `${baseColor}15`;
    const activeBorderColor = isCurrentCourse ? "#ff4d4f" : baseColor;

    return (
      <td
        key={`${day}-${period}`}
        rowSpan={rowSpan}
        style={{
          padding: "4px",
          border: "1px solid #f0f0f0",
          verticalAlign: "top",
        }}
      >
        <div
          style={{
            height: `${rowSpan * (isMobile ? 50 : 84) - (isMobile ? 4 : 8)}px`,
            minHeight: isMobile ? "44px" : "76px",
            padding: isMobile ? "3px" : "8px",
            backgroundColor: isDisabled ? "#f5f5f5" : activeBgColor,
            borderLeft: `3px solid ${isDisabled ? "#d9d9d9" : activeBorderColor}`,
            borderRadius: "4px",
            cursor: isAdmin ? "pointer" : "default",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            opacity: isDisabled ? 0.5 : 1,
            transition: "background-color 1s ease",
          }}
          onClick={() => isAdmin && handleEdit(course)}
        >
          {isCurrentCourse && (
            <div
              style={{
                background: "linear-gradient(135deg, #ff4d4f, #ff7875)",
                color: "#fff",
                padding: isMobile ? "1px 3px" : "2px 8px",
                borderRadius: "4px",
                fontSize: isMobile ? 9 : 11,
                fontWeight: "bold",
                textAlign: "center",
                marginBottom: isMobile ? 2 : 4,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 2,
              }}
            >
              {!isMobile && <ClockCircleOutlined />}
              正在上课
            </div>
          )}
          {isDisabled && (
            <Tag color="default" style={{ marginBottom: 4, fontSize: isMobile ? 9 : 11 }}>
              不推送
            </Tag>
          )}
          <div
            style={{
              fontWeight: "bold",
              fontSize: isMobile ? 11 : 13,
              color: isDisabled ? "#999" : isCurrentCourse ? "#ff4d4f" : baseColor,
              marginBottom: isMobile ? 2 : "4px",
              lineHeight: isMobile ? 1.2 : "normal",
            }}
          >
            {course.course_name}
          </div>
          <div
            style={{
              fontSize: isMobile ? 10 : 12,
              color: "#666",
              flex: 1,
              lineHeight: isMobile ? 1.2 : "normal",
            }}
          >
            {course.teacher && (
              <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <UserOutlined style={{ marginRight: 2 }} />
                {course.teacher}
              </div>
            )}
            {course.building && course.classroom && (
              <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <EnvironmentOutlined style={{ marginRight: 2 }} />
                {course.building} {course.classroom}
              </div>
            )}
            {!course.building && course.classroom && (
              <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <EnvironmentOutlined style={{ marginRight: 2 }} />
                {course.classroom}
              </div>
            )}
          </div>
          <div style={{ fontSize: isMobile ? 9 : 11, color: "#999", marginTop: "auto" }}>
            {course.start_time} - {course.end_time}
          </div>
          {/* 显示节次信息 */}
          <div style={{ fontSize: isMobile ? 9 : 11, color: "#999", marginTop: 2 }}>
            {(() => {
              // 优先使用 period_name（爬取数据格式，统一转阿拉伯数字）
              const periodName = (course as any).period_name;
              if (periodName) return normalizePeriodName(periodName);

              // 使用 periods 字段（支持 JSON 数组格式和旧字符串格式）
              const periodsData = (course as any).periods;
              let pArr: number[] = [];
              if (Array.isArray(periodsData)) {
                pArr = periodsData.map(Number).filter((n: number) => n >= 1 && n <= 12);
              } else if (typeof periodsData === "string") {
                pArr = periodsData
                  .split(",")
                  .map(Number)
                  .filter((n: number) => n >= 1 && n <= 12);
              }

              // 如果 periods 为空或无效，使用 period_idx
              if (pArr.length === 0) {
                pArr = [course.period_idx].filter((n: number) => n >= 1 && n <= 12);
              }

              if (pArr.length === 1) return PERIOD_MAP[pArr[0]]?.name || `第${pArr[0]}节`;
              if (pArr.length >= 2) {
                const first = pArr[0],
                  last = pArr[pArr.length - 1];
                return `第${first}-${last}节`;
              }
              return `第${course.period_idx}节`;
            })()}
          </div>
        </div>
      </td>
    );
  };

  /** 表格列定义 */
  const columns = useMemo(() => {
    const base = [
      { title: "课程名称", dataIndex: "course_name", key: "course_name" },
      { title: "教师", dataIndex: "teacher", key: "teacher" },
      { title: "教室", dataIndex: "classroom", key: "classroom" },
      {
        title: "星期",
        dataIndex: "week_day",
        key: "week_day",
        render: (v: number) => WEEK_DAY_MAP[v],
      },
      {
        title: "节次",
        dataIndex: "period_idx",
        key: "period_idx",
        render: (_: any, r: Course) => {
          // 优先使用 period_name（爬取数据格式，统一转阿拉伯数字）
          const periodName = (r as any).period_name;
          if (periodName) return normalizePeriodName(periodName);

          // 使用 periods 字段（支持 JSON 数组格式和旧字符串格式）
          const periodsData = (r as any).periods;
          let pArr: number[] = [];
          if (Array.isArray(periodsData)) {
            pArr = periodsData.map(Number).filter((n: number) => n >= 1 && n <= 12);
          } else if (typeof periodsData === "string") {
            pArr = periodsData
              .split(",")
              .map(Number)
              .filter((n: number) => n >= 1 && n <= 12);
          }

          // 如果 periods 为空或无效，使用 period_idx
          if (pArr.length === 0) {
            pArr = [r.period_idx].filter((n: number) => n >= 1 && n <= 12);
          }

          if (pArr.length === 1) return PERIOD_MAP[pArr[0]]?.name || `第${pArr[0]}节`;
          if (pArr.length >= 2) {
            return `第${pArr[0]}-${pArr[pArr.length - 1]}节`;
          }
          return `第${r.period_idx}节`;
        },
      },
      {
        title: "时间",
        key: "time",
        render: (_: any, r: Course) => `${r.start_time}-${r.end_time}`,
      },
      {
        title: "周次",
        dataIndex: "weeks",
        key: "weeks",
        render: (v: any) => {
          if (Array.isArray(v)) return v.join(",");
          if (typeof v === "string") return v;
          return "";
        },
      },
    ];
    if (isAdmin) {
      base.push({
        title: "操作",
        key: "action",
        render: (_: any, record: Course) => (
          <Space>
            <Button type="link" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
              编辑
            </Button>
            <Popconfirm title="确定删除该课程的所有节次吗？" onConfirm={() => handleDelete(record)}>
              <Button type="link" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
      } as any);
    }
    return base;
  }, [isAdmin]);

  // 是否正在查看"当前学期"：决定周次下拉是否标记"(本周)"，避免历史学期误标
  const isViewingCurrentSemester =
    selectedSemester !== undefined && selectedSemester === currentSemesterId;

  // 是否在「假期 / 非教学周」：当前学期 + 今天不在任何教学周日期区间内（或超出教学周范围）
  const inBreak = useMemo(() => {
    if (!isViewingCurrentSemester) return false;
    const weeks = timetableData?.available_weeks;

    // 兜底1：没有任何教学周数据 → 视为非教学周/假期
    if (!weeks || weeks.length === 0) return true;

    const t = currentTime;
    const today = new Date(t.getFullYear(), t.getMonth(), t.getDate());

    // 检查今天是否落在任一教学周的日期区间内
    const inAnyRange = weeks.some((w) => {
      if (!w.start_date || !w.end_date) return false;
      const p1 = w.start_date.split("-").map(Number);
      const p2 = w.end_date.split("-").map(Number);
      if (p1.length !== 3 || p2.length !== 3) return false;
      const s = new Date(p1[0], p1[1] - 1, p1[2]);
      const e = new Date(p2[0], p2[1] - 1, p2[2]);
      return today >= s && today <= e;
    });

    if (!inAnyRange) return true; // 今天不在任何教学周日期范围内 → 假期

    // 兜底2：当前周次已超过所有教学周的最大周次 → 视为假期
    const maxWeek = Math.max(...weeks.map((w) => w.week_number || 0));
    if (currentWeek && currentWeek > maxWeek) return true;

    return false;
  }, [isViewingCurrentSemester, timetableData, currentTime, currentWeek]);

  // 假期模式是否生效（管理员配置，权威来源）：仅在查看当前学期时有效
  const holidayModeActive = isViewingCurrentSemester && (holidayStatus?.active ?? false);

  // 选中周（默认当前周）对应的日期区间（含年份）：优先用后端 available_weeks 真实区间；
  // 超出教学周范围时用学期开学日推算，保证任何周次都能拿到正确日期用于假期判定。
  const selectedWeekRange = useMemo(() => {
    const wkNum = selectedWeek ?? currentWeek;
    if (!wkNum) return null;
    const weeks = timetableData?.available_weeks;
    const wk = weeks?.find((w) => w.week_number === wkNum);
    if (wk?.start_date && wk?.end_date) {
      const s = parseYmd(wk.start_date);
      const e = parseYmd(wk.end_date);
      if (s && e) return { start: s, end: e };
    }
    const start = getSemesterStartDate(selectedSemester);
    const monday = new Date(start);
    monday.setDate(start.getDate() + (wkNum - 1) * 7);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    return { start: monday, end: sunday };
  }, [selectedWeek, currentWeek, timetableData, selectedSemester]);

  // 假期模式：选中的周落在某条启用假期区间内 → 接管为假期视图
  const selectedWeekInHoliday = useMemo(() => {
    if (!holidayModeActive) return false;
    const ps = parseYmd(holidayStatus?.period?.start_date);
    const pe = parseYmd(holidayStatus?.period?.end_date);
    if (!ps || !pe || !selectedWeekRange) return false;
    return selectedWeekRange.start <= pe && selectedWeekRange.end >= ps;
  }, [holidayModeActive, holidayStatus, selectedWeekRange]);

  // 未配置假期模式时回退：选中的周不在任何教学周区间内（或超出范围）→ 视为非教学周
  const selectedWeekInBreak = useMemo(() => {
    if (!isViewingCurrentSemester || holidayModeActive) return false;
    const weeks = timetableData?.available_weeks;
    if (!weeks || weeks.length === 0) return true;
    if (!selectedWeekRange) return false;
    const inAny = weeks.some((w) => {
      const s = parseYmd(w.start_date);
      const e = parseYmd(w.end_date);
      if (!s || !e) return false;
      return selectedWeekRange.start <= e && selectedWeekRange.end >= s;
    });
    if (!inAny) return true;
    const maxWeek = Math.max(...weeks.map((w) => w.week_number || 0));
    if (selectedWeek && selectedWeek > maxWeek) return true;
    return false;
  }, [isViewingCurrentSemester, holidayModeActive, timetableData, selectedWeekRange, selectedWeek]);

  // 假期页是否接管课程表视图：按「选中周」是否处于假期/非教学周判定，而非按「今天」。
  // 这样假期区间内选中的周显示假期提示，历史教学周正常显示课表（周次选择器可自由切换）。
  const showHoliday = activeView === "timetable" && (selectedWeekInHoliday || selectedWeekInBreak);

  // 视图切换「课表/列表」按钮：放到标题「第X周课表」右侧，桌面端/移动端共用
  const viewSwitch = (
    <Space.Compact>
      <Button
        type={activeView === "timetable" ? "primary" : "default"}
        size={isMobile ? "small" : "middle"}
        onClick={() => setActiveView("timetable")}
        disabled={isPolling}
      >
        课程表
      </Button>
      <Button
        type={activeView === "list" ? "primary" : "default"}
        size={isMobile ? "small" : "middle"}
        onClick={() => setActiveView("list")}
        disabled={isPolling}
      >
        列表
      </Button>
    </Space.Compact>
  );

  // 课程管理工具栏：桌面端横排在卡片右上角(extra)；移动端改为内容区顶部独立全宽栏，竖向整齐分组
  const renderToolbar = () => {
    const termSelect = (
      <Select
        value={selectedSemester}
        onChange={handleSemesterChange}
        style={isMobile ? { flex: 1, minWidth: 0 } : { width: 180 }}
        disabled={isPolling}
        placeholder="选择学期"
      >
        {semesterList.map((s) => (
          <Option key={s.id} value={s.id}>
            <span
              style={{
                fontWeight: s.is_current ? "bold" : "normal",
                color: s.is_current ? "#1890ff" : undefined,
              }}
            >
              {s.name} {s.is_current ? "(当前)" : ""}
            </span>
          </Option>
        ))}
      </Select>
    );

    const weekSelect = (
      <Select
        value={selectedWeek}
        onChange={handleWeekChange}
        style={isMobile ? { flex: 1, minWidth: 0 } : { width: 140 }}
        disabled={isPolling}
      >
        {Array.from({ length: 25 }, (_, i) => i + 1).map((w) => {
          const isCurrentWeek =
            isViewingCurrentSemester && currentWeek === w && !inBreak && !holidayModeActive;
          return (
            <Option key={w} value={w}>
              <span
                style={{
                  fontWeight: isCurrentWeek ? "bold" : "normal",
                  color: isCurrentWeek ? "#1890ff" : undefined,
                }}
              >
                第{w}周 {isCurrentWeek ? "(本周)" : ""}
              </span>
            </Option>
          );
        })}
      </Select>
    );

    const actions = (
      <>
        {isAdmin && (
          <Button
            icon={<ImportOutlined />}
            onClick={handleImport}
            disabled={isPolling}
            loading={isPolling}
          >
            导入
          </Button>
        )}
        {isAdmin && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => handleAdd()}
            disabled={isPolling}
          >
            新增课程
          </Button>
        )}
        {isAdmin && (
          <Button
            icon={<ScheduleOutlined />}
            onClick={handleSyncCurrentWeek}
            disabled={isPolling || holidayStatus?.active}
            loading={isPolling}
          >
            同步课表
          </Button>
        )}
        {isAdmin && (
          <Button
            icon={<SyncOutlined />}
            onClick={() => {
              setIsFullCrawl(true);
              setCrawlModalVisible(true);
            }}
            disabled={isPolling || holidayStatus?.active}
          >
            全量爬取
          </Button>
        )}
        <Button
          icon={<ReloadOutlined />}
          onClick={() => {
            fetchTimetable(selectedWeek);
            fetchCourses();
          }}
          disabled={isPolling}
        >
          刷新
        </Button>
      </>
    );

    if (isMobile) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
          {/* 第一行：学期 + 周次 */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {termSelect}
            {weekSelect}
          </div>
          {/* 第二行：操作按钮 */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>
        </div>
      );
    }

    return (
      <Space wrap style={{ justifyContent: "flex-end" }}>
        {termSelect}
        {weekSelect}
        {actions}
      </Space>
    );
  };

  return (
    <div style={{ padding: isMobile ? 8 : 24 }} className="course-page">
      <Card
        className="course-card"
        title={
          <Space wrap align="center">
            <CalendarOutlined />
            {showHoliday ? "假期模式" : selectedWeek ? `第${selectedWeek}周课表` : "课程管理"}
            {viewSwitch}
            {isPolling && <Badge dot offset={[4, -4]} />}
            {!showHoliday &&
              isViewingCurrentSemester &&
              currentStatus.hasCurrentCourse &&
              currentStatus.isTeachingWeek &&
              currentWeek === selectedWeek &&
              currentStatus.currentPeriod >= 1 &&
              currentStatus.currentPeriod <= 12 && (
                <Tag color="red" icon={<ClockCircleOutlined />}>
                  上课中 - 第{currentStatus.currentPeriod}节
                </Tag>
              )}
          </Space>
        }
        extra={isMobile ? null : renderToolbar()}
      >
        {isMobile && renderToolbar()}
        {isPolling && (
          <Alert
            message={
              <div>
                <Space>
                  <LoadingOutlined spin />
                  <span>任务运行中，自动刷新...</span>
                </Space>
                {runningTasks.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    {runningTasks.map((task) => (
                      <div key={task.id} style={{ marginBottom: 4 }}>
                        <Tag color="processing">{task.task_type}</Tag>
                        <span style={{ fontSize: 12, color: "#666" }}>
                          {task.message || "正在执行..."}
                        </span>
                        {task.progress !== undefined && (
                          <Progress
                            percent={task.progress}
                            size="small"
                            style={{ marginTop: 4 }}
                            status={task.status === "failed" ? "exception" : "active"}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {crawlRunning.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    {crawlRunning.map((task) => (
                      <div key={`crawl-${task.id}`} style={{ marginBottom: 4 }}>
                        <Tag color="processing">
                          爬取任务
                          {task.scope === "all"
                            ? "·全量"
                            : task.semester_id
                              ? `·学期${task.semester_id}`
                              : ""}
                        </Tag>
                        <span style={{ fontSize: 12, color: "#666" }}>
                          {task.message || "正在执行..."}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            }
            type="info"
            showIcon={false}
            style={{ marginBottom: 16 }}
          />
        )}
        {loading ? (
          <div style={{ textAlign: "center", padding: 50 }}>
            <Spin size="large" />
          </div>
        ) : activeView === "timetable" ? (
          showHoliday ? (
            <HolidayCourseView
              today={currentTime}
              semesterName={semesterList.find((s: SemesterInfo) => s.id === selectedSemester)?.name}
              holidayPeriod={holidayStatus?.period ?? undefined}
            />
          ) : (
            <div
              style={
                isMobile
                  ? { width: "100%", overflow: "hidden" }
                  : { overflowX: "auto", WebkitOverflowScrolling: "touch" }
              }
            >
              <table
                style={{
                  width: "100%",
                  minWidth: isMobile ? "unset" : 900,
                  borderCollapse: "collapse",
                  tableLayout: "fixed",
                }}
              >
                {/* colgroup 锁定列宽：移动端只渲染有课的天，均分剩余宽度，空白列（如无课的周六/周日）不再占位置 */}
                <colgroup>
                  <col style={{ width: isMobile ? "34px" : "80px" }} />
                  {renderDayList.map((day) => (
                    <col
                      key={day}
                      style={{
                        width: `calc((100% - ${isMobile ? "34px" : "80px"}) / ${renderDayList.length})`,
                      }}
                    />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th
                      style={{
                        width: isMobile ? "32px" : "80px",
                        padding: isMobile ? "4px 2px" : "12px",
                        border: "1px solid #f0f0f0",
                        backgroundColor: "#fafafa",
                        fontSize: isMobile ? 11 : 14,
                      }}
                    >
                      {isMobile ? "节" : "时间"}
                    </th>
                    {renderDayList.map((day) => {
                      // 计算该天的日期
                      const label = WEEK_DAY_MAP[day];
                      const weekNum = selectedWeek || 1;
                      const dateStr = getWeekDateLabel(
                        weekNum,
                        day,
                        timetableData?.available_weeks
                      );
                      // 只有"正在查看当前学期"且选中的周次是真实本周时，才显示"今天"
                      const isToday =
                        isViewingCurrentSemester &&
                        currentWeek === weekNum &&
                        currentStatus.currentWeekDay === day;
                      return (
                        <th
                          key={day}
                          style={{
                            padding: isMobile ? "4px 1px" : "12px",
                            border: "1px solid #f0f0f0",
                            backgroundColor: isToday ? "#e6f7ff" : "#fafafa",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              gap: isMobile ? 0 : 8,
                            }}
                          >
                            <span style={{ fontSize: isMobile ? 12 : 14 }}>{label}</span>
                            {isToday && !isMobile && <Tag color="blue">今天</Tag>}
                          </div>
                          {!isMobile && (
                            <div style={{ fontSize: 12, color: "#999", fontWeight: "normal" }}>
                              {dateStr}
                            </div>
                          )}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((period) => {
                    const periodInfo = PERIOD_MAP[period];
                    const isCurrentPeriod = false; // 节次列不高亮
                    return (
                      <tr key={period}>
                        <td
                          style={{
                            padding: isMobile ? "2px" : "8px",
                            border: isCurrentPeriod ? "2px solid #ff4d4f" : "1px solid #f0f0f0",
                            textAlign: "center",
                            backgroundColor: isCurrentPeriod ? "#fff1f0" : "#fafafa",
                          }}
                        >
                          <div
                            style={{
                              fontWeight: "bold",
                              fontSize: isMobile ? 11 : 14,
                              color: isCurrentPeriod ? "#ff4d4f" : undefined,
                            }}
                          >
                            {isMobile ? period : periodInfo?.name}
                          </div>
                        </td>
                        {renderDayList.map((day) => renderCourseCell(day, period))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <Table
            dataSource={courses}
            columns={columns}
            rowKey="id"
            scroll={isMobile ? undefined : { x: isAdmin ? 850 : 700 }}
          />
        )}
      </Card>

      {/* 编辑弹窗 */}
      <Modal
        title={editingCourse ? "编辑课程" : "新增课程"}
        open={modalVisible}
        onOk={() => {
          if (!isDeleting) {
            form
              .validateFields()
              .then((values) => {
                handleSave(values);
              })
              .catch((err) => {
                message.error("请检查必填字段");
              });
          }
        }}
        onCancel={() => {
          setModalVisible(false);
          setEditingCourse(null);
          form.resetFields();
        }}
        width={600}
        footer={[
          <Button
            key="back"
            onClick={() => {
              setModalVisible(false);
              setEditingCourse(null);
              form.resetFields();
            }}
          >
            取消
          </Button>,
          editingCourse && (
            <Button
              key="delete"
              danger
              onClick={() => editingCourse && handleDelete(editingCourse)}
              loading={isDeleting}
            >
              删除
            </Button>
          ),
          <Button
            key="submit"
            type="primary"
            onClick={() => {
              if (!isDeleting) {
                form
                  .validateFields()
                  .then((values) => {
                    handleSave(values);
                  })
                  .catch((err) => {
                    message.error("请检查必填字段");
                  });
              }
            }}
            loading={isDeleting}
          >
            {editingCourse ? "确定" : "新增"}
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" onFinish={handleSave}>
          <Form.Item
            name="course_name"
            label="课程名称"
            rules={[{ required: true, message: "请输入课程名称" }]}
          >
            <Input placeholder="请输入课程名称" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="week_day"
                label="星期"
                rules={[{ required: true, message: "请选择星期" }]}
              >
                <Select placeholder="选择星期">
                  {Object.entries(WEEK_DAY_MAP).map(([value, label]) => (
                    <Option key={value} value={Number(value)}>
                      {label}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="building"
                label="教学楼"
                rules={[{ required: true, message: "请选择教学楼" }]}
              >
                <Select
                  placeholder="选择教学楼"
                  onChange={(value) => {
                    // 教学楼变化时，清空节次选择
                    form.setFieldsValue({ period_idx: undefined });
                  }}
                >
                  {BUILDINGS.map((b) => (
                    <Option key={b.code} value={b.name}>
                      {b.name}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="period_idx"
                label="节次"
                rules={[{ required: true, message: "请选择节次" }]}
              >
                <Select
                  mode="multiple"
                  placeholder="选择节次"
                  onChange={handlePeriodChange}
                  style={{ width: "100%" }}
                >
                  {(() => {
                    const schedule = getScheduleByBuilding(selectedBuilding || "");
                    return Object.entries(schedule).map(([value, { name, start, end }]) => (
                      <Option key={value} value={Number(value)}>
                        {name} ({start}-{end})
                      </Option>
                    ));
                  })()}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="teacher" label="教师">
                <Input placeholder="教师姓名" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="classroom" label="教室">
                <Input placeholder="教室位置" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="weeks" label="上课周次">
                <Input placeholder="如: 1-16 或 1,3,5" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="start_time" label="开始时间">
                <Input placeholder="根据节次自动填充" disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="end_time" label="结束时间">
                <Input placeholder="根据节次自动填充" disabled />
              </Form.Item>
            </Col>
          </Row>
          {/* 推送开关使用本地状态管理 */}
          {editingCourse && (
            <Form.Item label="推送提醒" extra="关闭后不会推送课前提醒，课程卡片变灰">
              <Switch checked={pushEnabled} onChange={(checked) => setPushEnabled(checked)} />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 爬取调度弹窗 */}
      <CrawlScheduler
        visible={crawlModalVisible}
        isFullCrawl={isFullCrawl}
        onClose={() => {
          setCrawlModalVisible(false);
          setIsFullCrawl(false);
        }}
        onStarted={(taskId) => {
          // 有 taskId 时用按 id 轮询（能正确处理 pending→completed 全生命周期）
          if (taskId) startCrawlTaskPolling(taskId);
          else startPolling();
        }}
      />
    </div>
  );
}
