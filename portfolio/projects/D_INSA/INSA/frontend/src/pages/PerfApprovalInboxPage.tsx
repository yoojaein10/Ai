import { useMemo } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { CheckOutlined, CloseOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useEvalRounds } from "../api/evalRounds";
import { useMe } from "../api/me";
import {
  useApprovePerfTarget,
  usePerfTargets,
  useRejectPerfTarget,
  type PerfTarget,
  type TargetStatus,
} from "../api/perfTarget";
import { useEvalApprovers } from "../api/evalApprovers";
import { useEmployees } from "../api/employees";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const STATUS_COLOR: Record<TargetStatus, string> = {
  DRAFT: "default",
  SUBMITTED: "processing",
  APPROVED: "success",
  REJECTED: "error",
};

export default function PerfApprovalInboxPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: me } = useMe();
  const { data: rounds } = useEvalRounds();
  const myEmpId = me?.employee?.id ?? null;

  const { data: approvers } = useEvalApprovers(selectedRoundId, "PERF");
  const { data: targets } = usePerfTargets({ round_id: selectedRoundId });
  const { data: empList } = useEmployees({ page_size: 200 });

  const empById = useMemo(() => {
    const m = new Map<number, { emp_no: string; name_ko: string }>();
    (empList?.items ?? []).forEach((e) =>
      m.set(e.id, { emp_no: e.emp_no, name_ko: e.name_ko }),
    );
    return m;
  }, [empList]);

  const myEvaluateeIds = useMemo(() => {
    if (!myEmpId) return new Set<number>();
    return new Set(
      (approvers ?? [])
        .filter((a) => a.evaluator_id === myEmpId)
        .map((a) => a.evaluatee_id),
    );
  }, [approvers, myEmpId]);

  const inbox = useMemo(
    () =>
      (targets ?? []).filter(
        (t) => t.status === "SUBMITTED" && myEvaluateeIds.has(t.emp_id),
      ),
    [targets, myEvaluateeIds],
  );

  const approveMutation = useApprovePerfTarget();
  const rejectMutation = useRejectPerfTarget();

  const columns: ColumnsType<PerfTarget> = [
    {
      title: "피평가자",
      dataIndex: "emp_id",
      key: "emp",
      render: (id: number) => {
        const e = empById.get(id);
        return e ? `${e.name_ko} (${e.emp_no})` : id;
      },
    },
    { title: "목표", dataIndex: "target_value", key: "tv" },
    {
      title: "가중치(%)",
      dataIndex: "weight_percent",
      key: "wp",
      width: 110,
      render: (v) => v ?? "-",
    },
    {
      title: "상태",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (s: TargetStatus) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
    },
    {
      title: "액션",
      key: "action",
      width: 200,
      render: (_, r) => (
        <Space>
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            onClick={() =>
              approveMutation.mutate(r.id, {
                onSuccess: () => message.success("승인되었습니다"),
                onError: (e: any) =>
                  message.error(e?.response?.data?.detail ?? "승인 실패"),
              })
            }
          >
            승인
          </Button>
          <Button
            size="small"
            danger
            icon={<CloseOutlined />}
            onClick={() =>
              rejectMutation.mutate(r.id, {
                onSuccess: () => message.success("반려되었습니다"),
                onError: (e: any) =>
                  message.error(e?.response?.data?.detail ?? "반려 실패"),
              })
            }
          >
            반려
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "성과평가" }, { title: "승인 대기" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        승인 대기 ({inbox.length})
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
        </Space>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={inbox}
        pagination={false}
        size="small"
      />
    </>
  );
}
