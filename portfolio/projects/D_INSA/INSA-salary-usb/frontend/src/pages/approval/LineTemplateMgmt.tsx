import { useMemo, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { PageShell } from "../../shell/PageShell";
import {
  useCreateTemplateMutation,
  useDeleteTemplateMutation,
  useDocTypes,
  useLineTemplates,
  useUpdateTemplateMutation,
  type ApproverType,
  type LineStepCreateBody,
  type LineTemplate,
} from "../../api/approval";

const APPROVER_TYPE_OPTIONS: { label: string; value: ApproverType }[] = [
  { label: "직속상사", value: "DIRECT_MANAGER" },
  { label: "부서장", value: "DEPT_HEAD" },
  { label: "직책 지정", value: "POSITION" },
  { label: "역할 지정", value: "ROLE" },
  { label: "사용자 지정", value: "USER" },
];

export default function LineTemplateMgmt() {
  const { data: docTypes } = useDocTypes(true);
  const [selectedDocTypeId, setSelectedDocTypeId] = useState<number | null>(null);
  const { data: templates, isLoading } = useLineTemplates(
    selectedDocTypeId ?? undefined,
  );

  const [editing, setEditing] = useState<LineTemplate | null>(null);
  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<LineStepCreateBody[]>([]);
  const [form] = Form.useForm();
  const create = useCreateTemplateMutation();
  const update = useUpdateTemplateMutation();
  const del = useDeleteTemplateMutation();

  const docTypeOptions = useMemo(
    () =>
      (docTypes ?? []).map((dt) => ({ label: `${dt.name} (${dt.code})`, value: dt.id })),
    [docTypes],
  );

  const openCreate = () => {
    if (!selectedDocTypeId) {
      message.warning("먼저 문서 타입을 선택하세요");
      return;
    }
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ scope: "GLOBAL", is_default: false });
    setSteps([
      { step_order: 1, approver_type: "DIRECT_MANAGER", approver_ref: null, is_required: true },
    ]);
    setOpen(true);
  };

  const openEdit = (t: LineTemplate) => {
    setEditing(t);
    form.setFieldsValue(t);
    setSteps(
      t.steps.map((s) => ({
        step_order: s.step_order,
        approver_type: s.approver_type,
        approver_ref: s.approver_ref,
        is_required: s.is_required,
      })),
    );
    setOpen(true);
  };

  const addStep = () => {
    setSteps((prev) => [
      ...prev,
      {
        step_order: prev.length + 1,
        approver_type: "DEPT_HEAD",
        approver_ref: null,
        is_required: true,
      },
    ]);
  };

  const removeStep = (idx: number) => {
    setSteps((prev) =>
      prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, step_order: i + 1 })),
    );
  };

  const updateStep = (idx: number, patch: Partial<LineStepCreateBody>) => {
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (steps.length === 0) {
      message.error("결재선에 최소 1단계가 필요합니다");
      return;
    }
    if (editing) {
      update.mutate(
        { id: editing.id, body: { ...values, steps } },
        {
          onSuccess: () => {
            message.success("수정되었습니다");
            setOpen(false);
          },
          onError: (err) => message.error((err as Error).message),
        },
      );
    } else {
      create.mutate(
        {
          doc_type_id: selectedDocTypeId!,
          name: values.name,
          scope: values.scope,
          scope_ref: values.scope_ref ?? null,
          is_default: values.is_default,
          steps,
        },
        {
          onSuccess: () => {
            message.success("생성되었습니다");
            setOpen(false);
          },
          onError: (err) => message.error((err as Error).message),
        },
      );
    }
  };

  const onDelete = (t: LineTemplate) => {
    Modal.confirm({
      title: "결재선 삭제",
      content: `"${t.name}" 템플릿을 삭제할까요?`,
      okText: "삭제",
      okButtonProps: { danger: true },
      cancelText: "취소",
      onOk: () =>
        del.mutate(t.id, {
          onSuccess: () => message.success("삭제되었습니다"),
          onError: (err) => message.error((err as Error).message),
        }),
    });
  };

  const columns: ColumnsType<LineTemplate> = [
    { title: "이름", dataIndex: "name" },
    {
      title: "범위",
      dataIndex: "scope",
      width: 100,
      render: (v: string) => (v === "GLOBAL" ? "전사" : "부서"),
    },
    {
      title: "기본값",
      dataIndex: "is_default",
      width: 80,
      render: (v: boolean) => (v ? <Tag color="gold">기본</Tag> : null),
    },
    { title: "단계 수", width: 80, render: (_, r) => r.steps.length },
    {
      title: "액션",
      width: 140,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => openEdit(r)}>
            수정
          </Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => onDelete(r)} />
        </Space>
      ),
    },
  ];

  return (
    <PageShell
      title="결재선 템플릿"
      subtitle="문서 타입별 결재 라인 관리"
      actions={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!selectedDocTypeId}>
          새 템플릿
        </Button>
      }
      toolbar={
        <Space>
          <span>문서 타입:</span>
          <Select
            value={selectedDocTypeId}
            onChange={setSelectedDocTypeId}
            options={docTypeOptions}
            placeholder="선택..."
            style={{ minWidth: 260 }}
            allowClear
          />
        </Space>
      }
    >
      <Card size="small">
        <Table
          columns={columns}
          dataSource={templates}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={false}
        />
      </Card>

      <Modal
        open={open}
        title={editing ? "결재선 수정" : "새 결재선"}
        onOk={onSubmit}
        onCancel={() => setOpen(false)}
        okText="저장"
        cancelText="취소"
        width={720}
        confirmLoading={create.isPending || update.isPending}
      >
        <Form form={form} layout="vertical" initialValues={{ scope: "GLOBAL", is_default: false }}>
          <Form.Item label="이름" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="범위" name="scope">
            <Select
              options={[
                { label: "전사", value: "GLOBAL" },
                { label: "부서", value: "DEPT" },
              ]}
            />
          </Form.Item>
          <Form.Item label="부서 ID (범위=부서일 때)" name="scope_ref">
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="기본 결재선" name="is_default" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>

        <Card size="small" title="결재 단계" extra={<Button size="small" onClick={addStep}>+ 단계 추가</Button>}>
          {steps.map((s, idx) => (
            <Space key={idx} style={{ width: "100%", marginBottom: 8 }}>
              <span style={{ width: 60 }}>{s.step_order}단계</span>
              <Select
                value={s.approver_type}
                onChange={(v) => updateStep(idx, { approver_type: v })}
                options={APPROVER_TYPE_OPTIONS}
                style={{ minWidth: 140 }}
              />
              <Input
                placeholder="참조값 (user_id / role code / position)"
                value={s.approver_ref ?? ""}
                onChange={(e) => updateStep(idx, { approver_ref: e.target.value || null })}
                style={{ minWidth: 220 }}
              />
              <Switch
                checked={s.is_required}
                checkedChildren="필수"
                unCheckedChildren="참조"
                onChange={(v) => updateStep(idx, { is_required: v })}
              />
              <Button danger size="small" icon={<DeleteOutlined />} onClick={() => removeStep(idx)} />
            </Space>
          ))}
        </Card>
      </Modal>
    </PageShell>
  );
}
