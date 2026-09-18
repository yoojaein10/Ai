import { useMemo, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { PageShell } from "../../shell/PageShell";
import {
  useCreateHoliday,
  useDeleteHoliday,
  useHolidays,
  type Holiday,
} from "../../api/holiday";

type FormValues = {
  date: Dayjs;
  name: string;
  is_recurring: boolean;
};

function thisYear() {
  return new Date().getFullYear();
}

export default function HolidayMgmtPage() {
  const [year, setYear] = useState<number>(thisYear());
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const { data = [], isLoading } = useHolidays(year);
  const create = useCreateHoliday();
  const remove = useDeleteHoliday();

  const yearOptions = useMemo(() => {
    const y = thisYear();
    return [y - 1, y, y + 1, y + 2].map((v) => ({ value: v, label: `${v}년` }));
  }, []);

  const onCreate = () => {
    form
      .validateFields()
      .then((v) => {
        create.mutate(
          {
            date: v.date.format("YYYY-MM-DD"),
            name: v.name,
            is_recurring: !!v.is_recurring,
          },
          {
            onSuccess: () => {
              message.success("공휴일이 등록되었습니다");
              setOpen(false);
              form.resetFields();
            },
            onError: (err) =>
              message.error(
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                (err as any)?.response?.data?.detail ??
                  (err as Error).message,
              ),
          },
        );
      })
      .catch(() => {});
  };

  const onDelete = (id: number) => {
    remove.mutate(id, {
      onSuccess: () => message.success("삭제되었습니다"),
      onError: (err) =>
        message.error(
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (err as any)?.response?.data?.detail ?? (err as Error).message,
        ),
    });
  };

  const columns: ColumnsType<Holiday> = [
    { title: "날짜", dataIndex: "date", width: 130 },
    {
      title: "요일",
      width: 70,
      render: (_, r) => dayjs(r.date).format("ddd"),
    },
    { title: "이름", dataIndex: "name" },
    {
      title: "반복",
      dataIndex: "is_recurring",
      width: 100,
      render: (v: boolean) =>
        v ? <Tag color="blue">매년 반복</Tag> : <Tag>단년</Tag>,
    },
    {
      title: "등록일",
      dataIndex: "created_at",
      width: 170,
      render: (v: string | null) =>
        v ? v.replace("T", " ").slice(0, 16) : "-",
    },
    {
      title: "액션",
      width: 90,
      render: (_, r) => (
        <Popconfirm
          title="이 공휴일을 삭제하시겠습니까?"
          okText="삭제"
          cancelText="닫기"
          onConfirm={() => onDelete(r.id)}
        >
          <Button size="small" danger>
            삭제
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <PageShell
      title="공휴일 관리"
      subtitle="영업일 계산에 반영되는 공휴일 등록"
      actions={
        <Space>
          <Select
            size="small"
            value={year}
            options={yearOptions}
            onChange={setYear}
            style={{ width: 110 }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setOpen(true)}
          >
            공휴일 등록
          </Button>
        </Space>
      }
    >
      <Card size="small">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {year}년 기준 · 총 {data.length}건 (반복 공휴일은 연도별로 자동 노출)
        </Typography.Text>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 30, size: "small" }}
          style={{ marginTop: 8 }}
          locale={{ emptyText: "등록된 공휴일이 없습니다" }}
        />
      </Card>

      <Modal
        title="공휴일 등록"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={onCreate}
        okText="등록"
        cancelText="닫기"
        confirmLoading={create.isPending}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          size="small"
          initialValues={{ is_recurring: false }}
        >
          <Form.Item
            name="date"
            label="날짜"
            rules={[{ required: true, message: "날짜를 선택하세요" }]}
          >
            <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item
            name="name"
            label="이름"
            rules={[{ required: true, message: "공휴일 이름을 입력하세요" }]}
          >
            <Input placeholder="예: 어린이날, 추석 연휴" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="is_recurring"
            valuePropName="checked"
            tooltip="매년 같은 월/일에 반복되는 공휴일 (양력 기준)"
          >
            <Checkbox>매년 반복 (양력)</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </PageShell>
  );
}
