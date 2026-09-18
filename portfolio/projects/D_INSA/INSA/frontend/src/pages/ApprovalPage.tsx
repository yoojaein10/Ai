import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Input,
  Modal,
  Radio,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { CheckOutlined, CloseOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useAllChangeRequests,
  useApproveChangeRequest,
  useRejectChangeRequest,
  type ChangeRequest,
} from "../api/changeRequests";

const { Title } = Typography;

const STATUS_COLOR: Record<ChangeRequest["status"], string> = {
  PENDING: "gold",
  APPROVED: "green",
  REJECTED: "red",
};

const STATUS_LABEL: Record<ChangeRequest["status"], string> = {
  PENDING: "대기",
  APPROVED: "승인",
  REJECTED: "반려",
};

export default function ApprovalPage() {
  const [statusFilter, setStatusFilter] = useState<string>("PENDING");
  const { data, isLoading } = useAllChangeRequests(statusFilter || undefined);
  const approve = useApproveChangeRequest();
  const reject = useRejectChangeRequest();

  const [reviewTarget, setReviewTarget] = useState<ChangeRequest | null>(null);
  const [reviewAction, setReviewAction] = useState<"approve" | "reject">("approve");
  const [comment, setComment] = useState("");

  const openReview = (req: ChangeRequest, action: "approve" | "reject") => {
    setReviewTarget(req);
    setReviewAction(action);
    setComment("");
  };

  const onSubmit = () => {
    if (!reviewTarget) return;
    const payload = { id: reviewTarget.id, comment: comment || undefined };
    const fn = reviewAction === "approve" ? approve : reject;
    fn.mutate(payload, {
      onSuccess: () => {
        message.success(reviewAction === "approve" ? "승인되었습니다" : "반려되었습니다");
        setReviewTarget(null);
      },
      onError: () => message.error("처리에 실패했습니다"),
    });
  };

  const columns: ColumnsType<ChangeRequest> = [
    {
      title: "상태",
      dataIndex: "status",
      key: "status",
      width: 70,
      render: (s: ChangeRequest["status"]) => (
        <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>
      ),
    },
    {
      title: "요청자",
      key: "requester",
      width: 140,
      render: (_, r) => (
        <span>
          {r.emp_name ?? "-"}{" "}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            ({r.emp_no ?? "-"})
          </Typography.Text>
        </span>
      ),
    },
    { title: "항목", dataIndex: "field_label", key: "field_label", width: 100 },
    {
      title: "변경전",
      dataIndex: "old_value",
      key: "old_value",
      render: (v: string | null) => v ?? <Typography.Text type="secondary">-</Typography.Text>,
    },
    {
      title: "변경후",
      dataIndex: "new_value",
      key: "new_value",
      render: (v: string | null) => (
        <Typography.Text strong>{v ?? "-"}</Typography.Text>
      ),
    },
    {
      title: "사유",
      dataIndex: "reason",
      key: "reason",
      render: (v: string | null) => v ?? <Typography.Text type="secondary">-</Typography.Text>,
    },
    {
      title: "요청일시",
      dataIndex: "requested_at",
      key: "requested_at",
      width: 150,
      render: (v: string) => v?.replace("T", " ").slice(0, 16),
    },
    {
      title: "처리",
      key: "actions",
      width: 150,
      render: (_, r) => {
        if (r.status !== "PENDING") {
          return (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {r.review_comment ?? "-"}
            </Typography.Text>
          );
        }
        return (
          <Space size="small">
            <Button
              type="primary"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => openReview(r, "approve")}
            >
              승인
            </Button>
            <Button
              danger
              size="small"
              icon={<CloseOutlined />}
              onClick={() => openReview(r, "reject")}
            >
              반려
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "인사관리" }, { title: "변경승인" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>변경승인</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Radio.Group
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <Radio.Button value="PENDING">대기</Radio.Button>
          <Radio.Button value="APPROVED">승인</Radio.Button>
          <Radio.Button value="REJECTED">반려</Radio.Button>
          <Radio.Button value="">전체</Radio.Button>
        </Radio.Group>
      </Card>

      <Card size="small" title={`총 ${data?.length ?? 0}건`}>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, size: "small" }}
        />
      </Card>

      <Modal
        title={reviewAction === "approve" ? "변경요청 승인" : "변경요청 반려"}
        open={!!reviewTarget}
        onOk={onSubmit}
        onCancel={() => setReviewTarget(null)}
        confirmLoading={approve.isPending || reject.isPending}
        okText={reviewAction === "approve" ? "승인" : "반려"}
        cancelText="취소"
        okButtonProps={{ danger: reviewAction === "reject" }}
      >
        {reviewTarget && (
          <div style={{ marginBottom: 12 }}>
            <div>
              <Typography.Text type="secondary">요청자:</Typography.Text>{" "}
              {reviewTarget.emp_name} ({reviewTarget.emp_no})
            </div>
            <div>
              <Typography.Text type="secondary">항목:</Typography.Text>{" "}
              {reviewTarget.field_label}
            </div>
            <div>
              <Typography.Text type="secondary">변경:</Typography.Text>{" "}
              {reviewTarget.old_value ?? "-"} → <strong>{reviewTarget.new_value ?? "-"}</strong>
            </div>
            {reviewTarget.reason && (
              <div>
                <Typography.Text type="secondary">사유:</Typography.Text> {reviewTarget.reason}
              </div>
            )}
          </div>
        )}
        <Input.TextArea
          rows={3}
          placeholder="검토 코멘트 (선택)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </Modal>
    </>
  );
}
