import { useMemo } from "react";
import {
  Breadcrumb,
  Card,
  Col,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useDepartments } from "../api/departments";
import { useEvalRounds } from "../api/evalRounds";
import { useEmployees } from "../api/employees";
import { usePerfTargets, type PerfTarget, type TargetStatus } from "../api/perfTarget";
import { useEvalUIStore } from "../store/evalUI";

const { Title } = Typography;

const STATUS_COLOR: Record<TargetStatus, string> = {
  DRAFT: "default",
  SUBMITTED: "processing",
  APPROVED: "success",
  REJECTED: "error",
};

export default function PerfTeamStatusPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: depts } = useDepartments();
  const { data: empList } = useEmployees({ page_size: 500 });
  const { data: targets } = usePerfTargets({ round_id: selectedRoundId });

  const empById = useMemo(() => {
    const m = new Map<number, { name_ko: string; emp_no: string; dept_id: number | null }>();
    (empList?.items ?? []).forEach((e) =>
      m.set(e.id, { name_ko: e.name_ko, emp_no: e.emp_no, dept_id: e.dept_id ?? null }),
    );
    return m;
  }, [empList]);

  const stats = useMemo(() => {
    const list = targets ?? [];
    return {
      total: list.length,
      draft: list.filter((t) => t.status === "DRAFT").length,
      submitted: list.filter((t) => t.status === "SUBMITTED").length,
      approved: list.filter((t) => t.status === "APPROVED").length,
      rejected: list.filter((t) => t.status === "REJECTED").length,
    };
  }, [targets]);

  const columns: ColumnsType<PerfTarget> = [
    {
      title: "사원",
      dataIndex: "emp_id",
      key: "emp",
      render: (id: number) => {
        const e = empById.get(id);
        return e ? `${e.name_ko} (${e.emp_no})` : id;
      },
    },
    {
      title: "부서",
      key: "dept",
      render: (_, r) => {
        const e = empById.get(r.emp_id);
        if (!e?.dept_id) return "-";
        const d = (depts ?? []).find((dept) => dept.id === e.dept_id);
        return d?.name ?? "-";
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
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "성과평가" }, { title: "부서별 현황" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        부서별 현황
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

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={4}><Card size="small"><Statistic title="총 목표" value={stats.total} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="작성중" value={stats.draft} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="제출" value={stats.submitted} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="승인" value={stats.approved} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="반려" value={stats.rejected} /></Card></Col>
      </Row>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={targets ?? []}
        pagination={{ pageSize: 20 }}
        size="small"
      />
    </>
  );
}
