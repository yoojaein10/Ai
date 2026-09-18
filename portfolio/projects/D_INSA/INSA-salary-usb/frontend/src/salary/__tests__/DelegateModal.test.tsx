// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DelegateModal from "../DelegateModal";

const USERS = [
  { id: 7, login_id: "lee", display_name: "이영희" },
  { id: 8, login_id: "park", display_name: "박민수" },
];

type Props = ComponentProps<typeof DelegateModal>;

function renderModal(overrides: Partial<Props> = {}) {
  const defaultProps: Props = {
    open: true,
    users: USERS,
    onCancel: vi.fn(),
    onConfirm: vi.fn().mockResolvedValue(undefined),
    onVerifyPassword: vi.fn().mockResolvedValue(true),
    suspendAutoLock: vi.fn(),
  };
  return render(<DelegateModal {...defaultProps} {...overrides} />);
}

describe("DelegateModal", () => {
  it("1단계에서는 새 비밀번호 입력란이 없다", () => {
    renderModal();
    expect(screen.getByLabelText("현재 비밀번호")).toBeInTheDocument();
    expect(screen.queryByLabelText("새 비밀번호")).not.toBeInTheDocument();
  });

  it("현재 비밀번호가 비어 있으면 다음으로 갈 수 없다", () => {
    renderModal();
    expect(screen.getByRole("button", { name: "다음" })).toBeDisabled();
  });

  it("2단계로 넘어가면 인계 안내와 새 비밀번호 입력란이 나온다", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(await screen.findByText(/자리를 넘겨주세요/)).toBeInTheDocument();
    expect(screen.getByLabelText("새 비밀번호")).toBeInTheDocument();
  });

  it("2단계 화면에 1단계 입력값이 남아 있지 않다", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByLabelText("새 비밀번호");

    expect(screen.queryByDisplayValue("old-password")).not.toBeInTheDocument();
  });

  it("새 비밀번호 2회가 다르면 완료할 수 없다", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.type(await screen.findByLabelText("새 비밀번호"), "new-password-1");
    await user.type(screen.getByLabelText("새 비밀번호 확인"), "different");

    expect(screen.getByRole("button", { name: "위임 완료" })).toBeDisabled();
  });

  it("후임자를 선택하지 않으면 새 비밀번호를 채워도 위임을 완료할 수 없다", async () => {
    const user = userEvent.setup();
    renderModal();

    // 후임자 선택 없이 바로 다음으로 넘어간다
    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.type(await screen.findByLabelText("새 비밀번호"), "new-password-1");
    await user.type(screen.getByLabelText("새 비밀번호 확인"), "new-password-1");

    expect(screen.getByText("후임자를 선택하지 않았습니다")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "위임 완료" })).toBeDisabled();
  });

  it("후임자를 선택하면 위임을 완료할 수 있다", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    renderModal({ onConfirm });

    await user.click(screen.getByRole("combobox", { name: "후임자" }));
    await user.click(await screen.findByText("이영희 (lee)"));
    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.type(await screen.findByLabelText("새 비밀번호"), "new-password-1");
    await user.type(screen.getByLabelText("새 비밀번호 확인"), "new-password-1");

    const finishButton = screen.getByRole("button", { name: "위임 완료" });
    expect(finishButton).toBeEnabled();
    await user.click(finishButton);

    expect(onConfirm).toHaveBeenCalledWith({
      currentPassword: "old-password",
      newPassword: "new-password-1",
      targetUserId: 7,
    });
  });

  it("취소하면 onConfirm이 호출되지 않는다", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderModal({ onConfirm, onCancel });

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.click(await screen.findByRole("button", { name: "취소" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
  });

  it("현재 비밀번호가 틀리면 1단계에 머물고 오류를 보여준다", async () => {
    const user = userEvent.setup();
    const onVerifyPassword = vi.fn().mockResolvedValue(false);
    renderModal({ onVerifyPassword });

    await user.type(screen.getByLabelText("현재 비밀번호"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(await screen.findByText("비밀번호가 올바르지 않습니다.")).toBeInTheDocument();
    expect(onVerifyPassword).toHaveBeenCalledWith("wrong-password");
    // 여전히 1단계다 — 새 비밀번호 입력란이 없다
    expect(screen.queryByLabelText("새 비밀번호")).not.toBeInTheDocument();
  });

  it("현재 비밀번호가 맞으면 실제로 검증을 거친 뒤 2단계로 넘어간다", async () => {
    const user = userEvent.setup();
    const onVerifyPassword = vi.fn().mockResolvedValue(true);
    renderModal({ onVerifyPassword });

    await user.type(screen.getByLabelText("현재 비밀번호"), "correct-password");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(await screen.findByLabelText("새 비밀번호")).toBeInTheDocument();
    expect(onVerifyPassword).toHaveBeenCalledWith("correct-password");
  });

  it("onConfirm이 실패하면 2단계에 머물고 오류를 보여주며 자동 잠금 유예를 해제한다", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockRejectedValue(new Error("USB가 분리되었습니다"));
    const suspendAutoLock = vi.fn();
    renderModal({ onConfirm, suspendAutoLock, passwordChangeOnly: true, users: [] });

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.type(await screen.findByLabelText("새 비밀번호"), "new-password-1");
    await user.type(screen.getByLabelText("새 비밀번호 확인"), "new-password-1");
    await user.click(screen.getByRole("button", { name: "변경 완료" }));

    expect(await screen.findByText("USB가 분리되었습니다")).toBeInTheDocument();
    // 실패해도 모달은 열려 있다 — 새 비밀번호 입력란이 그대로 있다
    expect(screen.getByLabelText("새 비밀번호")).toBeInTheDocument();
    expect(suspendAutoLock).toHaveBeenCalledWith(false);
  });
});
