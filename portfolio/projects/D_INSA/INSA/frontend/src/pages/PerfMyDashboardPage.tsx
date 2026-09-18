import { useMemo } from "react";
import {
  Breadcrumb,
  Card,
  Col,
  Empty,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import { useMe } from "../api/me";
import { usePerfTargets, type PerfTarget, type TargetStatus } from "../api/perfTarget";
import { usePerfResults } from "../api/perfResult";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const STATUS_COLOR: Record<TargetStatus, string> = {
  DRAFT: "default",
  SUBMITTED: "processing",
  APPROVED: "success",
  REJECTED: "error",
};

export default function PerfMyDashboardPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: me } = useMe();
  const { data: rounds } = useEvalRounds();

  const empId = me?.employee?.id ?? null;
  const { data: targets } = usePerfTargets({ emp_id: empId, round_id: selectedRoundId });
  const { data: results } = usePerfResults({ round_id: selectedRoundId });

  const myResults = useMemo(
    () => (results ?? []).filter((r) => r.emp_id === empId),
    [results, empId],
  );

  const counts = useMemo(() => {
    const data = targets ?? [];
    return {
      total: data.length,
      draft: data.filter((t) => t.status === "DRAFT").length,
      submitted: data.filter((t) => t.status === "SUBMITTED").length,
      approved: data.filter((t) => t.status === "APPROVED").length,
      rejected: data.filter((t) => t.status === "REJECTED").length,
    };
  }, [targets]);

  const columns: ColumnsType<PerfTarget> = [
    { title: "목표", dataIndex: "target_value", key: "target_value" },
    {
      title: "가중치(%)",
      dataIndex: "weight_percent",
      key: "weight_percent",
      width: 110,
      render: (v) => v ?? "-",
    },
    {
      title: "조직목표",
      dataIndex: "is_organization",
      key: "org",
      width: 100,
      render: (v: boolean) => (v ? "Y" : "N"),
    },
    {
      title: "상태",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (s: TargetStatus) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "성과평가" }, { title: "내 평가 현황" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        내 평가 현황
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

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}><Card size="small"><Statistic title="총 목표" value={counts.total} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="작성중" value={counts.draft} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="제출" value={counts.submitted} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="승인" value={counts.approved} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="반려" value={counts.rejected} /></Card></Col>
      </Row>

      <Card title="목표 목록" size="small" style={{ marginBottom: 12 }}>
        {empId == null ? (
          <Empty description="사원 정보가 매핑되어 있지 않습니다" />
        ) : (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={targets ?? []}
            pagination={false}
            size="small"
          />
        )}
      </Card>

      <Card title="내 평가 결과" size="small">
        {myResults.length === 0 ? (
          <Empty description="확정된 평가 결과가 없습니다" />
        ) : (
          <Row gutter={12}>
            {myResults.map((r) => (
              <Col key={r.id} span={6}>
                <Card size="small" title={`R#${r.round_id}`}>
                  <Statistic title="등급" value={r.grade ?? "-"} />
                  <Statistic title="점수" value={r.score ?? "-"} />
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>
    </>
  );
}
