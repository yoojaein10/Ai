"use client";

import React, { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense } from "react";
import { getAssignmentEmployees, getAssignmentData, saveAssignmentSchedule, deleteAssignmentSchedule, AssignmentEmployee, AssignmentDataItem } from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────

type AssignType = "assign" | "trip" | "hold" | "shlh" | "leave" | "chief" | "npl" | "taksan" | "gongga" | "vacation" | "schedule";

interface Assignment {
  type: AssignType;
  code?: string;
  location?: string;
  label?: string;
  status?: string;
  isDuplicate?: boolean;
  source?: "allocation" | "schedule";
}

interface Employee extends AssignmentEmployee {
  assignments: Record<number, Assignment[]>;
}

// ─── Config ──────────────────────────────────────────────────────────────────

const TEAM_META: Record<string, { label: string; accent: string }> = {
  pg1: { label: "평가 1팀", accent: "#5C7CFA" },
  pg2: { label: "평가 2팀", accent: "#51CF66" },
  su:  { label: "수습 평가사", accent: "#FF922B" },
};

const TYPE_STYLE: Record<AssignType, { bg: string; color: string }> = {
  assign: { bg: "#e7f5ff", color: "#1864ab" },
  trip:   { bg: "#fff4e6", color: "#e67700" },
  hold:   { bg: "#fff0f6", color: "#a61e4d" },
  shlh:   { bg: "#f3f0ff", color: "#5f3dc4" },
  leave:  { bg: "#f1f3f5", color: "#868e96" },
  chief:  { bg: "#ebfbee", color: "#2f9e44" },
  npl:      { bg: "#dbe4ff", color: "#1864ab" },
  taksan:   { bg: "#d3f9d8", color: "#2b8a3e" },
  gongga:   { bg: "#f3f0ff", color: "#6741d9" },
  vacation: { bg: "#fff0f6", color: "#c2255c" },
  schedule: { bg: "#fff9db", color: "#e67700" },
};

const WANRYO_STYLE = { bg: "#E5E7EB", color: "#374151" };
const DUP_STYLE    = { bg: "#FEF3C7", color: "#92400E" };

const BORDER = "1px solid var(--border-color,#e9ecef)";

const RANK_ORDER: Record<string, number> = {
  "대표이사": 1, "이사": 2, "본부장": 3, "지사장": 4,
  "국장": 5, "부장": 6, "실장": 7,
  "차장": 8, "자장": 8, "과장": 9,
  "대리": 10, "주임": 11, "사원": 12,
  "수습": 13, "수습평가사": 13,
};

function empRankOrder(emp: Employee): number {
  return RANK_ORDER[emp.rank?.trim() ?? ""] ?? 99;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getDaysInMonth(year: number, month: number): number[] {
  const count = new Date(year, month, 0).getDate();
  return Array.from({ length: count }, (_, i) => i + 1);
}

function getDow(year: number, month: number, day: number): number {
  return new Date(year, month - 1, day).getDay(); // 0=일,6=토
}

function stripSido(addr: string): string {
  const parts = addr.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "";
  if (/특별시$|광역시$|자치시$|특별자치도$|도$/.test(parts[0])) {
    return parts.slice(1).join(" ");
  }
  return parts.join(" ");
}

function dayHeaderStyle(dow: number): React.CSSProperties {
  if (dow === 0) return { color: "#b91c1c", borderBottom: "2px solid #b91c1c" };
  if (dow === 6) return { color: "#1d4ed8", borderBottom: "2px solid #1d4ed8" };
  return { color: "var(--text-primary,#212529)", borderBottom: "2px solid var(--border-color,#e9ecef)" };
}

// ─── AssignCell ───────────────────────────────────────────────────────────────

function AssignCell({ items }: { items: Assignment[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {items.map((item, i) => {
        const s = item.status === "완료처리(발송)" ? WANRYO_STYLE
          : item.isDuplicate ? DUP_STYLE
          : TYPE_STYLE[item.type];
        return (
          <div key={i} style={{ background: s.bg, color: s.color, borderRadius: 3, padding: "2px 4px", fontSize: 10, lineHeight: 1.4, textAlign: "left" }}>
            {item.code && <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.code}</div>}
            {item.location && <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.location}</div>}
            {!item.code && !item.location && item.label && (
              <div style={{ fontWeight: 600 }}>{item.label}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Grid ────────────────────────────────────────────────────────────────────

function AssignmentGrid({ year, month, employees = [], onCellContextMenu }: {
  year: number;
  month: number;
  employees: Employee[];
  onCellContextMenu: (apwid: number, day: number, x: number, y: number) => void;
}) {
  const days = getDaysInMonth(year, month);
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const FIX_RANK_W  = 44;
  const FIX_NAME_W  = 56;
  const FIX_CNT_W   = 72;
  const FIX_TOTAL   = FIX_RANK_W + FIX_NAME_W + FIX_CNT_W;
  const DAY_W       = 100;

  const grouped = (["pg1", "pg2", "su"] as const)
    .map((team) => ({
      team,
      employees: employees
        .filter((e) => e.team === team)
        .sort((a, b) => {
          const rd = empRankOrder(a) - empRankOrder(b);
          if (rd !== 0) return rd;
          return a.name.localeCompare(b.name, "ko");
        }),
    }))
    .filter((g) => g.employees.length > 0);

  const thBase: React.CSSProperties = {
    position: "sticky", top: 0, zIndex: 50,
    background: "var(--bg-secondary,#f8f9fa)",
    borderRight: BORDER,
    padding: "6px 4px", fontSize: 11, fontWeight: 600,
    whiteSpace: "nowrap", textAlign: "center",
    color: "var(--text-primary,#212529)",
  };

  const fixBase: React.CSSProperties = {
    position: "sticky", zIndex: 40,
    background: "var(--bg-primary,#fff)",
    borderBottom: BORDER, borderRight: BORDER,
    padding: "8px 6px", fontSize: 11,
    whiteSpace: "nowrap",
    height: 64,
  };

  const fixLastShadow: React.CSSProperties = {
    ...fixBase,
    borderRight: "none",
    boxShadow: "2px 0 6px rgba(0,0,0,0.10)",
  };

  return (
    <div style={{ overflowX: "auto", overflowY: "auto", flex: 1, border: BORDER, borderRadius: 6 }}>
      <table style={{ borderCollapse: "separate", borderSpacing: 0, minWidth: FIX_TOTAL + DAY_W * days.length }}>
        <thead>
          <tr>
            {/* 고정 헤더 */}
            <th style={{ ...thBase, left: 0, zIndex: 4, width: FIX_RANK_W, borderBottom: "2px solid var(--border-color,#e9ecef)" }}>직급</th>
            <th style={{ ...thBase, left: FIX_RANK_W, zIndex: 4, width: FIX_NAME_W, borderBottom: "2px solid var(--border-color,#e9ecef)" }}>이름</th>
            <th style={{ ...thBase, left: FIX_RANK_W + FIX_NAME_W, zIndex: 4, width: FIX_CNT_W, borderBottom: "2px solid var(--border-color,#e9ecef)", borderRight: "none", boxShadow: "2px 0 4px rgba(0,0,0,0.08)" }}>입사일</th>
            {/* 날짜 헤더 */}
            {days.map((d) => {
              const dow = getDow(year, month, d);
              return (
                <th key={d} style={{ ...thBase, width: DAY_W, ...dayHeaderStyle(dow) }}>
                  {month}/{d}<br />
                  <span style={{ fontSize: 9, fontWeight: 400 }}>{"일월화수목금토"[dow]}</span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {grouped.map(({ team, employees }) => {
            const meta = TEAM_META[team];
            return (
              <React.Fragment key={team}>
                {/* 팀 구분 행 */}
                <tr>
                  <td
                    colSpan={3 + days.length}
                    style={{
                      padding: "10px 14px",
                      background: "var(--bg-secondary,#f8f9fa)",
                      borderBottom: BORDER,
                      boxShadow: `inset 0 2px 0 0 ${meta.accent}`,
                    }}
                  >
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      background: meta.accent + "18",
                      border: `1px solid ${meta.accent}40`,
                      borderRadius: 20,
                      padding: "3px 10px 3px 6px",
                    }}>
                      <span style={{
                        width: 8, height: 8, borderRadius: "50%",
                        background: meta.accent,
                        flexShrink: 0,
                      }} />
                      <span style={{
                        fontSize: 11, fontWeight: 700,
                        letterSpacing: "0.05em",
                        color: meta.accent,
                      }}>
                        {meta.label}
                      </span>
                    </span>
                  </td>
                </tr>
                {/* 직원 행 */}
                {employees.map((emp) => {
                  const rowKey = `${team}-${emp.name}`;
                  const isHovered = hoveredRow === rowKey;
                  const rowBg = isHovered ? "var(--bg-secondary,#f8f9fa)" : "var(--bg-primary,#fff)";
                  const cellStyle: React.CSSProperties = {
                    background: rowBg,
                    borderBottom: BORDER,
                    borderRight: BORDER,
                    padding: "8px 6px",
                    verticalAlign: "top",
                    minWidth: DAY_W,
                    height: 64,
                    overflow: "hidden",
                  };
                  return (
                    <tr
                      key={rowKey}
                      onMouseEnter={() => setHoveredRow(rowKey)}
                      onMouseLeave={() => setHoveredRow(null)}
                    >
                      {/* 고정 열 */}
                      <td style={{ ...fixBase, left: 0, width: FIX_RANK_W, fontSize: 11, fontWeight: 700, textAlign: "center", color: "var(--text-primary,#212529)" }}>
                        {emp.rank}
                      </td>
                      <td style={{ ...fixBase, left: FIX_RANK_W, width: FIX_NAME_W, fontWeight: 700, color: "var(--text-primary,#212529)" }}>
                        {emp.name}
                      </td>
                      <td style={{ ...fixLastShadow, left: FIX_RANK_W + FIX_NAME_W, width: FIX_CNT_W, textAlign: "center", fontSize: 10, fontWeight: 600, color: "var(--text-secondary,#868e96)" }}>
                        {emp.hireDate ? emp.hireDate.replace(/-/g, ".") : "—"}
                      </td>
                      {/* 날짜 셀 */}
                      {days.map((d) => {
                        const items = emp.assignments[d];
                        const hasItem = items && items.length > 0;
                        return (
                          <td
                            key={d}
                            style={{
                              ...cellStyle,
                              outline: isHovered && hasItem ? "1px solid var(--accent-color,#4C6EF5)" : undefined,
                              cursor: "context-menu",
                            }}
                            onContextMenu={(e) => {
                              e.preventDefault();
                              onCellContextMenu(emp.apwid, d, e.clientX, e.clientY);
                            }}
                          >
                            <div style={{ overflow: "hidden", width: "100%", height: "100%" }}>
                              {hasItem && <AssignCell items={items} />}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Legend ──────────────────────────────────────────────────────────────────

const LEGEND_ITEMS: { label: string; bg: string; color: string }[] = [
  { label: "배정",           bg: TYPE_STYLE.assign.bg,   color: TYPE_STYLE.assign.color   },
  { label: "보류·취소",      bg: TYPE_STYLE.hold.bg,     color: TYPE_STYLE.hold.color     },
  { label: "NPL",            bg: TYPE_STYLE.npl.bg,      color: TYPE_STYLE.npl.color      },
  { label: "탁상",           bg: TYPE_STYLE.taksan.bg,   color: TYPE_STYLE.taksan.color   },
  { label: "공가",           bg: TYPE_STYLE.gongga.bg,   color: TYPE_STYLE.gongga.color   },
  { label: "휴가",           bg: TYPE_STYLE.vacation.bg, color: TYPE_STYLE.vacation.color },
  { label: "기타 일정",      bg: TYPE_STYLE.schedule.bg, color: TYPE_STYLE.schedule.color },
  { label: "완료처리(발송)", bg: WANRYO_STYLE.bg,        color: WANRYO_STYLE.color        },
  { label: "중복 배정",     bg: DUP_STYLE.bg,           color: DUP_STYLE.color           },
];

// ─── ScheduleModal ───────────────────────────────────────────────────────────

function ScheduleModal({ apwid: _apwid, defaultDate, x, y, existingMemo, onSave, onDelete, onClose }: {
  apwid: number;
  defaultDate: string;
  x: number;
  y: number;
  existingMemo: string;
  onSave: (startDate: string, endDate: string, gubun: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onClose: () => void;
}) {
  const [startDate, setStartDate] = useState(defaultDate);
  const [endDate,   setEndDate]   = useState(defaultDate);
  const [memo,      setMemo]      = useState(existingMemo);
  const [saving,    setSaving]    = useState(false);
  const [deleting,  setDeleting]  = useState(false);
  const [err,       setErr]       = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleSave = async () => {
    const trimmed = memo.trim();
    if (!trimmed) { setErr("메모를 입력해주세요."); return; }
    setSaving(true);
    setErr(null);
    try {
      await onSave(startDate, endDate, trimmed);
      onClose();
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { message?: string } } })?.response?.data?.message
        ?? (e instanceof Error ? e.message : "저장 실패");
      setErr(msg);
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setErr(null);
    try {
      await onDelete();
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { message?: string } } })?.response?.data?.message
        ?? (e instanceof Error ? e.message : "삭제 실패");
      setErr(msg);
      setDeleting(false);
    }
  };

  const mW = 280, mH = existingMemo ? 250 : 220;
  const safeL = typeof window !== "undefined" && x + mW > window.innerWidth  ? Math.max(0, x - mW) : x;
  const safeT = typeof window !== "undefined" && y + mH > window.innerHeight ? Math.max(0, y - mH) : y;

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 9998 }} onMouseDown={onClose} />
      <div
        style={{
          position: "fixed", left: safeL, top: safeT, zIndex: 9999,
          background: "var(--bg-primary,#fff)", border: "1px solid var(--border-color,#e9ecef)",
          borderRadius: 10, boxShadow: "0 8px 24px rgba(0,0,0,0.14)",
          width: mW, padding: "14px 16px",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary,#212529)", marginBottom: 12 }}>일정 저장</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
          <input
            type="date" value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            style={{ flex: 1, fontSize: 11, padding: "5px 6px", border: "1px solid var(--border-color,#e9ecef)", borderRadius: 6, color: "var(--text-primary,#212529)", background: "var(--bg-primary,#fff)" }}
          />
          <span style={{ fontSize: 11, color: "var(--text-secondary,#868e96)", flexShrink: 0 }}>~</span>
          <input
            type="date" value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            style={{ flex: 1, fontSize: 11, padding: "5px 6px", border: "1px solid var(--border-color,#e9ecef)", borderRadius: 6, color: "var(--text-primary,#212529)", background: "var(--bg-primary,#fff)" }}
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <input
            type="text"
            value={memo}
            onChange={(e) => { if (e.target.value.length <= 20) setMemo(e.target.value); }}
            placeholder="예: 공가, 휴가, 건강검진"
            maxLength={20}
            autoFocus
            style={{
              width: "100%", fontSize: 12, padding: "7px 8px",
              border: "1px solid var(--border-color,#e9ecef)", borderRadius: 6,
              color: "var(--text-primary,#212529)", background: "var(--bg-primary,#fff)", boxSizing: "border-box",
              outline: "none",
            }}
          />
          <div style={{ fontSize: 10, color: "var(--text-secondary,#868e96)", textAlign: "right", marginTop: 2 }}>{memo.length}/20</div>
        </div>
        {err && <div style={{ fontSize: 11, color: "#e03131", marginBottom: 8 }}>{err}</div>}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          {existingMemo ? (
            <button
              onClick={handleDelete}
              disabled={deleting || saving}
              style={{
                fontSize: 12, padding: "6px 14px", borderRadius: 6,
                background: deleting ? "#94a3b8" : "var(--bg-primary,#fff)",
                color: deleting ? "#fff" : "#e03131",
                border: "1px solid #fca5a5",
                cursor: deleting ? "not-allowed" : "pointer",
                fontWeight: 600,
              }}
            >
              {deleting ? "삭제 중..." : "삭제"}
            </button>
          ) : <div />}
          <button
            onClick={handleSave}
            disabled={saving || deleting || !memo.trim()}
            style={{
              fontSize: 12, padding: "6px 18px", borderRadius: 6,
              background: saving || deleting || !memo.trim() ? "#94a3b8" : "var(--accent-color,#4C6EF5)",
              color: "var(--accent-contrast,#fff)", border: "none",
              cursor: saving || deleting ? "not-allowed" : "pointer",
              fontWeight: 600,
            }}
          >
            {saving ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

function buildAssignments(
  empList: AssignmentEmployee[],
  items: AssignmentDataItem[]
): Employee[] {
  const indexByApwid: Record<number, number> = {};
  empList.forEach((e, i) => { indexByApwid[e.apwid] = i; });

  // 당월 중복 감정서번호 사전 계산 (같은 사람 + 같은 감정서번호 기준)
  const comboCount: Record<string, number> = {};
  for (const item of items) {
    const t = item.type;
    if (t !== "npl" && t !== "taksan" && t !== "gongga" && t !== "vacation" && t !== "schedule" && item.docId) {
      const key = `${item.apwid}|${item.docId}`;
      comboCount[key] = (comboCount[key] ?? 0) + 1;
    }
  }
  const dupCombos = new Set(Object.keys(comboCount).filter((k) => comboCount[k] >= 2));

  const maps: Record<number, Assignment[]>[] = empList.map(() => ({}));

  for (const item of items) {
    const idx = indexByApwid[item.apwid];
    if (idx === undefined) continue;
    const type = item.type as AssignType;
    const isSchedule = type === "npl" || type === "taksan" || type === "gongga" || type === "vacation" || type === "schedule";
    const loc = stripSido(item.address);
    const locFull = item.category ? `${loc} · ${item.category}` : loc;
    const asgn: Assignment = {
      type,
      code:        isSchedule ? undefined : item.docId,
      location:    isSchedule ? undefined : (locFull || undefined),
      label:       isSchedule ? item.status : undefined,
      status:      item.status,
      isDuplicate: !isSchedule && item.docId ? dupCombos.has(`${item.apwid}|${item.docId}`) : false,
      source:      isSchedule ? "schedule" : "allocation",
    };
    if (!maps[idx][item.day]) maps[idx][item.day] = [];
    maps[idx][item.day].push(asgn);
  }

  return empList.map((e, i) => ({ ...e, assignments: maps[i] }));
}

function AssignmentContent() {
  const searchParams = useSearchParams();
  const empno  = searchParams.get("empno") ?? "0";
  const today  = new Date();
  const initY  = parseInt(searchParams.get("year")  ?? String(today.getFullYear()), 10);
  const initM  = parseInt(searchParams.get("month") ?? String(today.getMonth() + 1), 10);
  const [viewYear,  setViewYear]  = useState(initY);
  const [viewMonth, setViewMonth] = useState(initM);
  const [empList,   setEmpList]   = useState<AssignmentEmployee[]>([]);
  const [assignItems, setAssignItems] = useState<AssignmentDataItem[]>([]);
  const [empLoading,  setEmpLoading]  = useState(true);
  const [dataLoading, setDataLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; apwid: number; day: number; existingMemo: string } | null>(null);

  useEffect(() => {
    getAssignmentEmployees()
      .then(setEmpList)
      .catch(() => setError("직원 목록을 불러오지 못했습니다."))
      .finally(() => setEmpLoading(false));
  }, []);

  useEffect(() => {
    setDataLoading(true);
    getAssignmentData(viewYear, viewMonth)
      .then(setAssignItems)
      .catch(() => setError("배정 데이터를 불러오지 못했습니다."))
      .finally(() => setDataLoading(false));
  }, [viewYear, viewMonth]);

  const employees = useMemo(
    () => buildAssignments(empList, assignItems),
    [empList, assignItems]
  );

  const loading = empLoading || dataLoading;

  const handleCellContextMenu = useCallback((apwid: number, day: number, x: number, y: number) => {
    const scheduleItem = assignItems.find(
      (item) => item.apwid === apwid && item.day === day &&
        item.type !== "assign" && item.type !== "hold"
    );
    setContextMenu({ x, y, apwid, day, existingMemo: scheduleItem?.status ?? "" });
  }, [assignItems]);

  const handleModalSave = useCallback(async (startDate: string, endDate: string, gubun: string) => {
    if (!contextMenu) return;
    await saveAssignmentSchedule({ apwid: contextMenu.apwid, start_date: startDate, end_date: endDate, gubun });
    const items = await getAssignmentData(viewYear, viewMonth);
    setAssignItems(items);
  }, [contextMenu, viewYear, viewMonth]);

  const handleModalDelete = useCallback(async () => {
    if (!contextMenu) return;
    const dateStr = `${viewYear}-${String(viewMonth).padStart(2, "0")}-${String(contextMenu.day).padStart(2, "0")}`;
    await deleteAssignmentSchedule({ apwid: contextMenu.apwid, date: dateStr });
    const items = await getAssignmentData(viewYear, viewMonth);
    setAssignItems(items);
    setContextMenu(null);
  }, [contextMenu, viewYear, viewMonth]);

  const moveMonth = useCallback((delta: number) => {
    startTransition(() => {
      setViewMonth((m) => {
        const next = m + delta;
        if (next < 1)  { setViewYear((y) => y - 1); return 12; }
        if (next > 12) { setViewYear((y) => y + 1); return 1;  }
        return next;
      });
    });
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-primary,#fff)", fontFamily: "'Inter','Pretendard',system-ui,sans-serif" }}>
      {/* 헤더 */}
      <header style={{ position: "sticky", top: 0, zIndex: 10, background: "var(--bg-primary,#fff)", borderBottom: BORDER, padding: "10px 16px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        {/* 뒤로가기 */}
        <Link
          href={`/daily-list?empno=${empno}`}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 8, background: "var(--bg-secondary,#f8f9fa)", color: "var(--text-primary,#212529)", fontSize: 13, fontWeight: 500, textDecoration: "none" }}
        >
          <svg width={14} height={14} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          출장리스트
        </Link>

        {/* 제목 */}
        <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary,#212529)" }}>
          업무 배정 현황
        </span>

        {/* 월 이동 */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button onClick={() => moveMonth(-1)} style={{ padding: "4px 6px", borderRadius: 6, border: BORDER, background: "transparent", cursor: "pointer", color: "var(--text-primary,#212529)", display: "flex", alignItems: "center" }}>
            <svg width={14} height={14} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <span style={{ fontSize: 13, fontWeight: 700, minWidth: 84, textAlign: "center", color: "var(--text-primary,#212529)" }}>
            {viewYear}년 {viewMonth}월
          </span>
          <button onClick={() => moveMonth(1)} style={{ padding: "4px 6px", borderRadius: 6, border: BORDER, background: "transparent", cursor: "pointer", color: "var(--text-primary,#212529)", display: "flex", alignItems: "center" }}>
            <svg width={14} height={14} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
          <button
            onClick={() => { setViewYear(today.getFullYear()); setViewMonth(today.getMonth() + 1); }}
            style={{ padding: "4px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: "var(--accent-color,#5C7CFA)", color: "var(--accent-contrast,#fff)", border: "none", cursor: "pointer" }}
          >
            이번 달
          </button>
        </div>

        {/* 레전드 */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginLeft: "auto" }}>
          {LEGEND_ITEMS.map(({ label, bg, color }) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
              <div style={{ width: 12, height: 12, borderRadius: 2, background: bg, border: `1px solid ${color}` }} />
              <span style={{ color: "var(--text-secondary,#868e96)" }}>{label}</span>
            </div>
          ))}
        </div>
      </header>

      {/* 그리드 */}
      <div style={{ flex: 1, padding: 16, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {loading && <div style={{ textAlign: "center", padding: 40, color: "var(--text-secondary,#868e96)", fontSize: 13 }}>로딩 중...</div>}
        {error   && <div style={{ textAlign: "center", padding: 40, color: "#e03131", fontSize: 13 }}>{error}</div>}
        {!loading && !error && <AssignmentGrid year={viewYear} month={viewMonth} employees={employees} onCellContextMenu={handleCellContextMenu} />}
      </div>
      {contextMenu && (
        <ScheduleModal
          apwid={contextMenu.apwid}
          defaultDate={`${viewYear}-${String(viewMonth).padStart(2,"0")}-${String(contextMenu.day).padStart(2,"0")}`}
          x={contextMenu.x}
          y={contextMenu.y}
          existingMemo={contextMenu.existingMemo}
          onSave={handleModalSave}
          onDelete={handleModalDelete}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
}

export default function AssignmentPage() {
  return (
    <Suspense fallback={<div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>로딩 중...</div>}>
      <AssignmentContent />
    </Suspense>
  );
}
