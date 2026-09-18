import { useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Descriptions,
  Modal,
  Select,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import {
  useAiReportDetail,
  useAiReports,
  useGenerateBatch,
  useGenerateOne,
  type AiReportListItem,
} from "../api/aiReport";

const { Title, Paragraph } = Typography;

export default function EvalAiReportPage() {
  const [roundId, setRoundId] = useState<number | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);

  const roundsQuery = useEvalRounds();
  const reportsQuery = useAiReports(roundId);
  const detailQuery = useAiReportDetail(selectedReportId);
  const batchMutation = useGenerateBatch();
  const oneMutation = useGenerateOne();

  const onBatch = () => {
    if (roundId == null) return;
    Modal.confirm({
      title: "회차 전체 직원에 대해 AI 리포트를 생성합니다",
      content: "외부 LLM(Gemini) 호출이 발생합니다. 진행할까요?",
      okText: "생성",
      cancelText: "취소",
      onOk: async () => {
        try {
          const summary = await batchMutation.mutateAsync(roundId);
          message.success(`완료: 성공 ${summary.success}건 / 실패 ${summary.failed}건`);
        } catch (e: unknown) {
          const detail =
            (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          message.error(detail ?? "생성 실패");
        }
      },
    });
  };

  const columns: ColumnsType<AiReportListItem> = useMemo(
    () => [
      { title: "직원", dataIndex: "employee_name", key: "employee_name" },
      {
        title: "종합 점수",
        dataIndex: "total_score",
        key: "total_score",
        render: (v: string | null) => (v == null ? "-" : Number(v).toFixed(2)),
      },
      { title: "등급", dataIndex: "final_grade", key: "final_grade" },
      {
        title: "버전",
        dataIndex: "version",
        key: "version",
        render: (v: number | null) => (v == null ? "-" : `v${v}`),
      },
      {
        title: "상태",
        dataIndex: "status",
        key: "status",
        render: (s: string | null) => {
          if (s == null) return <Badge status="default" text="미생성" />;
          if (s === "SUCCESS") return <Badge status="success" text="완료" />;
          if (s === "FAILED") return <Badge status="error" text="실패" />;
          return <Badge status="processing" text="진행중" />;
        },
      },
      {
        title: "액션",
        key: "actions",
        render: (_: unknown, row) => (
          <Space>
            {row.report_id != null && (
              <Button
                size="small"
                onClick={() => {
                  setSelectedReportId(row.report_id);
                }}
              >
                열람
              </Button>
            )}
            <Button
              size="small"
              loading={oneMutation.isPending}
              onClick={async () => {
                if (roundId == null) return;
                await oneMutation.mutateAsync({
                  roundId,
                  employeeId: row.employee_id,
                });
                message.success("생성 완료");
              }}
            >
              재생성
            </Button>
          </Space>
        ),
      },
    ],
    [oneMutation, roundId],
  );

  const detail = detailQuery.data;

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>AI 인사평가 리포트</Title>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Select
            style={{ minWidth: 240 }}
            placeholder="회차 선택"
            options={(roundsQuery.data ?? []).map((r) => ({
              value: r.id,
              label: `${r.year}년 ${r.name}`,
            }))}
            value={roundId ?? undefined}
            onChange={(v) => {
              setRoundId(v);
              setSelectedReportId(null);
            }}
          />
          <Button
            type="primary"
            disabled={roundId == null}
            loading={batchMutation.isPending}
            onClick={onBatch}
          >
            회차 일괄 생성
          </Button>
        </Space>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card size="small" title="직원 목록">
          <Table
            rowKey="employee_id"
            size="small"
            loading={reportsQuery.isLoading}
            dataSource={reportsQuery.data ?? []}
            columns={columns}
            pagination={{ pageSize: 20 }}
          />
        </Card>

        <Card size="small" title={detail ? `리포트 v${detail.version}` : "리포트"}>
          {!detail && (
            <Paragraph type="secondary">왼쪽 테이블에서 "열람"을 누르세요.</Paragraph>
          )}
          {detail && detail.status === "FAILED" && (
            <Alert
              type="error"
              message="생성 실패"
              description={detail.error_message}
              showIcon
            />
          )}
          {detail && detail.status === "SUCCESS" && (
            <Space direction="vertical" style={{ width: "100%" }}>
              <Descriptions size="small" column={2} bordered>
                <Descriptions.Item label="종합 점수">
                  {detail.total_score == null ? "-" : Number(detail.total_score).toFixed(2)}
                </Descriptions.Item>
                <Descriptions.Item label="등급">{detail.final_grade ?? "-"}</Descriptions.Item>
                <Descriptions.Item label="다면 응답">
                  {detail.multi_response_count ?? "-"}
                </Descriptions.Item>
                <Descriptions.Item label="다면 포함">
                  {detail.multi_included ? "Y" : "N"}
                </Descriptions.Item>
                <Descriptions.Item label="모델">{detail.model_version}</Descriptions.Item>
                <Descriptions.Item label="프롬프트">{detail.prompt_version}</Descriptions.Item>
              </Descriptions>
              <Card size="small" type="inner" title="강점">
                <Paragraph>{detail.content_strengths}</Paragraph>
              </Card>
              <Card size="small" type="inner" title="개선 영역">
                <Paragraph>{detail.content_improvements}</Paragraph>
              </Card>
              <Card size="small" type="inner" title="코칭 포인트">
                <Paragraph>{detail.content_coaching}</Paragraph>
              </Card>
              <Card size="small" type="inner" title="면담 가이드">
                <Paragraph>{detail.content_interview_guide}</Paragraph>
              </Card>
            </Space>
          )}
        </Card>
      </div>
    </div>
  );
}
