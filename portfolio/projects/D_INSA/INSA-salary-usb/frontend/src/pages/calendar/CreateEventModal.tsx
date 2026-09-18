import { useEffect } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  DatePicker,
  Switch,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import {
  useCreateEvent,
  type Calendar,
  type EventType,
  type Visibility,
} from "../../api/calendar";

const EVENT_TYPE_OPTIONS: { value: EventType; label: string }[] = [
  { value: "MANUAL", label: "일반" },
  { value: "LEAVE", label: "휴가" },
  { value: "TRAVEL", label: "출장" },
  { value: "MEETING", label: "회의" },
  { value: "OTHER", label: "기타" },
];

const VISIBILITY_OPTIONS: { value: Visibility; label: string }[] = [
  { value: "PUBLIC", label: "전체 공개" },
  { value: "DEPT", label: "부서 공개" },
  { value: "PRIVATE", label: "비공개" },
];

interface CreateEventModalProps {
  open: boolean;
  onClose: () => void;
  calendars: Calendar[];
  defaultStart?: Date | null;
  defaultEnd?: Date | null;
}

interface FormValues {
  calendar_id: number;
  title: string;
  event_type: EventType;
  range: [Dayjs, Dayjs];
  all_day: boolean;
  visibility: Visibility;
  location?: string;
  description?: string;
}

export function CreateEventModal({
  open,
  onClose,
  calendars,
  defaultStart,
  defaultEnd,
}: CreateEventModalProps) {
  const [form] = Form.useForm<FormValues>();
  const createMut = useCreateEvent();

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        calendar_id: calendars[0]?.id,
        event_type: "MANUAL",
        all_day: false,
        visibility: "PUBLIC",
        range: [
          defaultStart ? dayjs(defaultStart) : dayjs(),
          defaultEnd ? dayjs(defaultEnd) : dayjs().add(1, "hour"),
        ],
      });
    }
  }, [open, defaultStart, defaultEnd, calendars, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    const [start, end] = values.range;
    await createMut.mutateAsync({
      calendar_id: values.calendar_id,
      title: values.title,
      event_type: values.event_type,
      start_at: start.format("YYYY-MM-DDTHH:mm:ss"),
      end_at: end.format("YYYY-MM-DDTHH:mm:ss"),
      all_day: values.all_day,
      visibility: values.visibility,
      location: values.location || null,
      description: values.description || null,
    });
    form.resetFields();
    onClose();
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      title="이벤트 추가"
      okText="저장"
      cancelText="취소"
      confirmLoading={createMut.isPending}
      width={560}
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Form.Item
          name="calendar_id"
          label="캘린더"
          rules={[{ required: true }]}
        >
          <Select
            options={calendars.map((c) => ({
              value: c.id,
              label: c.name,
            }))}
          />
        </Form.Item>
        <Form.Item name="title" label="제목" rules={[{ required: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="event_type" label="구분" rules={[{ required: true }]}>
          <Select options={EVENT_TYPE_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="range"
          label="기간"
          rules={[{ required: true }]}
        >
          <DatePicker.RangePicker
            showTime={{ format: "HH:mm" }}
            style={{ width: "100%" }}
            format="YYYY-MM-DD HH:mm"
          />
        </Form.Item>
        <Form.Item
          name="all_day"
          label="종일"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="visibility"
          label="공개 범위"
          rules={[{ required: true }]}
        >
          <Select options={VISIBILITY_OPTIONS} />
        </Form.Item>
        <Form.Item name="location" label="장소">
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="description" label="설명">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
