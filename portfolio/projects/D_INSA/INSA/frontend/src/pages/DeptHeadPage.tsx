import { useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { EditOutlined, DeleteOutlined, UserOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useDepartments, useUpdateDepartment, type Department } from "../api/departments";
import { useEmployees, type Employee } from "../api/employees";

const { Title } = Typography;

export default function DeptHeadPage() {
  const { data: departments, isLoading: deptLoading } = useDepartments(true);
  const { data: empData } = useEmployees({ page: 1, page_size: 100, emp_status: "재직" });
  const update = useUpdateDepartment();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Department | null>(null);
  const [pickEmpId, setPickEmpId] = useState<number | null>(null);

  const empMap = useMemo(() => {
    const m = new Map<number, Employee>();
    empData?.items.forEach((e) => m.set(e.id, e));
    return m;
  }, [empData]);

  const onOpenEdit = (dept: Department) => {
    setEditTarget(dept);
    setPickEmpId(dept.head_employee_id ?? null);
    setModalOpen(true);
  };

  const onSave = () => {
    if (!editTarget) return;
    update.mutate(
      { id: editTarget.id, head_employee_id: pickEmpId },
      {
        onSuccess: () => {
          message.success("부서장이 지정되었습니다");
          setModalOpen(false);
          setEditTarget(null);
        },
        onError: () => message.error("저장에 실패했습니다"),
      }
    );
  };

  const onClear = (dept: Department) => {
    update.mutate(
      { id: dept.id, head_employee_id: null },
      {
        onSuccess: () => message.success("부서장이 해제되었습니다"),
        onError: () => message.error("해제에 실패했습니다"),
      }
    );
  };

  const columns: ColumnsType<Department> = [
    { title: "부서코드", dataIndex: "code", key: "code", width: 100 },
    {
      title: "부서명",
      dataIndex: "name",
      key: "name",
      width: 180,
      render: (name: string, r) => (
        <Space>
          {name}
          {!r.is_active && <Tag color="red">비활성</Tag>}
        </Space>
      ),
    },
    {
      title: "현재 부서장",
      key: "head",
      render: (_, r) => {
        if (!r.head_employee_id) return <Typography.Text type="secondary">미지정</Typography.Text>;
        const emp = empMap.get(r.head_employee_id);
        if (!emp) return <Typography.Text type="warning">사번 {r.head_employee_id} (조회 불가)</Typography.Text>;
        return (
          <Space>
            <UserOutlined />
            <span>
              {emp.name_ko} <Typography.Text type="secondary">({emp.emp_no})</Typography.Text>
            </span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {emp.job_rank ?? ""} · {emp.department_name ?? "-"}
            </Typography.Text>
          </Space>
        );
      },
    },
    {
      title: "",
      key: "actions",
      width: 160,
      render: (_, r) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onOpenEdit(r)}
          >
            {r.head_employee_id ? "변경" : "지정"}
          </Button>
          {r.head_employee_id && (
            <Popconfirm title="부서장을 해제하시겠습니까?" onConfirm={() => onClear(r)}>
              <Button danger size="small" icon={<DeleteOutlined />}>해제</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const candidateOptions = empData?.items
    .filter((e) => !editTarget || e.dept_id === editTarget.id)
    .map((e) => ({
      value: e.id,
      label: `${e.name_ko} (${e.emp_no}) · ${e.job_rank ?? "-"} · ${e.department_name ?? "-"}`,
    })) ?? [];

  const allCandidates = empData?.items.map((e) => ({
    value: e.id,
    label: `${e.name_ko} (${e.emp_no}) · ${e.job_rank ?? "-"} · ${e.department_name ?? "-"}`,
  })) ?? [];

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "부서관리" }, { title: "부서장관리" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>부서장관리</Title>

      <Card size="small" title={`총 ${departments?.length ?? 0}개 부서`}>
        <Table
          columns={columns}
          dataSource={departments}
          rowKey="id"
          loading={deptLoading}
          size="small"
          pagination={{ pageSize: 20, size: "small" }}
        />
      </Card>

      <Modal
        title={`부서장 지정 — ${editTarget?.name ?? ""}`}
        open={modalOpen}
        onOk={onSave}
        onCancel={() => { setModalOpen(false); setEditTarget(null); }}
        confirmLoading={update.isPending}
        okText="저장"
        cancelText="취소"
        width={520}
      >
        <div style={{ marginBottom: 12 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            해당 부서 소속 직원 중 선택 (없으면 아래에서 전체 직원 중 선택 가능)
          </Typography.Text>
        </div>
        <Select
          showSearch
          allowClear
          style={{ width: "100%" }}
          placeholder="해당 부서 소속 직원에서 선택"
          value={pickEmpId ?? undefined}
          onChange={(v) => setPickEmpId(v ?? null)}
          options={candidateOptions}
          filterOption={(input, opt) =>
            String(opt?.label ?? "").toLowerCase().includes(input.toLowerCase())
          }
          notFoundContent="해당 부서 소속 직원 없음"
        />
        <div style={{ marginTop: 16, marginBottom: 8 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            전체 직원에서 선택 (다른 부서 직원도 지정 가능)
          </Typography.Text>
        </div>
        <Select
          showSearch
          allowClear
          style={{ width: "100%" }}
          placeholder="전체 직원 검색"
          value={pickEmpId ?? undefined}
          onChange={(v) => setPickEmpId(v ?? null)}
          options={allCandidates}
          filterOption={(input, opt) =>
            String(opt?.label ?? "").toLowerCase().includes(input.toLowerCase())
          }
        />
      </Modal>
    </>
  );
}
