// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SideNav } from "../SideNav";
import { CommandPalette } from "../CommandPalette";
import { useAuthStore } from "../../store/auth";

describe("menu role filtering", () => {
  describe("SideNav component", () => {
    function renderSideNav(gnb: "인사" | "관리" = "인사") {
      return render(
        <MemoryRouter>
          <SideNav activeGnb={gnb} collapsed={false} onToggleCollapse={() => {}} />
        </MemoryRouter>
      );
    }

    beforeEach(() => {
      useAuthStore.setState({
        accessToken: "REDACTED_CONFIGURE_LOCALLY",
        roles: [],
        userId: null,
        loginId: null,
      });
    });

    afterEach(() => {
      useAuthStore.setState({
        accessToken: null,
        roles: [],
        userId: null,
        loginId: null,
      });
    });

    it("EMPLOYEE는 인사 > 연봉관리를 볼 수 없다", () => {
      useAuthStore.setState({ roles: ["EMPLOYEE"] });
      renderSideNav("인사");
      expect(screen.queryByText("연봉관리")).not.toBeInTheDocument();
    });

    it("HR_ADMIN은 인사 > 연봉관리를 본다", () => {
      useAuthStore.setState({ roles: ["HR_ADMIN"] });
      renderSideNav("인사");
      // /salary는 반드시 렌더링되는 메뉴 항목
      expect(screen.getByRole("menuitem", { name: /연봉관리/ })).toBeInTheDocument();
    });

    it("SYSTEM_ADMIN은 인사 > 연봉관리를 본다", () => {
      useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
      renderSideNav("인사");
      expect(screen.getByRole("menuitem", { name: /연봉관리/ })).toBeInTheDocument();
    });

    it("EMPLOYEE는 관리 > 연봉접근관리를 볼 수 없다", () => {
      useAuthStore.setState({ roles: ["EMPLOYEE"] });
      renderSideNav("관리");
      expect(screen.queryByText("연봉접근관리")).not.toBeInTheDocument();
    });

    it("HR_ADMIN은 관리 > 연봉접근관리를 볼 수 없다", () => {
      useAuthStore.setState({ roles: ["HR_ADMIN"] });
      renderSideNav("관리");
      expect(screen.queryByText("연봉접근관리")).not.toBeInTheDocument();
    });

    it("SYSTEM_ADMIN은 관리 > 연봉접근관리를 본다", () => {
      useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
      renderSideNav("관리");
      expect(screen.getByRole("menuitem", { name: /연봉접근관리/ })).toBeInTheDocument();
    });

    it("roles 필드가 없는 항목은 모든 사용자에게 보인다 (회귀 방지)", () => {
      useAuthStore.setState({ roles: ["EMPLOYEE"] });
      renderSideNav("인사");
      // 인사정보는 roles 필드가 없으므로 EMPLOYEE도 볼 수 있어야 함
      expect(screen.getByText("인사정보")).toBeInTheDocument();
    });

    it("empty roles 상태에서 roles 없는 항목은 보인다", () => {
      useAuthStore.setState({ roles: [] });
      renderSideNav("인사");
      // 부트스트랩 전 상태: roles가 []인 경우
      // roles 필드가 없는 항목은 여전히 보여야 함
      expect(screen.getByText("인사정보")).toBeInTheDocument();
      // 제한된 항목은 보이지 않아야 함
      expect(screen.queryByText("연봉관리")).not.toBeInTheDocument();
    });
  });

  describe("CommandPalette component", () => {
    function renderPalette() {
      return render(
        <MemoryRouter>
          <CommandPalette open={true} onClose={() => {}} />
        </MemoryRouter>
      );
    }

    beforeEach(() => {
      useAuthStore.setState({
        accessToken: "REDACTED_CONFIGURE_LOCALLY",
        roles: [],
        userId: null,
        loginId: null,
      });
    });

    afterEach(() => {
      useAuthStore.setState({
        accessToken: null,
        roles: [],
        userId: null,
        loginId: null,
      });
    });

    it("EMPLOYEE가 연봉을 검색하면 결과가 없다", () => {
      useAuthStore.setState({ roles: ["EMPLOYEE"] });
      renderPalette();
      const input = screen.getByRole("textbox") as HTMLInputElement;
      input.value = "연봉";
      input.dispatchEvent(new Event("change", { bubbles: true }));
      // 일치하는 메뉴가 없어야 함
      expect(screen.queryByText("연봉관리")).not.toBeInTheDocument();
      expect(screen.queryByText("연봉접근관리")).not.toBeInTheDocument();
    });

    it("HR_ADMIN이 연봉을 검색하면 연봉관리만 나온다", () => {
      useAuthStore.setState({ roles: ["HR_ADMIN"] });
      renderPalette();
      const input = screen.getByRole("textbox") as HTMLInputElement;
      input.value = "연봉";
      input.dispatchEvent(new Event("change", { bubbles: true }));
      expect(screen.getByText("연봉관리")).toBeInTheDocument();
      expect(screen.queryByText("연봉접근관리")).not.toBeInTheDocument();
    });

    it("SYSTEM_ADMIN이 연봉을 검색하면 둘 다 나온다", () => {
      useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
      renderPalette();
      const input = screen.getByRole("textbox") as HTMLInputElement;
      input.value = "연봉";
      input.dispatchEvent(new Event("change", { bubbles: true }));
      expect(screen.getByText("연봉관리")).toBeInTheDocument();
      expect(screen.getByText("연봉접근관리")).toBeInTheDocument();
    });

    it("roles 필드가 없는 항목은 검색되지 않음 (스태틱 메뉴와 달리 검색만 가능)", () => {
      useAuthStore.setState({ roles: ["EMPLOYEE"] });
      renderPalette();
      // 인사정보는 검색어가 없을 때 전체 메뉴 목록에 포함되어야 함
      expect(screen.getByText("인사정보")).toBeInTheDocument();
    });
  });
});
