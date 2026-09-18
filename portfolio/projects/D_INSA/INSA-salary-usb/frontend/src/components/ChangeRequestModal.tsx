import { useEffect, useState } from "react";
import { Form, Input, Modal, Select, Typography, message } from "antd";
import { useTabData } from "../api/empTabs";
import { useCreateChangeRequest } from "../api/changeRequests";
import { useMyChangeRequests } from "../api/changeRequests";
import { List, Tag } from "antd";

const FIELDS: { value: string; label: string }[] = [
  { value: "address", label: "주소" },
  { value: "phone", label: "연락처" },
  { value: "email", label: "이메일" },
  { value: "emergency_contact", label: "비상연락인" },
  { value: "emergency_phone", label: "비상연락처" },
];

const STATUS_LABEL: Record<string, { color: string; text: string }> = {
  PENDING: { color: "gold", text: "대기" },
  APPROVED: { color: "green", text: "승인" },
  REJECTED: { color: "red", text: "반려" },
};

interface Props {
  employeeId: number | null;
  open: boolean;
  onClose: () => void;
}

export default function ChangeRequestModal({ employeeId, open, onClose }: Props) {
  const { data: personal } = useTabData<Record<string, string | null>>(
    employeeId,
    "personal"
  );
  const { data: myRequests } = useMyChangeRequests();
  const create = useCreateChangeRequest();
  const [form] = Form.useForm();
  const [selectedField, setSelectedField] = useState<string>("address");

  useEffect(() => {
    if (open) {
      setSelectedField("address");
      form.resetFields();
    }
  }, [open, form]);

  const currentValue = personal?.[selectedField] ?? "";

  const onSubmit = async () => {
    const values = await form.validateFields();
    create.mutate(
      {
        field_name: values.field_name,
        new_value: values.new_value,
        reason: values.reason || null,
      },
      {
        onSuccess: () => {
          message.success("변경요청이 제출되었습니다. 관리자 승인 대기 중입니다.");
          form.resetFields();
          onClose();
        },
        onError: () => message.error("요청 제출에 실패했습니다"),
      }
    );
  };

  return (
    <Modal
      title="개인정보 변경요청"
      open={open}
      onOk={onSubmit}
      onCancel={onClose}
      confirmLoading={create.isPending}
      okText="요청 제출"
      cancelText="취소"
      width={560}
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
        주소, 연락처, 이메일 등 신상 정보는 인사 담당자 승인 후 반영됩니다.
      </Typography.Paragraph>

      <Form
        form={form}
        layout="vertical"
        initialValues={{ field_name: "address" }}
        onValuesChange={(changed) => {
          if (changed.field_name) setSelectedField(changed.field_name);
        }}
      >
        <Form.Item
          name="field_name"
          label="변경 항목"
          rules={[{ required: true, message: "항목을 선택하세요" }]}
        >
          <Select options={FIELDS} />
        </Form.Item>

        <Form.Item label="현재 값">
          <Input value={currentValue ?? ""} disabled />
        </Form.Item>

        <Form.Item
          name="new_value"
          label="변경 값"
          rules={[{ required: true, message: "변경할 값을 입력하세요" }]}
        >
          <Input placeholder="새 값 입력" />
        </Form.Item>

        <Form.Item name="reason" label="사유 (선택)">
          <Input.TextArea rows={2} placeholder="변경 사유 (선택)" />
        </Form.Item>
      </Form>

      {myRequests && myRequests.length > 0 && (
        <>
          <Typography.Title level={5} style={{ fontSize: 14, marginTop: 8 }}>
            나의 최근 요청
          </Typography.Title>
          <List
            size="small"
            bordered
            dataSource={myRequests.slice(0, 5)}
            renderItem={(r) => (
              <List.Item>
                <Tag color={STATUS_LABEL[r.status]?.color}>
                  {STATUS_LABEL[r.status]?.text}
                </Tag>
                <span style={{ flex: 1 }}>
                  <strong>{r.field_label}</strong> : {r.old_value ?? "-"} →{" "}
                  {r.new_value ?? "-"}
                </span>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {r.requested_at?.replace("T", " ").slice(0, 16)}
                </Typography.Text>
              </List.Item>
            )}
          />
        </>
      )}
    </Modal>
  );
}
