import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Tag,
  message,
} from "antd";
import type { Dayjs } from "dayjs";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import { useDocTypes, useLineTemplates } from "../../api/approval";
import { useEmployees } from "../../api/employees";
import {
  useCreateTravelOrder,
  useSubmitTravelOrder,
  type TravelType,
} from "../../api/travelOrder";

type FormValues = {
  line_template_id: number;
  travel_type: TravelType;
  title?: string;
  purpose: string;
  destination: string;
  client_company?: string;
  range: [Dayjs, Dayjs];
  transportation?: string;
  estimated_cost?: number;
  project_code?: string;
  appraisal_case_no?: string;
  remarks?: string;
  companion_emp_ids: number[];
};

export default function TravelOrderPage() {
  const [form] = Form.useForm<FormValues>();
  const navigate = useNavigate();
  const [empSearch, setEmpSearch] = useState("");

  const { data: docTypes = [] } = useDocTypes(true);
  const travelDocTypeId = useMemo(
    () => docTypes.find((d) => d.code === "TRAVEL_ORDER")?.id,
    [docTypes],
  );
  const { data: templates = [] } = useLineTemplates(travelDocTypeId);
  const { data: employeeData } = useEmployees({
    page: 1,
    page_size: 50,
    search: empSearch || undefined,
    emp_status: "ACTIVE",
  });
  const companionOptions = useMemo(
    () =>
      (employeeData?.items ?? []).map((e) => ({
        value: e.id,
        label: `${e.name_ko} (${e.emp_no}${e.department_name ? " · " + e.department_name : ""})`,
      })),
    [employeeData],
  );

  const createDraft = useCreateTravelOrder();
  const submit = useSubmitTravelOrder();

  useEffect(() => {
    if (!templates.length) return;
    const cur = form.getFieldValue("line_template_id");
    if (cur) return;
    const def = templates.find((t) => t.is_default) ?? templates[0];
    if (def) form.setFieldValue("line_template_id", def.id);
  }, [templates, form]);

  const onFinish = (values: FormValues, action: "draft" | "submit") => {
    const body = {
      line_template_id: values.line_template_id,
      title: values.title ?? null,
      travel_type: values.travel_type,
      purpose: values.purpose,
      destination: values.destination,
      client_company: values.client_company ?? null,
      start_at: values.range[0].format("YYYY-MM-DDTHH:mm:ss"),
      end_at: values.range[1].format("YYYY-MM-DDTHH:mm:ss"),
      transportation: values.transportation ?? null,
      estimated_cost:
        values.estimated_cost !== undefined && values.estimated_cost !== null
          ? String(values.estimated_cost)
          : null,
      project_code: values.project_code ?? null,
      appraisal_case_no: values.appraisal_case_no ?? null,
      remarks: values.remarks ?? null,
      companion_emp_ids: values.companion_emp_ids ?? [],
    };
    createDraft.mutate(body, {
      onSuccess: (r) => {
        if (action === "draft") {
          message.success("임시 저장되었습니다");
          navigate("/travel/my");
          return;
        }
        submit.mutate(r.doc_id, {
          onSuccess: () => {
            message.success("결재 요청되었습니다");
            navigate("/travel/my");
          },
          onError: (err) =>
            message.error(
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (err as any)?.response?.data?.detail ?? (err as Error).message,
            ),
        });
      },
      onError: (err) =>
        message.error(
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (err as any)?.response?.data?.detail ?? (err as Error).message,
        ),
    });
  };

  return (
    <PageShell
      title="출장명령부 기안"
      subtitle="출장 승인 요청 — 승인 시 캘린더에 자동 등록됩니다"
      actions={
        <Button onClick={() => navigate("/travel/my")}>내 출장 내역</Button>
      }
    >
      <Card size="small">
        <Form
          form={form}
          layout="vertical"
          size="small"
          initialValues={{
            travel_type: "DOMESTIC" as TravelType,
            companion_emp_ids: [],
          }}
          onFinish={(v) => onFinish(v, "submit")}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="travel_type"
                label="출장 구분"
                rules={[{ required: true }]}
              >
                <Radio.Group>
                  <Radio.Button value="DOMESTIC">국내</Radio.Button>
                  <Radio.Button value="OVERSEAS">해외</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item
                name="line_template_id"
                label="결재선"
                rules={[{ required: true, message: "결재선을 선택하세요" }]}
              >
                <Select
                  placeholder="선택"
                  options={templates.map((t) => ({
                    value: t.id,
                    label: `${t.name}${t.is_default ? " (기본)" : ""}`,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="destination"
            label="행선지"
            rules={[{ required: true, message: "행선지를 입력하세요" }]}
          >
            <Input placeholder="예: 부산, 도쿄" maxLength={200} />
          </Form.Item>

          <Form.Item
            name="purpose"
            label="출장 목적"
            rules={[{ required: true, message: "출장 목적을 입력하세요" }]}
          >
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="client_company" label="방문 업체">
                <Input maxLength={200} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="appraisal_case_no"
                label="감정평가 건번호"
                tooltip="감정평가 업무 관련 출장 시 입력"
              >
                <Input placeholder="예: 2026-감-001" maxLength={100} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="range"
            label="출장 기간"
            rules={[{ required: true, message: "기간을 선택하세요" }]}
          >
            <DatePicker.RangePicker
              style={{ width: "100%" }}
              showTime={{ format: "HH:mm", minuteStep: 30 }}
              format="YYYY-MM-DD HH:mm"
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="transportation" label="교통수단">
                <Input placeholder="KTX, 항공 등" maxLength={100} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="estimated_cost" label="예상 비용 (원)">
                <InputNumber<number>
                  style={{ width: "100%" }}
                  min={0}
                  step={10000}
                  formatter={(v) =>
                    `${v ?? ""}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
                  }
                  parser={(v) => Number((v ?? "").replace(/,/g, "")) as number}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="project_code" label="프로젝트 코드">
                <Input maxLength={50} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="companion_emp_ids"
            label="동행자"
            tooltip="본인은 자동으로 제외됩니다. 검색은 이름·사번 기준"
          >
            <Select
              mode="multiple"
              placeholder="동행자 검색 / 선택"
              options={companionOptions}
              filterOption={false}
              onSearch={setEmpSearch}
              showSearch
              tagRender={({ label, closable, onClose }) => (
                <Tag
                  closable={closable}
                  onClose={onClose}
                  style={{ marginRight: 3 }}
                >
                  {label}
                </Tag>
              )}
            />
          </Form.Item>

          <Form.Item name="title" label="제목">
            <Input placeholder="비워두면 '행선지 + 목적'으로 자동 생성" maxLength={200} />
          </Form.Item>

          <Form.Item name="remarks" label="비고">
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={createDraft.isPending || submit.isPending}
            >
              결재 요청
            </Button>
            <Button
              onClick={() => {
                form
                  .validateFields()
                  .then((v) => onFinish(v, "draft"))
                  .catch(() => {});
              }}
              loading={createDraft.isPending}
            >
              임시 저장
            </Button>
          </Space>
        </Form>
      </Card>
    </PageShell>
  );
}
