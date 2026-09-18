import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Descriptions,
  Empty,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { PrinterOutlined, UserOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useEmployees, useEmployee } from "../api/employees";
import { useTabData, useTabList } from "../api/empTabs";
import { useAppointmentsByEmployee } from "../api/appointments";

const { Title } = Typography;

interface Personal {
  address?: string | null;
  phone?: string | null;
  email?: string | null;
  emergency_contact?: string | null;
  emergency_phone?: string | null;
}

interface Family {
  id: number;
  relation?: string | null;
  name?: string | null;
  birth_date?: string | null;
  job?: string | null;
}

interface Education {
  id: number;
  school_name?: string | null;
  major?: string | null;
  degree?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  status?: string | null;
}

interface Career {
  id: number;
  company?: string | null;
  position?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  description?: string | null;
}

interface Certificate {
  id: number;
  name?: string | null;
  issuer?: string | null;
  acquired_date?: string | null;
  certificate_no?: string | null;
}

const valueOrDash = (v: unknown) => (v === null || v === undefined || v === "" ? "-" : String(v));

export default function RecordCardPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [searchText, setSearchText] = useState("");

  const { data: empList } = useEmployees({ page: 1, page_size: 100, search: searchText || undefined });
  const { data: detail } = useEmployee(selectedId);
  const { data: personal } = useTabData<Personal>(selectedId, "personal");
  const { data: families } = useTabList<Family>(selectedId, "families");
  const { data: educations } = useTabList<Education>(selectedId, "educations");
  const { data: careers } = useTabList<Career>(selectedId, "careers");
  const { data: certificates } = useTabList<Certificate>(selectedId, "certificates");
  const { data: appointments } = useAppointmentsByEmployee(selectedId);

  const familyColumns: ColumnsType<Family> = [
    { title: "관계", dataIndex: "relation", render: valueOrDash },
    { title: "성명", dataIndex: "name", render: valueOrDash },
    { title: "생년월일", dataIndex: "birth_date", render: valueOrDash },
    { title: "직업", dataIndex: "job", render: valueOrDash },
  ];

  const eduColumns: ColumnsType<Education> = [
    { title: "학교", dataIndex: "school_name", render: valueOrDash },
    { title: "전공", dataIndex: "major", render: valueOrDash },
    { title: "학위", dataIndex: "degree", render: valueOrDash },
    { title: "입학", dataIndex: "start_date", render: valueOrDash },
    { title: "졸업", dataIndex: "end_date", render: valueOrDash },
    { title: "졸업여부", dataIndex: "status", render: valueOrDash },
  ];

  const careerColumns: ColumnsType<Career> = [
    { title: "회사", dataIndex: "company", render: valueOrDash },
    { title: "직위", dataIndex: "position", render: valueOrDash },
    { title: "시작", dataIndex: "start_date", render: valueOrDash },
    { title: "종료", dataIndex: "end_date", render: valueOrDash },
    { title: "내용", dataIndex: "description", render: valueOrDash },
  ];

  const certColumns: ColumnsType<Certificate> = [
    { title: "자격증명", dataIndex: "name", render: valueOrDash },
    { title: "발행기관", dataIndex: "issuer", render: valueOrDash },
    { title: "취득일", dataIndex: "acquired_date", render: valueOrDash },
    { title: "번호", dataIndex: "certificate_no", render: valueOrDash },
  ];

  const apptColumns: ColumnsType<Record<string, unknown>> = [
    { title: "발령일", dataIndex: "appt_date", render: valueOrDash },
    { title: "유형", dataIndex: "appt_type", render: valueOrDash },
    { title: "이전직급", dataIndex: "old_rank", render: valueOrDash },
    { title: "새직급", dataIndex: "new_rank", render: valueOrDash },
    { title: "비고", dataIndex: "description", render: valueOrDash },
  ];

  const onPrint = () => window.print();

  return (
    <>
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .record-card { box-shadow: none !important; }
        }
      `}</style>

      <Breadcrumb
        className="no-print"
        items={[{ title: "인사" }, { title: "임직원조회" }, { title: "인사기록카드" }]}
        style={{ marginBottom: 12 }}
      />
      <div className="no-print" style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>인사기록카드</Title>
      </div>

      <Card size="small" className="no-print" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            showSearch
            placeholder="사번 또는 성명으로 선택"
            style={{ width: 320 }}
            value={selectedId ?? undefined}
            onChange={(v) => setSelectedId(v as number)}
            onSearch={setSearchText}
            filterOption={false}
            options={
              empList?.items.map((e) => ({
                value: e.id,
                label: `${e.emp_no}  ${e.name_ko}  (${e.department_name ?? "-"} / ${e.job_rank ?? "-"})`,
              })) ?? []
            }
          />
          <Button icon={<PrinterOutlined />} onClick={onPrint} disabled={!selectedId}>
            인쇄
          </Button>
        </Space>
      </Card>

      {!detail ? (
        <Card className="record-card">
          <Empty description="사원을 선택해주세요" image={<UserOutlined style={{ fontSize: 48, color: "#ccc" }} />} />
        </Card>
      ) : (
        <Card className="record-card" title={
          <Space>
            <UserOutlined />
            <span>인사기록카드 — {String(detail.name_ko ?? "")} ({String(detail.emp_no ?? "")})</span>
            <Tag color={detail.emp_status === "재직" ? "green" : "red"}>{String(detail.emp_status ?? "")}</Tag>
          </Space>
        }>
          <Descriptions title="기본정보" column={3} size="small" bordered style={{ marginBottom: 20 }}>
            <Descriptions.Item label="사번">{valueOrDash(detail.emp_no)}</Descriptions.Item>
            <Descriptions.Item label="성명">{valueOrDash(detail.name_ko)}</Descriptions.Item>
            <Descriptions.Item label="한자명">{valueOrDash(detail.name_cn)}</Descriptions.Item>
            <Descriptions.Item label="영문명">{valueOrDash(detail.name_en)}</Descriptions.Item>
            <Descriptions.Item label="성별">{detail.gender === "F" ? "여" : detail.gender === "M" ? "남" : "-"}</Descriptions.Item>
            <Descriptions.Item label="생년월일">{valueOrDash(detail.birth_date)}</Descriptions.Item>
            <Descriptions.Item label="부서">{valueOrDash(detail.department_name)}</Descriptions.Item>
            <Descriptions.Item label="직급">{valueOrDash(detail.job_rank)}</Descriptions.Item>
            <Descriptions.Item label="직위">{valueOrDash(detail.job_position)}</Descriptions.Item>
            <Descriptions.Item label="직책">{valueOrDash(detail.job_title)}</Descriptions.Item>
            <Descriptions.Item label="입사일">{valueOrDash(detail.hire_date)}</Descriptions.Item>
            <Descriptions.Item label="입사구분">{valueOrDash(detail.hire_type)}</Descriptions.Item>
            <Descriptions.Item label="사업장">{valueOrDash(detail.workplace)}</Descriptions.Item>
            <Descriptions.Item label="근무지">{valueOrDash(detail.work_location)}</Descriptions.Item>
            <Descriptions.Item label="사원구분">{valueOrDash(detail.emp_type)}</Descriptions.Item>
          </Descriptions>

          <Descriptions title="신상정보" column={2} size="small" bordered style={{ marginBottom: 20 }}>
            <Descriptions.Item label="주소" span={2}>{valueOrDash(personal?.address)}</Descriptions.Item>
            <Descriptions.Item label="연락처">{valueOrDash(personal?.phone)}</Descriptions.Item>
            <Descriptions.Item label="이메일">{valueOrDash(personal?.email)}</Descriptions.Item>
            <Descriptions.Item label="비상연락처">{valueOrDash(personal?.emergency_contact)}</Descriptions.Item>
            <Descriptions.Item label="비상연락번호">{valueOrDash(personal?.emergency_phone)}</Descriptions.Item>
          </Descriptions>

          <Title level={5}>가족</Title>
          <Table
            columns={familyColumns}
            dataSource={families}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "기록 없음" }}
            style={{ marginBottom: 20 }}
          />

          <Title level={5}>학력</Title>
          <Table
            columns={eduColumns}
            dataSource={educations}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "기록 없음" }}
            style={{ marginBottom: 20 }}
          />

          <Title level={5}>경력</Title>
          <Table
            columns={careerColumns}
            dataSource={careers}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "기록 없음" }}
            style={{ marginBottom: 20 }}
          />

          <Title level={5}>자격</Title>
          <Table
            columns={certColumns}
            dataSource={certificates}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "기록 없음" }}
            style={{ marginBottom: 20 }}
          />

          <Title level={5}>발령이력</Title>
          <Table
            columns={apptColumns}
            dataSource={appointments as unknown as Record<string, unknown>[]}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "기록 없음" }}
          />
        </Card>
      )}
    </>
  );
}
