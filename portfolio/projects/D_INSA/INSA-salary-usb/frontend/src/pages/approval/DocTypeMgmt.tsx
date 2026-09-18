import { useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { PageShell } from "../../shell/PageShell";
import {
  useCreateDocTypeMutation,
  useDocTypes,
  useUpdateDocTypeMutation,
  type DocCategory,
  type DocType,
} from "../../api/approval";

const CATEGORY_OPTIONS: { label: string; value: DocCategory }[] = [
  { label: "인사", value: "HR" },
  { label: "근태", value: "ATTENDANCE" },
  { label: "출장", value: "TRAVEL" },
  { label: "계약", value: "CONTRACT" },
  { label: "기타", value: "OTHER" },
];

export default function DocTypeMgmt() {
  const { data, isLoading } = useDocTypes(false);
  const [form] = Form.useForm();
  const [editing, setEditing] = useState<DocType | null>(null);
  const [open, setOpen] = useState(false);
  const create = useCreateDocTypeMutation();
  const update = useUpdateDocTypeMutation();

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setOpen(true);
  };
  const openEdit = (dt: DocType) => {
    setEditing(dt);
    form.setFieldsValue(dt);
    setOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (editing) {
      update.mutate(
        {
          id: editing.id,
          body: {
            name: values.name,
            category: values.category,
            description: values.description ?? null,
            is_active: values.is_active,
          },
        },
        {
          onSuccess: () => {
            message.success("수정되었습니다");
            setOpen(false);
          },
          onError: (err) => message.error((err as Error).message),
        },
      );
    } else {
      create.mutate(values, {
        onSuccess: () => {
          message.success("생성되었습니다");
          setOpen(false);
        },
        onError: (err) => message.error((err as Error).message),
      });
    }
  };

  const columns: ColumnsType<DocType> = [
    { title: "코드", dataIndex: "code", width: 160 },
    { title: "이름", dataIndex: "name" },
    {
      title: "분류",
      dataIndex: "category",
      width: 100,
      render: (c: DocCategory) =>
        CATEGORY_OPTIONS.find((o) => o.value === c)?.label ?? c,
    },
    { title: "설명", dataIndex: "description" },
    {
      title: "활성",
      dataIndex: "is_active",
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">사용</Tag> : <Tag>중지</Tag>),
    },
    {
      title: "수정",
      width: 80,
      render: (_, r) => (
        <Button size="small" onClick={() => openEdit(r)}>
          수정
        </Button>
      ),
    },
  ];

  return (
    <PageShell
      title="문서 타입 관리"
      subtitle="전자결재 문서 유형 마스터"
      actions={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          새 문서 타입
        </Button>
      }
    >
      <Card size="small">
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={false}
        />
      </Card>

      <Modal
        open={open}
        title={editing ? "문서 타입 수정" : "새 문서 타입"}
        okText="저장"
        cancelText="취소"
        onOk={onSubmit}
        onCancel={() => setOpen(false)}
        confirmLoading={create.isPending || update.isPending}
      >
        <Form form={form} layout="vertical" initialValues={{ is_active: true }}>
          {!editing && (
            <Form.Item
              label="코드"
              name="code"
              rules={[{ required: true, message: "코드는 필수입니다" }]}
            >
              <Input placeholder="예: ATT_LEAVE" />
            </Form.Item>
          )}
          <Form.Item label="이름" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="분류" name="category" rules={[{ required: true }]}>
            <Select options={CATEGORY_OPTIONS} />
          </Form.Item>
          <Form.Item label="설명" name="description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="활성" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </PageShell>
  );
}
