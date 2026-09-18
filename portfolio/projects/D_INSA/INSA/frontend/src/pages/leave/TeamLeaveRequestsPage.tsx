import { useMemo, useState } from "react";
import {
  Card,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import {
  useTeamLeaveRequests,
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

type Tab = "pending" | "APPROVED" | "REJECTED" | "all";

function thisYear() {
  return new Date().getFullYear();
}

export default function TeamLeaveRequestsPage() {
  const [year, setYear] = useState<number>(thisYear());
  const [tab, setTab] = useState<Tab>("pending");
  const navigate = useNavigate();

  const statusParam =
    tab === "all" || tab === "pending" ? undefined : (tab as string);
  const { data = [], isLoading } = useTeamLeaveRequests({
    year,
    status: statusParam,
  });

  const rows = useMemo(() => {
    if (tab === "pending") {
      return data.filter(
        (r) => r.status === "PENDING" || r.status === "IN_PROGRESS",
      );
    }
    return data;
  }, [data, tab]);

  const yearOptions = useMemo(() => {
    const y = thisYear();
    return [y - 1, y, y + 1].map((v) => ({ value: v, label: `${v}년` }));
  }, []);

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
    { title: "부서", dataIndex: "dept_name", width: 130 },
    {
      title: "신청자",
      width: 160,
      render: (_, r) =>
        `${r.drafter_name ?? "-"}${r.drafter_emp_no ? ` (${r.drafter_emp_no})` : ""}`,
    },
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
      title: "사유",
      dataIndex: "reason",
      ellipsis: true,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "기안일",
      dataIndex: "drafted_at",
      width: 150,
      render: (v: string | null) =>
        v ? v.replace("T", " ").slice(0, 16) : "-",
    },
  ];

  return (
    <PageShell
      title="팀 휴가 현황"
      subtitle="부서 구성원의 휴가 신청 조회"
      actions={
        <Select
          size="small"
          value={year}
          options={yearOptions}
          onChange={setYear}
          style={{ width: 110 }}
        />
      }
      toolbar={
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={[
            { label: "대기", value: "pending" },
            { label: "승인", value: "APPROVED" },
            { label: "반려", value: "REJECTED" },
            { label: "전체", value: "all" },
          ]}
        />
      }
    >
      <Card size="small">
        <Space direction="vertical" size={4} style={{ width: "100%" }}>
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
            locale={{ emptyText: "해당 조건의 신청이 없습니다" }}
          />
        </Space>
      </Card>
    </PageShell>
  );
}
