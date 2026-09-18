import { useMemo, type ReactNode } from "react";
import { Menu, Tooltip } from "antd";
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
import { useAuthStore } from "../store/auth";

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
};

export function SideNav({ activeGnb, collapsed, onToggleCollapse }: SideNavProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const userRoles = useAuthStore((s) => s.roles);

  const items = useMemo<MenuProps["items"]>(() => {
    const domain = MENU[activeGnb];
    return domain.groups
      .map((group) => {
        const filteredItems = group.items.filter(
          (item) => !item.roles || item.roles.some((r) => userRoles.includes(r))
        );
        return {
          key: group.key,
          label: group.label,
          type: "group" as const,
          children: filteredItems.map((item) => ({
            key: item.path,
            label: item.label,
            icon: item.icon ? ICON_MAP[item.icon] : undefined,
          })),
        };
      })
      .filter((group) => group.children.length > 0);
  }, [activeGnb, userRoles]);

  const handleClick: MenuProps["onClick"] = ({ key }) => {
    if (typeof key !== "string" || key === location.pathname) return;
    if (hasUnsavedChanges() && !window.confirm("저장 안 된 변경 사항이 있어요.\n계속 이동할까요?")) {
      return;
    }
    navigate(key);
  };

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
