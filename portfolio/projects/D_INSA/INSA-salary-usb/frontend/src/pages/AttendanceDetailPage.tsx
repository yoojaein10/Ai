import { useMemo, useState } from "react";
import {
  Card,
  DatePicker,
  Select,
  Table,
  Tag,
  Space,
  Row,
  Col,
  Statistic,
  Empty,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import {
  useMonthlySummary,
  usePersonalDetail,
  type AttendanceDetailDay,
} from "../api/attendance";

function formatMinutes(min: number | null): string {
  if (min === null || min === undefined) return "-";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}시간 ${m}분`;
}

export default function AttendanceDetailPage() {
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [empNo, setEmpNo] = useState<string | null>(null);

  const year = month.year();
  const monthNum = month.month() + 1;

  const { data: summary, isLoading: summaryLoading } = useMonthlySummary(
    year,
    monthNum
  );
  const { data: detail, isLoading: detailLoading } = usePersonalDetail(
    empNo,
    year,
    monthNum
  );

  const employeeOptions = useMemo(() => {
    const rows = summary?.rows ?? [];
    return rows.map((r) => ({
      value: r.emp_no,
      label: `${r.emp_no}  ${r.name}${r.dept_name ? `  (${r.dept_name})` : ""}`,
      searchText: `${r.emp_no} ${r.name} ${r.dept_name ?? ""}`.toLowerCase(),
    }));
  }, [summary]);

  const columns: ColumnsType<AttendanceDetailDay> = [
    {
      title: "일자",
      dataIndex: "work_date",
      width: 130,
      render: (v: string, r) => (
        <span style={{ color: r.is_weekend ? "#c41d7f" : undefined }}>
          {v} ({r.weekday})
        </span>
      ),
    },
    {
      title: "출근",
      dataIndex: "check_in",
      width: 100,
      align: "center",
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "퇴근",
      dataIndex: "check_out",
      width: 100,
      align: "center",
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "근로시간",
      dataIndex: "work_minutes",
      width: 130,
      align: "right",
      render: (v: number | null) => formatMinutes(v),
    },
    {
      title: "상태",
      key: "status",
      render: (_, r) => {
        const tags: React.ReactNode[] = [];
        if (r.leave_type === "휴가") {
          tags.push(
            <Tag key="leave" color="blue">
              {r.leave_half ? `반차${r.leave_remark ? `(${r.leave_remark})` : ""}` : "연차"}
            </Tag>
          );
        } else if (r.leave_type === "공가") {
          tags.push(
            <Tag key="gong" color="cyan">
              {r.leave_half ? "공가(반차)" : "공가"}
              {r.leave_remark ? ` · ${r.leave_remark}` : ""}
            </Tag>
          );
        } else if (r.leave_type) {
          tags.push(
            <Tag key="etc" color="default">
              {r.leave_type}
              {r.leave_remark ? ` · ${r.leave_remark}` : ""}
            </Tag>
          );
        }
        if (r.trip) {
          const placesText = r.trip_places.length
            ? ` (${r.trip_places.join(", ")})`
            : "";
          tags.push(
            <Tag key="trip" color="orange">
              출장{placesText}
            </Tag>
          );
        }
        if (!tags.length && r.tag_count > 0) {
          tags.push(
            <Tag key="work" color="green">
              근무
            </Tag>
          );
        }
        return <Space size={4}>{tags}</Space>;
      },
    },
    {
      title: "태그수",
      dataIndex: "tag_count",
      width: 80,
      align: "right",
    },
  ];

  return (
    <Card
      title="개인별 근태상세"
      extra={
        <Space>
          <Select
            showSearch
            allowClear
            placeholder="직원 선택 (사번/이름/부서 검색)"
            style={{ width: 320 }}
            value={empNo}
            onChange={(v) => setEmpNo(v ?? null)}
            loading={summaryLoading}
            options={employeeOptions}
            filterOption={(input, option) =>
              (option?.searchText ?? "").includes(input.toLowerCase())
            }
            optionFilterProp="label"
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
      {!empNo ? (
        <Empty description="직원을 선택하면 해당 월 상세 근태가 표시됩니다." />
      ) : (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={5}>
              <Statistic
                title="대상"
                value={
                  detail
                    ? `${detail.name}${detail.dept_name ? ` (${detail.dept_name})` : ""}`
                    : "-"
                }
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="근무일수"
                value={detail?.work_days ?? 0}
                suffix="일"
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="총근로시간"
                value={detail?.work_hours ?? 0}
                precision={1}
                suffix="시간"
              />
            </Col>
            <Col span={3}>
              <Statistic
                title="연차"
                value={detail?.leave_days ?? 0}
                suffix="일"
              />
            </Col>
            <Col span={3}>
              <Statistic
                title="공가"
                value={detail?.gong_days ?? 0}
                suffix="일"
              />
            </Col>
            <Col span={3}>
              <Statistic
                title="출장"
                value={detail?.trip_days ?? 0}
                suffix="일"
              />
            </Col>
          </Row>
          <Table<AttendanceDetailDay>
            rowKey="work_date"
            columns={columns}
            dataSource={detail?.days ?? []}
            loading={detailLoading}
            size="small"
            pagination={false}
          />
        </>
      )}
    </Card>
  );
}
