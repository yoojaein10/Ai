import { useEffect, useState } from "react";
import {
  Button,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  message,
} from "antd";
import { EditOutlined, SaveOutlined, CloseOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useUpdateEmployee } from "../../api/employees";

interface Props {
  employeeId: number;
  detail: Record<string, unknown>;
}

const genderLabel = (g: unknown) => (g === "F" ? "여" : g === "M" ? "남" : "-");
const dash = (v: unknown) => (v === null || v === undefined || v === "" ? "-" : String(v));

export default function MasterTab({ employeeId, detail }: Props) {
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm();
  const update = useUpdateEmployee(employeeId);

  useEffect(() => {
    if (editing) {
      form.setFieldsValue({
        name_ko: detail.name_ko ?? "",
        name_cn: detail.name_cn ?? "",
        name_en: detail.name_en ?? "",
        gender: detail.gender ?? undefined,
        birth_date: detail.birth_date ? dayjs(detail.birth_date as string) : null,
        hire_type: detail.hire_type ?? undefined,
        workplace: detail.workplace ?? "",
        work_location: detail.work_location ?? "",
        job_title: detail.job_title ?? "",
        emp_type: detail.emp_type ?? undefined,
      });
    }
  }, [editing, detail, form]);

  const onSave = async () => {
    const values = await form.validateFields();
    const payload = {
      name_ko: values.name_ko || null,
      name_cn: values.name_cn || null,
      name_en: values.name_en || null,
      gender: values.gender || null,
      birth_date: values.birth_date ? (values.birth_date as dayjs.Dayjs).format("YYYY-MM-DD") : null,
      hire_type: values.hire_type || null,
      workplace: values.workplace || null,
      work_location: values.work_location || null,
      job_title: values.job_title || null,
      emp_type: values.emp_type || null,
    };
    update.mutate(payload, {
      onSuccess: () => {
        message.success("저장되었습니다");
        setEditing(false);
      },
      onError: () => message.error("저장에 실패했습니다"),
    });
  };

  if (!editing) {
    return (
      <>
        <div style={{ marginBottom: 12, display: "flex", justifyContent: "flex-end" }}>
          <Button type="primary" icon={<EditOutlined />} onClick={() => setEditing(true)}>
            편집
          </Button>
        </div>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="사번">{dash(detail.emp_no)}</Descriptions.Item>
          <Descriptions.Item label="성명">{dash(detail.name_ko)}</Descriptions.Item>
          <Descriptions.Item label="한자명">{dash(detail.name_cn)}</Descriptions.Item>
          <Descriptions.Item label="영문명">{dash(detail.name_en)}</Descriptions.Item>
          <Descriptions.Item label="성별">{genderLabel(detail.gender)}</Descriptions.Item>
          <Descriptions.Item label="생년월일">{dash(detail.birth_date)}</Descriptions.Item>
          <Descriptions.Item label="입사일">{dash(detail.hire_date)}</Descriptions.Item>
          <Descriptions.Item label="입사구분">{dash(detail.hire_type)}</Descriptions.Item>
          <Descriptions.Item label="사업장">{dash(detail.workplace)}</Descriptions.Item>
          <Descriptions.Item label="근무지">{dash(detail.work_location)}</Descriptions.Item>
          <Descriptions.Item label="부서">{dash(detail.department_name)}</Descriptions.Item>
          <Descriptions.Item label="직급">{dash(detail.job_rank)}</Descriptions.Item>
          <Descriptions.Item label="직위">{dash(detail.job_position)}</Descriptions.Item>
          <Descriptions.Item label="직책">{dash(detail.job_title)}</Descriptions.Item>
          <Descriptions.Item label="재직구분">{dash(detail.emp_status)}</Descriptions.Item>
          <Descriptions.Item label="사원구분">{dash(detail.emp_type)}</Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 12, fontSize: 12, color: "#999" }}>
          ※ 부서 / 직급 / 직위 / 재직구분은 <strong>발령관리 → 인사발령</strong>에서 변경하세요.
        </div>
      </>
    );
  }

  return (
    <>
      <div style={{ marginBottom: 12, display: "flex", justifyContent: "flex-end" }}>
        <Space>
          <Button icon={<CloseOutlined />} onClick={() => setEditing(false)}>
            취소
          </Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={onSave} loading={update.isPending}>
            저장
          </Button>
        </Space>
      </div>
      <Form form={form} layout="vertical">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
          <Form.Item label="사번">
            <Input value={String(detail.emp_no ?? "")} disabled />
          </Form.Item>
          <Form.Item name="name_ko" label="성명" rules={[{ required: true, message: "성명을 입력하세요" }]}>
            <Input />
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
          <Form.Item label="입사일">
            <Input value={String(detail.hire_date ?? "")} disabled />
          </Form.Item>
          <Form.Item name="hire_type" label="입사구분">
            <Select allowClear options={[{ value: "신규", label: "신규" }, { value: "경력", label: "경력" }]} />
          </Form.Item>
          <Form.Item name="workplace" label="사업장">
            <Input />
          </Form.Item>
          <Form.Item name="work_location" label="근무지">
            <Input />
          </Form.Item>
          <Form.Item label="부서">
            <Input value={String(detail.department_name ?? "-")} disabled />
          </Form.Item>
          <Form.Item label="직급">
            <Input value={String(detail.job_rank ?? "-")} disabled />
          </Form.Item>
          <Form.Item label="직위">
            <Input value={String(detail.job_position ?? "-")} disabled />
          </Form.Item>
          <Form.Item name="job_title" label="직책">
            <Input />
          </Form.Item>
          <Form.Item label="재직구분">
            <Input value={String(detail.emp_status ?? "")} disabled />
          </Form.Item>
          <Form.Item name="emp_type" label="사원구분">
            <Select
              allowClear
              options={[
                { value: "정규직", label: "정규직" },
                { value: "계약직", label: "계약직" },
                { value: "인턴", label: "인턴" },
                { value: "파견", label: "파견" },
              ]}
            />
          </Form.Item>
        </div>
      </Form>
      <div style={{ fontSize: 12, color: "#999" }}>
        ※ 사번 / 입사일 / 부서 / 직급 / 직위 / 재직구분은 이 화면에서 수정할 수 없습니다.
      </div>
    </>
  );
}
