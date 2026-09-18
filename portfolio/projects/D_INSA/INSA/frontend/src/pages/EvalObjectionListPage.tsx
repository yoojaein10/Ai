import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import { useMe } from "../api/me";
import {
  useCreateObjection,
  useObjections,
  useReviewObjection,
  type ObjectionResponse,
  type ReviewDecision,
} from "../api/evalObjection";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const STATUS_COLOR: Record<string, string> = {
  PENDING: "default",
  REVIEWED: "blue",
  ACCEPTED: "green",
  REJECTED: "red",
};

export default function EvalObjectionListPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: me } = useMe();
  const { data: list } = useObjections(selectedRoundId);
  const createMutation = useCreateObjection();
  const reviewMutation = useReviewObjection();

  const isAdmin = (me?.roles ?? []).some((r) =>
    ["SYSTEM_ADMIN", "HR_ADMIN"].includes(r),
  );

  const [createOpen, setCreateOpen] = useState(false);
  const [reason, setReason] = useState("");

  const [reviewTarget, setReviewTarget] = useState<ObjectionResponse | null>(
    null,
  );
  const [decision, setDecision] = useState<ReviewDecision>("ACCEPTED");
  const [comment, setComment] = useState("");

  const handleCreate = () => {
    if (selectedRoundId == null) {
      message.warning("회차를 선택하세요");
      return;
    }
    if (!reason.trim()) {
      message.warning("사유를 입력하세요");
      return;
    }
    createMutation.mutate(
      { round_id: selectedRoundId, reason: reason.trim() },
      {
        onSuccess: () => {
          message.success("이의신청이 접수되었습니다");
          setCreateOpen(false);
          setReason("");
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "접수 실패"),
      },
    );
  };

  const handleReview = () => {
    if (reviewTarget == null) return;
    reviewMutation.mutate(
      {
        objection_id: reviewTarget.id,
        decision,
        comment: comment || null,
      },
      {
        onSuccess: () => {
          message.success("재심의가 완료되었습니다");
          setReviewTarget(null);
          setComment("");
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "처리 실패"),
      },
    );
  };

  const columns: ColumnsType<ObjectionResponse> = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "사원ID", dataIndex: "emp_id", key: "emp_id", width: 80 },
    { title: "사유", dataIndex: "reason", key: "reason", ellipsis: true },
    {
      title: "상태",
      dataIndex: "status",
      key: "s",
      width: 110,
      render: (s) => <Tag color={STATUS_COLOR[s] ?? "default"}>{s}</Tag>,
    },
    {
      title: "등록일",
      dataIndex: "created_at",
      key: "ca",
      width: 170,
      render: (v) => new Date(v).toLocaleString(),
    },
    ...(isAdmin
      ? [
          {
            title: "처리",
            key: "act",
            width: 100,
            render: (_: any, row: ObjectionResponse) =>
              row.status === "PENDING" || row.status === "REVIEWED" ? (
                <a onClick={() => setReviewTarget(row)}>재심의</a>
              ) : (
                <span style={{ color: "#999" }}>완료</span>
              ),
          },
        ]
      : []),
  ];

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "종합평가" },
          { title: "이의신청" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        이의신청
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
          {!isAdmin && (
            <Button
              type="primary"
              onClick={() => setCreateOpen(true)}
              disabled={selectedRoundId == null}
            >
              이의신청 작성
            </Button>
          )}
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

      <Modal
        open={createOpen}
        title="이의신청 작성"
        onCancel={() => {
          setCreateOpen(false);
          setReason("");
        }}
        onOk={handleCreate}
        confirmLoading={createMutation.isPending}
        okText="제출"
        cancelText="취소"
      >
        <Input.TextArea
          rows={5}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="이의신청 사유를 자세히 작성하세요"
        />
      </Modal>

      <Modal
        open={reviewTarget != null}
        title={reviewTarget ? `이의신청 #${reviewTarget.id} 재심의` : ""}
        onCancel={() => {
          setReviewTarget(null);
          setComment("");
        }}
        onOk={handleReview}
        confirmLoading={reviewMutation.isPending}
        okText="저장"
        cancelText="취소"
      >
        {reviewTarget && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <div style={{ background: "#fafafa", padding: 8, borderRadius: 4 }}>
              {reviewTarget.reason}
            </div>
            <Select
              style={{ width: "100%" }}
              value={decision}
              onChange={(v) => setDecision(v as ReviewDecision)}
              options={[
                { value: "ACCEPTED", label: "ACCEPTED (수용)" },
                { value: "REJECTED", label: "REJECTED (기각)" },
              ]}
            />
            <Input.TextArea
              rows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="검토 코멘트 (선택)"
            />
          </Space>
        )}
      </Modal>
    </>
  );
}
