import { useMemo, useState } from "react";
import {
  Button,
  Card,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import {
  useCancelLeave,
  useMyLeaveRequests,
  type LeaveRequestRow,
} from "../../api/leaveRequest";

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "임시",
  PENDING: "상신",
  IN_PROGRESS: "진행 중",
  APPROVED: "완료",
  REJECTED: "반려",
  RECALLED: "회수",
};
const STATUS_TAG_COLOR: Record<string, string> = {
  DRAFT: "default",
  PENDING: "gold",
  IN_PROGRESS: "blue",
  APPROVED: "green",
  REJECTED: "red",
  RECALLED: "default",
};

type Tab = "active" | "DRAFT" | "APPROVED" | "REJECTED" | "RECALLED" | "all";

function thisYear() {
  return new Date().getFullYear();
}

export default function MyLeaveRequestsPage() {
  const [year, setYear] = useState<number>(thisYear());
  const [tab, setTab] = useState<Tab>("active");
  const navigate = useNavigate();

  const statusParam =
    tab === "all" || tab === "active" ? undefined : (tab as string);
  const { data = [], isLoading } = useMyLeaveRequests({ year, status: statusParam });

  const cancel = useCancelLeave();

  const rows = useMemo(() => {
    if (tab === "active") {
      return data.filter((r) => r.status === "DRAFT" || r.status === "PENDING" || r.status === "IN_PROGRESS");
    }
    return data;
  }, [data, tab]);

  const yearOptions = useMemo(() => {
    const y = thisYear();
    return [y - 1, y, y + 1].map((v) => ({ value: v, label: `${v}년` }));
  }, []);

  const onCancel = (docId: number) => {
    cancel.mutate(docId, {
      onSuccess: () => message.success("취소되었습니다"),
      onError: (err) =>
        message.error(
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (err as any)?.response?.data?.detail ?? (err as Error).message,
        ),
    });
  };

  const columns: ColumnsType<LeaveRequestRow> = [
    {
      title: "상태",
      dataIndex: "status",
      width: 90,
      render: (s: string) => (
        <Tag color={STATUS_TAG_COLOR[s] ?? "default"}>
          {STATUS_LABEL[s] ?? s}
        </Tag>
      ),
    },
    { title: "문서번호", dataIndex: "doc_no", width: 140 },
    { title: "제목", dataIndex: "title" },
    {
      title: "휴가 종류",
      dataIndex: "leave_type_name",
      width: 110,
      render: (v: string | null, r) => (
        <span>
          {v ?? "-"}
          {r.half_type && <Tag style={{ marginLeft: 6 }}>{r.half_type}</Tag>}
        </span>
      ),
    },
    {
      title: "기간",
      width: 200,
      render: (_, r) =>
        r.start_date === r.end_date
          ? r.start_date
          : `${r.start_date} ~ ${r.end_date}`,
    },
    {
      title: "일수",
      dataIndex: "days",
      width: 80,
      align: "right",
      render: (v: string) => Number(v).toFixed(1),
    },
    {
      title: "기안일",
      dataIndex: "drafted_at",
      width: 150,
      render: (v: string | null) =>
        v ? v.replace("T", " ").slice(0, 16) : "-",
    },
    {
      title: "액션",
      width: 150,
      render: (_, r) => (
        <Space size="small" onClick={(e) => e.stopPropagation()}>
          {(r.status === "DRAFT" ||
            r.status === "PENDING" ||
            r.status === "IN_PROGRESS") && (
            <Popconfirm
              title="이 신청을 취소하시겠습니까?"
              okText="취소"
              cancelText="닫기"
              onConfirm={() => onCancel(r.doc_id)}
            >
              <Button size="small" danger>
                취소
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <PageShell
      title="내 휴가 신청"
      subtitle="내가 신청한 휴가 결재 내역"
      actions={
        <Space>
          <Select
            size="small"
            value={year}
            options={yearOptions}
            onChange={setYear}
            style={{ width: 110 }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => navigate("/att/leave/request")}
          >
            새 신청
          </Button>
        </Space>
      }
      toolbar={
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={[
            { label: "진행 중", value: "active" },
            { label: "임시", value: "DRAFT" },
            { label: "완료", value: "APPROVED" },
            { label: "반려", value: "REJECTED" },
            { label: "회수", value: "RECALLED" },
            { label: "전체", value: "all" },
          ]}
        />
      }
    >
      <Card size="small">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          총 {rows.length}건
        </Typography.Text>
        <Table
          columns={columns}
          dataSource={rows}
          rowKey="doc_id"
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, size: "small" }}
          onRow={(r) => ({
            onClick: () => navigate(`/approval/docs/${r.doc_id}`),
            style: { cursor: "pointer" },
          })}
          style={{ marginTop: 8 }}
          locale={{ emptyText: "신청 내역이 없습니다" }}
        />
      </Card>
    </PageShell>
  );
}
