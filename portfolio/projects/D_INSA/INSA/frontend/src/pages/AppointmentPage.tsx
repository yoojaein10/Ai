import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useEmployees } from "../api/employees";
import { useCreateAppointment } from "../api/appointments";
import { useDepartments } from "../api/departments";
import type { ColumnsType } from "antd/es/table";

const { Title } = Typography;

const apptTypes = ["신규", "전보", "승진", "직위변경", "퇴직"];
const rankOptions = ["사원", "대리", "과장", "차장", "부장", "이사"];
const positionOptions = ["팀원", "팀장", "실장", "본부장"];

export default function AppointmentPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const { data: empData, isLoading } = useEmployees({ page, search: search || undefined, page_size: 10 });
  const { data: departments } = useDepartments();
  const createAppt = useCreateAppointment();

  const columns: ColumnsType<Record<string, unknown>> = [
    { title: "사번", dataIndex: "emp_no", key: "emp_no", width: 100 },
    { title: "성명", dataIndex: "name_ko", key: "name_ko", width: 80 },
    { title: "부서", dataIndex: "department_name", key: "dept", width: 100 },
    { title: "직급", dataIndex: "job_rank", key: "rank", width: 70 },
    { title: "직위", dataIndex: "job_position", key: "pos", width: 70 },
    {
      title: "상태",
      dataIndex: "emp_status",
      key: "status",
      width: 60,
      render: (s: string) => <Tag color={s === "재직" ? "green" : "red"}>{s}</Tag>,
    },
    {
      title: "",
      key: "action",
      width: 80,
      render: (_, record) => (
        <Button
          size="small"
          type="primary"
          onClick={() => {
            form.setFieldsValue({
              employee_id: record.id,
              employee_name: `${record.name_ko} (${record.emp_no})`,
            });
            setModalOpen(true);
          }}
        >
          발령
        </Button>
      ),
    },
  ];

  const onSubmit = async () => {
    const values = await form.validateFields();
    createAppt.mutate(
      {
        employee_id: values.employee_id,
        appt_type: values.appt_type,
        appt_date: (values.appt_date as dayjs.Dayjs).format("YYYY-MM-DD"),
        new_dept_id: values.new_dept_id ?? null,
        new_rank: values.new_rank ?? null,
        new_position: values.new_position ?? null,
        description: values.description ?? null,
      },
      {
        onSuccess: () => {
          message.success("발령이 등록되었습니다");
          setModalOpen(false);
          form.resetFields();
        },
        onError: () => message.error("발령 등록에 실패했습니다"),
      }
    );
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "발령관리" }, { title: "인사발령" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>인사발령</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Input
            placeholder="사번 또는 성명 검색"
            prefix={<SearchOutlined />}
            style={{ width: 200 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onPressEnter={() => setPage(1)}
          />
          <Button type="primary" onClick={() => setPage(1)}>검색</Button>
          <Button onClick={() => { setSearch(""); setPage(1); }}>초기화</Button>
        </Space>
      </Card>

      <Card size="small" title="사원 목록 — 발령 대상자 선택">
        <Table
          columns={columns}
          dataSource={empData?.items as Record<string, unknown>[] | undefined}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={{
            current: page,
            pageSize: 10,
            total: empData?.total,
            onChange: setPage,
            size: "small",
            showTotal: (total) => `총 ${total}명`,
          }}
        />
      </Card>

      <Modal
        title="인사발령 등록"
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={createAppt.isPending}
        okText="발령 등록"
        cancelText="취소"
        width={500}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="employee_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="employee_name" label="대상자">
            <Input disabled />
          </Form.Item>
          <Form.Item name="appt_type" label="발령유형" rules={[{ required: true, message: "발령유형을 선택하세요" }]}>
            <Select options={apptTypes.map((t) => ({ value: t, label: t }))} placeholder="선택" />
          </Form.Item>
          <Form.Item name="appt_date" label="발령일" rules={[{ required: true, message: "발령일을 선택하세요" }]}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="new_dept_id" label="변경 부서">
            <Select
              allowClear
              placeholder="변경 시 선택"
              options={departments?.map((d) => ({ value: d.id, label: d.name })) ?? []}
            />
          </Form.Item>
          <Form.Item name="new_rank" label="변경 직급">
            <Select allowClear placeholder="변경 시 선택" options={rankOptions.map((r) => ({ value: r, label: r }))} />
          </Form.Item>
          <Form.Item name="new_position" label="변경 직위">
            <Select
              allowClear
              placeholder="변경 시 선택"
              options={positionOptions.map((p) => ({ value: p, label: p }))}
            />
          </Form.Item>
          <Form.Item name="description" label="비고">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
