import { useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Modal,
  Select,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import {
  useBulkUpsertEvalApprovers,
  useDeleteEvalApprover,
  useEvalApprovers,
  type EvalApprover,
  type EvalType,
  type RaterType,
} from "../api/evalApprovers";
import { useEmployees } from "../api/employees";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const EVAL_TYPE_OPTIONS: { value: EvalType; label: string }[] = [
  { value: "PERF", label: "성과평가" },
  { value: "COMP", label: "역량평가" },
  { value: "MULTI", label: "다면평가" },
];

const RATER_TYPE_OPTIONS: { value: RaterType; label: string }[] = [
  { value: "BOSS", label: "상사" },
  { value: "PEER", label: "동료" },
  { value: "SUBORDINATE", label: "부하" },
];

export default function EvalApproverPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const [evalType, setEvalType] = useState<EvalType | undefined>(undefined);
  const [addOpen, setAddOpen] = useState(false);
  const [form] = Form.useForm();

  const { data: rounds } = useEvalRounds();
  const { data: approvers, isLoading } = useEvalApprovers(selectedRoundId, evalType);
  const { data: empList } = useEmployees({ page_size: 200 });
  const createMutation = useBulkUpsertEvalApprovers();
  const deleteMutation = useDeleteEvalApprover();

  const empById = useMemo(() => {
    const map = new Map<number, { emp_no: string; name_ko: string }>();
    (empList?.items ?? []).forEach((e) =>
      map.set(e.id, { emp_no: e.emp_no, name_ko: e.name_ko }),
    );
    return map;
  }, [empList]);

  const columns: ColumnsType<EvalApprover> = [
    {
      title: "피평가자",
      key: "evaluatee",
      render: (_, r) => {
        const e = empById.get(r.evaluatee_id);
        return e ? `${e.name_ko} (${e.emp_no})` : r.evaluatee_id;
      },
    },
    {
      title: "평가자",
      key: "evaluator",
      render: (_, r) => {
        const e = empById.get(r.evaluator_id);
        return e ? `${e.name_ko} (${e.emp_no})` : r.evaluator_id;
      },
    },
    { title: "평가종류", dataIndex: "eval_type", key: "eval_type", width: 100 },
    { title: "다면구분", dataIndex: "rater_type", key: "rater_type", width: 100 },
    {
      title: "",
      key: "action",
      width: 80,
      render: (_, r) => (
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={() =>
            deleteMutation.mutate(r.id, {
              onSuccess: () => message.success("삭제되었습니다"),
            })
          }
        />
      ),
    },
  ];

  const handleAdd = async () => {
    if (selectedRoundId === null) return;
    const values = await form.validateFields();
    createMutation.mutate(
      {
        round_id: selectedRoundId,
        items: [
          {
            evaluatee_id: values.evaluatee_id,
            evaluator_id: values.evaluator_id,
            eval_type: values.eval_type,
            rater_type: values.eval_type === "MULTI" ? values.rater_type : null,
          },
        ],
      },
      {
        onSuccess: () => {
          message.success("매핑 추가");
          setAddOpen(false);
          form.resetFields();
        },
        onError: () => message.error("추가 실패"),
      },
    );
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "평가 설정" }, { title: "평가자 매핑" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        평가자 매핑
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            style={{ width: 240 }}
            value={selectedRoundId ?? undefined}
            placeholder="회차 선택"
            options={(rounds ?? []).map((r) => ({
              value: r.id,
              label: `${r.year} · ${r.name}`,
            }))}
            onChange={setSelectedRoundId}
          />
          <Select
            style={{ width: 140 }}
            placeholder="평가종류"
            allowClear
            value={evalType}
            onChange={setEvalType}
            options={EVAL_TYPE_OPTIONS}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setAddOpen(true)}
            disabled={selectedRoundId === null}
          >
            매핑 추가
          </Button>
        </Space>
      </Card>

      <Table
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={approvers ?? []}
        pagination={false}
        size="small"
      />

      <Modal
        title="평가자 매핑 추가"
        open={addOpen}
        onOk={handleAdd}
        onCancel={() => setAddOpen(false)}
        confirmLoading={createMutation.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="evaluatee_id" label="피평가자" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={(empList?.items ?? []).map((e) => ({
                value: e.id,
                label: `${e.name_ko} (${e.emp_no})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="evaluator_id" label="평가자" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={(empList?.items ?? []).map((e) => ({
                value: e.id,
                label: `${e.name_ko} (${e.emp_no})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="eval_type" label="평가종류" rules={[{ required: true }]}>
            <Select options={EVAL_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, curr) => prev.eval_type !== curr.eval_type}
          >
            {({ getFieldValue }) =>
              getFieldValue("eval_type") === "MULTI" && (
                <Form.Item name="rater_type" label="다면구분" rules={[{ required: true }]}>
                  <Select options={RATER_TYPE_OPTIONS} />
                </Form.Item>
              )
            }
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
