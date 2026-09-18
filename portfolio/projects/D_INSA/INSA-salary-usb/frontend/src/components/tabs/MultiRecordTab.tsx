import { useState } from "react";
import { Button, Form, Input, DatePicker, InputNumber, Modal, Popconfirm, Table, message, Spin } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useTabList, useTabCreate, useTabDelete } from "../../api/empTabs";
import type { ColumnsType } from "antd/es/table";

export interface ColumnConfig {
  name: string;
  label: string;
  type?: "text" | "date" | "number" | "boolean";
  required?: boolean;
}

interface Props {
  employeeId: number;
  tabKey: string;
  columns: ColumnConfig[];
  editable?: boolean;
}

export default function MultiRecordTab({ employeeId, tabKey, columns, editable = true }: Props) {
  const { data, isLoading } = useTabList<Record<string, unknown>>(employeeId, tabKey);
  const create = useTabCreate(employeeId, tabKey);
  const remove = useTabDelete(employeeId, tabKey);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const tableColumns: ColumnsType<Record<string, unknown>> = columns.map((c) => ({
    title: c.label,
    dataIndex: c.name,
    key: c.name,
    render: (val: unknown) => {
      if (val === null || val === undefined) return "-";
      if (c.type === "boolean") return val ? "예" : "아니오";
      return String(val);
    },
  }));

  if (editable) {
    tableColumns.push({
      title: "",
      key: "actions",
      width: 50,
      render: (_, record) => (
        <Popconfirm
          title="삭제하시겠습니까?"
          onConfirm={() =>
            remove.mutate(record.id as number, {
              onSuccess: () => message.success("삭제되었습니다"),
            })
          }
        >
          <Button type="text" danger size="small" icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    });
  }

  const onAdd = async () => {
    const values = await form.validateFields();
    const body: Record<string, unknown> = {};
    for (const c of columns) {
      const v = values[c.name];
      body[c.name] = c.type === "date" && v ? (v as dayjs.Dayjs).format("YYYY-MM-DD") : (v ?? null);
    }
    create.mutate(body, {
      onSuccess: () => {
        message.success("추가되었습니다");
        setOpen(false);
        form.resetFields();
      },
      onError: () => message.error("추가에 실패했습니다"),
    });
  };

  if (isLoading) return <Spin style={{ display: "block", margin: "40px auto" }} />;

  return (
    <>
      {editable && (
        <div style={{ marginBottom: 12 }}>
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            추가
          </Button>
        </div>
      )}
      <Table
        columns={tableColumns}
        dataSource={data ?? []}
        rowKey="id"
        size="small"
        pagination={false}
      />
      <Modal
        title="새 항목 추가"
        open={open}
        onOk={onAdd}
        onCancel={() => { setOpen(false); form.resetFields(); }}
        confirmLoading={create.isPending}
        okText="추가"
        cancelText="취소"
      >
        <Form form={form} layout="vertical">
          {columns.map((c) => (
            <Form.Item
              key={c.name}
              name={c.name}
              label={c.label}
              rules={c.required ? [{ required: true, message: `${c.label}을(를) 입력하세요` }] : undefined}
            >
              {c.type === "date" ? (
                <DatePicker style={{ width: "100%" }} />
              ) : c.type === "number" ? (
                <InputNumber style={{ width: "100%" }} />
              ) : (
                <Input />
              )}
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </>
  );
}
