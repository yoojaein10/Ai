import { useState } from "react";
import {
  Breadcrumb,
  Card,
  Col,
  DatePicker,
  Row,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  useAttendanceStat,
  type AttendanceStatDeptRow,
  type AttendanceStatMonthRow,
  type AttendanceStatTopRow,
} from "../api/stats";

const { Title } = Typography;

export default function StatAttendancePage() {
  const [year, setYear] = useState<number>(dayjs().year());
  const { data, isLoading } = useAttendanceStat(year);

  const totalWorkDays =
    data?.by_month.reduce((s, r) => s + r.total_work_days, 0) ?? 0;
  const totalLeaveDays =
    data?.by_month.reduce((s, r) => s + r.total_leave_days, 0) ?? 0;
  const avgHours =
    data && data.by_month.length > 0
      ? (
          data.by_month.reduce((s, r) => s + r.avg_work_hours, 0) /
          data.by_month.filter((r) => r.emp_count > 0).length || 0
        ).toFixed(1)
      : "0";

  const monthCols: ColumnsType<AttendanceStatMonthRow> = [
    { title: "월", dataIndex: "month", width: 70, render: (v) => `${v}월` },
    {
      title: "근무일 합계",
      dataIndex: "total_work_days",
      align: "right",
      width: 110,
    },
    {
      title: "인원",
      dataIndex: "emp_count",
      align: "right",
      width: 80,
    },
    {
      title: "평균 근무시간",
      dataIndex: "avg_work_hours",
      align: "right",
      width: 120,
      render: (v: number) => `${v}h`,
    },
    {
      title: "휴가 총합",
      dataIndex: "total_leave_days",
      align: "right",
      width: 110,
      render: (v: number) => `${v}일`,
    },
  ];

  const deptCols: ColumnsType<AttendanceStatDeptRow> = [
    { title: "부서", dataIndex: "dept_name" },
    { title: "인원", dataIndex: "emp_count", align: "right", width: 80 },
    {
      title: "휴가 총합",
      dataIndex: "total_leave_days",
      align: "right",
      width: 110,
      render: (v: number) => `${v}일`,
    },
    {
      title: "인당 평균",
      dataIndex: "avg_leave_per_emp",
      align: "right",
      width: 110,
      render: (v: number) => `${v}일`,
    },
  ];

  const topCols: ColumnsType<AttendanceStatTopRow> = [
    { title: "사번", dataIndex: "emp_no", width: 100 },
    { title: "이름", dataIndex: "name", width: 100 },
    {
      title: "부서",
      dataIndex: "dept_name",
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "값",
      dataIndex: "value",
      align: "right",
      width: 100,
      render: (v: number) => v.toFixed(1),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "통계" }, { title: "근태통계" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        근태통계
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
              title="연간 근무일 합계"
              value={totalWorkDays}
              suffix="일"
            />
          </Col>
          <Col span={6}>
            <Statistic title="평균 월 근무시간" value={avgHours} suffix="h" />
          </Col>
          <Col span={6}>
            <Statistic
              title="연간 휴가 사용"
              value={totalLeaveDays.toFixed(1)}
              suffix="일"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="집계 부서"
              value={data?.by_dept.length ?? 0}
              suffix="개"
            />
          </Col>
        </Row>
      </Card>

      <Row gutter={12}>
        <Col span={12}>
          <Card title="월별 근태" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="month"
              columns={monthCols}
              dataSource={data?.by_month ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="부서별 휴가 사용" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="dept_name"
              columns={deptCols}
              dataSource={data?.by_dept ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
              scroll={{ y: 420 }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col span={12}>
          <Card
            title="근무시간 상위 10명"
            size="small"
            style={{ marginBottom: 12 }}
          >
            <Table
              rowKey={(r) => `${r.emp_no ?? ""}${r.name}`}
              columns={topCols}
              dataSource={data?.top_work_hours ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card
            title="휴가 사용 상위 10명"
            size="small"
            style={{ marginBottom: 12 }}
          >
            <Table
              rowKey={(r) => `${r.emp_no ?? ""}${r.name}`}
              columns={topCols}
              dataSource={data?.top_leave_users ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
      </Row>
    </>
  );
}
