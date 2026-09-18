import { useEffect, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useAdminCodeGroups,
  useAdminCodes,
  useCreateAdminCode,
  useDeleteAdminCode,
  useUpdateAdminCode,
  type AdminCode,
} from "../api/admin";

const { Title, Text } = Typography;

export default function AdminCodesPage() {
  const { data: groupsData, isLoading: groupsLoading } = useAdminCodeGroups();
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const { data, isLoading } = useAdminCodes({
    group_code: selectedGroup ?? undefined,
    keyword,
  });
  const createCode = useCreateAdminCode();
  const updateCode = useUpdateAdminCode();
  const deleteCode = useDeleteAdminCode();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AdminCode | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    const first = groupsData?.groups?.[0];
    if (!selectedGroup && first) {
      setSelectedGroup(first.group_code);
    }
  }, [groupsData, selectedGroup]);

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    form.setFieldsValue({
      group_code: selectedGroup ?? "",
      is_active: true,
      sort_order: 0,
    });
    setModalOpen(true);
  };

  const openEdit = (c: AdminCode) => {
    setEditTarget(c);
    form.setFieldsValue({
      group_code: c.group_code,
      group_name: c.group_name,
      code: c.code,
      name: c.name,
      description: c.description,
      sort_order: c.sort_order,
      is_active: c.is_active,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (editTarget) {
      updateCode.mutate(
        { id: editTarget.id, data: values },
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
      createCode.mutate(values, {
        onSuccess: () => {
          message.success("생성되었습니다");
          setModalOpen(false);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "생성 실패"),
      });
    }
  };

  const columns: ColumnsType<AdminCode> = [
    { title: "코드", dataIndex: "code", width: 140 },
    { title: "이름", dataIndex: "name" },
    {
      title: "설명",
      dataIndex: "description",
      render: (v) => v ?? "-",
    },
    {
      title: "정렬",
      dataIndex: "sort_order",
      width: 70,
      align: "right",
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
      width: 90,
      render: (_, r) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(r)}
          />
          <Popconfirm
            title="삭제하시겠습니까?"
            okText="삭제"
            okButtonProps={{ danger: true }}
            cancelText="취소"
            onConfirm={() =>
              deleteCode.mutate(r.id, {
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
        items={[{ title: "관리" }, { title: "코드관리" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        코드관리
      </Title>
      <Row gutter={12}>
        <Col span={7}>
          <Card
            title="코드 그룹"
            size="small"
            extra={
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                onClick={openCreate}
              >
                코드 추가
              </Button>
            }
          >
            <List
              loading={groupsLoading}
              dataSource={groupsData?.groups ?? []}
              locale={{
                emptyText: <Empty description="코드가 없습니다" />,
              }}
              renderItem={(g) => (
                <List.Item
                  onClick={() => setSelectedGroup(g.group_code)}
                  style={{
                    cursor: "pointer",
                    background:
                      selectedGroup === g.group_code ? "#e6f4ff" : undefined,
                    padding: "8px 12px",
                  }}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <Text strong>{g.group_code}</Text>
                        <Tag color="blue">{g.count}</Tag>
                      </Space>
                    }
                    description={g.group_name ?? "-"}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={17}>
          <Card
            title={selectedGroup ?? "코드 목록"}
            size="small"
            extra={
              <Input.Search
                placeholder="코드/이름 검색"
                allowClear
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                style={{ width: 220 }}
              />
            }
          >
            <Table<AdminCode>
              rowKey="id"
              columns={columns}
              dataSource={data?.items ?? []}
              loading={isLoading}
              size="small"
              pagination={{ pageSize: 20 }}
            />
          </Card>
        </Col>
      </Row>

      <Modal
        title={editTarget ? "코드 수정" : "코드 추가"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createCode.isPending || updateCode.isPending}
        okText="저장"
        cancelText="취소"
        width={560}
      >
        <Form form={form} layout="vertical">
          <Space.Compact block>
            <Form.Item
              name="group_code"
              label="그룹코드"
              rules={[{ required: true, message: "그룹코드를 입력하세요" }]}
              style={{ width: "50%" }}
            >
              <Input disabled={!!editTarget} placeholder="EMP_STATUS" />
            </Form.Item>
            <Form.Item
              name="group_name"
              label="그룹명"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Input placeholder="재직상태" />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item
              name="code"
              label="코드"
              rules={[{ required: true, message: "코드를 입력하세요" }]}
              style={{ width: "50%" }}
            >
              <Input disabled={!!editTarget} placeholder="재직" />
            </Form.Item>
            <Form.Item
              name="name"
              label="이름"
              rules={[{ required: true, message: "이름을 입력하세요" }]}
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Input placeholder="재직" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="description" label="설명">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="sort_order" label="정렬" style={{ width: "50%" }}>
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              name="is_active"
              label="활성"
              valuePropName="checked"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Switch />
            </Form.Item>
          </Space.Compact>
        </Form>
      </Modal>
    </>
  );
}
