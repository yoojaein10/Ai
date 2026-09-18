import { Suspense, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Button,
  Card,
  Descriptions,
  Input,
  Modal,
  Spin,
  Tag,
  Timeline,
  Typography,
  message,
} from "antd";
import { PageShell } from "../../shell/PageShell";
import ApprovalLineView from "../../components/approval/ApprovalLineView";
import { resolveForm } from "../../components/approval/forms/FormRegistry";
import {
  useApproveStepMutation,
  useDocDetail,
  useRejectStepMutation,
  type DocStatus,
  type HistoryAction,
} from "../../api/approval";
import { useApprovalUIStore } from "../../store/approvalUI";

const STATUS_LABEL: Record<DocStatus, string> = {
  DRAFT: "임시",
  PENDING: "상신",
  IN_PROGRESS: "진행 중",
  APPROVED: "완료",
  REJECTED: "반려",
  RECALLED: "회수",
};
const STATUS_COLOR: Record<DocStatus, string> = {
  DRAFT: "default",
  PENDING: "gold",
  IN_PROGRESS: "blue",
  APPROVED: "green",
  REJECTED: "red",
  RECALLED: "default",
};
const ACTION_LABEL: Record<HistoryAction, string> = {
  PENDING: "요청",
  APPROVED: "승인",
  REJECTED: "반려",
  DELEGATED: "위임",
  COMMENTED: "의견",
  RECALLED: "회수",
};

export default function ApprovalDocDetail() {
  const { docId } = useParams<{ docId: string }>();
  const navigate = useNavigate();
  const id = docId ? Number(docId) : null;
  const { data, isLoading } = useDocDetail(id);

  const approve = useApproveStepMutation();
  const reject = useRejectStepMutation();
  const { actionComment, openAction, closeAction, setActionComment } =
    useApprovalUIStore();

  const [showAction, setShowAction] = useState<null | "approve" | "reject">(null);

  const onAction = () => {
    if (!id || !showAction) return;
    const fn = showAction === "approve" ? approve : reject;
    fn.mutate(
      { id, comment: actionComment || undefined },
      {
        onSuccess: () => {
          message.success(showAction === "approve" ? "승인되었습니다" : "반려되었습니다");
          setShowAction(null);
          closeAction();
        },
        onError: (err) => message.error(`처리 실패: ${(err as Error).message}`),
      },
    );
  };

  if (isLoading || !data || !id) {
    return (
      <PageShell title="문서 상세">
        <Spin />
      </PageShell>
    );
  }

  const Form = resolveForm(data.doc_type_code);

  return (
    <PageShell
      title={
        <span>
          <Typography.Text type="secondary" style={{ fontSize: 14, marginRight: 8 }}>
            {data.doc_no ?? "(미채번)"}
          </Typography.Text>
          {data.title}
        </span>
      }
      subtitle={
        <>
          <Tag color={STATUS_COLOR[data.status]}>{STATUS_LABEL[data.status]}</Tag>{" "}
          {data.doc_type_name} · 기안자 {data.drafter_name}
        </>
      }
      actions={
        <>
          <Button onClick={() => navigate(-1)}>뒤로</Button>
          {(data.status === "PENDING" || data.status === "IN_PROGRESS") && (
            <>
              <Button type="primary" onClick={() => { openAction("approve", id); setShowAction("approve"); }}>
                승인
              </Button>
              <Button danger onClick={() => { openAction("reject", id); setShowAction("reject"); }}>
                반려
              </Button>
            </>
          )}
        </>
      }
    >
      <Card size="small" title="결재선" style={{ marginBottom: 12 }}>
        <ApprovalLineView
          steps={data.line_steps}
          currentStep={data.current_step}
          status={data.status}
          history={data.history}
        />
      </Card>

      <Card size="small" title="문서 본문" style={{ marginBottom: 12 }}>
        <Descriptions size="small" column={2} bordered style={{ marginBottom: 12 }}>
          <Descriptions.Item label="문서번호">{data.doc_no ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="문서 종류">{data.doc_type_name}</Descriptions.Item>
          <Descriptions.Item label="기안자">{data.drafter_name}</Descriptions.Item>
          <Descriptions.Item label="기안일">
            {data.drafted_at?.replace("T", " ").slice(0, 16)}
          </Descriptions.Item>
        </Descriptions>
        <Suspense fallback={<Spin />}>
          <Form mode="view" initialData={data.content ?? {}} readOnly />
        </Suspense>
      </Card>

      <Card size="small" title="진행 이력">
        {data.history.length === 0 ? (
          <Typography.Text type="secondary">이력이 없습니다.</Typography.Text>
        ) : (
          <Timeline
            items={data.history.map((h) => ({
              color:
                h.action === "APPROVED"
                  ? "green"
                  : h.action === "REJECTED"
                    ? "red"
                    : h.action === "RECALLED"
                      ? "gray"
                      : "blue",
              children: (
                <div>
                  <div>
                    <strong>{ACTION_LABEL[h.action]}</strong>{" "}
                    <Typography.Text type="secondary">
                      {h.step_order > 0 ? `${h.step_order}단계 · ` : ""}
                      {h.approver_name ?? `user#${h.approver_id}`}
                    </Typography.Text>
                  </div>
                  {h.comment && <div>{h.comment}</div>}
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {h.acted_at?.replace("T", " ").slice(0, 16)}
                  </Typography.Text>
                </div>
              ),
            }))}
          />
        )}
      </Card>

      <Modal
        open={showAction !== null}
        title={showAction === "approve" ? "결재 승인" : "결재 반려"}
        okText={showAction === "approve" ? "승인" : "반려"}
        okButtonProps={{ danger: showAction === "reject" }}
        cancelText="취소"
        onOk={onAction}
        onCancel={() => { setShowAction(null); closeAction(); }}
        confirmLoading={approve.isPending || reject.isPending}
      >
        <Input.TextArea
          rows={4}
          value={actionComment}
          onChange={(e) => setActionComment(e.target.value)}
          placeholder={showAction === "approve" ? "검토 의견 (선택)" : "반려 사유"}
        />
      </Modal>
    </PageShell>
  );
}
