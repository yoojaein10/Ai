import { useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import {
  uploadBenefitHealth,
  useBenefitHealth,
  useCreateBenefitHealth,
  useDeleteBenefitHealth,
  useUpdateBenefitHealth,
  type BenefitHealth,
} from "../api/benefits";
import { useEmployees } from "../api/employees";

const { Title } = Typography;

const RESULT_OPTIONS = [
  { value: "정상A", label: "정상A" },
  { value: "정상B", label: "정상B" },
  { value: "요관찰", label: "요관찰" },
  { value: "유소견", label: "유소견" },
  { value: "질환의심", label: "질환의심" },
];

const PROVIDER_OPTIONS = [
  { value: "녹십자(서초)", label: "녹십자(서초)" },
  { value: "녹십자(종로)", label: "녹십자(종로)" },
  { value: "기쁨병원", label: "기쁨병원" },
  { value: "아산병원", label: "아산병원" },
  { value: "다온헬스케어", label: "다온헬스케어" },
  { value: "송도병원", label: "송도병원" },
];

const RESULT_COLOR: Record<string, string> = {
  정상A: "green",
  정상B: "green",
  요관찰: "gold",
  유소견: "red",
  질환의심: "red",
};

export default function BenefitHealthPage() {
  const [year, setYear] = useState<number | undefined>(dayjs().year());
  const [result, setResult] = useState<string | undefined>();
  const [recheckOnly, setRecheckOnly] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [empSearch, setEmpSearch] = useState("");

  const { data, isLoading } = useBenefitHealth({
    year,
    result,
    recheck_only: recheckOnly,
    keyword,
  });
  const { data: employeesData } = useEmployees({
    page: 1,
    page_size: 100,
    search: empSearch || undefined,
  });

  const createRec = useCreateBenefitHealth();
  const updateRec = useUpdateBenefitHealth();
  const deleteRec = useDeleteBenefitHealth();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<BenefitHealth | null>(null);
  const [form] = Form.useForm();

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
    form.setFieldsValue({
      check_year: dayjs().year(),
      recheck_required: false,
    });
    setModalOpen(true);
  };

  const openEdit = (r: BenefitHealth) => {
    setEditTarget(r);
    form.setFieldsValue({
      employee_id: r.employee_id,
      check_year: r.check_year,
      check_date: r.check_date ? dayjs(r.check_date) : null,
      provider: r.provider,
      check_type: r.check_type,
      result: r.result,
      recheck_required: r.recheck_required,
      recheck_date: r.recheck_date ? dayjs(r.recheck_date) : null,
      remark: r.remark,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      check_date: values.check_date
        ? values.check_date.format("YYYY-MM-DD")
        : null,
      recheck_date: values.recheck_date
        ? values.recheck_date.format("YYYY-MM-DD")
        : null,
    };
    if (editTarget) {
      const { employee_id: _drop, ...rest } = payload;
      void _drop;
      updateRec.mutate(
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
      createRec.mutate(payload, {
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
    deleteRec.mutate(id, {
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
        const res = await uploadBenefitHealth(file);
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

  const columns: ColumnsType<BenefitHealth> = [
    { title: "검진년도", dataIndex: "check_year", width: 100 },
    {
      title: "검진일",
      dataIndex: "check_date",
      width: 120,
      render: (v: string | null) => v ?? "-",
    },
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
      title: "검진기관",
      dataIndex: "provider",
      width: 160,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "종류",
      dataIndex: "check_type",
      width: 90,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "결과",
      dataIndex: "result",
      width: 100,
      render: (v: string | null) =>
        v ? <Tag color={RESULT_COLOR[v] ?? "default"}>{v}</Tag> : "-",
    },
    {
      title: "재검",
      dataIndex: "recheck_required",
      width: 90,
      render: (v: boolean, r) =>
        v ? (
          <Tag color="orange">
            재검{r.recheck_date ? ` ${r.recheck_date}` : ""}
          </Tag>
        ) : (
          "-"
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
        items={[{ title: "복리후생" }, { title: "건강검진" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        건강검진
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
              placeholder="결과"
              allowClear
              value={result}
              onChange={setResult}
              options={RESULT_OPTIONS}
              style={{ width: 120 }}
            />
            <Space size={4}>
              <span>재검만</span>
              <Switch
                size="small"
                checked={recheckOnly}
                onChange={setRecheckOnly}
              />
            </Space>
            <Input.Search
              placeholder="사번/이름"
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 200 }}
            />
            <Upload {...uploadProps}>
              <Button icon={<UploadOutlined />} loading={uploading}>
                엑셀 업로드
              </Button>
            </Upload>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              검진 등록
            </Button>
          </Space>
        }
      >
        <Table<BenefitHealth>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 30, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editTarget ? "건강검진 수정" : "건강검진 등록"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createRec.isPending || updateRec.isPending}
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
          <Space.Compact block>
            <Form.Item
              name="check_year"
              label="검진년도"
              rules={[{ required: true, message: "검진년도를 입력하세요" }]}
              getValueProps={(v) => ({
                value: v ? dayjs(`${v}-01-01`) : null,
              })}
              normalize={(v) =>
                v && typeof (v as any).year === "function"
                  ? (v as dayjs.Dayjs).year()
                  : v
              }
              style={{ width: "50%" }}
            >
              <DatePicker picker="year" style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              name="check_date"
              label="검진일"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="provider" label="검진기관">
            <Select allowClear options={PROVIDER_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="recheck_required"
            label="재검 필요"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="recheck_date" label="재검일">
            <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="remark" label="비고">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
