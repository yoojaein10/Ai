import { useState } from "react";
import { Popover } from "antd";
import { useNavigate } from "react-router-dom";
import { LogoutOutlined, UserOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { useMe } from "../api/me";
import apiClient from "../api/client";
import { useAuthStore } from "../store/auth";
import { Avatar } from "./Avatar";
import { hasUnsavedChanges } from "./hooks/useUnsavedState";

export function UserMenu() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const loginId = useAuthStore((s) => s.loginId);
  const queryClient = useQueryClient();
  const meQuery = useMe();

  const employee = meQuery.data?.employee;
  const displayName = employee?.name_ko ?? loginId ?? "사용자";
  const subline = [employee?.department, employee?.job_rank]
    .filter(Boolean)
    .join(" · ");

  const go = (path: string) => {
    if (hasUnsavedChanges() && !window.confirm("저장 안 된 변경 사항이 있어요.\n계속 이동할까요?")) {
      return;
    }
    setOpen(false);
    navigate(path);
  };

  const handleLogout = async () => {
    setOpen(false);
    // 서버의 refresh 쿠키를 먼저 지운다. 남겨두면 401 인터셉터가 다음 요청에서
    // 이전 사용자로 조용히 재로그인시킨다.
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // 네트워크 실패여도 클라이언트 쪽 로그아웃은 진행한다.
    }
    logout();
    // 이전 사용자의 /me·목록 캐시가 남으면 다음 로그인 사용자에게 그대로 보인다.
    queryClient.clear();
    navigate("/login");
  };

  const content = (
    <div className="insa-user-popover-content">
      <div className="insa-user-popover-header">
        <Avatar name={displayName} size={40} />
        <div>
          <div className="insa-user-popover-name">{displayName}</div>
          <div className="insa-user-popover-sub">
            {subline || loginId}
            {employee?.emp_no ? ` · ${employee.emp_no}` : ""}
          </div>
        </div>
      </div>
      <button
        type="button"
        className="insa-user-popover-item"
        onClick={() => go("/hr/my-info")}
      >
        <UserOutlined />
        내 정보
      </button>
      <button
        type="button"
        className="insa-user-popover-item insa-user-popover-item-danger"
        onClick={() => void handleLogout()}
      >
        <LogoutOutlined />
        로그아웃
      </button>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      arrow={false}
      styles={{ body: { padding: 0 } }}
    >
      <button type="button" className="insa-user-trigger" aria-label="사용자 메뉴">
        <Avatar name={displayName} size={28} />
        <span className="insa-user-text">
          <span className="insa-user-name">{displayName}</span>
          {subline && <span className="insa-user-sub">{subline}</span>}
        </span>
      </button>
    </Popover>
  );
}
