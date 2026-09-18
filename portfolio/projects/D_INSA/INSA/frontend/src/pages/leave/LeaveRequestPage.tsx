import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  message,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useNavigate } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import { useLeaveTypes, useMyBalance } from "../../api/leave";
import { useLineTemplates, useDocTypes } from "../../api/approval";
import {
  useCalculateDays,
  useCreateLeaveDraft,
  useSubmitLeave,
  type HalfType,
} from "../../api/leaveRequest";

type FormValues = {
  leave_type_id: number;
  line_template_id: number;
  range: [Dayjs, Dayjs];
  half_type: HalfType | "NONE";
  title?: string;
  reason?: string;
  contact_during_leave?: string;
};

export default function LeaveRequestPage() {
  const [form] = Form.useForm<FormValues>();
  const navigate = useNavigate();

  const { data: types = [] } = useLeaveTypes(true);
  const { data: docTypes = [] } = useDocTypes(true);
  const attLeaveTypeId = useMemo(
    () => docTypes.find((d) => d.code === "ATT_LEAVE")?.id,
    [docTypes],
  );
  const { data: templates = [] } = useLineTemplates(attLeaveTypeId);
  const { data: balance } = useMyBalance();

  const [preview, setPreview] = useState<{
    days: number;
    business_days: number;
    excluded: string[];
    unit: string;
  } | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  const calculate = useCalculateDays();
  const createDraft = useCreateLeaveDraft();
  const submit = useSubmitLeave();

  const selectedTypeId = Form.useWatch("leave_type_id", form);
  const range = Form.useWatch("range", form);
  const halfType = Form.useWatch("half_type", form);

  const selectedType = useMemo(
    () => types.find((t) => t.id === selectedTypeId),
    [types, selectedTypeId],
  );
  const isHalfEligible = selectedType?.unit === "HALF_DAY";

  // Auto-select default template when doc type resolves.
  useEffect(() => {
    if (!templates.length) return;
    const cur = form.getFieldValue("line_template_id");
    if (cur) return;
    const def = templates.find((t) => t.is_default) ?? templates[0];
    if (def) form.setFieldValue("line_template_id", def.id);
  }, [templates, form]);

  // Recalculate when inputs change.
  useEffect(() => {
    if (!selectedTypeId || !range?.[0] || !range?.[1]) {
      setPreview(null);
      setPreviewErr(null);
      return;
    }
    const startIso = range[0].format("YYYY-MM-DD");
    const endIso = range[1].format("YYYY-MM-DD");
    const ht = isHalfEligible && halfType && halfType !== "NONE" ? halfType : null;
    calculate.mutate(
      {
        leave_type_id: selectedTypeId,
        start_date: startIso,
        end_date: endIso,
        half_type: ht as HalfType | null,
      },
      {
        onSuccess: (d) => {
          setPreview({
            days: Number(d.days),
            business_days: d.business_days,
            excluded: d.excluded_holidays,
            unit: d.unit,
          });
          setPreviewErr(null);
        },
        onError: (err) => {
          setPreview(null);
          const detail =
            // axios error with server detail
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (err as any)?.response?.data?.detail ?? (err as Error).message;
          setPreviewErr(String(detail));
        },
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTypeId, range?.[0]?.valueOf(), range?.[1]?.valueOf(), halfType, isHalfEligible]);

  const onFinish = (values: FormValues, action: "draft" | "submit") => {
    if (!preview) {
      message.error("일수 계산이 완료되지 않았습니다");
      return;
    }
    const body = {
      leave_type_id: values.leave_type_id,
      line_template_id: values.line_template_id,
      title: values.title ?? null,
      start_date: values.range[0].format("YYYY-MM-DD"),
      end_date: values.range[1].format("YYYY-MM-DD"),
      half_type:
        isHalfEligible && values.half_type && values.half_type !== "NONE"
          ? (values.half_type as HalfType)
          : null,
      reason: values.reason ?? null,
      delegate_emp_id: null,
      contact_during_leave: values.contact_during_leave ?? null,
      evidence_file_url: null,
    };
    createDraft.mutate(body, {
      onSuccess: (r) => {
        if (action === "draft") {
          message.success("임시 저장되었습니다");
          navigate("/att/leave/my-requests");
          return;
        }
        submit.mutate(r.doc_id, {
          onSuccess: () => {
            message.success("결재 요청되었습니다");
            navigate("/att/leave/my-requests");
          },
          onError: (err) => {
            message.error(
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (err as any)?.response?.data?.detail ?? (err as Error).message,
            );
          },
        });
      },
      onError: (err) => {
        message.error(
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (err as any)?.response?.data?.detail ?? (err as Error).message,
        );
      },
    });
  };

  const remaining = Number(balance?.remaining ?? 0);

  return (
    <PageShell
      title="휴가 신청"
      subtitle="연차 · 반차 · 기타 휴가 결재 신청"
      actions={
        <Button onClick={() => navigate("/att/leave/my-requests")}>
          내 신청 내역
        </Button>
      }
      contextPanel={
        <Card size="small" title="요약">
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Statistic
              title="잔여 연차"
              value={remaining}
              precision={1}
              suffix="일"
            />
            {preview ? (
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="소요 일수">
                  {preview.days.toFixed(1)} 일
                </Descriptions.Item>
                <Descriptions.Item label="영업일">
                  {preview.business_days}일
                </Descriptions.Item>
                <Descriptions.Item label="제외 공휴일">
                  {preview.excluded.length === 0 ? (
                    <span style={{ color: "#999" }}>없음</span>
                  ) : (
                    <Space size={[4, 4]} wrap>
                      {preview.excluded.map((d) => (
                        <Tag key={d}>{d.slice(5)}</Tag>
                      ))}
                    </Space>
                  )}
                </Descriptions.Item>
              </Descriptions>
            ) : previewErr ? (
              <Alert type="warning" showIcon message={previewErr} />
            ) : (
              <Alert
                type="info"
                showIcon
                message="휴가 종류와 기간을 선택하면 일수가 계산됩니다"
              />
            )}
            {preview && selectedType?.deduct_from === "ANNUAL" && preview.days > remaining && (
              <Alert
                type="error"
                showIcon
                message={`잔여 연차(${remaining.toFixed(
                  1,
                )}일)를 초과합니다`}
              />
            )}
          </Space>
        </Card>
      }
    >
      <Card size="small">
        <Form
          form={form}
          layout="vertical"
          size="small"
          onFinish={(v) => onFinish(v, "submit")}
          initialValues={{ half_type: "NONE" }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="leave_type_id"
                label="휴가 종류"
                rules={[{ required: true, message: "휴가 종류를 선택하세요" }]}
              >
                <Select
                  placeholder="선택"
                  options={types.map((t) => ({ value: t.id, label: t.name }))}
                />
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

          <Row gutter={16}>
            <Col span={14}>
              <Form.Item
                name="range"
                label="기간"
                rules={[{ required: true, message: "기간을 선택하세요" }]}
              >
                <DatePicker.RangePicker
                  style={{ width: "100%" }}
                  format="YYYY-MM-DD"
                  disabledDate={(d) => d && d.isBefore(dayjs().startOf("day").subtract(30, "day"))}
                />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item
                name="half_type"
                label="반차"
                tooltip="반차 지원 휴가 종류에만 적용됩니다"
              >
                <Radio.Group disabled={!isHalfEligible}>
                  <Radio.Button value="NONE">종일</Radio.Button>
                  <Radio.Button value="AM">오전</Radio.Button>
                  <Radio.Button value="PM">오후</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="title" label="제목">
            <Input placeholder="비워두면 '휴가 종류 + 기간'으로 자동 생성" />
          </Form.Item>

          <Form.Item name="reason" label="사유">
            <Input.TextArea rows={3} maxLength={500} showCount />
          </Form.Item>

          <Form.Item name="contact_during_leave" label="휴가 중 연락처">
            <Input placeholder="예: 010-0000-0000" maxLength={50} />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              htmlType="submit"
              loading={createDraft.isPending || submit.isPending}
              disabled={!preview || !!previewErr}
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
              disabled={!preview || !!previewErr}
            >
              임시 저장
            </Button>
          </Space>
        </Form>
      </Card>
    </PageShell>
  );
}
