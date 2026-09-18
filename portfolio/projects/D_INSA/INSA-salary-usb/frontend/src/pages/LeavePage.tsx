import { useState } from "react";
import {
  Card,
  DatePicker,
  Select,
  Input,
  Space,
  Table,
  Tag,
  Row,
  Col,
  Statistic,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useLeaves, type LeaveRow } from "../api/leaves";

const LEAVE_TYPES = [
  { value: "", label: "전체" },
  { value: "연차", label: "연차" },
  { value: "공가", label: "공가" },
  { value: "특가", label: "특가" },
  { value: "경조휴가", label: "경조휴가" },
  { value: "가족돌봄", label: "가족돌봄" },
  { value: "병가", label: "병가" },
  { value: "기타휴가", label: "기타휴가" },
  { value: "예비군", label: "예비군" },
];

const TYPE_COLOR: Record<string, string> = {
  연차: "blue",
  공가: "cyan",
  특가: "purple",
  경조휴가: "magenta",
  가족돌봄: "geekblue",
  병가: "volcano",
  기타휴가: "default",
  예비군: "green",
};

export default function LeavePage() {
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [leaveType, setLeaveType] = useState<string>("");
  const [keyword, setKeyword] = useState<string>("");

  const { data, isLoading } = useLeaves(
    month.year(),
    month.month() + 1,
    leaveType,
    keyword
  );

  const columns: ColumnsType<LeaveRow> = [
    {
      title: "일자",
      dataIndex: "leave_date",
      width: 130,
      render: (v: string, r) => (
        <span>
          {v} ({r.weekday})
        </span>
      ),
      sorter: (a, b) => a.leave_date.localeCompare(b.leave_date),
      defaultSortOrder: "ascend",
    },
    {
      title: "사번",
      dataIndex: "emp_no",
      width: 90,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "이름",
      dataIndex: "name",
      width: 110,
      render: (name: string, r) => (
        <Space>
          <span>{name}</span>
          {!r.matched && <Tag color="default">미등록</Tag>}
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
      title: "구분",
      dataIndex: "leave_type",
      width: 110,
      render: (v: string, r) => (
        <Space size={4}>
          <Tag color={TYPE_COLOR[v] ?? "default"}>{v}</Tag>
          {r.half && <Tag color="orange">반차</Tag>}
        </Space>
      ),
      filters: LEAVE_TYPES.filter((x) => x.value).map((x) => ({
        text: x.label,
        value: x.value,
      })),
      onFilter: (value, r) => r.leave_type === value,
    },
    {
      title: "사유",
      dataIndex: "remark",
      render: (v: string | null) => v ?? "-",
    },
  ];

  const summary = data?.summary;

  return (
    <Card
      title="휴가관리"
      extra={
        <Space>
          <Select
            value={leaveType}
            onChange={setLeaveType}
            options={LEAVE_TYPES}
            style={{ width: 130 }}
          />
          <Input.Search
            placeholder="이름/부서 검색"
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 200 }}
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
        <Col span={4}>
          <Statistic
            title="연차"
            value={summary?.annual ?? 0}
            suffix="일"
            precision={1}
          />
        </Col>
        <Col span={3}>
          <Statistic title="반차" value={summary?.half ?? 0} suffix="건" />
        </Col>
        <Col span={3}>
          <Statistic
            title="공가"
            value={summary?.gong ?? 0}
            suffix="일"
            precision={1}
          />
        </Col>
        <Col span={3}>
          <Statistic
            title="특가"
            value={summary?.special ?? 0}
            suffix="일"
            precision={1}
          />
        </Col>
        <Col span={3}>
          <Statistic
            title="경조"
            value={summary?.bereavement ?? 0}
            suffix="일"
            precision={1}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="가족돌봄"
            value={summary?.family_care ?? 0}
            suffix="일"
            precision={1}
          />
        </Col>
        <Col span={4}>
          <Statistic title="총 건수" value={data?.total ?? 0} suffix="건" />
        </Col>
      </Row>
      <Table<LeaveRow>
        rowKey={(r) => `${r.leave_date}-${r.emp_no ?? ""}-${r.name}-${r.leave_type}`}
        columns={columns}
        dataSource={data?.rows ?? []}
        loading={isLoading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true }}
      />
    </Card>
  );
}
