import { useEffect, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Form,
  Select,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import { SaveOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useEvalRounds } from "../api/evalRounds";
import {
  useBulkUpsertEvalSchedules,
  useEvalSchedules,
  type EvalSchedule,
  type ScheduleStage,
} from "../api/evalSchedules";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const STAGE_OPTIONS: { value: ScheduleStage; label: string }[] = [
  { value: "TARGET", label: "목표 설정" },
  { value: "MID", label: "중간점검" },
  { value: "FINAL", label: "기말실적" },
  { value: "COMPREHENSIVE", label: "종합평가" },
];

interface Row {
  key: string;
  stage: ScheduleStage;
  range: [Dayjs | null, Dayjs | null] | null;
}

export default function EvalSchedulePage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: existing } = useEvalSchedules(selectedRoundId);
  const bulkMutation = useBulkUpsertEvalSchedules();

  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    if (existing) {
      setRows(
        existing.map((s: EvalSchedule) => ({
          key: String(s.id),
          stage: s.stage,
          range: [
            s.start_date ? dayjs(s.start_date) : null,
            s.end_date ? dayjs(s.end_date) : null,
          ],
        })),
      );
    }
  }, [existing]);

  const addRow = () => {
    setRows((prev) => [
      ...prev,
      { key: `new-${Date.now()}`, stage: "TARGET", range: null },
    ]);
  };

  const updateRow = (key: string, patch: Partial<Row>) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  };

  const removeRow = (key: string) => {
    setRows((prev) => prev.filter((r) => r.key !== key));
  };

  const handleSave = () => {
    if (selectedRoundId === null) {
      message.warning("회차를 먼저 선택하세요");
      return;
    }
    bulkMutation.mutate(
      {
        round_id: selectedRoundId,
        schedules: rows.map((r) => ({
          stage: r.stage,
          start_date: r.range?.[0]?.format("YYYY-MM-DD") ?? null,
          end_date: r.range?.[1]?.format("YYYY-MM-DD") ?? null,
        })),
      },
      {
        onSuccess: () => message.success("일정이 저장되었습니다"),
        onError: () => message.error("저장 실패"),
      },
    );
  };

  const columns: ColumnsType<Row> = [
    {
      title: "단계",
      dataIndex: "stage",
      key: "stage",
      render: (_, record) => (
        <Select
          style={{ width: 160 }}
          value={record.stage}
          options={STAGE_OPTIONS}
          onChange={(v) => updateRow(record.key, { stage: v })}
        />
      ),
    },
    {
      title: "기간",
      key: "range",
      render: (_, record) => (
        <DatePicker.RangePicker
          value={record.range as [Dayjs, Dayjs] | null}
          onChange={(v) => updateRow(record.key, { range: v })}
        />
      ),
    },
    {
      title: "",
      key: "action",
      width: 80,
      render: (_, record) => (
        <Button size="small" danger onClick={() => removeRow(record.key)}>
          삭제
        </Button>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "평가 설정" }, { title: "평가 일정" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        평가 일정
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Form.Item label="회차" style={{ marginBottom: 0 }}>
            <Select
              style={{ width: 240 }}
              value={selectedRoundId ?? undefined}
              placeholder="회차 선택"
              options={(rounds ?? []).map((r) => ({
                value: r.id,
                label: `${r.year} · ${r.name}`,
              }))}
              onChange={(v) => setSelectedRoundId(v)}
            />
          </Form.Item>
          <Button onClick={addRow} disabled={selectedRoundId === null}>
            단계 추가
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={bulkMutation.isPending}
            disabled={selectedRoundId === null}
          >
            저장
          </Button>
        </Space>
      </Card>

      <Table
        rowKey="key"
        columns={columns}
        dataSource={rows}
        pagination={false}
        size="small"
      />
    </>
  );
}
