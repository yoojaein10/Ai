import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
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
import {
  useCreateEduCourse,
  useDeleteEduCourse,
  useEduCourses,
  useUpdateEduCourse,
  type EduCourse,
} from "../api/eduCourses";

const { Title } = Typography;

const CATEGORY_OPTIONS = [
  { value: "법정", label: "법정" },
  { value: "직무", label: "직무" },
  { value: "리더십", label: "리더십" },
  { value: "어학", label: "어학" },
  { value: "기타", label: "기타" },
];

const TRAINING_TYPE_OPTIONS = [
  { value: "집합", label: "집합" },
  { value: "온라인", label: "온라인" },
  { value: "외부", label: "외부" },
  { value: "혼합", label: "혼합" },
];

const CATEGORY_COLOR: Record<string, string> = {
  법정: "red",
  직무: "blue",
  리더십: "purple",
  어학: "cyan",
  기타: "default",
};

export default function EduCoursesPage() {
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState<string | undefined>();
  const [showInactive, setShowInactive] = useState(false);

  const { data, isLoading } = useEduCourses({
    keyword,
    category,
    is_active: showInactive ? undefined : true,
  });
  const createCourse = useCreateEduCourse();
  const updateCourse = useUpdateEduCourse();
  const deleteCourse = useDeleteEduCourse();

  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EduCourse | null>(null);
  const [form] = Form.useForm();

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true });
    setModalOpen(true);
  };

  const openEdit = (course: EduCourse) => {
    setEditTarget(course);
    form.setFieldsValue({
      course_code: course.course_code,
      course_name: course.course_name,
      category: course.category,
      training_type: course.training_type,
      hours: course.hours,
      provider: course.provider,
      instructor: course.instructor,
      description: course.description,
      is_active: course.is_active,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    if (editTarget) {
      updateCourse.mutate(
        { id: editTarget.id, data: values },
        {
          onSuccess: () => {
            message.success("수정되었습니다");
            setModalOpen(false);
          },
          onError: (err: any) => {
            message.error(err?.response?.data?.detail ?? "수정 실패");
          },
        }
      );
    } else {
      createCourse.mutate(values, {
        onSuccess: () => {
          message.success("생성되었습니다");
          setModalOpen(false);
          form.resetFields();
        },
        onError: (err: any) => {
          message.error(err?.response?.data?.detail ?? "생성 실패");
        },
      });
    }
  };

  const onDelete = (id: number) => {
    deleteCourse.mutate(id, {
      onSuccess: () => message.success("삭제되었습니다"),
      onError: (err: any) => {
        message.error(err?.response?.data?.detail ?? "삭제 실패");
      },
    });
  };

  const columns: ColumnsType<EduCourse> = [
    {
      title: "과정코드",
      dataIndex: "course_code",
      width: 130,
    },
    {
      title: "과정명",
      dataIndex: "course_name",
    },
    {
      title: "구분",
      dataIndex: "category",
      width: 90,
      render: (v: string | null) =>
        v ? <Tag color={CATEGORY_COLOR[v] ?? "default"}>{v}</Tag> : "-",
    },
    {
      title: "형태",
      dataIndex: "training_type",
      width: 90,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "시간",
      dataIndex: "hours",
      width: 80,
      align: "right",
      render: (v: number | null) => (v != null ? `${v}h` : "-"),
    },
    {
      title: "교육기관",
      dataIndex: "provider",
      width: 160,
      render: (v: string | null) => v ?? "-",
    },
    {
      title: "강사",
      dataIndex: "instructor",
      width: 100,
      render: (v: string | null) => v ?? "-",
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
            description="이수 기록이 있으면 삭제되지 않습니다"
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
        items={[{ title: "교육" }, { title: "교육과정" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        교육과정
      </Title>

      <Card
        extra={
          <Space>
            <Input.Search
              placeholder="코드/과정명 검색"
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
              <Switch size="small" checked={showInactive} onChange={setShowInactive} />
            </Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              과정 추가
            </Button>
          </Space>
        }
      >
        <Table<EduCourse>
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editTarget ? "교육과정 수정" : "교육과정 추가"}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={createCourse.isPending || updateCourse.isPending}
        okText="저장"
        cancelText="취소"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Space.Compact block>
            <Form.Item
              name="course_code"
              label="과정코드"
              rules={[{ required: true, message: "과정코드를 입력하세요" }]}
              style={{ width: "40%" }}
            >
              <Input placeholder="예: SAFE-001" />
            </Form.Item>
            <Form.Item
              name="course_name"
              label="과정명"
              rules={[{ required: true, message: "과정명을 입력하세요" }]}
              style={{ width: "60%", marginLeft: 8 }}
            >
              <Input />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="category" label="구분" style={{ width: "33%" }}>
              <Select allowClear options={CATEGORY_OPTIONS} />
            </Form.Item>
            <Form.Item
              name="training_type"
              label="형태"
              style={{ width: "33%", marginLeft: 8 }}
            >
              <Select allowClear options={TRAINING_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item
              name="hours"
              label="시간"
              style={{ width: "33%", marginLeft: 8 }}
            >
              <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="provider" label="교육기관" style={{ width: "50%" }}>
              <Input />
            </Form.Item>
            <Form.Item
              name="instructor"
              label="강사"
              style={{ width: "50%", marginLeft: 8 }}
            >
              <Input />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="description" label="설명">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
