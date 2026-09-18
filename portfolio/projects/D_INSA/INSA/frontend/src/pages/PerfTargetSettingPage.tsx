import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Checkbox,
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
import { PlusOutlined, SendOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import { useMe } from "../api/me";
import { usePerfKpis } from "../api/perfKpi";
import {
  useCreatePerfTarget,
  usePerfTargets,
  useSubmitPerfTarget,
  useUpdatePerfTarget,
  type PerfTarget,
  type TargetStatus,
} from "../api/perfTarget";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const STATUS_COLOR: Record<TargetStatus, string> = {
  DRAFT: "default",
  SUBMITTED: "processing",
  APPROVED: "success",
  REJECTED: "error",
};

export default function PerfTargetSettingPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: me } = useMe();
  const { data: rounds } = useEvalRounds();
  const empId = me?.employee?.id ?? null;

  const { data: targets } = usePerfTargets({ emp_id: empId, round_id: selectedRoundId });
  const { data: kpis } = usePerfKpis(selectedRoundId);

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<PerfTarget | null>(null);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  const createMutation = useCreatePerfTarget();
  const updateMutation = useUpdatePerfTarget(editTarget?.id ?? null);
  const submitMutation = useSubmitPerfTarget();

  const handleCreate = async () => {
    if (!empId || !selectedRoundId) return;
    const v = await form.validateFields();
    createMutation.mutate(
      {
        emp_id: empId,
        round_id: selectedRoundId,
        kpi_id: v.kpi_id ?? null,
        target_value: v.target_value,
        is_organization: !!v.is_organization,
        weight_percent: v.weight_percent ?? null,
      },
      {
        onSuccess: () => {
          message.success("목표가 추가되었습니다");
          setCreateOpen(false);
          form.resetFields();
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "추가 실패"),
      },
    );
  };

  const handleUpdate = async () => {
    if (!editTarget) return;
    const v = await editForm.validateFields();
    updateMutation.mutate(
      {
        kpi_id: v.kpi_id ?? null,
        target_value: v.target_value,
        is_organization: !!v.is_organization,
        weight_percent: v.weight_percent ?? null,
      },
      {
        onSuccess: () => {
          message.success("목표가 수정되었습니다");
          setEditTarget(null);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "수정 실패"),
      },
    );
  };

  const columns: ColumnsType<PerfTarget> = [
    { title: "목표", dataIndex: "target_value", key: "tv" },
    { title: "KPI", dataIndex: "kpi_id", key: "kpi", width: 100 },
    {
      title: "가중치(%)",
      dataIndex: "weight_percent",
      key: "wp",
      width: 110,
      render: (v) => v ?? "-",
    },
    {
      title: "조직",
      dataIndex: "is_organization",
      key: "org",
      width: 80,
      render: (v: boolean) => (v ? "Y" : "N"),
    },
    {
      title: "상태",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (s: TargetStatus) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
    },
    {
      title: "액션",
      key: "action",
      width: 200,
      render: (_, r) => (
        <Space>
          <Button
            size="small"
            disabled={r.status === "APPROVED" || r.status === "SUBMITTED"}
            onClick={() => {
              setEditTarget(r);
              editForm.setFieldsValue({
                kpi_id: r.kpi_id,
                target_value: r.target_value,
                is_organization: r.is_organization,
                weight_percent: r.weight_percent ? Number(r.weight_percent) : null,
              });
            }}
          >
            수정
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<SendOutlined />}
            disabled={r.status !== "DRAFT" && r.status !== "REJECTED"}
            onClick={() =>
              submitMutation.mutate(r.id, {
                onSuccess: () => message.success("제출되었습니다"),
                onError: (e: any) =>
                  message.error(e?.response?.data?.detail ?? "제출 실패"),
              })
            }
          >
            제출
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "성과평가" }, { title: "목표과제 작성" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        목표과제 작성
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            style={{ width: 280 }}
            placeholder="회차 선택"
            value={selectedRoundId ?? undefined}
            options={(rounds ?? []).map((r) => ({
              value: r.id,
              label: `${r.year} · ${r.name}`,
            }))}
            onChange={setSelectedRoundId}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!empId || !selectedRoundId}
            onClick={() => setCreateOpen(true)}
          >
            목표 추가
          </Button>
        </Space>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={targets ?? []}
        pagination={false}
        size="small"
      />

      <Modal
        title="목표 추가"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createMutation.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="kpi_id" label="KPI 매핑">
            <Select
              allowClear
              options={(kpis ?? []).map((k) => ({ value: k.id, label: `${k.code} · ${k.name}` }))}
            />
          </Form.Item>
          <Form.Item name="target_value" label="목표 내용" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="weight_percent" label="가중치(%)">
            <InputNumber min={0} max={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="is_organization" valuePropName="checked">
            <Checkbox>조직목표 여부</Checkbox>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="목표 수정"
        open={editTarget !== null}
        onOk={handleUpdate}
        onCancel={() => setEditTarget(null)}
        confirmLoading={updateMutation.isPending}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="kpi_id" label="KPI 매핑">
            <Select
              allowClear
              options={(kpis ?? []).map((k) => ({ value: k.id, label: `${k.code} · ${k.name}` }))}
            />
          </Form.Item>
          <Form.Item name="target_value" label="목표 내용" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="weight_percent" label="가중치(%)">
            <InputNumber min={0} max={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="is_organization" valuePropName="checked">
            <Checkbox>조직목표 여부</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
