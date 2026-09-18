import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useAllAppointments, type AppointmentListItem } from "../api/appointments";

const { Title } = Typography;
const { RangePicker } = DatePicker;

const apptTypes = ["신규", "전보", "승진", "직위변경", "퇴직"];

const typeColor: Record<string, string> = {
  신규: "blue",
  전보: "cyan",
  승진: "gold",
  직위변경: "purple",
  퇴직: "red",
};

function arrow(from: string | null, to: string | null) {
  if (!from && !to) return "-";
  if (!from) return to;
  if (!to || from === to) return from;
  return `${from} → ${to}`;
}

export default function AppointmentStatusPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState<string | undefined>();
  const [apptType, setApptType] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  const params = {
    search,
    appt_type: apptType,
    date_from: dateRange?.[0]?.format("YYYY-MM-DD"),
    date_to: dateRange?.[1]?.format("YYYY-MM-DD"),
  };

  const { data, isLoading } = useAllAppointments(params);

  const columns: ColumnsType<AppointmentListItem> = [
    { title: "발령일", dataIndex: "appt_date", key: "appt_date", width: 110 },
    {
      title: "발령유형",
      dataIndex: "appt_type",
      key: "appt_type",
      width: 100,
      render: (t: string) => <Tag color={typeColor[t] ?? "default"}>{t}</Tag>,
    },
    { title: "사번", dataIndex: "emp_no", key: "emp_no", width: 100 },
    { title: "성명", dataIndex: "emp_name", key: "emp_name", width: 90 },
    {
      title: "부서",
      key: "dept",
      width: 200,
      render: (_, r) => arrow(r.old_dept_name, r.new_dept_name),
    },
    {
      title: "직급",
      key: "rank",
      width: 140,
      render: (_, r) => arrow(r.old_rank, r.new_rank),
    },
    {
      title: "직위",
      key: "position",
      width: 140,
      render: (_, r) => arrow(r.old_position, r.new_position),
    },
    { title: "비고", dataIndex: "description", key: "description", ellipsis: true },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "발령관리" }, { title: "발령현황" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>발령현황</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Input
            placeholder="사번 또는 성명 검색"
            prefix={<SearchOutlined />}
            style={{ width: 200 }}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onPressEnter={() => setSearch(searchInput || undefined)}
          />
          <Select
            placeholder="발령유형 전체"
            style={{ width: 130 }}
            allowClear
            value={apptType}
            onChange={setApptType}
            options={apptTypes.map((t) => ({ value: t, label: t }))}
          />
          <RangePicker
            value={dateRange as [dayjs.Dayjs, dayjs.Dayjs] | null}
            onChange={(v) => setDateRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null)}
          />
          <Button type="primary" onClick={() => setSearch(searchInput || undefined)}>
            검색
          </Button>
          <Button
            onClick={() => {
              setSearchInput("");
              setSearch(undefined);
              setApptType(undefined);
              setDateRange(null);
            }}
          >
            초기화
          </Button>
        </Space>
      </Card>

      <Card size="small" title={`총 ${data?.length ?? 0}건`}>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, size: "small", showTotal: (total) => `총 ${total}건` }}
        />
      </Card>
    </>
  );
}
