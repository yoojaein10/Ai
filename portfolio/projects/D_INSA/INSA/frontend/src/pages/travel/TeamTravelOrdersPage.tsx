import { useMemo, useState } from "react";
import {
  Card,
  Input,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import {
  useTeamTravelOrders,
  useTravelOrdersByCaseNo,
  type TravelOrderListRow,
} from "../../api/travelOrder";

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "임시",
  PENDING: "상신",
  IN_PROGRESS: "진행 중",
  APPROVED: "승인",
  REJECTED: "반려",
  RECALLED: "회수",
};
const STATUS_COLOR: Record<string, string> = {
  DRAFT: "default",
  PENDING: "gold",
  IN_PROGRESS: "blue",
  APPROVED: "green",
  REJECTED: "red",
  RECALLED: "default",
};

type Tab = "active" | "APPROVED" | "all";

export default function TeamTravelOrdersPage() {
  const [tab, setTab] = useState<Tab>("active");
  const [caseQuery, setCaseQuery] = useState<string>("");
  const [caseSearch, setCaseSearch] = useState<string | null>(null);
  const navigate = useNavigate();

  const statusParam = tab === "active" || tab === "all" ? undefined : tab;
  const { data: teamRows = [], isLoading: teamLoading } = useTeamTravelOrders({
    status: statusParam,
  });
  const { data: caseRows = [], isLoading: caseLoading } =
    useTravelOrdersByCaseNo(caseSearch);

  const usingCaseFilter = !!caseSearch;
  const sourceRows = usingCaseFilter ? caseRows : teamRows;

  const rows = useMemo(() => {
    if (usingCaseFilter) return sourceRows;
    if (tab === "active") {
      return sourceRows.filter((r) =>
        ["DRAFT", "PENDING", "IN_PROGRESS"].includes(r.status),
      );
    }
    return sourceRows;
  }, [sourceRows, tab, usingCaseFilter]);

  const columns: ColumnsType<TravelOrderListRow> = [
    {
      title: "상태",
      dataIndex: "status",
      width: 90,
      render: (s: string) => (
        <Tag color={STATUS_COLOR[s] ?? "default"}>
          {STATUS_LABEL[s] ?? s}
        </Tag>
      ),
    },
    { title: "문서번호", dataIndex: "doc_no", width: 140 },
    { title: "기안자", dataIndex: "drafter_name", width: 100 },
    { title: "부서", dataIndex: "dept_name", width: 120 },
    {
      title: "행선지",
      dataIndex: "destination",
      width: 130,
      render: (v, r) => (
        <span>
          {v}
          <Tag
            style={{ marginLeft: 6 }}
            color={r.travel_type === "OVERSEAS" ? "volcano" : "default"}
          >
            {r.travel_type === "OVERSEAS" ? "해외" : "국내"}
          </Tag>
        </span>
      ),
    },
    { title: "목적", dataIndex: "purpose", ellipsis: true },
    {
      title: "기간",
      width: 200,
      render: (_, r) => {
        const s = r.start_at.replace("T", " ").slice(0, 16);
        const e = r.end_at.replace("T", " ").slice(0, 16);
        return `${s.slice(5)} ~ ${e.slice(5)}`;
      },
    },
    {
      title: "건번호",
      dataIndex: "appraisal_case_no",
      width: 130,
      render: (v) => v ?? "-",
    },
  ];

  return (
    <PageShell
      title="팀 출장 현황"
      subtitle="부서 전체 출장 (HR은 전사)"
      toolbar={
        <Space wrap>
          <Segmented
            value={tab}
            onChange={(v) => setTab(v as Tab)}
            options={[
              { label: "진행 중", value: "active" },
              { label: "승인", value: "APPROVED" },
              { label: "전체", value: "all" },
            ]}
            disabled={usingCaseFilter}
          />
          <Input
            size="small"
            placeholder="감정평가 건번호 검색"
            prefix={<SearchOutlined />}
            value={caseQuery}
            onChange={(e) => setCaseQuery(e.target.value)}
            onPressEnter={() =>
              setCaseSearch(caseQuery.trim() ? caseQuery.trim() : null)
            }
            onBlur={() =>
              setCaseSearch(caseQuery.trim() ? caseQuery.trim() : null)
            }
            allowClear
            style={{ width: 220 }}
          />
          {usingCaseFilter && (
            <Tag
              closable
              color="blue"
              onClose={() => {
                setCaseSearch(null);
                setCaseQuery("");
              }}
            >
              건번호: {caseSearch}
            </Tag>
          )}
        </Space>
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
          loading={usingCaseFilter ? caseLoading : teamLoading}
          size="small"
          pagination={{ pageSize: 20, size: "small" }}
          onRow={(r) => ({
            onClick: () => navigate(`/approval/docs/${r.doc_id}`),
            style: { cursor: "pointer" },
          })}
          style={{ marginTop: 8 }}
          locale={{ emptyText: "출장 내역이 없습니다" }}
        />
      </Card>
    </PageShell>
  );
}
