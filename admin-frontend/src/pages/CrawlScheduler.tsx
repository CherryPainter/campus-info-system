/**
 * 课程爬取调度弹窗组件
 *
 * 支持：
 *  - 爬取范围：指定学期 / 全部学期（全量，遍历所有历史学期）
 *  - 执行方式：立即执行 / 预约时间
 *  - 创建后写入「爬取预约任务」，可在【进程管理】中查看并增删改查
 */
import { useState, useEffect } from "react";
import { Modal, Form, Select, Radio, Space, Alert, Tag, DatePicker } from "antd";
import { ScheduleOutlined } from "@ant-design/icons";
import dayjs, { Dayjs } from "dayjs";
import { courseApi } from "@/api/course";
import { useSemester } from "@/hooks/useSemester";
import { formatDateTime } from "@/utils/datetime";
import { useMessage } from "@/utils/message";

const { Option } = Select;

interface CrawlSchedulerProps {
  visible: boolean;
  onClose: () => void;
  onStarted?: (taskId?: number) => void; // 任务已创建并后台运行，交由父页面用 useTaskPolling 按 id 接管
  isFullCrawl?: boolean; // 预留，已不再强制全量
}

export default function CrawlScheduler({
  visible,
  onClose,
  onStarted,
  isFullCrawl = false,
}: CrawlSchedulerProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  // 学期列表与加载态统一由 useSemester Hook 提供（避免与 Course 重复实现 fetchSemesters）
  const { semesters: semesterList, loading: loadingSemesters, currentSemesterId } = useSemester();
  // 弹窗内的工作态学期选择（与 Course 视图的选中态隔离，避免互相污染）
  const [selectedSemester, setSelectedSemester] = useState<number | undefined>(undefined);
  const [selectedEamsId, setSelectedEamsId] = useState<string | undefined>(undefined);
  const message = useMessage();

  useEffect(() => {
    if (visible) {
      form.resetFields();
      form.setFieldsValue({ scope: "semester", schedule_type: "immediate" });
      // 学期已由 useSemester 自动选中当前项，同步到弹窗工作态与 eams_id
      const curId = currentSemesterId;
      if (curId !== undefined) {
        setSelectedSemester(curId);
        const cur = semesterList.find((s) => s.id === curId);
        setSelectedEamsId(cur?.eams_id ? String(cur.eams_id) : undefined);
        form.setFieldsValue({ semester_id: curId });
      }
    }
  }, [visible, currentSemesterId, semesterList]);

  // 提交
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      const payload: any = {
        scope: values.scope,
        schedule_type: values.schedule_type,
      };

      if (values.scope === "semester") {
        if (!selectedSemester) {
          message.error("请选择学期");
          setLoading(false);
          return;
        }
        payload.semester_id = selectedSemester;
        payload.eams_id = selectedEamsId;
      }

      if (values.schedule_type === "scheduled") {
        if (!values.scheduled_at) {
          message.error("请选择预约时间");
          setLoading(false);
          return;
        }
        const at: Dayjs = values.scheduled_at;
        if (at.isBefore(dayjs())) {
          message.error("预约时间必须晚于当前时间");
          setLoading(false);
          return;
        }
        payload.scheduled_at = at.format("YYYY-MM-DDTHH:mm:ss");
      }

      const res = await courseApi.crawlTasks.create(payload);
      if (res.status === "success") {
        const taskId = res.data?.id;
        if (values.schedule_type === "immediate") {
          message.success("爬取任务已启动，正在后台执行...");
          // 弹窗自身不再轮询（关闭即卸载），统一交由父组件通过 useTaskPolling 按 id 接管
          onStarted?.(taskId);
          onClose();
          setLoading(false);
        } else {
          const when = formatDateTime(payload.scheduled_at);
          message.success(`已预约，将于 ${when} 自动执行`);
          onClose();
          setLoading(false);
        }
      } else {
        message.error(res.message || "创建爬取任务失败");
        setLoading(false);
      }
    } catch (error) {
      console.error("提交失败:", error);
      setLoading(false);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <ScheduleOutlined />
          <span>课程表爬取调度</span>
        </Space>
      }
      open={visible}
      onOk={handleSubmit}
      onCancel={onClose}
      confirmLoading={loading}
      width={600}
      okText="创建任务"
      cancelText="取消"
    >
      <Alert
        message="爬取说明"
        description={
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            <li>指定学期：仅爬取所选学期的整学期课表（自动切换教务系统学期）</li>
            <li>全量爬取：遍历教务系统所有历史学期，逐个爬取并入库（耗时较长）</li>
            <li>预约任务创建后可在【进程管理 → 爬取预约】中查看、修改或删除</li>
          </ul>
        }
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 16 }}
        initialValues={{ scope: "semester", schedule_type: "immediate" }}
      >
        {/* 爬取范围 */}
        <Form.Item
          label="爬取范围"
          name="scope"
          rules={[{ required: true, message: "请选择爬取范围" }]}
        >
          <Radio.Group
            onChange={(e) => {
              if (
                e.target.value === "semester" &&
                selectedSemester === undefined &&
                semesterList.length
              ) {
                const cur = semesterList.find((s) => s.is_current);
                if (cur) {
                  setSelectedSemester(cur.id);
                  setSelectedEamsId(cur.eams_id ? String(cur.eams_id) : undefined);
                  form.setFieldsValue({ semester_id: cur.id });
                }
              }
            }}
          >
            <Radio value="semester">指定学期</Radio>
            <Radio value="all">全部学期（全量）</Radio>
          </Radio.Group>
        </Form.Item>

        {/* 学期选择（仅指定学期时） */}
        <Form.Item noStyle shouldUpdate={(p, c) => p.scope !== c.scope}>
          {({ getFieldValue }) =>
            getFieldValue("scope") === "semester" ? (
              <Form.Item
                name="semester_id"
                label="选择学期"
                rules={[{ required: true, message: "请选择学期" }]}
              >
                <Select
                  placeholder="加载中..."
                  loading={loadingSemesters}
                  onChange={(value, opt: any) => {
                    setSelectedSemester(value);
                    setSelectedEamsId(opt?.eams_id ? String(opt.eams_id) : undefined);
                  }}
                >
                  {semesterList.map((sem) => (
                    <Option key={sem.id} value={sem.id} eams_id={sem.eams_id}>
                      <Space>
                        {sem.name}
                        {sem.is_current && <Tag color="blue">当前学期</Tag>}
                      </Space>
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            ) : null
          }
        </Form.Item>

        {/* 执行方式 */}
        <Form.Item
          label="执行方式"
          name="schedule_type"
          rules={[{ required: true, message: "请选择执行方式" }]}
        >
          <Radio.Group>
            <Radio value="immediate">立即执行</Radio>
            <Radio value="scheduled">预约时间</Radio>
          </Radio.Group>
        </Form.Item>

        {/* 预约时间（仅预约时） */}
        <Form.Item noStyle shouldUpdate={(p, c) => p.schedule_type !== c.schedule_type}>
          {({ getFieldValue }) =>
            getFieldValue("schedule_type") === "scheduled" ? (
              <Form.Item
                name="scheduled_at"
                label="预约执行时间"
                rules={[{ required: true, message: "请选择预约时间" }]}
              >
                <DatePicker
                  showTime
                  format="YYYY-MM-DD HH:mm"
                  placeholder="选择执行时间"
                  style={{ width: "100%" }}
                  disabledDate={(current) => current && current < dayjs().startOf("day")}
                />
              </Form.Item>
            ) : null
          }
        </Form.Item>
      </Form>
    </Modal>
  );
}
