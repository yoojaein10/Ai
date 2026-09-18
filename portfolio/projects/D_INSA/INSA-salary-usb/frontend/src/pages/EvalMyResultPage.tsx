import {
  Alert,
  Breadcrumb,
  Card,
  Col,
  Descriptions,
  Empty,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEvalRounds } from "../api/evalRounds";
import { useComprehensiveList } from "../api/evalComprehensive";
import { useMe } from "../api/me";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const fmt = (v: string | null) => (v == null ? "-" : Number(v).toFixed(2));

export default function EvalMyResultPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: me } = useMe();
  const { data: list } = useComprehensiveList(selectedRoundId);

  const myEmpId = me?.employee?.id ?? null;
  const myRow = (list ?? []).find((r) => r.emp_id === myEmpId) ?? null;

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "종합평가" },
          { title: "내 종합 결과" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        내 종합 결과
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
      ) : myRow == null ? (
        <Empty description="해당 회차의 종합 결과가 아직 산정되지 않았습니다" />
      ) : (
        <>
          <Row gutter={12} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="성과" value={fmt(myRow.perf_score)} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="역량" value={fmt(myRow.comp_score)} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="다면" value={fmt(myRow.multi_score)} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="총점"
                  value={fmt(myRow.total_score)}
                  valueStyle={{ color: "#1677ff" }}
                />
              </Card>
            </Col>
          </Row>

          <Card size="small" style={{ marginBottom: 12 }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="원등급">
                {myRow.original_grade ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="최종등급">
                <Space>
                  <span>{myRow.final_grade ?? "-"}</span>
                  {myRow.is_adjusted && <Tag color="orange">조정</Tag>}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="산정일" span={2}>
                {new Date(myRow.calculated_at).toLocaleString()}
              </Descriptions.Item>
              {myRow.is_adjusted && (
                <Descriptions.Item label="조정 사유" span={2}>
                  {myRow.adjusted_reason ?? "-"}
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          {myRow.is_adjusted && (
            <Alert
              type="warning"
              showIcon
              message="등급 조정 이력"
              description="원등급과 최종등급이 다를 경우 인사위원회의 조정이 있었음을 의미합니다. 이의가 있는 경우 이의신청을 등록하세요."
            />
          )}
        </>
      )}
    </>
  );
}
