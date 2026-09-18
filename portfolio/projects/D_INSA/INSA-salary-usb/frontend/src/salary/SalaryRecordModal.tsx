import { useEffect } from "react";
import { DatePicker, Form, Input, InputNumber, Modal, Select } from "antd";
import dayjs from "dayjs";
import type { SalaryRecord } from "./types";

export interface EmployeeOption {
  id: number;
  emp_no: string;
  name: string;
}

interface Props {
  open: boolean;
  initial: SalaryRecord | null;
  employees: EmployeeOption[];
  onCancel: () => void;
  onSubmit: (record: SalaryRecord) => void;
}

export default function SalaryRecordModal({
  open,
  initial,
  employees,
  onCancel,
  onSubmit,
}: Props) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open) return;
    if (initial) {
      form.setFieldsValue({
        ...initial,
        effectiveDate: dayjs(initial.effectiveDate),
      });
    } else {
      form.resetFields();
    }
  }, [open, initial, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    const employee = employees.find((e) => e.id === values.empId);
    onSubmit({
      empId: values.empId,
      empNo: employee?.emp_no ?? initial?.empNo ?? "",
      empName: employee?.name ?? initial?.empName ?? "",
      year: values.year,
      effectiveDate: values.effectiveDate.format("YYYY-MM-DD"),
      annualSalary: values.annualSalary,
      raiseRate: values.raiseRate ?? null,
      note: values.note ?? null,
    });
  };

  return (
    <Modal
      open={open}
      title={initial ? "연봉 수정" : "연봉 등록"}
      onCancel={onCancel}
      onOk={handleOk}
      okText="확인"
      cancelText="취소"
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Form.Item
          name="empId"
          label="직원"
          rules={[{ required: true, message: "직원을 선택하세요" }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            disabled={initial !== null}
            options={employees.map((e) => ({
              value: e.id,
              label: `${e.name} (${e.emp_no})`,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="year"
          label="연도"
          rules={[{ required: true, message: "연도를 입력하세요" }]}
        >
          <InputNumber min={1990} max={2100} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="effectiveDate"
          label="적용일"
          rules={[{ required: true, message: "적용일을 선택하세요" }]}
        >
          <DatePicker style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="annualSalary"
          label="연봉액 (원)"
          rules={[{ required: true, message: "연봉액을 입력하세요" }]}
        >
          <InputNumber<number>
            min={0}
            style={{ width: "100%" }}
            formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
            parser={(v) => Number((v ?? "").replace(/,/g, ""))}
          />
        </Form.Item>
        <Form.Item name="raiseRate" label="인상률 (%)">
          <InputNumber step={0.1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="note" label="비고">
          <Input.TextArea rows={2} maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
