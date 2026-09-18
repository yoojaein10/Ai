// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SalaryPage from "../SalaryPage";
import { useAuthStore } from "../../store/auth";

const vaultMock = vi.hoisted(() => ({
  state: {
    status: "DISCONNECTED" as string,
    records: [] as unknown[],
    dirty: false,
    errorMessage: null as string | null,
    lockCountdown: null as number | null,
  },
  // 렌더마다 새 vi.fn()을 만들면 호출 여부를 확인할 수 없다. 훅 바깥에 두고
  // 테스트마다 초기화한다.
  fns: {
    connect: vi.fn(),
    unlock: vi.fn(),
    createVault: vi.fn(),
    lock: vi.fn(),
    save: vi.fn(),
    upsertRecord: vi.fn(),
    removeRecord: vi.fn(),
    reencrypt: vi.fn(),
    suspendAutoLock: vi.fn(),
    verifyPassword: vi.fn().mockResolvedValue(true),
  },
}));

vi.mock("../../salary/useSalaryVault", () => ({
  AUTO_LOCK_MS: 600000,
  WARN_BEFORE_MS: 30000,
  useSalaryVault: () => ({ ...vaultMock.state, ...vaultMock.fns }),
}));

interface PolicyData {
  allowed: boolean;
  current_ip: string | null;
  configured: boolean;
  reason: string | null;
}

const policyMock = vi.hoisted(() => ({
  state: {
    data: {
      allowed: true,
      current_ip: "192.0.2.10",
      configured: true,
      reason: null,
    } as PolicyData | undefined,
    isLoading: false,
  },
}));

vi.mock("../../api/salaryPolicy", () => ({
  usePolicyCheck: () => ({ data: policyMock.state.data, isLoading: policyMock.state.isLoading }),
}));

vi.mock("../../salary/vault", () => ({
  isFileSystemAccessSupported: () => true,
}));

vi.mock("../../api/employees", () => ({
  useAllEmployees: () => ({ data: [], isLoading: false }),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SalaryPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(vaultMock.fns).forEach((fn) => fn.mockClear());
});

describe("SalaryPage — 잠금 해제 이전 상태", () => {
  it("역할이 없으면 권한 없음을 보여준다", () => {
    useAuthStore.setState({ roles: ["EMPLOYEE"] });
    vaultMock.state = {
      status: "DISCONNECTED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = {
      data: { allowed: true, current_ip: "192.0.2.10", configured: true, reason: null },
      isLoading: false,
    };
    renderPage();
    expect(screen.getByText(/권한이 없습니다/)).toBeInTheDocument();
  });

  it("미연결 상태에서 USB 폴더 선택 버튼을 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "DISCONNECTED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = {
      data: { allowed: true, current_ip: "192.0.2.10", configured: true, reason: null },
      isLoading: false,
    };
    renderPage();
    expect(screen.getByRole("button", { name: /USB 폴더 선택/ })).toBeInTheDocument();
  });

  it("미연결 상태에서도 실패 메시지를 화면에 보여준다", () => {
    // 폴더를 고르지 않고 [새 연봉 금고 만들기]를 누른 경우가 여기로 온다.
    // 훅이 errorMessage를 세워도 화면이 그리지 않으면 사용자에게는 여전히
    // "아무 일도 일어나지 않는" 화면이다.
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "DISCONNECTED",
      records: [],
      dirty: false,
      errorMessage: "새 금고를 만들지 못했습니다. 먼저 USB 폴더를 선택했는지 확인하세요.",
      lockCountdown: null,
    };
    policyMock.state = {
      data: { allowed: true, current_ip: "192.0.2.10", configured: true, reason: null },
      isLoading: false,
    };
    renderPage();
    expect(screen.getByText(/먼저 USB 폴더를 선택했는지 확인하세요/)).toBeInTheDocument();
  });

  it("정책 확인이 끝나기 전에는 비밀번호 입력란을 렌더링하지 않는다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "DISCONNECTED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = {
      data: undefined,
      isLoading: true,
    };
    renderPage();
    expect(screen.queryByLabelText("비밀번호")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("새 금고 비밀번호")).not.toBeInTheDocument();
  });

  it("허용되지 않은 IP에서는 비밀번호 입력란을 렌더링하지 않는다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "LOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = {
      data: {
        allowed: false,
        current_ip: "192.0.2.10",
        configured: true,
        reason: "IP 192.0.2.10 및 접근 ID admin에 연봉 접근 권한이 없습니다.",
      },
      isLoading: false,
    };
    renderPage();
    expect(screen.queryByLabelText("비밀번호")).not.toBeInTheDocument();
    expect(screen.getByText(/192\.168\.0\.99/)).toBeInTheDocument();
  });

  it("허용된 IP의 잠김 상태에서는 비밀번호 입력란을 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "LOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = {
      data: { allowed: true, current_ip: "192.0.2.10", configured: true, reason: null },
      isLoading: false,
    };
    renderPage();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
  });

  it("열기 후 다시 잠기면 비밀번호 입력란이 비어 있다", async () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    policyMock.state = {
      data: { allowed: true, current_ip: "192.0.2.10", configured: true, reason: null },
      isLoading: false,
    };
    const locked = {
      status: "LOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    vaultMock.state = { ...locked };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    // 같은 엘리먼트 객체를 다시 넘기면 React가 재렌더를 건너뛴다. 매번 새로 만든다.
    const ui = () => (
      <QueryClientProvider client={client}>
        <SalaryPage />
      </QueryClientProvider>
    );
    const { rerender } = render(ui());

    await userEvent.type(screen.getByLabelText("비밀번호"), "correct horse");
    expect(screen.getByLabelText("비밀번호")).toHaveValue("correct horse");

    // 열기 성공 → 잠금(수동·자동·비밀번호 변경 취소 모두 같은 경로)
    vaultMock.state = { ...locked, status: "UNLOCKED" };
    rerender(ui());
    expect(screen.queryByLabelText("비밀번호")).toBeNull();
    vaultMock.state = { ...locked };
    rerender(ui());

    expect(screen.getByLabelText("비밀번호")).toHaveValue("");
  });

  it("오류 상태에서는 백업 복원 안내를 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "ERROR",
      records: [],
      dirty: false,
      errorMessage: "파일이 손상되었습니다.",
      lockCountdown: null,
    };
    policyMock.state = {
      data: { allowed: true, current_ip: "192.0.2.10", configured: true, reason: null },
      isLoading: false,
    };
    renderPage();
    expect(screen.getByText(/salary\.enc\.bak/)).toBeInTheDocument();
  });
});

describe("SalaryPage — 열림 상태", () => {
  const allowedPolicy: PolicyData = {
    allowed: true,
    current_ip: "192.0.2.10",
    configured: true,
    reason: null,
  };

  const sampleRecord = {
    empId: 1,
    empNo: "20200001",
    empName: "김철수",
    year: 2026,
    effectiveDate: "2026-01-01",
    annualSalary: 52_000_000,
    raiseRate: 4.5,
    note: null,
  };

  it("연봉 레코드를 테이블에 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [sampleRecord],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.getByText("김철수")).toBeInTheDocument();
    expect(screen.getByText("52,000,000")).toBeInTheDocument();
  });

  it("dirty가 아니면 저장 버튼이 비활성이다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
  });

  it("dirty가 아니면 + 연봉 등록이 Primary이고 저장은 아니다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    const registerButton = screen.getByRole("button", { name: "+ 연봉 등록" });
    const saveButton = screen.getByRole("button", { name: "저장" });
    expect(registerButton).toHaveClass("ant-btn-primary");
    expect(saveButton).not.toHaveClass("ant-btn-primary");
  });

  it("dirty면 저장이 Primary이고 + 연봉 등록은 아니다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: true,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    const registerButton = screen.getByRole("button", { name: "+ 연봉 등록" });
    const saveButton = screen.getByRole("button", { name: "저장" });
    expect(saveButton).toHaveClass("ant-btn-primary");
    expect(registerButton).not.toHaveClass("ant-btn-primary");
  });

  it("잠김 상태에서는 금액이 DOM에 없다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    // records에 실제 값을 채워, 훅이 어떤 이유로든 레코드를 들고 있는 채로
    // LOCKED 상태가 되더라도 화면이 절대 금액을 그리지 않는지를 검증한다.
    vaultMock.state = {
      status: "LOCKED",
      records: [sampleRecord],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.queryByText("52,000,000")).not.toBeInTheDocument();
  });

  it("자동 잠금 경고를 카운트다운으로 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: 25,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.getByText(/25초 후 자동으로 잠깁니다/)).toBeInTheDocument();
  });

  it("dirty가 아니면 비밀번호 변경·담당자 위임 버튼이 활성이다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.getByRole("button", { name: "비밀번호 변경" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "담당자 위임" })).toBeEnabled();
  });

  it("dirty면 비밀번호 변경·담당자 위임 버튼이 비활성이다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: true,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.getByRole("button", { name: "비밀번호 변경" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "담당자 위임" })).toBeDisabled();
  });

  it("위임을 취소하면 금고를 잠근다", async () => {
    // 취소와 5분 초과가 같은 경로다(모달 타이머가 onCancel을 부른다).
    // 잠그지 않으면 연봉 테이블이 그대로 드러난 화면이 빈자리에 남는다 (§11).
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();

    await user.click(screen.getByRole("button", { name: "담당자 위임" }));
    await user.click(await screen.findByRole("button", { name: "취소" }));

    expect(vaultMock.fns.lock).toHaveBeenCalledTimes(1);
  });

  it("비밀번호 변경을 취소해도 금고를 잠근다", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();

    await user.click(screen.getByRole("button", { name: "비밀번호 변경" }));
    await user.click(await screen.findByRole("button", { name: "취소" }));

    expect(vaultMock.fns.lock).toHaveBeenCalledTimes(1);
  });

  it("dirty 상태의 잠그기는 확인을 묻고, 취소하면 잠그지 않는다", async () => {
    // 스펙 §7: ③ → ② 전환에서 dirty면 먼저 저장 여부를 묻는다.
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: true,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();

    await user.click(screen.getByRole("button", { name: "잠그기" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(vaultMock.fns.lock).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "잠그기" }));
    expect(vaultMock.fns.lock).toHaveBeenCalledTimes(1);

    confirmSpy.mockRestore();
  });

  it("dirty가 아니면 잠그기가 확인을 묻지 않는다", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: false,
      errorMessage: null,
      lockCountdown: null,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    await user.click(screen.getByRole("button", { name: "잠그기" }));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(vaultMock.fns.lock).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  it("dirty 상태의 자동 잠금 카운트다운은 사라질 편집이 있음을 알린다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state = {
      status: "UNLOCKED",
      records: [],
      dirty: true,
      errorMessage: null,
      lockCountdown: 25,
    };
    policyMock.state = { data: allowedPolicy, isLoading: false };
    renderPage();
    expect(screen.getByText(/저장하지 않은 편집이 있습니다/)).toBeInTheDocument();
  });
});
