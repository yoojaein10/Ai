// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import EvalAiReportPage from "../EvalAiReportPage";

vi.mock("../../api/evalRounds", () => ({
  useEvalRounds: () => ({
    data: [{ id: 1, year: 2026, name: "정기" }],
    isLoading: false,
  }),
}));

const mockReports = vi.hoisted(() => ({
  list: [
    {
      employee_id: 10,
      employee_name: "홍길동",
      total_score: "82",
      final_grade: "A",
      report_id: null,
      version: null,
      status: null,
      generated_at: null,
      error_message: null,
    },
  ],
}));

vi.mock("../../api/aiReport", () => ({
  useAiReports: () => ({ data: mockReports.list, isLoading: false }),
  useAiReportDetail: () => ({ data: undefined }),
  useGenerateBatch: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ success: 1, failed: 0 }),
    isPending: false,
  }),
  useGenerateOne: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EvalAiReportPage />
    </QueryClientProvider>,
  );
}

describe("EvalAiReportPage", () => {
  it("회차 선택 후 직원 목록을 렌더한다", async () => {
    renderPage();
    const select = screen.getByRole("combobox");
    await userEvent.click(select);
    await userEvent.click(await screen.findByText("2026년 정기"));
    await waitFor(() => {
      expect(screen.getByText("홍길동")).toBeInTheDocument();
      expect(screen.getByText("미생성")).toBeInTheDocument();
    });
  });

  it("일괄 생성 버튼 클릭 시 confirm 모달이 뜬다", async () => {
    renderPage();
    const select = screen.getByRole("combobox");
    await userEvent.click(select);
    await userEvent.click(await screen.findByText("2026년 정기"));
    await userEvent.click(screen.getByRole("button", { name: /회차 일괄 생성/ }));
    expect(await screen.findByText(/외부 LLM/)).toBeInTheDocument();
  });
});
