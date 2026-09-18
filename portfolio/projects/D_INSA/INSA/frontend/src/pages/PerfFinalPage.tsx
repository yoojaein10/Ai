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
import { usePerfFinal, useUpsertPerfFinal } from "../api/perfFinal";
import { usePerfTargets } from "../api/perfTarget";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

export default function PerfFinalPage() {
  const { selectedRoundId, setSelectedRoundId, selectedTargetId, setSelectedTargetId } =
    useEvalUIStore();
  const { data: me } = useMe();
  const { data: rounds } = useEvalRounds();
  const empId = me?.employee?.id ?? null;
  const { data: targets } = usePerfTargets({ emp_id: empId, round_id: selectedRoundId });
  const { data: final } = usePerfFinal(selectedTargetId);
  const upsertMutation = useUpsertPerfFinal();

  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      achievement_rate: final?.achievement_rate ? Number(final.achievement_rate) : null,
      self_score: final?.self_score ? Number(final.self_score) : null,
      description: final?.description ?? "",
    });
  }, [final, form]);

  const handleSave = async () => {
    if (selectedTargetId == null) return;
    const v = await form.validateFields();
    upsertMutation.mutate(
      {
        target_id: selectedTargetId,
        achievement_rate: v.achievement_rate,
        self_score: v.self_score,
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
        items={[{ title: "인사평가" }, { title: "성과평가" }, { title: "기말실적" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        기말실적
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
        <Card title="기말 실적" size="small">
          <Form form={form} layout="vertical">
            <Form.Item name="achievement_rate" label="달성률(%)">
              <InputNumber min={0} max={200} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="self_score" label="자기평가 점수">
              <InputNumber min={0} max={100} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="description" label="실적 설명">
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
