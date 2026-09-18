import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Typography,
  Avatar,
  Tag,
  Empty,
  Spin,
} from "antd";
import { EditOutlined, UserOutlined } from "@ant-design/icons";
import { useMe } from "../api/me";
import { useEmployee } from "../api/employees";
import EmployeeDetailTabs from "../components/tabs/EmployeeDetailTabs";
import ChangeRequestModal from "../components/ChangeRequestModal";

const { Title } = Typography;

export default function MyInfoPage() {
  const { data: me, isLoading: meLoading } = useMe();
  const empId = me?.employee?.id ?? null;
  const { data: detail, isLoading: detailLoading } = useEmployee(empId);
  const [reqOpen, setReqOpen] = useState(false);

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사" }, { title: "나의 인사정보" }, { title: "인사정보" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>인사정보</Title>

      <Card size="small" style={{ minHeight: "calc(100vh - 220px)" }} styles={{ body: { padding: 0 } }}>
        {meLoading || detailLoading ? (
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin />
          </div>
        ) : !me?.employee ? (
          <div style={{ padding: 48 }}>
            <Empty description="로그인 계정에 연결된 사원 정보가 없습니다" />
          </div>
        ) : detail ? (
          <>
            <div
              style={{
                padding: "14px 18px",
                borderBottom: "1px solid #f0f0f0",
                display: "flex",
                alignItems: "center",
                gap: 16,
              }}
            >
              <Avatar size={48} icon={<UserOutlined />}>
                {detail.name_ko?.[0]}
              </Avatar>
              <div>
                <Typography.Text strong style={{ fontSize: 16 }}>
                  {detail.name_ko}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                  {detail.emp_no}
                </Typography.Text>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {detail.department_name} / {detail.job_rank} / {detail.emp_type}
                  </Typography.Text>
                  <Tag
                    color={detail.emp_status === "재직" ? "green" : "red"}
                    style={{ marginLeft: 8 }}
                  >
                    {detail.emp_status}
                  </Tag>
                </div>
              </div>
              <div style={{ marginLeft: "auto" }}>
                <Button
                  type="primary"
                  icon={<EditOutlined />}
                  onClick={() => setReqOpen(true)}
                >
                  개인정보 변경요청
                </Button>
              </div>
            </div>
            <EmployeeDetailTabs employeeId={empId!} detail={detail} />
            <ChangeRequestModal
              employeeId={empId}
              open={reqOpen}
              onClose={() => setReqOpen(false)}
            />
          </>
        ) : (
          <Empty description="정보를 불러올 수 없습니다" style={{ padding: 48 }} />
        )}
      </Card>
    </>
  );
}
