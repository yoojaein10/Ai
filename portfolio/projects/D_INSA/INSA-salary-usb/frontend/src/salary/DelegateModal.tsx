import { useEffect, useState } from "react";
import { Alert, Button, Input, Modal, Select, Space, Typography } from "antd";

const { Title, Paragraph, Text } = Typography;

export interface UserOption {
  id: number;
  login_id: string;
  display_name: string;
}

interface Props {
  open: boolean;
  users: UserOption[];
  /** 위임이 아니라 본인 비밀번호 변경 모드로 연다 */
  passwordChangeOnly?: boolean;
  onCancel: () => void;
  onConfirm: (input: {
    currentPassword: string;
    newPassword: string;
    targetUserId: number | null;
  }) => Promise<void>;
  /**
   * 1단계 재인증. 실제로 파일을 복호해본 결과를 준다 — 메모리에 든
   * 비밀번호와의 문자열 비교가 아니다 (스펙 §8.1.2). true를 받아야만
   * 2단계로 넘어간다.
   */
  onVerifyPassword: (candidate: string) => Promise<boolean>;
  /**
   * onConfirm이 실패했을 때도 자동 잠금 유예를 직접 풀기 위해 필요하다.
   * 부모의 onCancel/onConfirm 성공 경로는 각자 이미 풀어주지만, 실패
   * 경로는 모달이 계속 열려 있어 그 두 경로를 타지 않는다.
   */
  suspendAutoLock: (suspended: boolean) => void;
}

const STEP_TIMEOUT_MS = 5 * 60 * 1000;

export default function DelegateModal({
  open,
  users,
  passwordChangeOnly = false,
  onCancel,
  onConfirm,
  onVerifyPassword,
  suspendAutoLock,
}: Props) {
  const [step, setStep] = useState<1 | 2>(1);
  const [currentPassword, setCurrentPassword] = useState("");
  const [targetUserId, setTargetUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [finishError, setFinishError] = useState<string | null>(null);

  const reset = () => {
    setStep(1);
    setCurrentPassword("");
    setTargetUserId(null);
    setNewPassword("");
    setConfirmPassword("");
    setSubmitting(false);
    setVerifying(false);
    setVerifyError(null);
    setFinishError(null);
  };

  // 닫힐 때 입력값을 지운다. Modal의 onCancel(X·마스크·ESC 포함)과 footer의
  // 취소·완료 버튼이 모두 이 컴포넌트 안에서 reset()을 직접 호출하므로
  // (아래), open이 false가 되는 모든 경로가 이미 덮여 있다 — 부모가 open을
  // 별도 경로로 바꾸지 않는 한 여기서 추가로 감시할 필요가 없다.

  // 모달이 5분을 넘기면 취소한다. 후임자 입력 중 자동 잠금은 유예되므로,
  // 그 유예가 무기한이 되지 않도록 여기서 상한을 둔다.
  useEffect(() => {
    if (!open) return undefined;
    const timer = setTimeout(() => {
      reset();
      onCancel();
    }, STEP_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [open, onCancel]);

  // 1단계에서 "다음"은 입력란이 비어 있지 않은지만 본다. 실제 관문은
  // handleVerify의 onVerifyPassword 호출이다 — 여기서는 버튼 활성 여부만
  // 결정한다. 후임자 선택은 2단계로 넘어간 뒤에도 비어 있을 수 있으므로,
  // 위임을 실제로 완료할 때 canFinish에서 막는다 — 그래야 후임자를 고르지
  // 않고 완료를 눌러 "위임"이 조용히 "비밀번호 변경"으로 격하되는 일이
  // 없다.
  const canGoNext = currentPassword.length > 0 && !verifying;

  const canFinish =
    newPassword.length >= 8 &&
    newPassword === confirmPassword &&
    !submitting &&
    (passwordChangeOnly || targetUserId !== null);

  const targetName =
    users.find((u) => u.id === targetUserId)?.display_name ?? "후임자";

  /**
   * 실제로 파일을 복호해봐야 재인증이 성립한다 (스펙 §8.1.2). 메모리에 든
   * 값과 문자열 비교하면, 화면이 잠금 해제된 채 방치된 상태에서 지나가던
   * 사람이 아무 값이나 입력해도 통과해버린다.
   */
  const handleVerify = async () => {
    setVerifying(true);
    setVerifyError(null);
    try {
      const ok = await onVerifyPassword(currentPassword);
      if (ok) {
        setStep(2);
      } else {
        setVerifyError("비밀번호가 올바르지 않습니다.");
      }
    } catch (error) {
      setVerifyError(
        error instanceof Error ? error.message : "확인하지 못했습니다.",
      );
    } finally {
      setVerifying(false);
    }
  };

  const handleFinish = async () => {
    setSubmitting(true);
    setFinishError(null);
    try {
      await onConfirm({ currentPassword, newPassword, targetUserId });
      reset();
    } catch (error) {
      // 모달을 닫지 않는다 — 실패를 보여주고 재시도할 기회를 준다. 다만
      // 자동 잠금 유예는 여기서 직접 풀어야 한다. 부모의 onCancel/onConfirm
      // 성공 경로만으로는 이 실패 경로를 덮지 못해, 유예가 풀리지 않은 채
      // 모달이 열린 화면이 방치될 수 있다.
      setFinishError(
        error instanceof Error ? error.message : "완료하지 못했습니다.",
      );
      suspendAutoLock(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={passwordChangeOnly ? "비밀번호 변경" : "담당자 위임"}
      onCancel={() => {
        reset();
        onCancel();
      }}
      destroyOnClose
      footer={
        step === 1
          ? [
              <Button
                key="cancel"
                onClick={() => {
                  reset();
                  onCancel();
                }}
              >
                취소
              </Button>,
              <Button
                key="next"
                type="primary"
                disabled={!canGoNext}
                loading={verifying}
                onClick={() => void handleVerify()}
              >
                다음
              </Button>,
            ]
          : [
              <Button
                key="cancel"
                onClick={() => {
                  reset();
                  onCancel();
                }}
              >
                취소
              </Button>,
              <Button
                key="finish"
                type="primary"
                disabled={!canFinish}
                loading={submitting}
                onClick={() => void handleFinish()}
              >
                {passwordChangeOnly ? "변경 완료" : "위임 완료"}
              </Button>,
            ]
      }
    >
      {step === 1 ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          {!passwordChangeOnly && (
            <>
              <Text>후임 담당자를 선택하세요.</Text>
              <Select
                aria-label="후임자"
                showSearch
                optionFilterProp="label"
                style={{ width: "100%" }}
                value={targetUserId ?? undefined}
                onChange={(v) => setTargetUserId(v)}
                options={users.map((u) => ({
                  value: u.id,
                  label: `${u.display_name} (${u.login_id})`,
                }))}
              />
            </>
          )}
          <Text>본인 확인을 위해 현재 비밀번호를 입력하세요.</Text>
          <Input.Password
            aria-label="현재 비밀번호"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
          {verifyError && <Alert type="error" showIcon message={verifyError} />}
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: "100%" }}>
          {!passwordChangeOnly && (
            <Alert
              type="info"
              showIcon
              message="이제 후임자에게 자리를 넘겨주세요"
              description="아래 비밀번호는 후임자가 직접 입력해야 합니다. 전임자에게 보이지 않습니다."
            />
          )}
          <Title level={5}>
            {passwordChangeOnly
              ? "새 비밀번호를 입력하세요"
              : `${targetName} 님, 새 비밀번호를 입력하세요`}
          </Title>
          {!passwordChangeOnly && targetUserId === null && (
            <Alert
              type="warning"
              showIcon
              message="후임자를 선택하지 않았습니다"
              description="완료하려면 취소한 뒤 처음부터 다시 후임자를 선택하세요."
            />
          )}
          <Input.Password
            aria-label="새 비밀번호"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <Input.Password
            aria-label="새 비밀번호 확인"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
            8자 이상. 잃어버리면 복구할 수 없습니다. 완료하면 금고가 즉시 잠기며,
            새 비밀번호로 열리는지 그 자리에서 확인하세요.
          </Paragraph>
          {finishError && (
            <Alert
              type="error"
              showIcon
              message="완료하지 못했습니다"
              description={finishError}
            />
          )}
        </Space>
      )}
    </Modal>
  );
}
