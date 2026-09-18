import { useEffect } from "react";
import { Button, Form, Input, DatePicker, message, Spin } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useTabData, useTabUpsert } from "../../api/empTabs";

export interface FieldConfig {
  name: string;
  label: string;
  type?: "text" | "date";
}

interface Props {
  employeeId: number;
  tabKey: string;
  fields: FieldConfig[];
  editable?: boolean;
}

export default function SingleRecordTab({ employeeId, tabKey, fields, editable = true }: Props) {
  const { data, isLoading } = useTabData<Record<string, unknown>>(employeeId, tabKey);
  const upsert = useTabUpsert(employeeId, tabKey);
  const [form] = Form.useForm();

  useEffect(() => {
    if (data) {
      const values: Record<string, unknown> = {};
      for (const f of fields) {
        const val = data[f.name];
        values[f.name] = f.type === "date" && val ? dayjs(val as string) : val;
      }
      form.setFieldsValue(values);
    } else {
      form.resetFields();
    }
  }, [data, form, fields]);

  const onSave = async () => {
    const values = await form.validateFields();
    const body: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.name];
      body[f.name] = f.type === "date" && v ? (v as dayjs.Dayjs).format("YYYY-MM-DD") : (v ?? null);
    }
    upsert.mutate(body, {
      onSuccess: () => message.success("저장되었습니다"),
      onError: () => message.error("저장에 실패했습니다"),
    });
  };

  if (isLoading) return <Spin style={{ display: "block", margin: "40px auto" }} />;

  return (
    <Form form={form} layout="vertical" style={{ maxWidth: 600 }}>
      {fields.map((f) => (
        <Form.Item key={f.name} name={f.name} label={f.label}>
          {f.type === "date" ? (
            <DatePicker style={{ width: "100%" }} disabled={!editable} />
          ) : (
            <Input disabled={!editable} />
          )}
        </Form.Item>
      ))}
      {editable && (
        <Form.Item>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={onSave}
            loading={upsert.isPending}
          >
            저장
          </Button>
        </Form.Item>
      )}
    </Form>
  );
}
