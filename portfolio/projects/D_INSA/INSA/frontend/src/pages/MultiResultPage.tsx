import {
  Alert,
  Breadcrumb,
  Card,
  Empty,
  Select,
  Space,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import { useMe } from "../api/me";
import {
  useMyMultiResult,
  type MultiIndicatorResult,
} from "../api/multiResult";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

export default function MultiResultPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: me } = useMe();
  const { data: rounds } = useEvalRounds();
  const empId = me?.employee?.id ?? null;
  const { data: result } = useMyMultiResult(empId, selectedRoundId);

  const columns: ColumnsType<MultiIndicatorResult> = [
    { title: "지표", dataIndex: "indicator_name", key: "name" },
    {
      title: "평균 점수",
      dataIndex: "avg_score",
      key: "avg",
      width: 140,
      render: (v) => (v == null ? "-" : Number(v).toFixed(2)),
    },
    {
      title: "응답 수",
      dataIndex: "response_count",
      key: "cnt",
      width: 100,
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "다면평가" },
          { title: "내 결과" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        내 다면평가 결과
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
        </Space>
      </Card>

      {selectedRoundId == null ? (
        <Empty description="회차를 선택하세요" />
      ) : result?.insufficient ? (
        <Alert
          type="warning"
          showIcon
          message="응답자 부족"
          description={`익명성 보호를 위해 응답자가 최소 ${result.min_required}명 이상이어야 결과를 표시합니다.`}
        />
      ) : (
        <Card size="small">
          <Table
            rowKey="indicator_id"
            columns={columns}
            dataSource={result?.indicators ?? []}
            pagination={false}
            size="small"
          />
        </Card>
      )}
    </>
  );
}
