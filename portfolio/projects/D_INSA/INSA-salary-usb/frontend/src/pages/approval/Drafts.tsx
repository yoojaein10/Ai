import { useState } from "react";
import { Button, Card, Segmented, Space, Table, Tag, Typography, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import {
  useDrafts,
  useRecallDocMutation,
  type DocListItem,
  type DocStatus,
} from "../../api/approval";

const STATUS_LABEL: Record<DocStatus, string> = {
  DRAFT: "임시",
  PENDING: "상신",
  IN_PROGRESS: "진행 중",
  APPROVED: "완료",
  REJECTED: "반려",
  RECALLED: "회수",
};
const STATUS_TAG_COLOR: Record<DocStatus, string> = {
  DRAFT: "default",
  PENDING: "gold",
  IN_PROGRESS: "blue",
  APPROVED: "green",
  REJECTED: "red",
  RECALLED: "default",
};

type Tab = "all" | DocStatus;

export default function ApprovalDrafts() {
  const [tab, setTab] = useState<Tab>("all");
  const navigate = useNavigate();
  const filter: DocStatus | "" = tab === "all" ? "" : tab;
  const { data, isLoading } = useDrafts(filter);
  const recall = useRecallDocMutation();

  const onRecall = (id: number) => {
    recall.mutate(id, {
      onSuccess: () => message.success("회수되었습니다"),
      onError: (err) => message.error(`회수 실패: ${(err as Error).message}`),
    });
  };

  const columns: ColumnsType<DocListItem> = [
    {
      title: "상태",
      dataIndex: "status",
      width: 90,
      render: (s: DocStatus) => <Tag color={STATUS_TAG_COLOR[s]}>{STATUS_LABEL[s]}</Tag>,
    },
    { title: "문서번호", dataIndex: "doc_no", width: 140 },
    { title: "제목", dataIndex: "title" },
    { title: "문서 종류", dataIndex: "doc_type_name", width: 160 },
    {
      title: "진행",
      width: 100,
      render: (_, r) => `${r.current_step}/${r.total_steps}`,
    },
    {
      title: "기안일",
      dataIndex: "drafted_at",
      width: 150,
      render: (v: string) => v?.replace("T", " ").slice(0, 16),
    },
    {
      title: "액션",
      width: 120,
      render: (_, r) => (
        <Space size="small">
          {r.status === "PENDING" && r.current_step === 1 && (
            <Button
              size="small"
              danger
              onClick={(e) => {
                e.stopPropagation();
                onRecall(r.id);
              }}
            >
              회수
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <PageShell
      title="기안함"
      subtitle="내가 기안한 문서"
      actions={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate("/approval/docs/new")}
        >
          새 기안
        </Button>
      }
      toolbar={
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={[
            { label: "전체", value: "all" },
            { label: "임시", value: "DRAFT" },
            { label: "진행", value: "PENDING" },
            { label: "완료", value: "APPROVED" },
            { label: "반려", value: "REJECTED" },
            { label: "회수", value: "RECALLED" },
          ]}
        />
      }
    >
      <Card size="small">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          총 {data?.length ?? 0}건
        </Typography.Text>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, size: "small" }}
          onRow={(r) => ({
            onClick: () => navigate(`/approval/docs/${r.id}`),
            style: { cursor: "pointer" },
          })}
          style={{ marginTop: 8 }}
        />
      </Card>
    </PageShell>
  );
}
