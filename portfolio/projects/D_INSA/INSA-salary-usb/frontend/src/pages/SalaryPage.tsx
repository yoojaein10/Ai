import { useState, useEffect } from "react";
import { Alert, Button, Card, Empty, Input, Modal, Space, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import apiClient from "../api/client";
import { useAuthStore } from "../store/auth";
import { usePolicyCheck } from "../api/salaryPolicy";
import { useAllEmployees } from "../api/employees";
import { useSalaryVault } from "../salary/useSalaryVault";
import { isFileSystemAccessSupported } from "../salary/vault";
import SalaryRecordModal, { type EmployeeOption } from "../salary/SalaryRecordModal";
import SalaryRecordTable from "../salary/SalaryRecordTable";
import DelegateModal, { type UserOption } from "../salary/DelegateModal";
import type { SalaryRecord } from "../salary/types";

const { Title, Paragraph, Text } = Typography;

const ALLOWED_ROLES = ["SYSTEM_ADMIN", "HR_ADMIN"];

export default function SalaryPage() {
  const roles = useAuthStore((s) => s.roles);
  const policy = usePolicyCheck();
  const vault = useSalaryVault();
  // 새 금고 생성 필드와 잠금 해제 필드는 서로 다른 상태를 쓴다. 하나로 묶으면
  // DISCONNECTED에서 입력한 값이 LOCKED 전환 후 비밀번호 입력란에 그대로
  // 남아버린다 (Task 9 리뷰 지적).
  const [createPassword, setCreatePassword] = useState("");
  const [createPasswordConfirm, setCreatePasswordConfirm] = useState("");
  const [unlockPassword, setUnlockPassword] = useState("");
  const [search, setSearch] = useState("");

  // 금고 상태가 바뀌면 비밀번호 입력값을 비운다. 열기에 쓴 비밀번호가 상태에
  // 남으면, 잠근 뒤(수동·자동·비밀번호 변경 취소) 입력란에 그대로 채워져 있어
  // 지나가던 사람이 [열기]만 눌러도 들어가진다.
  useEffect(() => {
    setUnlockPassword("");
    setCreatePassword("");
    setCreatePasswordConfirm("");
  }, [vault.status]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SalaryRecord | null>(null);
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const [delegateModalOpen, setDelegateModalOpen] = useState(false);

  const employeesQuery = useAllEmployees();
  const employeeOptions: EmployeeOption[] = (employeesQuery.data ?? []).map(
    (e) => ({ id: e.id, emp_no: e.emp_no, name: e.name_ko }),
  );

  // 담당자 위임 모달이 열렸을 때만 조회한다. /admin/users에는 아직 역할
  // 가드가 없으므로(스펙 §9.1, 별도 결함) 이름 표시가 필요한 순간에만 부른다.
  const usersQuery = useQuery({
    queryKey: ["admin", "users", "for-delegate"],
    queryFn: async () => {
      const { data } = await apiClient.get<{
        items: Array<{ id: number; login_id: string; name_ko: string | null }>;
      }>("/admin/users");
      return data.items;
    },
    enabled: delegateModalOpen,
  });

  const userOptions: UserOption[] = (usersQuery.data ?? []).map((u) => ({
    id: u.id,
    login_id: u.login_id,
    display_name: u.name_ko ?? u.login_id,
  }));

  const visibleRecords = vault.records.filter((r) =>
    search ? r.empName.includes(search) : true,
  );

  const hasAccess = roles.some((r) => ALLOWED_ROLES.includes(r));

  if (!hasAccess) {
    return (
      <Card>
        <Empty description="연봉 관리 권한이 없습니다." />
      </Card>
    );
  }

  if (!isFileSystemAccessSupported()) {
    // File System Access API는 보안 컨텍스트(HTTPS 또는 localhost)에서만 노출된다.
    const insecure = typeof window !== "undefined" && !window.isSecureContext;
    return (
      <Alert
        type="warning"
        showIcon
        message={
          insecure
            ? "연봉 접근 권한이 없습니다"
            : "Chrome 또는 Edge에서 이용해 주세요"
        }
        description={
          insecure
            ? "현재 접속 위치에서는 연봉 금고를 이용할 수 없습니다."
            : "이 기능은 File System Access API가 필요합니다. Firefox와 Safari는 지원하지 않습니다."
        }
      />
    );
  }

  if (!policy.data) {
    return (
      <Card loading>
        <Paragraph>접속 위치를 확인하는 중입니다...</Paragraph>
      </Card>
    );
  }

  if (!policy.data.allowed) {
    return (
      <Card>
        <Title level={4}>IP 및 접근 ID에 연봉 접근 권한이 없습니다</Title>
        <Paragraph>
          접속 IP: <Text strong>{policy.data.current_ip ?? "확인 불가"}</Text>
          {" · "}접근 ID: <Text strong>{policy.data.login_id ?? "확인 불가"}</Text>
        </Paragraph>
        {policy.data.reason && <Paragraph type="danger">{policy.data.reason}</Paragraph>}
        <Paragraph type="secondary">
          {policy.data.seat_expected_ip
            ? `이 ID의 등록 좌석 IP는 ${policy.data.seat_expected_ip} 입니다. 본인 PC에서 다시 시도하거나, `
            : "이 ID에 등록된 좌석 IP가 없습니다. "}
          다른 자리에서 열어야 하면 시스템 관리자에게 현재 IP의 수동 허용을 요청하세요.
        </Paragraph>
      </Card>
    );
  }

  const header = (
    <Space direction="vertical" size={4} style={{ marginBottom: 24 }}>
      <Title level={3} style={{ margin: 0 }}>
        연봉 관리
      </Title>
      <Text type="secondary">
        연봉 데이터는 서버에 저장되지 않습니다. USB의 salary.enc 파일에만 있습니다.
      </Text>
    </Space>
  );

  if (vault.status === "ERROR") {
    return (
      <>
        {header}
        <Alert
          type="error"
          showIcon
          message="금고 파일을 열 수 없습니다"
          description={
            <>
              <Paragraph>{vault.errorMessage}</Paragraph>
              <Paragraph>
                같은 폴더의 <Text code>salary.enc.bak</Text> 파일이 저장 직전의 원본입니다.
                파일명을 <Text code>salary.enc</Text>로 바꾼 뒤 다시 시도하세요.
              </Paragraph>
            </>
          }
        />
      </>
    );
  }

  if (vault.status === "DISCONNECTED") {
    return (
      <>
        {header}
        <Card>
          <Empty
            description={
              <Space direction="vertical">
                <Text>연봉 금고가 있는 USB 폴더를 선택하세요.</Text>
                <Text type="secondary">
                  폴더에 salary.enc가 없으면 새 금고를 만들 수 있습니다.
                </Text>
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: 280 }}>
              {/* 폴더 선택·새 금고 만들기의 실패를 여기서 보여준다. 없으면
                  폴더를 고르지 않고 [새 연봉 금고 만들기]를 누른 담당자에게
                  아무 반응도 보이지 않는다. */}
              {vault.errorMessage && (
                <Alert type="error" showIcon message={vault.errorMessage} />
              )}
              <Button type="primary" onClick={() => void vault.connect()}>
                USB 폴더 선택
              </Button>
              <Input.Password
                aria-label="새 금고 비밀번호"
                placeholder="새 금고 비밀번호"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
              />
              <Input.Password
                aria-label="새 금고 비밀번호 확인"
                placeholder="비밀번호 확인"
                value={createPasswordConfirm}
                onChange={(e) => setCreatePasswordConfirm(e.target.value)}
              />
              <Button
                disabled={
                  createPassword.length < 8 || createPassword !== createPasswordConfirm
                }
                onClick={() => void vault.createVault(createPassword)}
              >
                새 연봉 금고 만들기
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                비밀번호를 잃어버리면 복구할 수 없습니다.
              </Text>
            </Space>
          </Empty>
        </Card>
      </>
    );
  }

  if (vault.status === "LOCKED") {
    return (
      <>
        {header}
        <Card style={{ maxWidth: 420 }}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <Text>금고가 잠겨 있습니다. 비밀번호를 입력하세요.</Text>
            <Input.Password
              aria-label="비밀번호"
              value={unlockPassword}
              onChange={(e) => setUnlockPassword(e.target.value)}
              onPressEnter={() => void vault.unlock(unlockPassword)}
            />
            {vault.errorMessage && (
              <Alert type="error" showIcon message={vault.errorMessage} />
            )}
            <Button
              type="primary"
              block
              onClick={() => void vault.unlock(unlockPassword)}
            >
              열기
            </Button>
          </Space>
        </Card>
      </>
    );
  }

  return (
    <>
      <Space
        style={{ width: "100%", justifyContent: "space-between", marginBottom: 24 }}
        align="start"
      >
        <Space direction="vertical" size={4}>
          <Title level={3} style={{ margin: 0 }}>
            연봉 관리
          </Title>
          <Text type="secondary">
            열림 · 저장하지 않은 편집은 USB에 반영되지 않습니다.
          </Text>
        </Space>
        <Space>
          <Button
            disabled={vault.dirty}
            onClick={() => {
              setPasswordModalOpen(true);
              vault.suspendAutoLock(true);
            }}
          >
            비밀번호 변경
          </Button>
          <Button
            disabled={vault.dirty}
            onClick={() => {
              setDelegateModalOpen(true);
              vault.suspendAutoLock(true);
            }}
          >
            담당자 위임
          </Button>
          {/* 스펙 §7: ③ → ② 전환에서 dirty면 먼저 저장 여부를 묻는다.
              페이지가 언로드되지 않으므로 beforeunload는 뜨지 않는다. */}
          <Button
            onClick={() => {
              if (
                vault.dirty &&
                !window.confirm(
                  "저장하지 않은 편집이 있습니다.\n지금 잠그면 편집 내용이 사라집니다. 계속할까요?",
                )
              ) {
                return;
              }
              vault.lock();
            }}
          >
            잠그기
          </Button>
          <Button
            type={vault.dirty ? "primary" : "default"}
            disabled={!vault.dirty}
            onClick={() => void vault.save()}
          >
            저장
          </Button>
        </Space>
      </Space>

      {vault.lockCountdown !== null && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${vault.lockCountdown}초 후 자동으로 잠깁니다`}
          // 자동 잠금은 보안이 우선이므로 막지 않는다. 대신 사라질 편집이
          // 있다는 사실을 카운트다운 안에서 알려, 30초 안에 저장할 수 있게 한다.
          description={
            vault.dirty
              ? "저장하지 않은 편집이 있습니다. 지금 저장하지 않으면 사라집니다."
              : undefined
          }
        />
      )}

      {vault.errorMessage && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={vault.errorMessage}
        />
      )}

      <Space style={{ marginBottom: 16 }}>
        <Input
          allowClear
          placeholder="직원명 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 200 }}
        />
        <Button
          type={vault.dirty ? "default" : "primary"}
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          + 연봉 등록
        </Button>
      </Space>

      <SalaryRecordTable
        records={visibleRecords}
        onEdit={(row) => {
          setEditing(row);
          setModalOpen(true);
        }}
        onDelete={(empId, year) => vault.removeRecord(empId, year)}
      />

      <SalaryRecordModal
        open={modalOpen}
        initial={editing}
        employees={employeeOptions}
        onCancel={() => setModalOpen(false)}
        onSubmit={(record) => {
          vault.upsertRecord(record);
          setModalOpen(false);
        }}
      />

      <DelegateModal
        open={passwordModalOpen}
        passwordChangeOnly
        users={[]}
        onVerifyPassword={vault.verifyPassword}
        suspendAutoLock={vault.suspendAutoLock}
        // 취소와 5분 초과가 모두 이 경로로 들어온다(모달의 타이머가 onCancel을
        // 부른다). 스펙 §8.1.3·§11: 파일은 그대로 두고 잠근다(②). 5분 상한은
        // 자동 잠금을 유예했기 때문에 존재하는 것이므로, 여기서 잠그지 않으면
        // suspendAutoLock(false)가 유휴 시계를 다시 0부터 돌려 최대 10분 동안
        // 열린 화면이 빈자리에 남는다.
        onCancel={() => {
          setPasswordModalOpen(false);
          vault.suspendAutoLock(false);
          vault.lock();
        }}
        onConfirm={async ({ newPassword }) => {
          await vault.reencrypt(newPassword);
          setPasswordModalOpen(false);
          vault.suspendAutoLock(false);
        }}
      />

      <DelegateModal
        open={delegateModalOpen}
        users={userOptions}
        onVerifyPassword={vault.verifyPassword}
        suspendAutoLock={vault.suspendAutoLock}
        // 위임 취소·5분 초과도 같다(§11 "파일 미변경 + 잠금(②)"). 후임자를
        // 데리러 간 사이 모달이 스스로 닫히고 연봉 테이블이 그대로 드러나던
        // 경로다.
        onCancel={() => {
          setDelegateModalOpen(false);
          vault.suspendAutoLock(false);
          vault.lock();
        }}
        onConfirm={async ({ newPassword, targetUserId }) => {
          await vault.reencrypt(newPassword, {
            targetUserId: targetUserId ?? undefined,
          });
          setDelegateModalOpen(false);
          vault.suspendAutoLock(false);
          Modal.info({
            title: "위임이 완료되었습니다",
            content:
              "후임자에게 연봉 메뉴 권한이 없다면 관리자 화면에서 부여해야 합니다. " +
              "후임자가 다른 자리를 쓴다면 허용 IP도 갱신해야 합니다.",
          });
        }}
      />
    </>
  );
}
