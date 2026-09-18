import { useMemo, type ReactNode } from "react";
import { Badge, Menu, Tooltip } from "antd";
import type { MenuProps } from "antd";
import {
  UserOutlined,
  TeamOutlined,
  SwapOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
  ReadOutlined,
  HeartOutlined,
  InboxOutlined,
  BarChartOutlined,
  SettingOutlined,
  SolutionOutlined,
  CalendarOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";
import { MENU, type GnbKey } from "./menuRegistry";
import { hasUnsavedChanges } from "./hooks/useUnsavedState";
import { useInboxCount } from "../api/approval";
import { useAuthStore } from "../store/auth";

const INBOX_PATH = "/approval/inbox";

const ICON_MAP: Record<string, ReactNode> = {
  User: <UserOutlined />,
  Team: <TeamOutlined />,
  Swap: <SwapOutlined />,
  File: <FileTextOutlined />,
  Clock: <ClockCircleOutlined />,
  Read: <ReadOutlined />,
  Heart: <HeartOutlined />,
  Inbox: <InboxOutlined />,
  Chart: <BarChartOutlined />,
  Setting: <SettingOutlined />,
  Solution: <SolutionOutlined />,
  Calendar: <CalendarOutlined />,
};

type SideNavProps = {
  activeGnb: GnbKey;
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobile?: boolean;
};

export function SideNav({
  activeGnb,
  collapsed,
  onToggleCollapse,
  mobile = false,
}: SideNavProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: inboxCount = 0 } = useInboxCount();
  const userRoles = useAuthStore((s) => s.roles);

  const items = useMemo<MenuProps["items"]>(() => {
    const domain = MENU[activeGnb];
    return domain.groups.flatMap((group) => {
      const visibleItems = group.items.filter(
        (item) => !item.roles || item.roles.some((r) => userRoles.includes(r)),
      );
      if (visibleItems.length === 0) return [];
      return [{
        key: group.key,
        label: group.label,
        type: "group" as const,
        children: visibleItems.map((item) => {
          const isInbox = item.path === INBOX_PATH;
          const showBadge = isInbox && inboxCount > 0;
          return {
            key: item.path,
            label: showBadge ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                {item.label}
                <Badge count={inboxCount} size="small" overflowCount={99} />
              </span>
            ) : (
              item.label
            ),
            icon: item.icon ? ICON_MAP[item.icon] : undefined,
          };
        }),
      }];
    });
  }, [activeGnb, inboxCount, userRoles]);

  const handleClick: MenuProps["onClick"] = ({ key }) => {
    if (typeof key !== "string" || key === location.pathname) return;
    if (hasUnsavedChanges() && !window.confirm("저장 안 된 변경 사항이 있어요.\n계속 이동할까요?")) {
      return;
    }
    navigate(key);
  };

  if (mobile) {
    return (
      <div className="insa-sider insa-sider-mobile">
        <div className="insa-sider-scroll">
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={items}
            onClick={handleClick}
            style={{ borderRight: 0, background: "transparent" }}
          />
        </div>
      </div>
    );
  }

  return (
    <aside
      className="insa-sider"
      style={{
        width: collapsed ? "var(--shell-sider-w-collapsed)" : "var(--shell-sider-w)",
      }}
    >
      <div className="insa-sider-scroll">
        <Menu
          mode="inline"
          inlineCollapsed={collapsed}
          selectedKeys={[location.pathname]}
          items={items}
          onClick={handleClick}
          style={{ borderRight: 0, background: "transparent" }}
        />
      </div>
      <div className="insa-sider-footer">
        <Tooltip title={collapsed ? "사이드바 펼치기" : "사이드바 접기"} placement="right">
          <button
            type="button"
            className="insa-sider-collapse-btn"
            onClick={onToggleCollapse}
            aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
        </Tooltip>
      </div>
    </aside>
  );
}
