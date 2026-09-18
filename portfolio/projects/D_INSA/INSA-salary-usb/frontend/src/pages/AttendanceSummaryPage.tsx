import { useMemo, useState } from "react";
import {
  Card,
  DatePicker,
  Table,
  Tag,
  Space,
  Input,
  Row,
  Col,
  Statistic,
  Button,
  message,
} from "antd";
import { FileExcelOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import {
  exportAttendanceHistory,
  exportAttendanceSummary,
  useMonthlySummary,
  type AttendanceSummaryRow,
} from "../api/attendance";

export default function AttendanceSummaryPage() {
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [keyword, setKeyword] = useState("");
  const [exporting, setExporting] = useState<"summary" | "history" | null>(null);
  const { data, isLoading } = useMonthlySummary(
    month.year(),
    month.month() + 1
  );

  const handleExport = async (kind: "summary" | "history") => {
    try {
      setExporting(kind);
      const y = month.year();
      const m = month.month() + 1;
      if (kind === "summary") {
        await exportAttendanceSummary(y, m);
      } else {
        await exportAttendanceHistory(y, m);
      }
      message.success("다운로드가 시작되었습니다");
    } catch (e) {
      console.error(e);
      message.error("엑셀 생성에 실패했습니다");
    } finally {
      setExporting(null);
    }
  };

  const filtered = useMemo(() => {
    const rows = data?.rows ?? [];
    if (!keyword.trim()) return rows;
    const k = keyword.trim().toLowerCase();
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(k) ||
        r.emp_no.toLowerCase().includes(k) ||
        (r.dept_name?.toLowerCase() ?? "").includes(k)
    );
  }, [data, keyword]);

  const columns: ColumnsType<AttendanceSummaryRow> = [
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
      title: "근무일수",
      dataIndex: "work_days",
      width: 100,
      align: "right",
      sorter: (a, b) => a.work_days - b.work_days,
    },
    {
      title: "총근로시간",
      dataIndex: "work_hours",
      width: 120,
      align: "right",
      render: (v: number) => `${v.toFixed(1)}시간`,
      sorter: (a, b) => a.work_hours - b.work_hours,
    },
    {
      title: "연차",
      dataIndex: "leave_days",
      width: 90,
      align: "right",
      render: (v: number) => (v > 0 ? `${v}일` : "-"),
      sorter: (a, b) => a.leave_days - b.leave_days,
    },
    {
      title: "공가",
      dataIndex: "gong_days",
      width: 90,
      align: "right",
      render: (v: number) => (v > 0 ? `${v}일` : "-"),
      sorter: (a, b) => a.gong_days - b.gong_days,
    },
    {
      title: "출장",
      dataIndex: "trip_days",
      width: 90,
      align: "right",
      render: (v: number) => (v > 0 ? `${v}일` : "-"),
      sorter: (a, b) => a.trip_days - b.trip_days,
    },
  ];

  return (
    <Card
      title="근태집계"
      extra={
        <Space>
          <Button
            icon={<FileExcelOutlined />}
            onClick={() => handleExport("summary")}
            loading={exporting === "summary"}
          >
            출퇴근현황
          </Button>
          <Button
            icon={<FileExcelOutlined />}
            onClick={() => handleExport("history")}
            loading={exporting === "history"}
          >
            출퇴근이력
          </Button>
          <Input.Search
            placeholder="사번/이름/부서 검색"
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 220 }}
          />
          <DatePicker
            picker="month"
            value={month}
            onChange={(v) => v && setMonth(v)}
            allowClear={false}
            format="YYYY-MM"
          />
        </Space>
      }
    >
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Statistic title="총 인원" value={data?.total ?? 0} suffix="명" />
        </Col>
        <Col span={6}>
          <Statistic
            title="INSA 등록"
            value={data?.matched_count ?? 0}
            suffix="명"
          />
        </Col>
        <Col span={6}>
          <Statistic
            title="표시 중"
            value={filtered.length}
            suffix="명"
          />
        </Col>
      </Row>
      <Table<AttendanceSummaryRow>
        rowKey={(r) => `${r.emp_no}-${r.name}`}
        columns={columns}
        dataSource={filtered}
        loading={isLoading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true }}
      />
    </Card>
  );
}
