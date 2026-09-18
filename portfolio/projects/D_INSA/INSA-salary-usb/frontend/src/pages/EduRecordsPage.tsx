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
  uploadEduRecords,
  useCreateEduRecord,
  useDeleteEduRecord,
  useEduRecords,
  useUpdateEduRecord,
  type EduRecord,
} from "../api/eduRecords";
import { useEduCourses } from "../api/eduCourses";
import { useEmployees } from "../api/employees";

const { Title } = Typography;

const CATEGORY_OPTIONS = [
  { value: "법정", label: "법정" },
  { value: "직무", label: "직무" },
  { value: "리더십", label: "리더십" },
  { value: "어학", label: "어학" },
  { value: "기타", label: "기타" },
];

const RESULT_OPTIONS = [
  { value: "수료", label: "수료" },
  { value: "미수료", label: "미수료" },
  { value: "진행중", label: "진행중" },
];

const RESULT_COLOR: Record<string, string> = {
  수료: "green",
  미수료: "red",
  진행중: "blue",
};

export default function EduRecordsPage() {
  const [year, setYear] = useState<number | undefined>(dayjs().year());
  const [category, setCategory] = useState<string | undefined>();
  const [keyword, setKeyword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [empSearch, setEmpSearch] = useState("");

  const { data, isLoading } = useEduRecords({ year, category, keyword });
  const { data: coursesData } = useEduCourses({ is_active: true });
  const { data: employeesData } = useEmployees({
    page: 1,
    page_size: 100,
    search: empSearch || undefined,
  });

  const createRec = useCreateEduRecord();
  const updateRec = useUpdateEduRecord();
  const deleteRec = useDeleteEduRecord();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EduRecord | null>(null);
  const [form] = Form.useForm();

  const courseOptions = useMemo(
    () =>
      (coursesData?.items ?? []).map((c) => ({
        value: c.id,
        label: `${c.course_code} · ${c.course_name}`,
        course: c,
      })),
    [coursesData]
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
    setModalOpen(true);
  };

  const openEdit = (r: EduRecord) => {
    setEditTarget(r);
    form.setFieldsValue({
      employee_id: r.employee_id,
      course_id: r.course_id,
      course_name_snapshot: r.course_name_snapshot,
      start_date: r.start_date ? dayjs(r.start_date) : null,
      end_date: r.end_date ? dayjs(r.end_date) : null,
      hours: r.hours,
      score: r.score,
      result: r.result,
      certificate_no: r.certificate_no,
      remark: r.remark,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      start_date: values.start_date
        ? values.start_date.format("YYYY-MM-DD")
        : null,
      end_date: values.end_date ? values.end_date.format("YYYY-MM-DD") : null,
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

  const onCourseChange = (courseId: number | null) => {
    if (!courseId) return;
    const found = courseOptions.find((o) => o.value === courseId);
    if (found) {
      form.setFieldsValue({
        course_name_snapshot: found.course.course_name,
        hours: form.getFieldValue("hours") ?? found.course.hours,
      });
    }
  };

  const uploadProps: UploadProps = {
    accept: ".xlsx,.xlsm",
    showUploadList: false,
    beforeUpload: async (file) => {
      setUploading(true);
      try {
        const res = await uploadEduRecords(file);
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

  const columns: ColumnsType<EduRecord> = [
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
      title: "과정코드",
      dataIndex: "course_code",
      width: 120,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "과정명",
      dataIndex: "course_name_snapshot",
    },
    {
      title: "구분",
      dataIndex: "category",
      width: 80,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "시작일",
      dataIndex: "start_date",
      width: 110,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "종료일",
      dataIndex: "end_date",
      width: 110,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "시간",
      dataIndex: "hours",
      width: 70,
      align: "right",
      render: (v: number | null) => (v != null ? `${v}h` : "-"),
    },
    {
      title: "점수",
      dataIndex: "score",
      width: 70,
      align: "right",
      render: (v: number | null) => (v != null ? v : "-"),
    },
    {
      title: "결과",
      dataIndex: "result",
      width: 90,
      render: (v: string | null) =>
        v ? <Tag color={RESULT_COLOR[v] ?? "default"}>{v}</Tag> : "-",
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
        items={[{ title: "교육" }, { title: "교육이수현황" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        교육이수현황
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
              placeholder="구분"
              allowClear
              value={category}
              onChange={setCategory}
              options={CATEGORY_OPTIONS}
              style={{ width: 120 }}
            />
            <Input.Search
              placeholder="사번/이름/과정명"
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
              이수 등록
            </Button>
          </Space>
        }
      >
        <Table<EduRecord>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 30, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editTarget ? "이수 기록 수정" : "이수 기록 등록"}
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
          <Form.Item name="course_id" label="교육과정">
            <Select
              showSearch
              allowClear
              placeholder="과정 선택 (선택사항)"
              options={courseOptions.map(({ course: _c, ...rest }) => {
                void _c;
                return rest;
              })}
              optionFilterProp="label"
              onChange={onCourseChange}
            />
          </Form.Item>
          <Form.Item
            name="course_name_snapshot"
            label="과정명 (기록용)"
            rules={[{ required: true, message: "과정명을 입력하세요" }]}
          >
            <Input />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="start_date" label="시작일" style={{ width: "50%" }}>
              <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
            </Form.Item>
            <Form.Item
              name="end_date"
              label="종료일"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="hours" label="이수시간" style={{ width: "33%" }}>
              <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              name="score"
              label="점수"
              style={{ width: "33%", marginLeft: 8 }}
            >
              <InputNumber min={0} max={100} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              name="result"
              label="결과"
              style={{ width: "33%", marginLeft: 8 }}
            >
              <Select allowClear options={RESULT_OPTIONS} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="certificate_no" label="수료증번호">
            <Input />
          </Form.Item>
          <Form.Item name="remark" label="비고">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
