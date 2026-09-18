import { useEffect } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Typography,
  message,
} from "antd";
import { useEvalRounds } from "../api/evalRounds";
import { useMe } from "../api/me";
import {
  usePerfMidterm,
  useUpsertPerfMidterm,
} from "../api/perfMidterm";
import { usePerfTargets } from "../api/perfTarget";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

export default function PerfMidtermPage() {
  const { selectedRoundId, setSelectedRoundId, selectedTargetId, setSelectedTargetId } =
    useEvalUIStore();
  const { data: me } = useMe();
  const { data: rounds } = useEvalRounds();
  const empId = me?.employee?.id ?? null;
  const { data: targets } = usePerfTargets({ emp_id: empId, round_id: selectedRoundId });
  const { data: midterm } = usePerfMidterm(selectedTargetId);
  const upsertMutation = useUpsertPerfMidterm();

  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      progress_rate: midterm?.progress_rate ? Number(midterm.progress_rate) : null,
      expected_rate: midterm?.expected_rate ? Number(midterm.expected_rate) : null,
      description: midterm?.description ?? "",
    });
  }, [midterm, form]);

  const handleSave = async () => {
    if (selectedTargetId == null) return;
    const v = await form.validateFields();
    upsertMutation.mutate(
      {
        target_id: selectedTargetId,
        progress_rate: v.progress_rate,
        expected_rate: v.expected_rate,
        description: v.description,
      },
      {
        onSuccess: () => message.success("저장되었습니다"),
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "저장 실패"),
      },
    );
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "성과평가" }, { title: "중간점검" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        중간점검
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
          <Select
            style={{ width: 320 }}
            placeholder="목표 선택"
            value={selectedTargetId ?? undefined}
            options={(targets ?? []).map((t) => ({
              value: t.id,
              label: `[${t.status}] ${t.target_value ?? "(no title)"}`,
            }))}
            onChange={setSelectedTargetId}
          />
        </Space>
      </Card>

      {selectedTargetId && (
        <Card title="중간점검 내용" size="small">
          <Form form={form} layout="vertical">
            <Form.Item name="progress_rate" label="진행률(%)">
              <InputNumber min={0} max={100} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="expected_rate" label="기대 달성률(%)">
              <InputNumber min={0} max={150} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="description" label="진행 내역">
              <Input.TextArea rows={5} />
            </Form.Item>
            <Button type="primary" loading={upsertMutation.isPending} onClick={handleSave}>
              저장
            </Button>
          </Form>
        </Card>
      )}
    </>
  );
}
