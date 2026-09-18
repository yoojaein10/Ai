import { useState } from "react";
import { Popover } from "antd";
import { useNavigate } from "react-router-dom";
import { LogoutOutlined, UserOutlined } from "@ant-design/icons";
import { useMe } from "../api/me";
import { useAuthStore } from "../store/auth";
import { Avatar } from "./Avatar";
import { hasUnsavedChanges } from "./hooks/useUnsavedState";

export function UserMenu() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const loginId = useAuthStore((s) => s.loginId);
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

  const handleLogout = () => {
    setOpen(false);
    logout();
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
        onClick={handleLogout}
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
