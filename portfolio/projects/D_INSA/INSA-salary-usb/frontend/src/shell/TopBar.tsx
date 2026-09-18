import { useNavigate, useLocation } from "react-router-dom";
import { MENU, GNB_ORDER, type GnbKey, resolveGnbFromPath } from "./menuRegistry";
import NotificationBell from "../components/NotificationBell";
import { UserMenu } from "./UserMenu";
import { hasUnsavedChanges } from "./hooks/useUnsavedState";

type TopBarProps = {
  shortcutLabel: string;
  onOpenPalette: () => void;
};

export function TopBar({ shortcutLabel, onOpenPalette }: TopBarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const activeGnb: GnbKey = resolveGnbFromPath(location.pathname);

  const handleGnbClick = (gnb: GnbKey) => {
    if (hasUnsavedChanges() && !window.confirm("저장 안 된 변경 사항이 있어요.\n계속 이동할까요?")) {
      return;
    }
    navigate(MENU[gnb].defaultPath);
  };

  const handleHomeClick = () => {
    if (hasUnsavedChanges() && !window.confirm("저장 안 된 변경 사항이 있어요.\n계속 이동할까요?")) {
      return;
    }
    navigate("/hr/employees");
  };

  return (
    <header className="insa-topbar">
      <button
        type="button"
        className="insa-wordmark"
        onClick={handleHomeClick}
        aria-label="홈으로"
        style={{ background: "transparent", border: 0 }}
      >
        <span className="insa-wordmark-name">Daehwa</span>
        <span className="insa-wordmark-sub">인사관리</span>
      </button>

      <nav className="insa-gnb" aria-label="주 메뉴">
        {GNB_ORDER.map((gnb) => (
          <button
            key={gnb}
            type="button"
            className="insa-gnb-item"
            aria-current={activeGnb === gnb ? "page" : undefined}
            onClick={() => handleGnbClick(gnb)}
          >
            {gnb}
          </button>
        ))}
      </nav>

      <div className="insa-topbar-right">
        <button
          type="button"
          className="insa-cmdk-hint"
          onClick={onOpenPalette}
          aria-label="명령 팔레트 열기"
        >
          <span>페이지 찾기</span>
          <span className="insa-cmdk-kbd">{shortcutLabel}</span>
        </button>

        <span className="insa-notification">
          <NotificationBell />
        </span>

        <UserMenu />
      </div>
    </header>
  );
}
