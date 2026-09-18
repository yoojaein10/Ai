import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tree,
  Typography,
  message,
} from "antd";
import { PlusOutlined, EditOutlined, StopOutlined, DeleteOutlined, CheckCircleOutlined } from "@ant-design/icons";
import {
  useDepartments,
  useDepartmentTree,
  useCreateDepartment,
  useUpdateDepartment,
  useDeleteDepartment,
} from "../api/departments";
import type { DepartmentTreeNode } from "../api/departments";
import type { DataNode } from "antd/es/tree";

const { Title } = Typography;

function toTreeData(nodes: DepartmentTreeNode[]): DataNode[] {
  return nodes.map((n) => ({
    key: n.id,
    title: (
      <span>
        {n.name} <Typography.Text type="secondary" style={{ fontSize: 11 }}>({n.code})</Typography.Text>
        {!n.is_active && <Tag color="red" style={{ marginLeft: 4 }}>비활성</Tag>}
      </span>
    ),
    children: n.children ? toTreeData(n.children) : [],
  }));
}

export default function DepartmentPage() {
  const { data: tree, isLoading: treeLoading } = useDepartmentTree();
  const { data: list } = useDepartments(true);
  const createDept = useCreateDepartment();
  const updateDept = useUpdateDepartment();
  const deleteDept = useDeleteDepartment();

  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<{ id: number; name: string } | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const selectedDept = list?.find((d) => d.id === selectedId);

  const onCreateSubmit = async () => {
    const values = await createForm.validateFields();
    createDept.mutate(
      { code: values.code, name: values.name, parent_id: selectedId },
      {
        onSuccess: () => {
          message.success("부서가 생성되었습니다");
          setCreateOpen(false);
          createForm.resetFields();
        },
        onError: () => message.error("생성에 실패했습니다"),
      }
    );
  };

  const onEditSubmit = async () => {
    if (!editTarget) return;
    const values = await editForm.validateFields();
    updateDept.mutate(
      { id: editTarget.id, name: values.name },
      {
        onSuccess: () => {
          message.success("수정되었습니다");
          setEditOpen(false);
        },
        onError: () => message.error("수정에 실패했습니다"),
      }
    );
  };

  const onDeactivate = (id: number) => {
    updateDept.mutate(
      { id, is_active: false },
      {
        onSuccess: () => message.success("비활성화되었습니다"),
        onError: () => message.error("비활성화에 실패했습니다"),
      }
    );
  };

  const onReactivate = (id: number) => {
    updateDept.mutate(
      { id, is_active: true },
      {
        onSuccess: () => message.success("활성화되었습니다"),
        onError: () => message.error("활성화에 실패했습니다"),
      }
    );
  };

  const onDelete = (id: number) => {
    deleteDept.mutate(id, {
      onSuccess: () => message.success("삭제되었습니다"),
      onError: (err: any) => {
        const detail = err?.response?.data?.detail ?? "삭제에 실패했습니다";
        message.error(detail);
      },
    });
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "부서관리" }, { title: "부서관리" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>부서관리</Title>

      <div style={{ display: "flex", gap: 12, height: "calc(100vh - 200px)" }}>
        <Card
          size="small"
          title="조직도"
          extra={
            <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              {selectedId ? "하위부서 추가" : "최상위 부서 추가"}
            </Button>
          }
          style={{ width: 350 }}
          styles={{ body: { overflow: "auto" } }}
        >
          {treeLoading ? (
            <Typography.Text type="secondary">로딩 중...</Typography.Text>
          ) : (
            <Tree
              treeData={tree ? toTreeData(tree) : []}
              defaultExpandAll
              onSelect={(keys) => setSelectedId(keys[0] as number ?? null)}
              selectedKeys={selectedId ? [selectedId] : []}
            />
          )}
        </Card>

        <Card size="small" title="부서 목록" style={{ flex: 1 }} styles={{ body: { overflow: "auto" } }}>
          <Table
            dataSource={list}
            rowKey="id"
            size="small"
            pagination={false}
            columns={[
              { title: "코드", dataIndex: "code", key: "code", width: 100 },
              { title: "부서명", dataIndex: "name", key: "name" },
              {
                title: "상태",
                dataIndex: "is_active",
                key: "is_active",
                width: 80,
                render: (active: boolean) => (
                  <Tag color={active ? "green" : "red"}>{active ? "활성" : "비활성"}</Tag>
                ),
              },
              {
                title: "",
                key: "actions",
                width: 160,
                render: (_, record) => (
                  <Space size="small">
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => {
                        setEditTarget({ id: record.id, name: record.name });
                        editForm.setFieldsValue({ name: record.name });
                        setEditOpen(true);
                      }}
                    />
                    {record.is_active ? (
                      <Popconfirm title="비활성화하시겠습니까?" onConfirm={() => onDeactivate(record.id)}>
                        <Button type="text" danger size="small" icon={<StopOutlined />} />
                      </Popconfirm>
                    ) : (
                      <Popconfirm title="활성화하시겠습니까?" onConfirm={() => onReactivate(record.id)}>
                        <Button type="text" size="small" style={{ color: "#52c41a" }} icon={<CheckCircleOutlined />} />
                      </Popconfirm>
                    )}
                    <Popconfirm
                      title="정말 삭제하시겠습니까?"
                      description="소속 직원·하위 부서가 있으면 삭제되지 않습니다"
                      okText="삭제"
                      okButtonProps={{ danger: true }}
                      cancelText="취소"
                      onConfirm={() => onDelete(record.id)}
                    >
                      <Button type="text" danger size="small" icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
            onRow={(record) => ({
              onClick: () => setSelectedId(record.id),
              style: {
                cursor: "pointer",
                background: record.id === selectedId ? "#e8f0fe" : undefined,
              },
            })}
          />
        </Card>
      </div>

      <Modal
        title={selectedId ? "하위부서 추가" : "최상위 부서 추가"}
        open={createOpen}
        onOk={onCreateSubmit}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        confirmLoading={createDept.isPending}
        okText="생성"
        cancelText="취소"
      >
        {selectedDept && (
          <Typography.Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
            상위부서: {selectedDept.name} ({selectedDept.code})
          </Typography.Text>
        )}
        <Form form={createForm} layout="vertical">
          <Form.Item name="code" label="부서코드" rules={[{ required: true, message: "부서코드를 입력하세요" }]}>
            <Input placeholder="예: HR, DEV" />
          </Form.Item>
          <Form.Item name="name" label="부서명" rules={[{ required: true, message: "부서명을 입력하세요" }]}>
            <Input placeholder="예: 인사팀" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="부서 수정"
        open={editOpen}
        onOk={onEditSubmit}
        onCancel={() => setEditOpen(false)}
        confirmLoading={updateDept.isPending}
        okText="저장"
        cancelText="취소"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="name" label="부서명" rules={[{ required: true, message: "부서명을 입력하세요" }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
