import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  useCloseEvalRound,
  useCreateEvalRound,
  useEvalRounds,
  type EvalRound,
  type RoundStatus,
} from "../api/evalRounds";

const { Title } = Typography;

const STATUS_COLOR: Record<RoundStatus, string> = {
  PLANNED: "default",
  IN_PROGRESS: "processing",
  CLOSED: "success",
};

export default function EvalRoundPage() {
  const [year, setYear] = useState<number | undefined>(undefined);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const { data: rounds, isLoading } = useEvalRounds(year);
  const createMutation = useCreateEvalRound();
  const closeMutation = useCloseEvalRound();

  const columns: ColumnsType<EvalRound> = [
    { title: "연도", dataIndex: "year", key: "year", width: 80 },
    { title: "회차명", dataIndex: "name", key: "name" },
    { title: "시작", dataIndex: "start_date", key: "start", width: 120 },
    { title: "종료", dataIndex: "end_date", key: "end", width: 120 },
    {
      title: "상태",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (s: RoundStatus) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
    },
    {
      title: "액션",
      key: "action",
      width: 100,
      render: (_, record) =>
        record.status !== "CLOSED" && (
          <Button
            size="small"
            onClick={() => {
              closeMutation.mutate(record.id, {
                onSuccess: () => message.success("회차를 마감했습니다"),
                onError: () => message.error("마감 실패"),
              });
            }}
          >
            마감
          </Button>
        ),
    },
  ];

  const handleCreate = async () => {
    const values = await form.validateFields();
    createMutation.mutate(
      {
        year: values.year,
        name: values.name,
        start_date: values.range?.[0]?.format("YYYY-MM-DD") ?? null,
        end_date: values.range?.[1]?.format("YYYY-MM-DD") ?? null,
        status: values.status,
      },
      {
        onSuccess: () => {
          message.success("회차가 생성되었습니다");
          setCreateOpen(false);
          form.resetFields();
        },
        onError: () => message.error("생성 실패"),
      },
    );
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "평가 설정" }, { title: "평가 회차" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        평가 회차
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <InputNumber
            placeholder="연도"
            value={year}
            onChange={(v) => setYear(typeof v === "number" ? v : undefined)}
            style={{ width: 120 }}
          />
          <Button onClick={() => setYear(undefined)}>초기화</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            회차 생성
          </Button>
        </Space>
      </Card>

      <Table
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={rounds ?? []}
        pagination={false}
        size="small"
      />

      <Modal
        title="평가 회차 생성"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createMutation.isPending}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ year: dayjs().year(), status: "PLANNED" }}
        >
          <Form.Item name="year" label="연도" rules={[{ required: true }]}>
            <InputNumber style={{ width: "100%" }} min={2000} max={2100} />
          </Form.Item>
          <Form.Item name="name" label="회차명" rules={[{ required: true }]}>
            <Input placeholder="예: 2026 상반기 정기평가" />
          </Form.Item>
          <Form.Item name="range" label="기간">
            <DatePicker.RangePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="status" label="상태">
            <Select
              options={[
                { value: "PLANNED", label: "PLANNED" },
                { value: "IN_PROGRESS", label: "IN_PROGRESS" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
