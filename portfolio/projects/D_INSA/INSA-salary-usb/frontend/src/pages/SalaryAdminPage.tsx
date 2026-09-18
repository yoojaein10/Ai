import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useAuthStore } from "../store/auth";
import {
  usePolicy,
  usePolicyCheck,
  useUpsertPolicy,
  type PolicyRow,
} from "../api/salaryPolicy";
import { useAccessLogs, type AccessLogRow } from "../api/salaryAudit";

const { Title, Text } = Typography;

export default function SalaryAdminPage() {
  const roles = useAuthStore((s) => s.roles);
  const policyQuery = usePolicy();
  const checkQuery = usePolicyCheck();
  const upsert = useUpsertPolicy();
  const logsQuery = useAccessLogs({});

  const [allowedIp, setAllowedIp] = useState("");
  const [ownerUserId, setOwnerUserId] = useState<number | null>(null);
  // 서버 정책을 폼 상태로 동기화한다. useEffect에서 setState하면 커밋 후
  // 추가 렌더가 발생하므로(react-hooks/set-state-in-effect), React 문서가
  // 권장하는 "렌더 중 조건부 setState + 마지막으로 반영한 값 추적" 패턴을 쓴다.
  const [syncedPolicy, setSyncedPolicy] = useState<PolicyRow | null>(null);
  if (policyQuery.data && policyQuery.data !== syncedPolicy) {
    setSyncedPolicy(policyQuery.data);
    setAllowedIp(policyQuery.data.allowed_ip);
    setOwnerUserId(policyQuery.data.owner_user_id);
  }

  if (!roles.includes("SYSTEM_ADMIN")) {
    return (
      <Card>
        <Empty description="연봉 접근 관리 권한이 없습니다." />
      </Card>
    );
  }

  const handleSave = async () => {
    if (ownerUserId === null) {
      message.error("담당자 사용자 ID를 입력하세요");
      return;
    }
    try {
      await upsert.mutateAsync({
        owner_user_id: ownerUserId,
        allowed_ip: allowedIp,
      });
      message.success("허용 IP를 저장했습니다");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail ?? "저장에 실패했습니다");
    }
  };

  const columns = [
    { title: "일시", dataIndex: "occurred_at", key: "occurred_at" },
    { title: "사용자", dataIndex: "user_id", key: "user_id" },
    {
      title: "동작",
      dataIndex: "action",
      key: "action",
      render: (v: string) =>
        v === "IP_DENIED" ? <Tag color="red">{v}</Tag> : <Tag>{v}</Tag>,
    },
    { title: "IP", dataIndex: "ip_address", key: "ip_address" },
    {
      title: "건수",
      dataIndex: "record_count",
      key: "record_count",
      align: "right" as const,
      render: (v: number | null) => v ?? "-",
    },
    {
      title: "후임자",
      dataIndex: "target_user_id",
      key: "target_user_id",
      render: (v: number | null) => v ?? "-",
    },
  ];

  return (
    <Space direction="vertical" size={32} style={{ width: "100%" }}>
      <div>
        <Title level={3} style={{ margin: 0 }}>
          연봉 접근 관리
        </Title>
        <Text type="secondary">
          누가 열 수 있는지와 누가 열었는지를 함께 확인합니다.
        </Text>
      </div>

      <Card title="허용 IP 정책">
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          {!policyQuery.data && (
            <Alert
              type="warning"
              showIcon
              message="수동 허용 IP가 설정되지 않았습니다"
              description="기본적으로 각 담당자는 APW 좌석 정보(SEAT_USERINFO)에 등록된 본인 PC IP에서만 금고를 열 수 있습니다. 다른 자리에서 열어야 할 때만 여기서 담당자별 허용 IP를 추가하세요."
            />
          )}
          <Space wrap>
            <label>
              담당자 사용자 ID{" "}
              <InputNumber
                aria-label="담당자 사용자 ID"
                value={ownerUserId ?? undefined}
                onChange={(v) => setOwnerUserId(v ?? null)}
              />
            </label>
            <label>
              허용 IP{" "}
              <Input
                aria-label="허용 IP"
                style={{ width: 200 }}
                value={allowedIp}
                onChange={(e) => setAllowedIp(e.target.value)}
              />
            </label>
            <Button
              onClick={() => setAllowedIp(checkQuery.data?.current_ip ?? "")}
            >
              현재 접속 IP로 설정 ({checkQuery.data?.current_ip ?? "확인 불가"})
            </Button>
            <Button
              type="primary"
              loading={upsert.isPending}
              onClick={() => void handleSave()}
            >
              저장
            </Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            좌석 규칙(좌석 IP = 10.40.0.&#123;UID&#125;)과 이 수동 허용 중 하나만 맞으면 열 수
            있습니다. 수동 허용은 담당자 사용자 ID 본인에게만 적용되며, DHCP로 IP가 바뀌면
            다시 등록해야 합니다.
          </Text>
        </Space>
      </Card>

      <Card title="접근 기록">
        <Table<AccessLogRow>
          size="small"
          rowKey="id"
          loading={logsQuery.isLoading}
          dataSource={logsQuery.data?.items ?? []}
          columns={columns}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </Space>
  );
}
