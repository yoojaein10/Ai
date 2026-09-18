import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useEmployees, type Employee } from "../api/employees";
import { useDepartments } from "../api/departments";

const { Title } = Typography;

const statusColor: Record<string, string> = {
  재직: "green",
  휴직: "orange",
  퇴직: "red",
};

export default function RosterPage() {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState<string | undefined>();
  const [deptId, setDeptId] = useState<number | undefined>();
  const [empStatus, setEmpStatus] = useState<string | undefined>("재직");

  const { data: departments } = useDepartments();
  const { data, isLoading } = useEmployees({
    page,
    page_size: 20,
    search,
    dept_id: deptId,
    emp_status: empStatus,
  });

  const columns: ColumnsType<Employee> = [
    {
      title: "번호",
      key: "idx",
      width: 60,
      render: (_, __, index) => (page - 1) * 20 + index + 1,
    },
    { title: "사번", dataIndex: "emp_no", key: "emp_no", width: 100 },
    { title: "성명", dataIndex: "name_ko", key: "name_ko", width: 90 },
    {
      title: "성별",
      dataIndex: "gender",
      key: "gender",
      width: 60,
      render: (g: string | null) => (g === "M" ? "남" : g === "F" ? "여" : "-"),
    },
    { title: "부서", dataIndex: "department_name", key: "dept", width: 120 },
    { title: "직급", dataIndex: "job_rank", key: "rank", width: 80 },
    { title: "직위", dataIndex: "job_position", key: "pos", width: 80 },
    { title: "근무지", dataIndex: "workplace", key: "workplace", width: 100 },
    { title: "입사일", dataIndex: "hire_date", key: "hire_date", width: 110 },
    { title: "입사구분", dataIndex: "hire_type", key: "hire_type", width: 90 },
    { title: "고용형태", dataIndex: "emp_type", key: "emp_type", width: 90 },
    {
      title: "상태",
      dataIndex: "emp_status",
      key: "status",
      width: 70,
      render: (s: string) => <Tag color={statusColor[s] ?? "default"}>{s}</Tag>,
    },
  ];

  const onSearch = () => {
    setPage(1);
    setSearch(searchInput || undefined);
  };

  const onReset = () => {
    setSearchInput("");
    setSearch(undefined);
    setDeptId(undefined);
    setEmpStatus("재직");
    setPage(1);
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "임직원조회" }, { title: "재직자명부" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>재직자명부</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Input
            placeholder="사번 또는 성명"
            prefix={<SearchOutlined />}
            style={{ width: 200 }}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onPressEnter={onSearch}
          />
          <Select
            placeholder="부서 전체"
            style={{ width: 160 }}
            allowClear
            value={deptId}
            onChange={(v) => { setDeptId(v); setPage(1); }}
            options={departments?.map((d) => ({ value: d.id, label: d.name })) ?? []}
          />
          <Select
            placeholder="상태"
            style={{ width: 100 }}
            allowClear
            value={empStatus}
            onChange={(v) => { setEmpStatus(v); setPage(1); }}
            options={[
              { value: "재직", label: "재직" },
              { value: "휴직", label: "휴직" },
              { value: "퇴직", label: "퇴직" },
            ]}
          />
          <Button type="primary" onClick={onSearch}>검색</Button>
          <Button onClick={onReset}>초기화</Button>
        </Space>
      </Card>

      <Card size="small" title={`총 ${data?.total ?? 0}명`}>
        <Table
          columns={columns}
          dataSource={data?.items}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
          pagination={{
            current: page,
            pageSize: 20,
            total: data?.total,
            onChange: setPage,
            size: "small",
            showTotal: (total) => `총 ${total}명`,
          }}
        />
      </Card>
    </>
  );
}
