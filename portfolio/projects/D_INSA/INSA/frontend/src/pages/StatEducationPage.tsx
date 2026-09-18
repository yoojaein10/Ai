import { useState } from "react";
import {
  Breadcrumb,
  Card,
  Col,
  DatePicker,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  useEducationStat,
  type EducationStatCategoryRow,
  type EducationStatDeptRow,
  type EducationStatIncompleteRow,
  type EducationStatMonthRow,
} from "../api/stats";

const { Title } = Typography;

export default function StatEducationPage() {
  const [year, setYear] = useState<number>(dayjs().year());
  const { data, isLoading } = useEducationStat(year);

  const catCols: ColumnsType<EducationStatCategoryRow> = [
    { title: "구분", dataIndex: "category" },
    { title: "건수", dataIndex: "count", align: "right", width: 90 },
    {
      title: "총 시간",
      dataIndex: "total_hours",
      align: "right",
      width: 110,
      render: (v: number) => `${v}h`,
    },
    {
      title: "수료",
      dataIndex: "completed",
      align: "right",
      width: 90,
    },
    {
      title: "수료율",
      key: "rate",
      align: "right",
      width: 140,
      render: (_, r) => {
        const pct =
          r.count > 0 ? Math.round((r.completed / r.count) * 100) : 0;
        return <Progress percent={pct} size="small" />;
      },
    },
  ];

  const deptCols: ColumnsType<EducationStatDeptRow> = [
    { title: "부서", dataIndex: "dept_name" },
    { title: "인원", dataIndex: "emp_count", align: "right", width: 80 },
    { title: "이수건수", dataIndex: "record_count", align: "right", width: 100 },
    {
      title: "총 시간",
      dataIndex: "total_hours",
      align: "right",
      width: 100,
      render: (v: number) => `${v}h`,
    },
    {
      title: "인당 평균",
      dataIndex: "avg_hours_per_emp",
      align: "right",
      width: 100,
      render: (v: number) => `${v}h`,
    },
  ];

  const monthCols: ColumnsType<EducationStatMonthRow> = [
    { title: "월", dataIndex: "month", width: 70, render: (v) => `${v}월` },
    { title: "이수 건수", dataIndex: "count", align: "right" },
  ];

  const incompleteCols: ColumnsType<EducationStatIncompleteRow> = [
    { title: "사번", dataIndex: "emp_no", width: 100 },
    { title: "이름", dataIndex: "name", width: 100 },
    {
      title: "부서",
      dataIndex: "dept_name",
      render: (v: string | null) => v ?? "-",
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "통계" }, { title: "교육통계" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        교육통계
      </Title>

      <Card
        size="small"
        style={{ marginBottom: 12 }}
        loading={isLoading}
        extra={
          <Space>
            <DatePicker
              picker="year"
              value={dayjs(`${year}-01-01`)}
              onChange={(v) => setYear(v ? v.year() : dayjs().year())}
              allowClear={false}
              style={{ width: 110 }}
            />
          </Space>
        }
      >
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="연간 이수 건수"
              value={data?.total_records ?? 0}
              suffix="건"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="총 이수 시간"
              value={data?.total_hours ?? 0}
              suffix="h"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="수료"
              value={data?.completed ?? 0}
              suffix="건"
              valueStyle={{ color: "#52c41a" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="수료율"
              value={data?.completion_rate ?? 0}
              suffix="%"
            />
          </Col>
        </Row>
      </Card>

      <Row gutter={12}>
        <Col span={12}>
          <Card title="구분별 이수" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="category"
              columns={catCols}
              dataSource={data?.by_category ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="부서별 이수" size="small" style={{ marginBottom: 12 }}>
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
      </Row>

      <Row gutter={12}>
        <Col span={8}>
          <Card title="월별 이수" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="month"
              columns={monthCols}
              dataSource={data?.by_month ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
            />
          </Card>
        </Col>
        <Col span={16}>
          <Card
            title={`미이수자 (${data?.incomplete_employees.length ?? 0}명)`}
            size="small"
            style={{ marginBottom: 12 }}
          >
            <Table
              rowKey="emp_no"
              columns={incompleteCols}
              dataSource={data?.incomplete_employees ?? []}
              loading={isLoading}
              size="small"
              pagination={{ pageSize: 10 }}
            />
          </Card>
        </Col>
      </Row>
    </>
  );
}
