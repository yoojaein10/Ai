import { type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { TopBar } from "../shell/TopBar";
import { SideNav } from "../shell/SideNav";
import { CommandPalette } from "../shell/CommandPalette";
import { useCommandPalette } from "../shell/hooks/useCommandPalette";
import { resolveGnbFromPath } from "../shell/menuRegistry";
import { useShellStore } from "../store/shellStore";

export default function MainLayout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const activeGnb = resolveGnbFromPath(location.pathname);
  const collapsed = useShellStore((s) => s.siderCollapsed);
  const toggleSider = useShellStore((s) => s.toggleSider);
  const { open, setOpen, shortcutLabel } = useCommandPalette();

  return (
    <div className="insa-shell">
      <TopBar shortcutLabel={shortcutLabel} onOpenPalette={() => setOpen(true)} />
      <div className="insa-shell-body">
        <SideNav
          activeGnb={activeGnb}
          collapsed={collapsed}
          onToggleCollapse={toggleSider}
        />
        <main className="insa-shell-content">{children}</main>
      </div>
      <CommandPalette open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
