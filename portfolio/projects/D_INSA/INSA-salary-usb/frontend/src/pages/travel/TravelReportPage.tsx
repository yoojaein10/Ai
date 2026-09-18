import { useEffect, useMemo } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Space,
  Tag,
  message,
} from "antd";
import { useNavigate, useParams } from "react-router-dom";
import { PageShell } from "../../shell/PageShell";
import { useDocTypes, useLineTemplates } from "../../api/approval";
import { useTravelOrderDetail } from "../../api/travelOrder";
import {
  useCancelTravelReport,
  useCreateTravelReport,
  useSubmitTravelReport,
  useTravelReport,
} from "../../api/travelReport";

type FormValues = {
  line_template_id: number;
  title?: string;
  report_content: string;
  actual_cost?: number;
  receipts_url?: string;
};

export default function TravelReportPage() {
  const { docId: docIdParam } = useParams<{ docId: string }>();
  const docId = Number(docIdParam);
  const [form] = Form.useForm<FormValues>();
  const navigate = useNavigate();

  const { data: order, isLoading: orderLoading } = useTravelOrderDetail(
    Number.isFinite(docId) ? docId : null,
  );
  const { data: report } = useTravelReport(
    Number.isFinite(docId) ? docId : null,
  );

  const { data: docTypes = [] } = useDocTypes(true);
  const reportDocTypeId = useMemo(
    () => docTypes.find((d) => d.code === "TRAVEL_REPORT")?.id,
    [docTypes],
  );
  const { data: templates = [] } = useLineTemplates(reportDocTypeId);

  const createReport = useCreateTravelReport(docId);
  const submit = useSubmitTravelReport();
  const cancel = useCancelTravelReport();

  useEffect(() => {
    if (!templates.length) return;
    const cur = form.getFieldValue("line_template_id");
    if (cur) return;
    const def = templates.find((t) => t.is_default) ?? templates[0];
    if (def) form.setFieldValue("line_template_id", def.id);
  }, [templates, form]);

  const readonly = !!report;

  const onFinish = (values: FormValues, action: "draft" | "submit") => {
    const body = {
      line_template_id: values.line_template_id,
      title: values.title ?? null,
      report_content: values.report_content,
      actual_cost:
        values.actual_cost !== undefined && values.actual_cost !== null
          ? String(values.actual_cost)
          : null,
      receipts_url: values.receipts_url ?? null,
    };
    createReport.mutate(body, {
      onSuccess: (r) => {
        if (action === "draft") {
          message.success("복명서 임시 저장되었습니다");
          navigate("/travel/my");
          return;
        }
        submit.mutate(r.report_doc_id, {
          onSuccess: () => {
            message.success("복명서가 결재 요청되었습니다");
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

  const onCancelReport = () => {
    if (!report?.doc_id) return;
    cancel.mutate(report.doc_id, {
      onSuccess: () => {
        message.success("복명서가 취소되었습니다");
        navigate("/travel/my");
      },
      onError: (err) =>
        message.error(
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (err as any)?.response?.data?.detail ?? (err as Error).message,
        ),
    });
  };

  if (orderLoading) {
    return (
      <PageShell title="복명서 작성">
        <Card size="small">
          <Skeleton active />
        </Card>
      </PageShell>
    );
  }

  if (!order) {
    return (
      <PageShell title="복명서 작성">
        <Alert type="error" showIcon message="출장 정보를 찾을 수 없습니다" />
      </PageShell>
    );
  }

  return (
    <PageShell
      title="복명서 작성"
      subtitle="출장 결과 보고 및 실 비용 정산"
      actions={
        <Button onClick={() => navigate("/travel/my")}>내 출장 내역</Button>
      }
      contextPanel={
        <Card size="small" title="출장 정보">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="행선지">
              {order.destination}
              <Tag
                style={{ marginLeft: 6 }}
                color={order.travel_type === "OVERSEAS" ? "volcano" : "default"}
              >
                {order.travel_type === "OVERSEAS" ? "해외" : "국내"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="목적">{order.purpose}</Descriptions.Item>
            <Descriptions.Item label="기간">
              {order.start_at.replace("T", " ").slice(0, 16)} ~{" "}
              {order.end_at.replace("T", " ").slice(0, 16)}
            </Descriptions.Item>
            {order.estimated_cost && (
              <Descriptions.Item label="예상 비용">
                {Number(order.estimated_cost).toLocaleString()} 원
              </Descriptions.Item>
            )}
            {order.companions.length > 0 && (
              <Descriptions.Item label="동행자">
                <Space size={[4, 4]} wrap>
                  {order.companions.map((c) => (
                    <Tag key={c.emp_id}>{c.name_ko ?? c.emp_no}</Tag>
                  ))}
                </Space>
              </Descriptions.Item>
            )}
          </Descriptions>
        </Card>
      }
    >
      <Card size="small">
        {readonly ? (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message={
                report?.reported_at
                  ? `복명서가 승인되었습니다 (${report.reported_at.replace("T", " ").slice(0, 16)})`
                  : "복명서가 작성되어 결재 진행 중입니다"
              }
            />
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="보고 내용">
                <div style={{ whiteSpace: "pre-wrap" }}>
                  {report?.report_content}
                </div>
              </Descriptions.Item>
              {report?.actual_cost && (
                <Descriptions.Item label="실 비용">
                  {Number(report.actual_cost).toLocaleString()} 원
                </Descriptions.Item>
              )}
              {report?.receipts_url && (
                <Descriptions.Item label="증빙">
                  <a href={report.receipts_url} target="_blank" rel="noreferrer">
                    {report.receipts_url}
                  </a>
                </Descriptions.Item>
              )}
            </Descriptions>
            {!report?.reported_at && report?.doc_id && (
              <Space>
                <Button
                  onClick={() =>
                    report.doc_id && navigate(`/approval/docs/${report.doc_id}`)
                  }
                >
                  결재 진행 보기
                </Button>
                <Button danger onClick={onCancelReport}>
                  복명서 취소
                </Button>
              </Space>
            )}
          </Space>
        ) : (
          <Form
            form={form}
            layout="vertical"
            size="small"
            onFinish={(v) => onFinish(v, "submit")}
          >
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

            <Form.Item name="title" label="제목">
              <Input
                placeholder="비워두면 '[복명] + 출장명'으로 자동 생성"
                maxLength={200}
              />
            </Form.Item>

            <Form.Item
              name="report_content"
              label="보고 내용"
              rules={[{ required: true, message: "보고 내용을 입력하세요" }]}
            >
              <Input.TextArea rows={8} maxLength={5000} showCount />
            </Form.Item>

            <Form.Item name="actual_cost" label="실 비용 (원)">
              <InputNumber<number>
                style={{ width: 240 }}
                min={0}
                step={10000}
                formatter={(v) =>
                  `${v ?? ""}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
                }
                parser={(v) => Number((v ?? "").replace(/,/g, "")) as number}
              />
            </Form.Item>

            <Form.Item name="receipts_url" label="증빙 링크">
              <Input placeholder="영수증/증빙 URL (선택)" maxLength={500} />
            </Form.Item>

            <Space>
              <Button
                type="primary"
                htmlType="submit"
                loading={createReport.isPending || submit.isPending}
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
                loading={createReport.isPending}
              >
                임시 저장
              </Button>
            </Space>
          </Form>
        )}
      </Card>
    </PageShell>
  );
}
