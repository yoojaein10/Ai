import { Tooltip } from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleOutlined,
  MinusCircleOutlined,
  PlayCircleFilled,
} from "@ant-design/icons";
import type {
  DocHistoryItem,
  DocLineStepView,
  DocStatus,
} from "../../api/approval";

type Props = {
  steps: DocLineStepView[];
  currentStep: number;
  status: DocStatus;
  history: DocHistoryItem[];
};

type StepVisual =
  | { tone: "done"; icon: JSX.Element; label: string }
  | { tone: "active"; icon: JSX.Element; label: string }
  | { tone: "rejected"; icon: JSX.Element; label: string }
  | { tone: "pending"; icon: JSX.Element; label: string }
  | { tone: "skipped"; icon: JSX.Element; label: string };

function resolveVisual(
  step: DocLineStepView,
  currentStep: number,
  status: DocStatus,
  history: DocHistoryItem[],
): StepVisual {
  const acted = history.find(
    (h) => h.step_order === step.step_order && h.action !== "PENDING",
  );
  if (acted?.action === "APPROVED") {
    return {
      tone: "done",
      icon: <CheckCircleFilled style={{ color: "var(--color-success)" }} />,
      label: "승인",
    };
  }
  if (acted?.action === "REJECTED") {
    return {
      tone: "rejected",
      icon: <CloseCircleFilled style={{ color: "var(--color-danger)" }} />,
      label: "반려",
    };
  }
  if (status === "RECALLED") {
    return {
      tone: "skipped",
      icon: <MinusCircleOutlined style={{ color: "var(--text-tertiary)" }} />,
      label: "회수",
    };
  }
  if (step.step_order === currentStep && status !== "DRAFT") {
    return {
      tone: "active",
      icon: <PlayCircleFilled style={{ color: "var(--brand-primary)" }} />,
      label: "진행 중",
    };
  }
  return {
    tone: "pending",
    icon: <ClockCircleOutlined style={{ color: "var(--text-tertiary)" }} />,
    label: "대기",
  };
}

const APPROVER_TYPE_LABEL: Record<string, string> = {
  USER: "지정",
  ROLE: "역할",
  POSITION: "직책",
  DEPT_HEAD: "부서장",
  DIRECT_MANAGER: "직속상사",
};

export default function ApprovalLineView({
  steps,
  currentStep,
  status,
  history,
}: Props) {
  if (steps.length === 0) {
    return (
      <div style={{ color: "var(--text-tertiary)", fontSize: 13 }}>
        결재선이 설정되지 않았습니다.
      </div>
    );
  }
  return (
    <ol
      style={{
        display: "flex",
        gap: 12,
        listStyle: "none",
        padding: 0,
        margin: 0,
        overflowX: "auto",
      }}
    >
      {steps.map((s, i) => {
        const v = resolveVisual(s, currentStep, status, history);
        const bg =
          v.tone === "done"
            ? "color-mix(in oklab, var(--color-success) 8%, transparent)"
            : v.tone === "active"
              ? "color-mix(in oklab, var(--brand-primary) 10%, transparent)"
              : v.tone === "rejected"
                ? "color-mix(in oklab, var(--color-danger) 10%, transparent)"
                : "var(--surface-subtle)";
        return (
          <li
            key={s.step_order}
            style={{
              flex: "1 1 auto",
              minWidth: 140,
              padding: "10px 14px",
              background: bg,
              borderRadius: 8,
              display: "flex",
              flexDirection: "column",
              gap: 4,
              position: "relative",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontSize: 12,
                color: "var(--text-secondary)",
              }}
            >
              <span>{s.step_order}단계</span>
              <span>·</span>
              <span>{APPROVER_TYPE_LABEL[s.approver_type] ?? s.approver_type}</span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontWeight: 500,
              }}
            >
              {v.icon}
              <span>{s.resolved_name ?? "미지정"}</span>
            </div>
            <Tooltip title={v.label}>
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                {v.label}
              </span>
            </Tooltip>
            {i < steps.length - 1 && (
              <div
                aria-hidden
                style={{
                  position: "absolute",
                  right: -8,
                  top: "50%",
                  transform: "translateY(-50%)",
                  width: 8,
                  height: 2,
                  background: "var(--border-subtle)",
                }}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
