import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { SearchOutlined } from "@ant-design/icons";
import { flattenMenu, findEntryByPath, type FlatMenuEntry } from "./menuRegistry";
import { loadRecentPaths, pushRecentPath } from "./hooks/useCommandPalette";
import { hasUnsavedChanges } from "./hooks/useUnsavedState";
import { useAuthStore } from "../store/auth";

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
};

type Section = {
  label: string;
  entries: FlatMenuEntry[];
};

function scoreEntry(entry: FlatMenuEntry, query: string): number {
  if (!query) return 0;
  const q = query.toLowerCase();
  const label = entry.label.toLowerCase();
  const breadcrumb = entry.breadcrumb.toLowerCase();
  const keywords = (entry.keywords ?? []).join(" ").toLowerCase();

  if (label === q) return 100;
  if (label.startsWith(q)) return 80;
  if (label.includes(q)) return 60;
  if (breadcrumb.includes(q)) return 40;
  if (keywords.includes(q)) return 30;
  return 0;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [focusIndex, setFocusIndex] = useState(0);
  const userRoles = useAuthStore((s) => s.roles);

  const allEntries = useMemo(() => {
    const entries = flattenMenu();
    return entries.filter((entry) => !entry.roles || entry.roles.some((r) => userRoles.includes(r)));
  }, [userRoles]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setFocusIndex(0);
      const id = window.setTimeout(() => inputRef.current?.focus(), 30);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  const sections = useMemo<Section[]>(() => {
    const q = query.trim();
    if (!q) {
      const recents = loadRecentPaths()
        .map((path) => findEntryByPath(path))
        .filter((e): e is FlatMenuEntry => Boolean(e));
      if (recents.length > 0) {
        return [
          { label: "최근 방문", entries: recents.slice(0, 6) },
          { label: "모든 메뉴", entries: allEntries.slice(0, 40) },
        ];
      }
      return [{ label: "모든 메뉴", entries: allEntries }];
    }
    const scored = allEntries
      .map((entry) => ({ entry, score: scoreEntry(entry, q) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 20)
      .map((x) => x.entry);
    return [{ label: "검색 결과", entries: scored }];
  }, [query, allEntries]);

  const flatList = useMemo(
    () => sections.flatMap((s) => s.entries),
    [sections]
  );

  useEffect(() => {
    if (focusIndex >= flatList.length) {
      setFocusIndex(Math.max(0, flatList.length - 1));
    }
  }, [flatList.length, focusIndex]);

  const go = (entry: FlatMenuEntry) => {
    if (hasUnsavedChanges() && !window.confirm("저장 안 된 변경 사항이 있어요.\n계속 이동할까요?")) {
      return;
    }
    pushRecentPath(entry.path);
    onClose();
    navigate(entry.path);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusIndex((i) => Math.min(i + 1, flatList.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = flatList[focusIndex];
      if (target) go(target);
    }
  };

  if (!open) return null;

  let runningIdx = 0;

  return createPortal(
    <div
      className="insa-palette-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="페이지 찾기"
    >
      <div className="insa-palette-dialog" onKeyDown={onKeyDown}>
        <div className="insa-palette-search">
          <SearchOutlined className="insa-palette-search-icon" />
          <input
            ref={inputRef}
            className="insa-palette-input"
            placeholder="메뉴 이름 또는 키워드로 검색"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setFocusIndex(0);
            }}
            aria-label="검색어"
          />
          <span className="insa-palette-esc">ESC</span>
        </div>
        <div className="insa-palette-body">
          {flatList.length === 0 ? (
            <div className="insa-palette-empty">
              일치하는 메뉴가 없어요
              <div className="insa-palette-empty-sub">
                다른 단어로 다시 검색해 보세요
              </div>
            </div>
          ) : (
            sections.map((section) => (
              <div key={section.label}>
                <div className="insa-palette-section-label">{section.label}</div>
                {section.entries.map((entry) => {
                  const idx = runningIdx++;
                  const focused = idx === focusIndex;
                  return (
                    <button
                      key={`${section.label}-${entry.path}`}
                      type="button"
                      className="insa-palette-item"
                      data-focused={focused}
                      onMouseEnter={() => setFocusIndex(idx)}
                      onClick={() => go(entry)}
                    >
                      <span className="insa-palette-item-label">{entry.label}</span>
                      <span className="insa-palette-item-breadcrumb">
                        {entry.breadcrumb}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
