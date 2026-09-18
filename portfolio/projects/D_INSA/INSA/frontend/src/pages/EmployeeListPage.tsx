import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Card,
  Avatar,
} from "antd";
import { PlusOutlined, SearchOutlined, UserOutlined } from "@ant-design/icons";
import { useEmployees, useEmployee } from "../api/employees";
import type { Employee } from "../api/employees";
import type { ColumnsType } from "antd/es/table";
import EmployeeDetailTabs from "../components/tabs/EmployeeDetailTabs";
import CreateEmployeeModal from "../components/CreateEmployeeModal";

const { Title } = Typography;

const columns: ColumnsType<Employee> = [
  { title: "사번", dataIndex: "emp_no", key: "emp_no", width: 100 },
  { title: "성명", dataIndex: "name_ko", key: "name_ko", width: 80 },
  { title: "부서", dataIndex: "department_name", key: "dept", width: 80 },
  { title: "직급", dataIndex: "job_rank", key: "rank", width: 60 },
  {
    title: "상태",
    dataIndex: "emp_status",
    key: "status",
    width: 60,
    render: (status: string) => (
      <Tag color={status === "재직" ? "green" : "red"}>{status}</Tag>
    ),
  },
];

export default function EmployeeListPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isLoading } = useEmployees({ page, search: search || undefined });
  const { data: detail } = useEmployee(selectedId);

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사" },
          { title: "인사관리" },
          { title: "인사정보관리" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        인사정보관리
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select defaultValue="" style={{ width: 120 }} options={[{ value: "", label: "전체 사업장" }]} />
          <Select defaultValue="" style={{ width: 120 }} options={[{ value: "", label: "전체 부서" }]} />
          <Select defaultValue="" style={{ width: 130 }} options={[{ value: "", label: "재직구분: 전체" }]} />
          <Input
            placeholder="사번 또는 성명 검색"
            prefix={<SearchOutlined />}
            style={{ width: 180 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onPressEnter={() => setPage(1)}
          />
          <Button type="primary" onClick={() => setPage(1)}>
            검색
          </Button>
          <Button onClick={() => { setSearch(""); setPage(1); }}>초기화</Button>
        </Space>
      </Card>

      <div style={{ display: "flex", gap: 12, height: "calc(100vh - 240px)" }}>
        <Card
          size="small"
          title={`사원 목록 (${data?.total ?? 0}명)`}
          extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>신규등록</Button>}
          style={{ width: 400, display: "flex", flexDirection: "column" }}
          styles={{ body: { flex: 1, overflow: "auto", padding: 0 } }}
        >
          <Table
            columns={columns}
            dataSource={data?.items}
            rowKey="id"
            loading={isLoading}
            size="small"
            pagination={{
              current: page,
              pageSize: 10,
              total: data?.total,
              onChange: setPage,
              size: "small",
              showTotal: (total) => `총 ${total}명`,
            }}
            onRow={(record) => ({
              onClick: () => setSelectedId(record.id),
              style: {
                cursor: "pointer",
                background: record.id === selectedId ? "#e8f0fe" : undefined,
              },
            })}
          />
        </Card>

        <Card
          size="small"
          style={{ flex: 1, display: "flex", flexDirection: "column" }}
          styles={{ body: { flex: 1, overflow: "auto", padding: 0 } }}
        >
          {detail ? (
            <>
              <div
                style={{
                  padding: "14px 18px",
                  borderBottom: "1px solid #f0f0f0",
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                }}
              >
                <Avatar size={48} icon={<UserOutlined />}>
                  {detail.name_ko?.[0]}
                </Avatar>
                <div>
                  <Typography.Text strong style={{ fontSize: 16 }}>
                    {detail.name_ko}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    {detail.emp_no}
                  </Typography.Text>
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {detail.department_name} / {detail.job_rank} / {detail.emp_type}
                    </Typography.Text>
                    <Tag
                      color={detail.emp_status === "재직" ? "green" : "red"}
                      style={{ marginLeft: 8 }}
                    >
                      {detail.emp_status}
                    </Tag>
                  </div>
                </div>
                <div style={{ marginLeft: "auto" }}>
                  <Button size="small" onClick={() => window.print()}>인사카드 인쇄</Button>
                </div>
              </div>
              <EmployeeDetailTabs employeeId={selectedId!} detail={detail} />
            </>
          ) : (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                height: "100%",
                color: "#999",
              }}
            >
              좌측 목록에서 사원을 선택하세요
            </div>
          )}
        </Card>
      </div>

      <CreateEmployeeModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </>
  );
}
