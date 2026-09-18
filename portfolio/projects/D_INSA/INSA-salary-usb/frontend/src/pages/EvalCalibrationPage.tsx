import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, PlusOutlined, TeamOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useAddCalibrationMembers,
  useCalibrationGroup,
  useCalibrationGroups,
  useCreateCalibrationGroup,
  useRemoveCalibrationMember,
  type CalibrationGroup,
  type CalibrationMember,
} from "../api/evalCalibration";
import { useEmployees } from "../api/employees";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

export default function EvalCalibrationPage() {
  const { selectedGroupId, setSelectedGroupId } = useEvalUIStore();
  const [year, setYear] = useState<number | undefined>(undefined);
  const [createOpen, setCreateOpen] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [form] = Form.useForm();
  const [memberForm] = Form.useForm();

  const { data: groups, isLoading } = useCalibrationGroups(year);
  const { data: detail } = useCalibrationGroup(selectedGroupId);
  const { data: empList } = useEmployees({ page_size: 200 });
  const createMutation = useCreateCalibrationGroup();
  const addMemberMutation = useAddCalibrationMembers(selectedGroupId);
  const removeMemberMutation = useRemoveCalibrationMember(selectedGroupId);

  const groupColumns: ColumnsType<CalibrationGroup> = [
    { title: "연도", dataIndex: "year", key: "year", width: 80 },
    { title: "그룹명", dataIndex: "name", key: "name" },
    { title: "인원", dataIndex: "member_count", key: "count", width: 80 },
    {
      title: "",
      key: "action",
      width: 120,
      render: (_, r) => (
        <Button size="small" icon={<TeamOutlined />} onClick={() => setSelectedGroupId(r.id)}>
          구성원
        </Button>
      ),
    },
  ];

  const memberColumns: ColumnsType<CalibrationMember> = [
    { title: "사번", dataIndex: "emp_no", key: "emp_no", width: 120 },
    { title: "성명", dataIndex: "emp_name", key: "name" },
    {
      title: "",
      key: "action",
      width: 60,
      render: (_, r) => (
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={() =>
            removeMemberMutation.mutate(r.emp_id, {
              onSuccess: () => message.success("제거"),
            })
          }
        />
      ),
    },
  ];

  const handleCreate = async () => {
    const values = await form.validateFields();
    createMutation.mutate(values, {
      onSuccess: () => {
        message.success("그룹 생성");
        setCreateOpen(false);
        form.resetFields();
      },
    });
  };

  const handleAddMembers = async () => {
    const values = await memberForm.validateFields();
    addMemberMutation.mutate(values.emp_ids, {
      onSuccess: (r) => {
        message.success(`${r.added}명 추가`);
        setMemberOpen(false);
        memberForm.resetFields();
      },
    });
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "평가 설정" }, { title: "보정집단" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        보정집단
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <InputNumber
            placeholder="연도"
            value={year}
            onChange={(v) => setYear(typeof v === "number" ? v : undefined)}
            style={{ width: 120 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            그룹 생성
          </Button>
        </Space>
      </Card>

      <Space align="start" style={{ width: "100%" }} size={16}>
        <Card size="small" title="그룹 목록" style={{ flex: 1 }}>
          <Table
            rowKey="id"
            loading={isLoading}
            columns={groupColumns}
            dataSource={groups ?? []}
            pagination={false}
            size="small"
          />
        </Card>
        <Card
          size="small"
          title={detail ? `${detail.name} — 구성원` : "구성원 (그룹 선택)"}
          style={{ flex: 1 }}
          extra={
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setMemberOpen(true)}
              disabled={selectedGroupId === null}
            >
              추가
            </Button>
          }
        >
          <Table
            rowKey="id"
            columns={memberColumns}
            dataSource={detail?.members ?? []}
            pagination={false}
            size="small"
          />
        </Card>
      </Space>

      <Modal
        title="보정집단 생성"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createMutation.isPending}
      >
        <Form form={form} layout="vertical" initialValues={{ year: new Date().getFullYear() }}>
          <Form.Item name="year" label="연도" rules={[{ required: true }]}>
            <InputNumber style={{ width: "100%" }} min={2000} max={2100} />
          </Form.Item>
          <Form.Item name="name" label="그룹명" rules={[{ required: true }]}>
            <Input placeholder="예: 과장급, 영업본부 등" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="구성원 추가"
        open={memberOpen}
        onOk={handleAddMembers}
        onCancel={() => setMemberOpen(false)}
        confirmLoading={addMemberMutation.isPending}
      >
        <Form form={memberForm} layout="vertical">
          <Form.Item name="emp_ids" label="직원 선택" rules={[{ required: true }]}>
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              options={(empList?.items ?? []).map((e) => ({
                value: e.id,
                label: `${e.name_ko} (${e.emp_no})`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
