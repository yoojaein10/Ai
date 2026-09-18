import { useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  KeyOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useAdminRoles,
  useAdminUsers,
  useCreateAdminUser,
  useDeleteAdminUser,
  useResetPassword,
  useUpdateAdminUser,
  type AdminUser,
} from "../api/admin";
import { useEmployees } from "../api/employees";

const { Title } = Typography;

export default function AdminUsersPage() {
  const [keyword, setKeyword] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const { data, isLoading } = useAdminUsers({
    keyword,
    is_active: showInactive ? undefined : true,
  });
  const { data: rolesData } = useAdminRoles();
  const createUser = useCreateAdminUser();
  const updateUser = useUpdateAdminUser();
  const deleteUser = useDeleteAdminUser();
  const resetPw = useResetPassword();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AdminUser | null>(null);
  const [form] = Form.useForm();

  const [pwModalOpen, setPwModalOpen] = useState(false);
  const [pwTarget, setPwTarget] = useState<AdminUser | null>(null);
  const [pwForm] = Form.useForm();

  const [empSearch, setEmpSearch] = useState("");
  const { data: empData } = useEmployees({ search: empSearch, page_size: 20 });

  const roleOptions = useMemo(
    () =>
      (rolesData?.items ?? []).map((r) => ({
        value: r.id,
        label: `${r.name} (${r.code})`,
      })),
    [rolesData]
  );

  const empOptions = useMemo(
    () =>
      (empData?.items ?? []).map((e) => ({
        value: e.id,
        label: `${e.emp_no} ${e.name_ko}${
          e.department_name ? ` - ${e.department_name}` : ""
        }`,
      })),
    [empData]
  );

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, role_ids: [] });
    setModalOpen(true);
  };

  const openEdit = (u: AdminUser) => {
    setEditTarget(u);
    const roleIds = (rolesData?.items ?? [])
      .filter((r) => u.role_codes.includes(r.code))
      .map((r) => r.id);
    form.setFieldsValue({
      login_id: u.login_id,
      employee_id: u.employee_id,
      is_active: u.is_active,
      role_ids: roleIds,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (editTarget) {
      updateUser.mutate(
        {
          id: editTarget.id,
          data: {
            employee_id: values.employee_id,
            is_active: values.is_active,
            role_ids: values.role_ids ?? [],
          },
        },
        {
          onSuccess: () => {
            message.success("수정되었습니다");
            setModalOpen(false);
          },
          onError: (e: any) =>
            message.error(e?.response?.data?.detail ?? "수정 실패"),
        }
      );
    } else {
      createUser.mutate(values, {
        onSuccess: () => {
          message.success("생성되었습니다");
          setModalOpen(false);
          form.resetFields();
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "생성 실패"),
      });
    }
  };

  const openResetPw = (u: AdminUser) => {
    setPwTarget(u);
    pwForm.resetFields();
    setPwModalOpen(true);
  };

  const onResetPw = async () => {
    const values = await pwForm.validateFields();
    if (!pwTarget) return;
    resetPw.mutate(
      { id: pwTarget.id, new_password: values.new_password },
      {
        onSuccess: () => {
          message.success("비밀번호가 초기화되었습니다");
          setPwModalOpen(false);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "초기화 실패"),
      }
    );
  };

  const columns: ColumnsType<AdminUser> = [
    { title: "로그인ID", dataIndex: "login_id", width: 140 },
    { title: "사번", dataIndex: "emp_no", width: 100, render: (v) => v ?? "-" },
    { title: "이름", dataIndex: "name_ko", width: 100, render: (v) => v ?? "-" },
    {
      title: "부서",
      dataIndex: "dept_name",
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "권한",
      dataIndex: "role_names",
      width: 220,
      render: (v: string[]) =>
        v.length > 0 ? (
          <Space size={4} wrap>
            {v.map((n) => (
              <Tag key={n} color="blue">
                {n}
              </Tag>
            ))}
          </Space>
        ) : (
          "-"
        ),
    },
    {
      title: "상태",
      dataIndex: "is_active",
      width: 80,
      render: (v: boolean) => (
        <Tag color={v ? "green" : "red"}>{v ? "활성" : "비활성"}</Tag>
      ),
    },
    {
      title: "",
      key: "actions",
      width: 140,
      render: (_, r) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(r)}
          />
          <Button
            type="text"
            size="small"
            icon={<KeyOutlined />}
            onClick={() => openResetPw(r)}
          />
          <Popconfirm
            title="삭제하시겠습니까?"
            okText="삭제"
            okButtonProps={{ danger: true }}
            cancelText="취소"
            onConfirm={() =>
              deleteUser.mutate(r.id, {
                onSuccess: () => message.success("삭제되었습니다"),
                onError: (e: any) =>
                  message.error(e?.response?.data?.detail ?? "삭제 실패"),
              })
            }
          >
            <Button type="text" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "관리" }, { title: "사용자관리" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        사용자관리
      </Title>
      <Card
        extra={
          <Space>
            <Input.Search
              placeholder="로그인ID/사번/이름"
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 220 }}
            />
            <Space size={4}>
              <span>비활성 포함</span>
              <Switch
                size="small"
                checked={showInactive}
                onChange={setShowInactive}
              />
            </Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              사용자 추가
            </Button>
          </Space>
        }
      >
        <Table<AdminUser>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editTarget ? "사용자 수정" : "사용자 추가"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createUser.isPending || updateUser.isPending}
        okText="저장"
        cancelText="취소"
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="login_id"
            label="로그인ID"
            rules={[{ required: true, message: "로그인ID를 입력하세요" }]}
          >
            <Input disabled={!!editTarget} />
          </Form.Item>
          {!editTarget && (
            <Form.Item
              name="password"
              label="비밀번호"
              rules={[
                { required: true, message: "비밀번호를 입력하세요" },
                { min: 4, message: "4자 이상" },
              ]}
            >
              <Input.Password />
            </Form.Item>
          )}
          <Form.Item name="employee_id" label="직원 연결">
            <Select
              showSearch
              allowClear
              filterOption={false}
              onSearch={setEmpSearch}
              options={empOptions}
              placeholder="사번/이름 검색"
              notFoundContent={null}
            />
          </Form.Item>
          <Form.Item name="role_ids" label="권한">
            <Select mode="multiple" options={roleOptions} />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`비밀번호 초기화 - ${pwTarget?.login_id ?? ""}`}
        open={pwModalOpen}
        onOk={onResetPw}
        onCancel={() => setPwModalOpen(false)}
        confirmLoading={resetPw.isPending}
        okText="초기화"
        cancelText="취소"
        width={400}
      >
        <Form form={pwForm} layout="vertical">
          <Form.Item
            name="new_password"
            label="새 비밀번호"
            rules={[
              { required: true, message: "새 비밀번호를 입력하세요" },
              { min: 4, message: "4자 이상" },
            ]}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
