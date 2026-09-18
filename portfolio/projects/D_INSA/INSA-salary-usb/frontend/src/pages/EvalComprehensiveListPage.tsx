import {
  Breadcrumb,
  Button,
  Card,
  Empty,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import {
  useCalculateComprehensive,
  useComprehensiveList,
  type ComprehensiveResponse,
} from "../api/evalComprehensive";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const fmt = (v: string | null) => (v == null ? "-" : Number(v).toFixed(2));

export default function EvalComprehensiveListPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: list } = useComprehensiveList(selectedRoundId);
  const calcMutation = useCalculateComprehensive();

  const columns: ColumnsType<ComprehensiveResponse> = [
    { title: "사원ID", dataIndex: "emp_id", key: "emp_id", width: 80 },
    { title: "성과", dataIndex: "perf_score", key: "p", width: 90, render: fmt },
    { title: "역량", dataIndex: "comp_score", key: "c", width: 90, render: fmt },
    { title: "다면", dataIndex: "multi_score", key: "m", width: 90, render: fmt },
    {
      title: "총점",
      dataIndex: "total_score",
      key: "t",
      width: 90,
      render: fmt,
    },
    {
      title: "원등급",
      dataIndex: "original_grade",
      key: "og",
      width: 80,
      render: (g: string | null) => g ?? "-",
    },
    {
      title: "최종등급",
      dataIndex: "final_grade",
      key: "fg",
      width: 100,
      render: (g: string | null, row) => (
        <Space>
          <span>{g ?? "-"}</span>
          {row.is_adjusted && <Tag color="orange">조정</Tag>}
        </Space>
      ),
    },
    {
      title: "사유",
      dataIndex: "adjusted_reason",
      key: "reason",
      ellipsis: true,
      render: (v: string | null) => v ?? "-",
    },
  ];

  const handleCalculate = () => {
    if (selectedRoundId == null) {
      message.warning("회차를 선택하세요");
      return;
    }
    calcMutation.mutate(selectedRoundId, {
      onSuccess: (res) => message.success(`${res.upserted}명 계산 완료`),
      onError: (e: any) =>
        message.error(e?.response?.data?.detail ?? "계산 실패"),
    });
  };

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "종합평가" },
          { title: "종합평가 조회" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        종합평가 조회
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
            onClick={handleCalculate}
            loading={calcMutation.isPending}
          >
            일괄 계산
          </Button>
        </Space>
      </Card>

      {selectedRoundId == null ? (
        <Empty description="회차를 선택하세요" />
      ) : (
        <Card size="small">
          <Table
            rowKey="id"
            columns={columns}
            dataSource={list ?? []}
            pagination={{ pageSize: 20 }}
            size="small"
          />
        </Card>
      )}
    </>
  );
}
