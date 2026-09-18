import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  useBenefitItems,
  useCreateBenefitItem,
  useUpdateBenefitItem,
  useDeleteBenefitItem,
  useBenefitOverview,
  useBenefitEvents,
  useBenefitHealth,
  type BenefitItem,
} from "../api/benefits";
import { useEmployees } from "../api/employees";

const { Title } = Typography;

const CATEGORY_OPTIONS = [
  { value: "경조", label: "경조" },
  { value: "건강", label: "건강" },
  { value: "포상", label: "포상" },
  { value: "기타", label: "기타" },
];

const CATEGORY_COLOR: Record<string, string> = {
  경조: "red",
  건강: "green",
  포상: "gold",
  기타: "default",
};

const EVENT_TYPE_OPTIONS = [
  { value: "결혼", label: "결혼(본인/자녀)" },
  { value: "출산", label: "출산" },
  { value: "회갑", label: "회갑" },
  { value: "사망", label: "사망(배우자/부모/자녀)" },
  { value: "기타", label: "기타" },
];

function ItemsTab() {
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState<string | undefined>();
  const [showInactive, setShowInactive] = useState(false);

  const { data, isLoading } = useBenefitItems({
    keyword,
    category,
    is_active: showInactive ? undefined : true,
  });
  const createItem = useCreateBenefitItem();
  const updateItem = useUpdateBenefitItem();
  const deleteItem = useDeleteBenefitItem();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<BenefitItem | null>(null);
  const [form] = Form.useForm();

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, category: "경조" });
    setModalOpen(true);
  };

  const openEdit = (item: BenefitItem) => {
    setEditTarget(item);
    form.setFieldsValue(item);
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (editTarget) {
      updateItem.mutate(
        { id: editTarget.id, data: values },
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
      createItem.mutate(values, {
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
    deleteItem.mutate(id, {
      onSuccess: () => message.success("삭제되었습니다"),
      onError: (err: any) =>
        message.error(err?.response?.data?.detail ?? "삭제 실패"),
    });
  };

  const columns: ColumnsType<BenefitItem> = [
    { title: "코드", dataIndex: "code", width: 120 },
    { title: "항목명", dataIndex: "name" },
    {
      title: "구분",
      dataIndex: "category",
      width: 90,
      render: (v: string) => (
        <Tag color={CATEGORY_COLOR[v] ?? "default"}>{v}</Tag>
      ),
    },
    {
      title: "이벤트타입",
      dataIndex: "event_type",
      width: 120,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "기본금액",
      dataIndex: "default_amount",
      width: 120,
      align: "right",
      render: (v: number | null) =>
        v != null ? Number(v).toLocaleString() : "-",
    },
    {
      title: "기본휴가",
      dataIndex: "default_leave_days",
      width: 100,
      align: "right",
      render: (v: number | null) => (v != null ? `${v}일` : "-"),
    },
    {
      title: "상태",
      dataIndex: "is_active",
      width: 80,
      render: (v: boolean) => (
        <Tag color={v ? "green" : "red"}>{v ? "활성" : "비활성"}</Tag>
      ),
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
            description="이력이 있으면 삭제되지 않습니다"
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
      <Card
        extra={
          <Space>
            <Input.Search
              placeholder="코드/항목명 검색"
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 220 }}
            />
            <Select
              placeholder="구분"
              allowClear
              value={category}
              onChange={setCategory}
              options={CATEGORY_OPTIONS}
              style={{ width: 120 }}
            />
            <Space size={4}>
              <span>비활성 포함</span>
              <Switch
                size="small"
                checked={showInactive}
                onChange={setShowInactive}
              />
            </Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              항목 추가
            </Button>
          </Space>
        }
      >
        <Table<BenefitItem>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editTarget ? "항목 수정" : "항목 추가"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createItem.isPending || updateItem.isPending}
        okText="저장"
        cancelText="취소"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Space.Compact block>
            <Form.Item
              name="code"
              label="코드"
              rules={[{ required: true, message: "코드를 입력하세요" }]}
              style={{ width: "40%" }}
            >
              <Input placeholder="예: BFT-001" />
            </Form.Item>
            <Form.Item
              name="name"
              label="항목명"
              rules={[{ required: true, message: "항목명을 입력하세요" }]}
              style={{ width: "60%", marginLeft: 8 }}
            >
              <Input />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item
              name="category"
              label="구분"
              rules={[{ required: true, message: "구분을 선택하세요" }]}
              style={{ width: "50%" }}
            >
              <Select options={CATEGORY_OPTIONS} />
            </Form.Item>
            <Form.Item
              name="event_type"
              label="이벤트타입"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Select allowClear options={EVENT_TYPE_OPTIONS} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item
              name="default_amount"
              label="기본금액"
              style={{ width: "50%" }}
            >
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
              name="default_leave_days"
              label="기본휴가(일)"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="description" label="설명">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function DashboardTab() {
  const [year, setYear] = useState<number>(dayjs().year());
  const { data, isLoading } = useBenefitOverview(year);

  const categoryColumns: ColumnsType<any> = [
    {
      title: "구분",
      dataIndex: "category",
      render: (v: string) => (
        <Tag color={CATEGORY_COLOR[v] ?? "default"}>{v}</Tag>
      ),
    },
    { title: "건수", dataIndex: "count", align: "right", width: 100 },
    {
      title: "금액 합계",
      dataIndex: "total_amount",
      align: "right",
      width: 180,
      render: (v: number) => Number(v ?? 0).toLocaleString(),
    },
    {
      title: "휴가 합계",
      dataIndex: "total_leave_days",
      align: "right",
      width: 120,
      render: (v: number) => `${Number(v ?? 0)}일`,
    },
  ];

  const monthlyColumns: ColumnsType<any> = [
    {
      title: "월",
      dataIndex: "month",
      width: 80,
      render: (v: number) => `${v}월`,
    },
    { title: "건수", dataIndex: "count", align: "right", width: 100 },
    {
      title: "금액 합계",
      dataIndex: "total_amount",
      align: "right",
      render: (v: number) => Number(v ?? 0).toLocaleString(),
    },
  ];

  return (
    <>
      <Card
        size="small"
        style={{ marginBottom: 12 }}
        extra={
          <DatePicker
            picker="year"
            value={dayjs(`${year}-01-01`)}
            onChange={(v) => setYear(v ? v.year() : dayjs().year())}
            allowClear={false}
            style={{ width: 110 }}
          />
        }
      >
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="연간 경조 건수"
              value={data?.event_total_count ?? 0}
              loading={isLoading}
              suffix="건"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="연간 경조 금액"
              value={Number(data?.event_total_amount ?? 0)}
              loading={isLoading}
              suffix="원"
              formatter={(v) =>
                Number(v).toLocaleString()
              }
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="연간 경조 휴가"
              value={Number(data?.event_total_leave_days ?? 0)}
              loading={isLoading}
              suffix="일"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="건강검진 수검"
              value={data?.health.total ?? 0}
              loading={isLoading}
              suffix="명"
            />
          </Col>
        </Row>
      </Card>

      <Row gutter={12}>
        <Col span={12}>
          <Card title="구분별 집계" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="category"
              columns={categoryColumns}
              dataSource={data?.by_category ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="월별 집계" size="small" style={{ marginBottom: 12 }}>
            <Table
              rowKey="month"
              columns={monthlyColumns}
              dataSource={data?.by_month ?? []}
              loading={isLoading}
              size="small"
              pagination={false}
              scroll={{ y: 340 }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="건강검진 결과 요약" size="small">
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="정상"
              value={data?.health.normal ?? 0}
              loading={isLoading}
              suffix="명"
              valueStyle={{ color: "#52c41a" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="요관찰"
              value={data?.health.caution ?? 0}
              loading={isLoading}
              suffix="명"
              valueStyle={{ color: "#faad14" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="유소견/질환의심"
              value={data?.health.abnormal ?? 0}
              loading={isLoading}
              suffix="명"
              valueStyle={{ color: "#f5222d" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="재검 필요"
              value={data?.health.recheck_required ?? 0}
              loading={isLoading}
              suffix="명"
              valueStyle={{ color: "#fa541c" }}
            />
          </Col>
        </Row>
      </Card>
    </>
  );
}

function HistoryTab() {
  const [empSearch, setEmpSearch] = useState("");
  const [employeeId, setEmployeeId] = useState<number | undefined>();
  const [year, setYear] = useState<number | undefined>(dayjs().year());

  const { data: employeesData } = useEmployees({
    page: 1,
    page_size: 100,
    search: empSearch || undefined,
  });

  const { data: eventsData, isLoading: eventsLoading } = useBenefitEvents({
    year,
    keyword: undefined,
  });
  const { data: healthData, isLoading: healthLoading } = useBenefitHealth({
    year,
  });

  const employeeOptions = (employeesData?.items ?? []).map((e) => ({
    value: e.id,
    label: `${e.emp_no} ${e.name_ko}${
      e.department_name ? ` (${e.department_name})` : ""
    }`,
  }));

  const filteredEvents = (eventsData?.items ?? []).filter(
    (e) => !employeeId || e.employee_id === employeeId
  );
  const filteredHealth = (healthData?.items ?? []).filter(
    (h) => !employeeId || h.employee_id === employeeId
  );

  const eventColumns: ColumnsType<any> = [
    { title: "일자", dataIndex: "event_date", width: 110 },
    { title: "사번", dataIndex: "emp_no", width: 90 },
    { title: "이름", dataIndex: "emp_name", width: 100 },
    { title: "부서", dataIndex: "dept_name", width: 150 },
    { title: "경조구분", dataIndex: "event_type", width: 100 },
    {
      title: "대상자",
      dataIndex: "target_person",
      width: 100,
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
      width: 100,
      render: (v: any[]) =>
        v && v.length ? <Tag color="blue">{v.length}건</Tag> : "-",
    },
  ];

  const healthColumns: ColumnsType<any> = [
    { title: "검진년도", dataIndex: "check_year", width: 100 },
    { title: "검진일", dataIndex: "check_date", width: 120 },
    { title: "사번", dataIndex: "emp_no", width: 90 },
    { title: "이름", dataIndex: "emp_name", width: 100 },
    { title: "부서", dataIndex: "dept_name", width: 150 },
    {
      title: "검진종류",
      dataIndex: "check_type",
      width: 100,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "결과",
      dataIndex: "result",
      width: 100,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "재검필요",
      dataIndex: "recheck_required",
      width: 90,
      render: (v: boolean) =>
        v ? <Tag color="orange">재검</Tag> : <Tag>-</Tag>,
    },
  ];

  return (
    <>
      <Card
        size="small"
        style={{ marginBottom: 12 }}
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
              showSearch
              allowClear
              placeholder="직원 선택 (사번/이름)"
              options={employeeOptions}
              value={employeeId}
              onChange={(v) => setEmployeeId(v)}
              filterOption={false}
              onSearch={(v) => setEmpSearch(v)}
              style={{ width: 280 }}
              notFoundContent={empSearch ? "검색 결과 없음" : "입력하세요"}
            />
          </Space>
        }
      />
      <Card title="경조사 이력" size="small" style={{ marginBottom: 12 }}>
        <Table
          rowKey="id"
          columns={eventColumns}
          dataSource={filteredEvents}
          loading={eventsLoading}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>
      <Card title="건강검진 이력" size="small">
        <Table
          rowKey="id"
          columns={healthColumns}
          dataSource={filteredHealth}
          loading={healthLoading}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>
    </>
  );
}

export default function BenefitOverviewPage() {
  return (
    <>
      <Breadcrumb
        items={[{ title: "복리후생" }, { title: "복리후생현황" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        복리후생현황
      </Title>
      <Tabs
        defaultActiveKey="dashboard"
        items={[
          { key: "dashboard", label: "대시보드", children: <DashboardTab /> },
          { key: "items", label: "항목 카탈로그", children: <ItemsTab /> },
          { key: "history", label: "직원별 이력", children: <HistoryTab /> },
        ]}
      />
    </>
  );
}
