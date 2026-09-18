import { useMemo, useState } from "react";
import {
  Button,
  Card,
  Popconfirm,
  Segmented,
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
  useCancelTravelOrder,
  useMyTravelOrders,
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

type Tab = "active" | "APPROVED" | "REJECTED" | "all";

function fmtDateRange(start: string, end: string) {
  const s = start.replace("T", " ").slice(0, 16);
  const e = end.replace("T", " ").slice(0, 16);
  return s.slice(0, 10) === e.slice(0, 10) ? `${s.slice(0, 10)} ${s.slice(11)}~${e.slice(11)}` : `${s} ~ ${e}`;
}

export default function MyTravelOrdersPage() {
  const [tab, setTab] = useState<Tab>("active");
  const navigate = useNavigate();
  const statusParam = tab === "active" || tab === "all" ? undefined : tab;
  const { data = [], isLoading } = useMyTravelOrders({
    status: statusParam,
    include_companion: true,
  });

  const cancel = useCancelTravelOrder();

  const rows = useMemo(() => {
    if (tab === "active") {
      return data.filter((r) =>
        ["DRAFT", "PENDING", "IN_PROGRESS"].includes(r.status),
      );
    }
    return data;
  }, [data, tab]);

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
    {
      title: "행선지",
      dataIndex: "destination",
      width: 130,
      render: (v, r) => (
        <span>
          {v}
          <Tag style={{ marginLeft: 6 }} color={r.travel_type === "OVERSEAS" ? "volcano" : "default"}>
            {r.travel_type === "OVERSEAS" ? "해외" : "국내"}
          </Tag>
        </span>
      ),
    },
    { title: "제목", dataIndex: "title", ellipsis: true },
    {
      title: "기간",
      width: 260,
      render: (_, r) => fmtDateRange(r.start_at, r.end_at),
    },
    {
      title: "동행",
      dataIndex: "companion_count",
      width: 70,
      align: "right",
      render: (n: number) => (n > 0 ? `${n}명` : "-"),
    },
    { title: "건번호", dataIndex: "appraisal_case_no", width: 130, render: (v) => v ?? "-" },
    {
      title: "복명서",
      dataIndex: "has_report",
      width: 100,
      render: (has: boolean, r) =>
        has ? (
          <Tag color="green">작성</Tag>
        ) : r.status === "APPROVED" ? (
          <Button
            size="small"
            type="link"
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/travel/${r.doc_id}/report`);
            }}
          >
            작성
          </Button>
        ) : (
          "-"
        ),
    },
    {
      title: "액션",
      width: 100,
      render: (_, r) => (
        <Space size="small" onClick={(e) => e.stopPropagation()}>
          {["DRAFT", "PENDING", "IN_PROGRESS"].includes(r.status) && (
            <Popconfirm
              title="이 출장을 취소하시겠습니까?"
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
      title="내 출장"
      subtitle="본인이 기안했거나 동행자로 포함된 출장"
      actions={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate("/travel/new")}
        >
          출장 기안
        </Button>
      }
      toolbar={
        <Segmented
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={[
            { label: "진행 중", value: "active" },
            { label: "승인", value: "APPROVED" },
            { label: "반려", value: "REJECTED" },
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
          locale={{ emptyText: "출장 내역이 없습니다" }}
        />
      </Card>
    </PageShell>
  );
}
