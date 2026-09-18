import { useState } from "react";
import { Card, Segmented, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import {
  useInbox,
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

type Tab = "active" | "APPROVED" | "REJECTED";

export default function ApprovalInbox() {
  const [tab, setTab] = useState<Tab>("active");
  const navigate = useNavigate();
  const statusFilter: DocStatus | "" = tab === "active" ? "" : tab;
  const { data, isLoading } = useInbox(statusFilter);

  const columns: ColumnsType<DocListItem> = [
    {
      title: "상태",
      dataIndex: "status",
      width: 90,
      render: (s: DocStatus) => (
        <Tag color={STATUS_TAG_COLOR[s]}>{STATUS_LABEL[s]}</Tag>
      ),
    },
    { title: "문서번호", dataIndex: "doc_no", width: 140 },
    { title: "제목", dataIndex: "title" },
    { title: "문서 종류", dataIndex: "doc_type_name", width: 160 },
    { title: "기안자", dataIndex: "drafter_name", width: 120 },
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
  ];

  return (
    <PageShell
      title="결재함"
      subtitle="내가 결재해야 하는 문서"
      toolbar={
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={[
            { label: "대기/진행", value: "active" },
            { label: "완료", value: "APPROVED" },
            { label: "반려", value: "REJECTED" },
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
