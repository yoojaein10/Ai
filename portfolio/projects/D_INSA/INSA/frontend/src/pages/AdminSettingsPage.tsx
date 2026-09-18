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
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useAdminSettings,
  useCreateAdminSetting,
  useDeleteAdminSetting,
  useUpdateAdminSetting,
  type AdminSetting,
} from "../api/admin";

const { Title } = Typography;

const CATEGORY_OPTIONS = [
  { value: "회사정보", label: "회사정보" },
  { value: "시스템", label: "시스템" },
  { value: "보안", label: "보안" },
  { value: "기타", label: "기타" },
];

const VALUE_TYPE_OPTIONS = [
  { value: "string", label: "문자열" },
  { value: "int", label: "숫자" },
  { value: "bool", label: "Bool" },
  { value: "json", label: "JSON" },
];

export default function AdminSettingsPage() {
  const [activeTab, setActiveTab] = useState<string>("ALL");
  const { data, isLoading } = useAdminSettings(
    activeTab === "ALL" ? undefined : activeTab
  );
  const createSetting = useCreateAdminSetting();
  const updateSetting = useUpdateAdminSetting();
  const deleteSetting = useDeleteAdminSetting();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AdminSetting | null>(null);
  const [form] = Form.useForm();

  const categories = useMemo(() => {
    const cats = new Set<string>(CATEGORY_OPTIONS.map((o) => o.value));
    (data?.items ?? []).forEach((s) => s.category && cats.add(s.category));
    return Array.from(cats);
  }, [data]);

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    form.setFieldsValue({
      value_type: "string",
      is_editable: true,
      category: activeTab === "ALL" ? undefined : activeTab,
    });
    setModalOpen(true);
  };

  const openEdit = (s: AdminSetting) => {
    setEditTarget(s);
    form.setFieldsValue({
      key: s.key,
      name: s.name,
      value: s.value,
      category: s.category,
      description: s.description,
      value_type: s.value_type,
      is_editable: s.is_editable,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (editTarget) {
      updateSetting.mutate(
        {
          id: editTarget.id,
          data: {
            value: values.value,
            name: values.name,
            description: values.description,
            category: values.category,
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
      createSetting.mutate(values, {
        onSuccess: () => {
          message.success("생성되었습니다");
          setModalOpen(false);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "생성 실패"),
      });
    }
  };

  const columns: ColumnsType<AdminSetting> = [
    { title: "키", dataIndex: "key", width: 200 },
    { title: "이름", dataIndex: "name", render: (v) => v ?? "-" },
    {
      title: "값",
      dataIndex: "value",
      render: (v: string | null) =>
        v == null ? (
          <span style={{ color: "#aaa" }}>(없음)</span>
        ) : (
          <code>{v.length > 80 ? v.slice(0, 80) + "..." : v}</code>
        ),
    },
    {
      title: "구분",
      dataIndex: "category",
      width: 100,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "타입",
      dataIndex: "value_type",
      width: 80,
    },
    {
      title: "편집",
      dataIndex: "is_editable",
      width: 70,
      render: (v: boolean) => (
        <Tag color={v ? "green" : "default"}>{v ? "가능" : "불가"}</Tag>
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
            disabled={!r.is_editable}
            icon={<EditOutlined />}
            onClick={() => openEdit(r)}
          />
          <Popconfirm
            title="삭제하시겠습니까?"
            okText="삭제"
            okButtonProps={{ danger: true }}
            cancelText="취소"
            disabled={!r.is_editable}
            onConfirm={() =>
              deleteSetting.mutate(r.id, {
                onSuccess: () => message.success("삭제되었습니다"),
                onError: (e: any) =>
                  message.error(e?.response?.data?.detail ?? "삭제 실패"),
              })
            }
          >
            <Button
              type="text"
              danger
              size="small"
              disabled={!r.is_editable}
              icon={<DeleteOutlined />}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const tabs = [
    { key: "ALL", label: "전체" },
    ...categories.map((c) => ({ key: c, label: c })),
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "관리" }, { title: "시스템설정" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        시스템설정
      </Title>
      <Card
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            설정 추가
          </Button>
        }
      >
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabs} />
        <Table<AdminSetting>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Modal
        title={editTarget ? "설정 수정" : "설정 추가"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createSetting.isPending || updateSetting.isPending}
        okText="저장"
        cancelText="취소"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Space.Compact block>
            <Form.Item
              name="key"
              label="키"
              rules={[{ required: true, message: "키를 입력하세요" }]}
              style={{ width: "50%" }}
            >
              <Input disabled={!!editTarget} placeholder="company.name" />
            </Form.Item>
            <Form.Item
              name="name"
              label="이름"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Input placeholder="회사명" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="value" label="값">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="category" label="구분" style={{ width: "50%" }}>
              <Select allowClear options={CATEGORY_OPTIONS} />
            </Form.Item>
            <Form.Item
              name="value_type"
              label="타입"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Select
                options={VALUE_TYPE_OPTIONS}
                disabled={!!editTarget}
              />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="description" label="설명">
            <Input.TextArea rows={2} />
          </Form.Item>
          {!editTarget && (
            <Form.Item
              name="is_editable"
              label="편집 가능"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}
