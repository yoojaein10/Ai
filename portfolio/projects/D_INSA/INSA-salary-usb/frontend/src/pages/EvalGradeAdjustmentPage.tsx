import { useMemo, useState } from "react";
import {
  Alert,
  Breadcrumb,
  Card,
  Col,
  Empty,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import {
  useAdjustGrade,
  useComprehensiveList,
  type ComprehensiveResponse,
} from "../api/evalComprehensive";
import { useEvalUIStore } from "../store/evalUI";

const { Title, Text } = Typography;
const GRADES = ["S", "A", "B", "C", "D"];

const fmt = (v: string | null) => (v == null ? "-" : Number(v).toFixed(2));

export default function EvalGradeAdjustmentPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: list } = useComprehensiveList(selectedRoundId);
  const adjust = useAdjustGrade();

  const [active, setActive] = useState<ComprehensiveResponse | null>(null);
  const [newGrade, setNewGrade] = useState<string>("S");
  const [reason, setReason] = useState<string>("");

  const distribution = useMemo(() => {
    const dist: Record<string, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
    (list ?? []).forEach((r) => {
      const g = r.final_grade ?? "-";
      if (g in dist) dist[g] = (dist[g] ?? 0) + 1;
    });
    return dist;
  }, [list]);

  const total = useMemo(() => (list ?? []).length, [list]);

  const handleSubmit = () => {
    if (active == null) return;
    if (!reason.trim()) {
      message.warning("변경 사유는 필수입니다");
      return;
    }
    adjust.mutate(
      {
        comp_id: active.id,
        new_grade: newGrade,
        adjusted_reason: reason.trim(),
      },
      {
        onSuccess: () => {
          message.success("등급이 조정되었습니다");
          setActive(null);
          setReason("");
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "조정 실패"),
      },
    );
  };

  const openModal = (row: ComprehensiveResponse) => {
    setActive(row);
    setNewGrade(row.final_grade ?? "B");
    setReason(row.adjusted_reason ?? "");
  };

  const columns: ColumnsType<ComprehensiveResponse> = [
    { title: "사원ID", dataIndex: "emp_id", key: "emp_id", width: 80 },
    { title: "총점", dataIndex: "total_score", key: "t", width: 90, render: fmt },
    { title: "원등급", dataIndex: "original_grade", key: "og", width: 80 },
    {
      title: "최종등급",
      dataIndex: "final_grade",
      key: "fg",
      width: 100,
      render: (g, row) => (
        <Space>
          <span>{g ?? "-"}</span>
          {row.is_adjusted && <Tag color="orange">조정</Tag>}
        </Space>
      ),
    },
    { title: "사유", dataIndex: "adjusted_reason", key: "r", ellipsis: true },
    {
      title: "조정",
      key: "act",
      width: 100,
      render: (_, row) => (
        <a onClick={() => openModal(row)}>편집</a>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "종합평가" },
          { title: "등급 조정" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        등급 조정 (인사위원회)
      </Title>

      <Alert
        type="info"
        showIcon
        message="원등급은 보존됩니다"
        description="조정 시 final_grade 만 변경되며 original_grade 는 변경되지 않습니다. 변경 사유는 필수 입력입니다."
        style={{ marginBottom: 12 }}
      />

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
            {GRADES.map((g) => (
              <Col span={4} key={g}>
                <Card size="small">
                  <Statistic
                    title={`${g} 등급`}
                    value={distribution[g] ?? 0}
                    suffix={` / ${total}`}
                  />
                </Card>
              </Col>
            ))}
          </Row>

          <Card size="small">
            <Table
              rowKey="id"
              columns={columns}
              dataSource={list ?? []}
              pagination={{ pageSize: 20 }}
              size="small"
            />
          </Card>
        </>
      )}

      <Modal
        open={active != null}
        title={active ? `사원 ${active.emp_id} 등급 조정` : ""}
        onCancel={() => {
          setActive(null);
          setReason("");
        }}
        onOk={handleSubmit}
        confirmLoading={adjust.isPending}
        okText="저장"
        cancelText="취소"
      >
        {active && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Text>총점: {fmt(active.total_score)}</Text>
            <Text>원등급: {active.original_grade ?? "-"}</Text>
            <div>
              <Text>새 등급</Text>
              <Select
                style={{ width: "100%" }}
                value={newGrade}
                onChange={setNewGrade}
                options={GRADES.map((g) => ({ value: g, label: g }))}
              />
            </div>
            <div>
              <Text>변경 사유 (필수)</Text>
              <Input.TextArea
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="조정 근거를 입력하세요"
              />
            </div>
          </Space>
        )}
      </Modal>
    </>
  );
}
