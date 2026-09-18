import { useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  LinkOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  uploadBenefitEvents,
  useBenefitEvents,
  useBenefitItems,
  useCreateBenefitEvent,
  useDeleteBenefitEvent,
  useUpdateBenefitEvent,
  type BenefitEvent,
} from "../api/benefits";
import { useEmployees } from "../api/employees";

const { Title } = Typography;

const EVENT_TYPE_OPTIONS = [
  { value: "결혼", label: "결혼" },
  { value: "출산", label: "출산" },
  { value: "회갑", label: "회갑" },
  { value: "사망", label: "사망" },
  { value: "기타", label: "기타" },
];

const EVENT_COLOR: Record<string, string> = {
  결혼: "pink",
  출산: "cyan",
  회갑: "gold",
  사망: "default",
  기타: "default",
};

export default function BenefitEventsPage() {
  const [year, setYear] = useState<number | undefined>(dayjs().year());
  const [eventType, setEventType] = useState<string | undefined>();
  const [keyword, setKeyword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [empSearch, setEmpSearch] = useState("");

  const { data, isLoading } = useBenefitEvents({
    year,
    event_type: eventType,
    keyword,
  });
  const { data: itemsData } = useBenefitItems({
    category: "경조",
    is_active: true,
  });
  const { data: employeesData } = useEmployees({
    page: 1,
    page_size: 100,
    search: empSearch || undefined,
  });

  const createEv = useCreateBenefitEvent();
  const updateEv = useUpdateBenefitEvent();
  const deleteEv = useDeleteBenefitEvent();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<BenefitEvent | null>(null);
  const [form] = Form.useForm();

  const itemOptions = useMemo(
    () =>
      (itemsData?.items ?? []).map((i) => ({
        value: i.id,
        label: `${i.code} · ${i.name}`,
        item: i,
      })),
    [itemsData]
  );

  const employeeOptions = useMemo(
    () =>
      (employeesData?.items ?? []).map((e) => ({
        value: e.id,
        label: `${e.emp_no} ${e.name_ko}${
          e.department_name ? ` (${e.department_name})` : ""
        }`,
      })),
    [employeesData]
  );

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    form.setFieldsValue({ event_date: dayjs() });
    setModalOpen(true);
  };

  const openEdit = (r: BenefitEvent) => {
    setEditTarget(r);
    form.setFieldsValue({
      employee_id: r.employee_id,
      item_id: r.item_id,
      event_type: r.event_type,
      target_person: r.target_person,
      event_date: r.event_date ? dayjs(r.event_date) : null,
      amount: r.amount,
      leave_days: r.leave_days,
      remark: r.remark,
    });
    setModalOpen(true);
  };

  const onItemChange = (itemId: number | null) => {
    if (!itemId) return;
    const found = itemOptions.find((o) => o.value === itemId);
    if (found) {
      form.setFieldsValue({
        event_type: form.getFieldValue("event_type") ?? found.item.event_type,
        amount: form.getFieldValue("amount") ?? found.item.default_amount,
        leave_days:
          form.getFieldValue("leave_days") ?? found.item.default_leave_days,
      });
    }
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      event_date: values.event_date.format("YYYY-MM-DD"),
    };
    if (editTarget) {
      const { employee_id: _drop, ...rest } = payload;
      void _drop;
      updateEv.mutate(
        { id: editTarget.id, data: rest },
        {
          onSuccess: () => {
            message.success("수정되었습니다");
            setModalOpen(false);
          },
          onError: (err: any) =>
            message.error(err?.response?.data?.detail ?? "수정 실패"),
        }
      );
    } else {
      createEv.mutate(payload, {
        onSuccess: () => {
          message.success("등록되었습니다");
          setModalOpen(false);
          form.resetFields();
        },
        onError: (err: any) =>
          message.error(err?.response?.data?.detail ?? "등록 실패"),
      });
    }
  };

  const onDelete = (id: number) => {
    deleteEv.mutate(id, {
      onSuccess: () => message.success("삭제되었습니다"),
      onError: () => message.error("삭제 실패"),
    });
  };

  const uploadProps: UploadProps = {
    accept: ".xlsx,.xlsm",
    showUploadList: false,
    beforeUpload: async (file) => {
      setUploading(true);
      try {
        const res = await uploadBenefitEvents(file);
        if (res.errors.length) {
          Modal.warning({
            title: `업로드 완료 (생성 ${res.created} / 스킵 ${res.skipped})`,
            content: (
              <div style={{ maxHeight: 300, overflow: "auto" }}>
                {res.errors.map((e, i) => (
                  <div key={i}>{e}</div>
                ))}
              </div>
            ),
            width: 600,
          });
        } else {
          message.success(
            `업로드 완료: 생성 ${res.created}건, 스킵 ${res.skipped}건`
          );
        }
      } catch (err: any) {
        message.error(err?.response?.data?.detail ?? "업로드 실패");
      } finally {
        setUploading(false);
      }
      return false;
    },
  };

  const columns: ColumnsType<BenefitEvent> = [
    { title: "일자", dataIndex: "event_date", width: 110 },
    {
      title: "사번",
      dataIndex: "emp_no",
      width: 90,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "이름",
      dataIndex: "emp_name",
      width: 100,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "부서",
      dataIndex: "dept_name",
      width: 150,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "경조구분",
      dataIndex: "event_type",
      width: 100,
      render: (v: string) => (
        <Tag color={EVENT_COLOR[v] ?? "default"}>{v}</Tag>
      ),
    },
    {
      title: "대상자",
      dataIndex: "target_person",
      width: 100,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "항목",
      dataIndex: "item_name",
      width: 140,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "금액",
      dataIndex: "amount",
      width: 120,
      align: "right",
      render: (v: number | null) =>
        v != null ? Number(v).toLocaleString() : "-",
    },
    {
      title: "휴가",
      dataIndex: "leave_days",
      width: 80,
      align: "right",
      render: (v: number | null) => (v != null ? `${v}일` : "-"),
    },
    {
      title: "휴가연동",
      dataIndex: "linked_schedules",
      width: 110,
      render: (v: any[]) => {
        if (!v || v.length === 0) return <span style={{ color: "#bbb" }}>-</span>;
        const content = (
          <div style={{ maxWidth: 280 }}>
            {v.map((s, i) => (
              <div key={i}>
                {dayjs(s.schedule_date).format("MM/DD")} · {s.gubun}
                {s.bigo ? ` · ${s.bigo}` : ""}
              </div>
            ))}
          </div>
        );
        return (
          <Tooltip title={content}>
            <Tag icon={<LinkOutlined />} color="blue">
              {v.length}건
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_, r) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(r)}
          />
          <Popconfirm
            title="삭제하시겠습니까?"
            okText="삭제"
            okButtonProps={{ danger: true }}
            cancelText="취소"
            onConfirm={() => onDelete(r.id)}
          >
            <Button type="text" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Breadcrumb
        items={[{ title: "복리후생" }, { title: "경조사관리" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        경조사관리
      </Title>

      <Card
        extra={
          <Space wrap>
            <DatePicker
              picker="year"
              value={year ? dayjs(`${year}-01-01`) : null}
              onChange={(v) => setYear(v ? v.year() : undefined)}
              allowClear
              style={{ width: 110 }}
            />
            <Select
              placeholder="경조구분"
              allowClear
              value={eventType}
              onChange={setEventType}
              options={EVENT_TYPE_OPTIONS}
              style={{ width: 120 }}
            />
            <Input.Search
              placeholder="사번/이름/대상자"
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 220 }}
            />
            <Upload {...uploadProps}>
              <Button icon={<UploadOutlined />} loading={uploading}>
                엑셀 업로드
              </Button>
            </Upload>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              경조사 등록
            </Button>
          </Space>
        }
      >
        <Table<BenefitEvent>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 30, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editTarget ? "경조사 수정" : "경조사 등록"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createEv.isPending || updateEv.isPending}
        okText="저장"
        cancelText="취소"
        width={680}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="employee_id"
            label="직원"
            rules={[{ required: true, message: "직원을 선택하세요" }]}
          >
            <Select
              showSearch
              placeholder="사번/이름 입력 (2자 이상)"
              options={employeeOptions}
              filterOption={false}
              onSearch={(v) => setEmpSearch(v)}
              notFoundContent={empSearch ? "검색 결과 없음" : "이름/사번을 입력하세요"}
              disabled={!!editTarget}
            />
          </Form.Item>
          <Form.Item name="item_id" label="항목 카탈로그">
            <Select
              showSearch
              allowClear
              placeholder="항목 선택 (선택사항, 자동으로 기본값 채움)"
              options={itemOptions.map(({ item: _i, ...rest }) => {
                void _i;
                return rest;
              })}
              optionFilterProp="label"
              onChange={onItemChange}
            />
          </Form.Item>
          <Space.Compact block>
            <Form.Item
              name="event_type"
              label="경조구분"
              rules={[{ required: true, message: "구분을 선택하세요" }]}
              style={{ width: "50%" }}
            >
              <Select options={EVENT_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item
              name="event_date"
              label="일자"
              rules={[{ required: true, message: "일자를 선택하세요" }]}
              style={{ width: "50%", marginLeft: 8 }}
            >
              <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="target_person" label="대상자">
            <Input placeholder="예: 본인, 부친, 장녀" />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="amount" label="금액" style={{ width: "50%" }}>
              <InputNumber
                min={0}
                step={10000}
                style={{ width: "100%" }}
                formatter={(v) =>
                  `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
                }
              />
            </Form.Item>
            <Form.Item
              name="leave_days"
              label="휴가일수"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="remark" label="비고">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
