import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Input,
  Radio,
  Space,
  Typography,
  Empty,
  Spin,
  Table,
} from "antd";
import { PrinterOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useMe } from "../api/me";
import { useEmployee } from "../api/employees";
import { useTabList } from "../api/empTabs";

const { Title, Text } = Typography;

type CertType = "employment" | "career";

interface CareerRow {
  id: number;
  company_name: string;
  department: string | null;
  position: string | null;
  start_date: string | null;
  end_date: string | null;
  description: string | null;
}

const CERT_LABEL: Record<CertType, string> = {
  employment: "재직증명서",
  career: "경력증명서",
};

const COMPANY_NAME = "주식회사 대화";
const COMPANY_CEO = "대표이사";
const COMPANY_ADDRESS = "";

export default function CertificatePage() {
  const [certType, setCertType] = useState<CertType>("employment");
  const [purpose, setPurpose] = useState("제출용");

  const { data: me, isLoading: meLoading } = useMe();
  const empId = me?.employee?.id ?? null;
  const { data: detail, isLoading: detailLoading } = useEmployee(empId);
  const { data: careers } = useTabList<CareerRow>(empId, "careers");

  const today = dayjs().format("YYYY년 MM월 DD일");
  const onPrint = () => window.print();

  return (
    <>
      <style>{`
        @media print {
          body * { visibility: hidden; }
          .cert-print, .cert-print * { visibility: visible; }
          .cert-print { position: absolute; left: 0; top: 0; width: 100%; padding: 40px; }
          .cert-nav { display: none !important; }
        }
      `}</style>

      <div className="cert-nav">
        <Breadcrumb
          items={[{ title: "인사" }, { title: "나의 인사정보" }, { title: "증명서발급" }]}
          style={{ marginBottom: 12 }}
        />
        <Title level={4} style={{ marginBottom: 16 }}>증명서발급</Title>

        <Card size="small" style={{ marginBottom: 12 }}>
          <Space size="large" wrap>
            <div>
              <Text type="secondary" style={{ marginRight: 8 }}>증명서 종류</Text>
              <Radio.Group value={certType} onChange={(e) => setCertType(e.target.value)}>
                <Radio.Button value="employment">재직증명서</Radio.Button>
                <Radio.Button value="career">경력증명서</Radio.Button>
              </Radio.Group>
            </div>
            <div>
              <Text type="secondary" style={{ marginRight: 8 }}>용도</Text>
              <Input
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                style={{ width: 200 }}
                placeholder="예: 제출용, 은행 제출용"
              />
            </div>
            <Button type="primary" icon={<PrinterOutlined />} onClick={onPrint} disabled={!detail}>
              인쇄
            </Button>
          </Space>
        </Card>
      </div>

      <Card size="small" styles={{ body: { padding: 0 } }}>
        {meLoading || detailLoading ? (
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin />
          </div>
        ) : !me?.employee || !detail ? (
          <div style={{ padding: 48 }}>
            <Empty description="로그인 계정에 연결된 사원 정보가 없습니다" />
          </div>
        ) : (
          <div className="cert-print" style={{ padding: "48px 64px", background: "white", minHeight: 800 }}>
            <div style={{ textAlign: "center", marginBottom: 48 }}>
              <Title level={2} style={{ marginBottom: 8, letterSpacing: 16 }}>
                {CERT_LABEL[certType]}
              </Title>
              <div style={{ borderBottom: "2px solid #000", width: 120, margin: "0 auto" }} />
            </div>

            <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 32 }}>
              <tbody>
                <tr>
                  <td style={cellHead}>성 명</td>
                  <td style={cellBody}>{detail.name_ko}</td>
                  <td style={cellHead}>사 번</td>
                  <td style={cellBody}>{detail.emp_no}</td>
                </tr>
                <tr>
                  <td style={cellHead}>생년월일</td>
                  <td style={cellBody}>{detail.birth_date ?? "-"}</td>
                  <td style={cellHead}>성 별</td>
                  <td style={cellBody}>{detail.gender === "F" ? "여" : detail.gender === "M" ? "남" : "-"}</td>
                </tr>
                <tr>
                  <td style={cellHead}>부 서</td>
                  <td style={cellBody}>{detail.department_name ?? "-"}</td>
                  <td style={cellHead}>직 급</td>
                  <td style={cellBody}>{detail.job_rank ?? "-"}</td>
                </tr>
                <tr>
                  <td style={cellHead}>입사일</td>
                  <td style={cellBody}>{detail.hire_date ?? "-"}</td>
                  <td style={cellHead}>재직상태</td>
                  <td style={cellBody}>{detail.emp_status}</td>
                </tr>
              </tbody>
            </table>

            {certType === "career" && (
              <div style={{ marginBottom: 32 }}>
                <Title level={5} style={{ marginBottom: 12 }}>경력사항</Title>
                <Table
                  size="small"
                  bordered
                  pagination={false}
                  rowKey="id"
                  dataSource={careers ?? []}
                  columns={[
                    { title: "회사명", dataIndex: "company_name" },
                    { title: "부서", dataIndex: "department", render: (v) => v ?? "-" },
                    { title: "직위", dataIndex: "position", render: (v) => v ?? "-" },
                    { title: "근무기간", key: "period", render: (_, r) => `${r.start_date ?? "-"} ~ ${r.end_date ?? "현재"}` },
                  ]}
                  locale={{ emptyText: "등록된 경력사항이 없습니다" }}
                />
              </div>
            )}

            <div style={{ margin: "48px 0", lineHeight: 2, fontSize: 15 }}>
              위 사람은 당사에 {certType === "employment" ? "재직 중임" : "재직하였음"}을 증명합니다.
              <br />
              <Text type="secondary">용도: {purpose || "-"}</Text>
            </div>

            <div style={{ textAlign: "center", marginTop: 64 }}>
              <div style={{ fontSize: 16, marginBottom: 24 }}>{today}</div>
              <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: 4 }}>
                {COMPANY_NAME}
              </div>
              <div style={{ fontSize: 16, marginTop: 8 }}>
                {COMPANY_CEO} (인)
              </div>
              {COMPANY_ADDRESS && (
                <div style={{ fontSize: 12, color: "#666", marginTop: 8 }}>{COMPANY_ADDRESS}</div>
              )}
            </div>
          </div>
        )}
      </Card>
    </>
  );
}

const cellHead: React.CSSProperties = {
  border: "1px solid #333",
  padding: "10px 14px",
  background: "#f5f5f5",
  width: "15%",
  textAlign: "center",
  fontWeight: 600,
};

const cellBody: React.CSSProperties = {
  border: "1px solid #333",
  padding: "10px 14px",
  width: "35%",
};
