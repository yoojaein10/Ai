// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SalaryAdminPage from "../SalaryAdminPage";
import { useAuthStore } from "../../store/auth";

const mocks = vi.hoisted(() => ({
  policy: null as { allowed_ip: string; owner_user_id: number } | null,
  check: { allowed: true, current_ip: "192.0.2.10", configured: false, reason: null },
  upsert: vi.fn(),
  logs: [
    {
      id: 1,
      user_id: 2,
      action: "IP_DENIED",
      target_user_id: null,
      record_count: null,
      ip_address: "192.0.2.10",
      user_agent: "Chrome",
      occurred_at: "2026-08-19T01:00:00",
    },
  ],
}));

vi.mock("../../api/salaryPolicy", () => ({
  usePolicy: () => ({ data: mocks.policy, isLoading: false }),
  usePolicyCheck: () => ({ data: mocks.check, isLoading: false }),
  useUpsertPolicy: () => ({ mutateAsync: mocks.upsert, isPending: false }),
}));

vi.mock("../../api/salaryAudit", () => ({
  useAccessLogs: () => ({
    data: { items: mocks.logs, total: 1 },
    isLoading: false,
  }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SalaryAdminPage />
    </QueryClientProvider>,
  );
}

describe("SalaryAdminPage", () => {
  it("SYSTEM_ADMIN이 아니면 권한 없음을 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    renderPage();
    expect(screen.getByText(/권한이 없습니다/)).toBeInTheDocument();
  });

  it("정책 미설정이면 경고를 보여준다", () => {
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    mocks.policy = null;
    renderPage();
    expect(screen.getByText(/허용 IP가 설정되지 않았습니다/)).toBeInTheDocument();
  });

  it("현재 접속 IP로 설정 버튼이 입력란을 채운다", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    mocks.policy = null;
    renderPage();

    await user.click(screen.getByRole("button", { name: /현재 접속 IP로 설정/ }));
    expect(screen.getByLabelText("허용 IP")).toHaveValue("192.0.2.10");
  });

  it("정책 저장이 실패하면 관리자에게 오류를 보여준다", async () => {
    // 저장이 조용히 실패하면 관리자는 허용 IP가 바뀐 줄 알고 자리를 뜬다.
    // 그 상태로 담당자가 금고를 열려다 막히는 것이 이 분기의 대가다.
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    mocks.policy = null;
    mocks.upsert = vi.fn().mockRejectedValue({
      response: { data: { detail: "이미 등록된 IP입니다" } },
    });
    renderPage();

    await user.type(screen.getByLabelText("담당자 사용자 ID"), "3");
    await user.click(screen.getByRole("button", { name: /현재 접속 IP로 설정/ }));
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByText("이미 등록된 IP입니다")).toBeInTheDocument();
    mocks.upsert = vi.fn();
  });

  it("접근 로그를 보여주고 IP_DENIED를 표시한다", () => {
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    renderPage();
    const tag = screen.getByText("IP_DENIED");
    expect(tag).toBeInTheDocument();
    // 단순히 행이 존재하는지가 아니라, 거부된 시도가 시각적으로 구분되는지를
    // 검증한다 — 태그가 위험 색상(ant-tag-red)을 갖는지 확인한다.
    expect(tag.closest(".ant-tag")).toHaveClass("ant-tag-red");
    expect(screen.getByText("192.0.2.10")).toBeInTheDocument();
  });
});
