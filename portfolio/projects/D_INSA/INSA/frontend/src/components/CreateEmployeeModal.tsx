import { DatePicker, Form, Input, Modal, Select, message } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import apiClient from "../api/client";
import { useDepartments } from "../api/departments";

const rankOptions = ["사원", "대리", "과장", "차장", "부장", "이사"];
const positionOptions = ["팀원", "팀장", "실장", "본부장"];

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function CreateEmployeeModal({ open, onClose }: Props) {
  const [form] = Form.useForm();
  const qc = useQueryClient();
  const { data: departments } = useDepartments();

  const create = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const { data } = await apiClient.post("/employees", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      message.success("직원이 등록되었습니다");
      form.resetFields();
      onClose();
    },
    onError: () => message.error("등록에 실패했습니다"),
  });

  const onSubmit = async () => {
    const values = await form.validateFields();
    create.mutate({
      emp_no: values.emp_no,
      name_ko: values.name_ko,
      name_cn: values.name_cn || null,
      name_en: values.name_en || null,
      gender: values.gender || null,
      birth_date: values.birth_date ? (values.birth_date as dayjs.Dayjs).format("YYYY-MM-DD") : null,
      hire_date: (values.hire_date as dayjs.Dayjs).format("YYYY-MM-DD"),
      hire_type: values.hire_type || "신규",
      workplace: values.workplace || null,
      work_location: values.work_location || null,
      dept_id: values.dept_id || null,
      job_rank: values.job_rank || null,
      job_position: values.job_position || null,
      emp_status: "재직",
      emp_type: values.emp_type || "정규직",
    });
  };

  return (
    <Modal
      title="신규 직원 등록"
      open={open}
      onOk={onSubmit}
      onCancel={() => { form.resetFields(); onClose(); }}
      confirmLoading={create.isPending}
      okText="등록"
      cancelText="취소"
      width={600}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
          <Form.Item name="emp_no" label="사번" rules={[{ required: true, message: "사번을 입력하세요" }]}>
            <Input placeholder="예: 20250001" />
          </Form.Item>
          <Form.Item name="name_ko" label="성명" rules={[{ required: true, message: "성명을 입력하세요" }]}>
            <Input placeholder="홍길동" />
          </Form.Item>
          <Form.Item name="name_cn" label="한자명">
            <Input />
          </Form.Item>
          <Form.Item name="name_en" label="영문명">
            <Input />
          </Form.Item>
          <Form.Item name="gender" label="성별">
            <Select allowClear options={[{ value: "M", label: "남" }, { value: "F", label: "여" }]} />
          </Form.Item>
          <Form.Item name="birth_date" label="생년월일">
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="hire_date" label="입사일" rules={[{ required: true, message: "입사일을 선택하세요" }]}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="hire_type" label="입사구분" initialValue="신규">
            <Select options={[{ value: "신규", label: "신규" }, { value: "경력", label: "경력" }]} />
          </Form.Item>
          <Form.Item name="dept_id" label="부서">
            <Select
              allowClear
              placeholder="선택"
              options={departments?.map((d) => ({ value: d.id, label: d.name })) ?? []}
            />
          </Form.Item>
          <Form.Item name="job_rank" label="직급">
            <Select allowClear placeholder="선택" options={rankOptions.map((r) => ({ value: r, label: r }))} />
          </Form.Item>
          <Form.Item name="job_position" label="직위">
            <Select allowClear placeholder="선택" options={positionOptions.map((p) => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="emp_type" label="사원구분" initialValue="정규직">
            <Select options={[{ value: "정규직", label: "정규직" }, { value: "계약직", label: "계약직" }]} />
          </Form.Item>
          <Form.Item name="workplace" label="사업장">
            <Input placeholder="예: 본사" />
          </Form.Item>
          <Form.Item name="work_location" label="근무지">
            <Input placeholder="예: 서울 강남" />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
