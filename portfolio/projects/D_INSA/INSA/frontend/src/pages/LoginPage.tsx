import { useState } from "react";
import { Button, Card, Form, Input, message, Typography } from "antd";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuthStore } from "../store/auth";

const { Title } = Typography;

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);

  const onFinish = async (values: { login_id: string; password: string }) => {
    setLoading(true);
    try {
      const { data } = await axios.post("/api/v1/auth/login", values, {
        withCredentials: true,
      });
      setAuth({
        accessToken: data.access_token,
        userId: data.user_id,
        loginId: data.login_id,
        roles: data.roles,
      });
      navigate("/hr/employees");
    } catch {
      message.error("아이디 또는 비밀번호가 올바르지 않습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "100vh",
        background: "var(--surface-sunken)",
      }}
    >
      <Card style={{ width: 380 }} styles={{ body: { padding: 32 } }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <Title
            level={2}
            style={{
              marginBottom: 4,
              letterSpacing: "0.04em",
              fontFamily: "var(--font-display)",
              fontWeight: 400,
              color: "var(--text-primary)",
            }}
          >
            Daehwa
          </Title>
          <Typography.Text type="secondary">인사관리 시스템</Typography.Text>
        </div>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="login_id" rules={[{ required: true, message: "아이디를 입력하세요" }]}>
            <Input prefix={<UserOutlined />} placeholder="아이디" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: "비밀번호를 입력하세요" }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="비밀번호" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              로그인
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
