import {
  Breadcrumb,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Typography,
} from "antd";
import { useEvalRounds } from "../api/evalRounds";
import { useMultiStatus } from "../api/multiResult";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

export default function MultiStatusPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: status } = useMultiStatus(selectedRoundId);

  const ratePercent = status ? Math.round(status.submission_rate * 100) : 0;

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "다면평가" },
          { title: "제출 현황" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        제출 현황 (관리자)
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
      ) : (
        <>
          <Row gutter={12} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="예상 평가 건" value={status?.expected ?? 0} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="제출 완료" value={status?.submitted ?? 0} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="제출률"
                  value={ratePercent}
                  suffix="%"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="최근 제출"
                  value={
                    status?.submitted_at_latest
                      ? new Date(status.submitted_at_latest).toLocaleString()
                      : "-"
                  }
                  valueStyle={{ fontSize: 14 }}
                />
              </Card>
            </Col>
          </Row>

          <Card size="small">
            <Progress
              percent={ratePercent}
              status={ratePercent === 100 ? "success" : "active"}
            />
          </Card>
        </>
      )}
    </>
  );
}
