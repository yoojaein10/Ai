import { useState } from "react";
import { Card, DatePicker, Table, Tag, Space, Statistic, Row, Col } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useDailyAttendance, type AttendanceDailyRow } from "../api/attendance";

function formatMinutes(min: number | null): string {
  if (min === null || min === undefined) return "-";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}시간 ${m}분`;
}

export default function AttendanceDailyPage() {
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const dateStr = selectedDate.format("YYYY-MM-DD");
  const { data, isLoading } = useDailyAttendance(dateStr);

  const columns: ColumnsType<AttendanceDailyRow> = [
    {
      title: "사번",
      dataIndex: "emp_no",
      width: 100,
      sorter: (a, b) => a.emp_no.localeCompare(b.emp_no),
    },
    {
      title: "이름",
      dataIndex: "name",
      width: 120,
      render: (name: string, record) => (
        <Space>
          <span>{name}</span>
          {!record.matched && <Tag color="default">미등록</Tag>}
        </Space>
      ),
    },
    {
      title: "부서",
      dataIndex: "dept_name",
      width: 160,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "출근",
      dataIndex: "check_in",
      width: 110,
      align: "center",
      render: (v: string | null) => v ?? "-",
      sorter: (a, b) => (a.check_in ?? "").localeCompare(b.check_in ?? ""),
    },
    {
      title: "퇴근",
      dataIndex: "check_out",
      width: 110,
      align: "center",
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "근로시간",
      dataIndex: "work_minutes",
      width: 140,
      align: "right",
      render: (v: number | null) => formatMinutes(v),
      sorter: (a, b) => (a.work_minutes ?? 0) - (b.work_minutes ?? 0),
    },
    {
      title: "태그 수",
      dataIndex: "tag_count",
      width: 90,
      align: "right",
    },
  ];

  return (
    <Card
      title="출퇴근현황"
      extra={
        <DatePicker
          value={selectedDate}
          onChange={(v) => v && setSelectedDate(v)}
          allowClear={false}
          format="YYYY-MM-DD"
        />
      }
    >
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Statistic title="총 인원" value={data?.total ?? 0} suffix="명" />
        </Col>
        <Col span={6}>
          <Statistic
            title="INSA 등록 직원"
            value={data?.matched_count ?? 0}
            suffix="명"
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="미등록"
            value={(data?.total ?? 0) - (data?.matched_count ?? 0)}
            suffix="명"
          />
        </Col>
      </Row>
      <Table<AttendanceDailyRow>
        rowKey="emp_no"
        columns={columns}
        dataSource={data?.rows ?? []}
        loading={isLoading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true }}
      />
    </Card>
  );
}
