import { useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Space,
  Tag,
  Tree,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";
import {
  useAdminMenus,
  useAdminRoles,
  useCreateAdminRole,
  useDeleteAdminRole,
  useUpdateAdminRole,
  type AdminMenu,
  type AdminRole,
} from "../api/admin";

const { Title, Text } = Typography;

function buildMenuTree(menus: AdminMenu[]): DataNode[] {
  const map = new Map<number, DataNode & { children: DataNode[] }>();
  menus.forEach((m) =>
    map.set(m.id, { key: m.id, title: m.name, children: [] })
  );
  const roots: DataNode[] = [];
  menus.forEach((m) => {
    const node = map.get(m.id)!;
    if (m.parent_id && map.has(m.parent_id)) {
      map.get(m.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

export default function AdminRolesPage() {
  const { data: rolesData, isLoading } = useAdminRoles();
  const { data: menusData } = useAdminMenus();
  const createRole = useCreateAdminRole();
  const updateRole = useUpdateAdminRole();
  const deleteRole = useDeleteAdminRole();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AdminRole | null>(null);
  const [form] = Form.useForm();
  const [checkedKeys, setCheckedKeys] = useState<number[]>([]);

  const roles = rolesData?.items ?? [];
  const selected = roles.find((r) => r.id === selectedId) ?? null;

  const menuTree = useMemo(
    () => buildMenuTree(menusData?.items ?? []),
    [menusData]
  );

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    setCheckedKeys([]);
    setModalOpen(true);
  };

  const openEdit = (r: AdminRole) => {
    setEditTarget(r);
    form.setFieldsValue({
      code: r.code,
      name: r.name,
      description: r.description,
    });
    setCheckedKeys(r.menu_ids);
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    const payload = { ...values, menu_ids: checkedKeys };
    if (editTarget) {
      updateRole.mutate(
        { id: editTarget.id, data: payload },
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
      createRole.mutate(payload, {
        onSuccess: () => {
          message.success("생성되었습니다");
          setModalOpen(false);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "생성 실패"),
      });
    }
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "관리" }, { title: "권한관리" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        권한관리
      </Title>
      <Row gutter={12}>
        <Col span={10}>
          <Card
            title="권한 목록"
            size="small"
            extra={
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                onClick={openCreate}
              >
                추가
              </Button>
            }
          >
            <List
              loading={isLoading}
              dataSource={roles}
              renderItem={(r) => (
                <List.Item
                  onClick={() => setSelectedId(r.id)}
                  style={{
                    cursor: "pointer",
                    background:
                      selectedId === r.id ? "#e6f4ff" : undefined,
                    padding: "8px 12px",
                  }}
                  actions={[
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        openEdit(r);
                      }}
                    />,
                    <Popconfirm
                      title="삭제하시겠습니까?"
                      okText="삭제"
                      okButtonProps={{ danger: true }}
                      cancelText="취소"
                      onConfirm={(e) => {
                        e?.stopPropagation();
                        deleteRole.mutate(r.id, {
                          onSuccess: () =>
                            message.success("삭제되었습니다"),
                          onError: (err: any) =>
                            message.error(
                              err?.response?.data?.detail ?? "삭제 실패"
                            ),
                        });
                      }}
                    >
                      <Button
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <Text strong>{r.name}</Text>
                        <Tag>{r.code}</Tag>
                        <Tag color="blue">{r.user_count}명</Tag>
                      </Space>
                    }
                    description={r.description ?? "-"}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={14}>
          <Card title="메뉴 권한" size="small">
            {selected ? (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Text strong>{selected.name}</Text>
                  <Tag>{selected.code}</Tag>
                </Space>
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">
                    할당된 메뉴: {selected.menu_ids.length}개
                  </Text>
                </div>
                <Tree
                  checkable
                  selectable={false}
                  treeData={menuTree}
                  checkedKeys={selected.menu_ids}
                  disabled
                />
                <div style={{ marginTop: 12 }}>
                  <Button onClick={() => openEdit(selected)}>메뉴 편집</Button>
                </div>
              </>
            ) : (
              <Empty description="좌측에서 권한을 선택하세요" />
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        title={editTarget ? "권한 수정" : "권한 추가"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createRole.isPending || updateRole.isPending}
        okText="저장"
        cancelText="취소"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Space.Compact block>
            <Form.Item
              name="code"
              label="코드"
              rules={[{ required: true, message: "코드를 입력하세요" }]}
              style={{ width: "40%" }}
            >
              <Input disabled={!!editTarget} placeholder="HR_ADMIN" />
            </Form.Item>
            <Form.Item
              name="name"
              label="이름"
              rules={[{ required: true, message: "이름을 입력하세요" }]}
              style={{ width: "60%", marginLeft: 8 }}
            >
              <Input />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="description" label="설명">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="메뉴 권한">
            <div
              style={{
                maxHeight: 320,
                overflow: "auto",
                border: "1px solid #f0f0f0",
                padding: 8,
                borderRadius: 4,
              }}
            >
              <Tree
                checkable
                selectable={false}
                treeData={menuTree}
                checkedKeys={checkedKeys}
                onCheck={(keys) => setCheckedKeys(keys as number[])}
              />
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
