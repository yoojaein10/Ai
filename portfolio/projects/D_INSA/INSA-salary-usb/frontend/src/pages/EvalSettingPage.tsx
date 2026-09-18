import { useEffect, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import { SaveOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useEvalSetting,
  useUpsertEvalSetting,
  type GradeCriterion,
} from "../api/evalSettings";

const { Title } = Typography;

interface WeightRow {
  key: "perf" | "comp" | "multi";
  label: string;
  value: number;
}

const DEFAULT_WEIGHTS: WeightRow[] = [
  { key: "perf", label: "성과", value: 40 },
  { key: "comp", label: "역량", value: 30 },
  { key: "multi", label: "다면", value: 30 },
];

const DEFAULT_CRITERIA: GradeCriterion[] = [
  { grade: "S", min: 90, max: 100, default_ratio: 10 },
  { grade: "A", min: 80, max: 90, default_ratio: 20 },
  { grade: "B", min: 70, max: 80, default_ratio: 40 },
  { grade: "C", min: 60, max: 70, default_ratio: 20 },
  { grade: "D", min: 0, max: 60, default_ratio: 10 },
];

export default function EvalSettingPage() {
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const { data, isLoading } = useEvalSetting(year);
  const upsertMutation = useUpsertEvalSetting();

  const [weights, setWeights] = useState<WeightRow[]>(DEFAULT_WEIGHTS);
  const [criteria, setCriteria] = useState<GradeCriterion[]>(DEFAULT_CRITERIA);

  useEffect(() => {
    if (data) {
      setWeights(
        DEFAULT_WEIGHTS.map((w) => ({
          ...w,
          value: data.weight_config[w.key] ?? 0,
        })),
      );
      setCriteria(data.grade_criteria.length ? data.grade_criteria : DEFAULT_CRITERIA);
    } else {
      setWeights(DEFAULT_WEIGHTS);
      setCriteria(DEFAULT_CRITERIA);
    }
  }, [data]);

  const weightSum = weights.reduce((sum, w) => sum + (w.value || 0), 0);

  const handleSave = () => {
    if (weightSum !== 100) {
      message.warning(`반영비율 합계가 ${weightSum}%입니다. 100%로 맞춰주세요.`);
      return;
    }
    upsertMutation.mutate(
      {
        year,
        weight_config: weights.reduce(
          (acc, w) => ({ ...acc, [w.key]: w.value }),
          {} as Record<string, number>,
        ),
        grade_criteria: criteria,
      },
      {
        onSuccess: () => message.success("저장되었습니다"),
        onError: () => message.error("저장 실패"),
      },
    );
  };

  const weightColumns: ColumnsType<WeightRow> = [
    { title: "구분", dataIndex: "label", key: "label", width: 120 },
    {
      title: "비율 (%)",
      key: "value",
      render: (_, r) => (
        <InputNumber
          min={0}
          max={100}
          value={r.value}
          onChange={(v) =>
            setWeights((prev) =>
              prev.map((w) => (w.key === r.key ? { ...w, value: Number(v) || 0 } : w)),
            )
          }
        />
      ),
    },
  ];

  const criteriaColumns: ColumnsType<GradeCriterion> = [
    {
      title: "등급",
      dataIndex: "grade",
      key: "grade",
      width: 100,
      render: (_, r, i) => (
        <Input
          value={r.grade}
          onChange={(e) =>
            setCriteria((prev) =>
              prev.map((c, idx) => (idx === i ? { ...c, grade: e.target.value } : c)),
            )
          }
        />
      ),
    },
    {
      title: "Min",
      dataIndex: "min",
      key: "min",
      width: 120,
      render: (_, r, i) => (
        <InputNumber
          value={r.min}
          onChange={(v) =>
            setCriteria((prev) =>
              prev.map((c, idx) => (idx === i ? { ...c, min: Number(v) || 0 } : c)),
            )
          }
        />
      ),
    },
    {
      title: "Max",
      dataIndex: "max",
      key: "max",
      width: 120,
      render: (_, r, i) => (
        <InputNumber
          value={r.max}
          onChange={(v) =>
            setCriteria((prev) =>
              prev.map((c, idx) => (idx === i ? { ...c, max: Number(v) || 0 } : c)),
            )
          }
        />
      ),
    },
    {
      title: "기본 비율 (%)",
      dataIndex: "default_ratio",
      key: "default_ratio",
      width: 140,
      render: (_, r, i) => (
        <InputNumber
          value={r.default_ratio}
          onChange={(v) =>
            setCriteria((prev) =>
              prev.map((c, idx) =>
                idx === i ? { ...c, default_ratio: Number(v) || 0 } : c,
              ),
            )
          }
        />
      ),
    },
    {
      title: "",
      key: "action",
      width: 80,
      render: (_, _r, i) => (
        <Button
          size="small"
          danger
          onClick={() => setCriteria((prev) => prev.filter((_, idx) => idx !== i))}
        >
          삭제
        </Button>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "평가 설정" }, { title: "반영비율/등급" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        반영비율 / 등급 기준
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Form.Item label="연도" style={{ marginBottom: 0 }}>
            <InputNumber
              value={year}
              min={2000}
              max={2100}
              onChange={(v) => typeof v === "number" && setYear(v)}
              style={{ width: 120 }}
            />
          </Form.Item>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={upsertMutation.isPending}
          >
            저장
          </Button>
        </Space>
      </Card>

      <Space align="start" style={{ width: "100%" }} size={16}>
        <Card
          size="small"
          title={`반영비율 (합계 ${weightSum}%)`}
          style={{ flex: 1 }}
        >
          <Table
            rowKey="key"
            loading={isLoading}
            columns={weightColumns}
            dataSource={weights}
            pagination={false}
            size="small"
          />
        </Card>

        <Card
          size="small"
          title="등급 기준"
          style={{ flex: 2 }}
          extra={
            <Button
              size="small"
              onClick={() =>
                setCriteria((prev) => [
                  ...prev,
                  { grade: "", min: 0, max: 0, default_ratio: 0 },
                ])
              }
            >
              등급 추가
            </Button>
          }
        >
          <Table
            rowKey={(r) => r.grade || Math.random().toString()}
            columns={criteriaColumns}
            dataSource={criteria}
            pagination={false}
            size="small"
          />
        </Card>
      </Space>
    </>
  );
}
