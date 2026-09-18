import {
  Breadcrumb,
  Card,
  Col,
  Progress,
  Row,
  Statistic,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  useWorkforceStat,
  type WorkforceAgeGroupRow,
  type WorkforceDeptRow,
  type WorkforceRankRow,
  type WorkforceTenureRow,
  type WorkforceTrendRow,
} from "../api/stats";

const { Title } = Typography;

export default function StatWorkforcePage() {
  const { data, isLoading } = useWorkforceStat();

  const total = data?.total ?? 0;
  const male = data?.male ?? 0;
  const female = data?.female ?? 0;
  const malePct = total > 0 ? Math.round((male / total) * 100) : 0;
  const femalePct = total > 0 ? Math.round((female / total) * 100) : 0;

  const deptCols: ColumnsType<WorkforceDeptRow> = [
    { title: "부서", dataIndex: "dept_name" },
    { title: "인원", dataIndex: "count", align: "right", width: 90 },
    { title: "남", dataIndex: "male", align: "right", width: 70 },
    { title: "여", dataIndex: "female", align: "right", width: 70 },
    {
      title: "남성비",
      key: "mp",
      align: "right",
      width: 120,
      render: (_, r) => {
        const pct = r.count > 0 ? Math.round((r.male / r.count) * 100) : 0;
        return <Progress percent={pct} size="small" />;
      },
    },
  ];

  const rankCols: ColumnsType<WorkforceRankRow> = [
    { title: "직급", dataIndex: "rank" },
    { title: "인원", dataIndex: "count", align: "right", width: 90 },
    {
      title: "비율",
      key: "pct",
      align: "right",
      width: 140,
      render: (_, r) => (
        <Progress
          percent={total > 0 ? Math.round((r.count / total) * 100) : 0}
          size="small"
        />
      ),
    },
  ];

  const ageCols: ColumnsType<WorkforceAgeGroupRow> = [
    { title: "연령대", dataIndex: "group" },
    { title: "인원", dataIndex: "count", align: "right", width: 90 },
    {
      title: "비율",
      key: "pct",
      align: "right",
      width: 140,
      render: (_, r) => (
        <Progress
          percent={total > 0 ? Math.round((r.count / total) * 100) : 0}
          size="small"
        />
      ),
    },
  ];

  const tenureCols: ColumnsType<WorkforceTenureRow> = [
    { title: "재직기간", dataIndex: "group" },
    { title: "인원", dataIndex: "count", align: "right", width: 90 },
    {
      title: "비율",
      key: "pct",
      align: "right",
      width: 140,
      render: (_, r) => (
        <Progress
          percent={total > 0 ? Math.round((r.count / total) * 100) : 0}
          size="small"
        />
      ),
    },
  ];

  const trendCols: ColumnsType<WorkforceTrendRow> = [
    {
      title: "월",
      key: "ym",
      width: 110,
      render: (_, r) => `${r.year}-${String(r.month).padStart(2, "0")}`,
    },
    {
      title: "입사",
      dataIndex: "hired",
      align: "right",
      width: 90,
      render: (v: number) => (v > 0 ? <b style={{ color: "#52c41a" }}>{v}</b> : v),
    },
    {
      title: "퇴사",
      dataIndex: "resigned",
      align: "right",
      width: 90,
      render: (v: number) => (v > 0 ? <b style={{ color: "#f5222d" }}>{v}</b> : v),
    },
    {
      title: "순증",
      key: "net",
      align: "right",
      width: 90,
      render: (_, r) => {
        const net = r.hired - r.resigned;
        const color = net > 0 ? "#52c41a" : net < 0 ? "#f5222d" : undefined;
        return <span style={{ color }}>{net > 0 ? `+${net}` : net}</span>;
      },
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "통계" }, { title: "인력현황" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        인력현황
      </Title>

      <Card size="small" style={{ marginBottom: 12 }} loading={isLoading}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="전체 재직자" value={total} suffix="명" />
          </Col>
          <Col span={6}>
            <Statistic
              title="남"
              value={male}
              suffix={`명 (${malePct}%)`}
              valueStyle={{ color: "#1677ff" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="여"
              value={female}
              suffix={`명 (${femalePct}%)`}
              valueStyle={{ color: "#eb2f96" }}
            />
          </Col>
          <Col span={6}>
            <Statistic title="부서수" value={data?.by_dept.length ?? 0} suffix="개" />
          </Col>
        </Row>
      </Card>

      <Row gutter={12}>
        <Col span={12}>
          <Card title="부서별 인원" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="dept_name"
              columns={deptCols}
              dataSource={data?.by_dept ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
              scroll={{ y: 360 }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="직급별 인원" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="rank"
              columns={rankCols}
              dataSource={data?.by_rank ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
              scroll={{ y: 360 }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col span={8}>
          <Card title="연령대 분포" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="group"
              columns={ageCols}
              dataSource={data?.by_age_group ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="재직기간 분포" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="group"
              columns={tenureCols}
              dataSource={data?.by_tenure ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="최근 12개월 입·퇴사" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey={(r) => `${r.year}-${r.month}`}
              columns={trendCols}
              dataSource={data?.trend_12m ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
              scroll={{ y: 360 }}
            />
          </Card>
        </Col>
      </Row>
    </>
  );
}
